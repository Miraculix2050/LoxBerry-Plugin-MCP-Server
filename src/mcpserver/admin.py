"""Narrow JSON stdin/stdout boundary used by the authenticated Perl UI."""

# ruff: noqa: E402

from __future__ import annotations

import time

_MODULE_IMPORT_STARTED_NS = time.time_ns()

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.request import Request, urlopen
from uuid import UUID

from mcpserver import __version__

if TYPE_CHECKING:
    from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.loxone.client import LoxoneClient, MiniserverEndpoint

from mcpserver.config import AtomicConfigStore, PluginConfig

_MODULE_IMPORT_FINISHED_NS = time.time_ns()

_MAX_REQUEST_BYTES: Final = 32 * 1024
_SERVICE: Final = "loxberry-mcpserver.service"
_SERVICE_ACTIONS: Final = frozenset({"start", "stop", "restart"})
_SYSTEMD_COMMANDS: Final = frozenset({"enable", "disable", "start", "stop", "restart"})
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")
_INTERNAL_EMERGENCY_STOP_STATUS_URL: Final = "http://127.0.0.1:8765/internal/emergency-stop-status"
_INTERNAL_RESPONSE_MAX_BYTES: Final = 4 * 1024
_EMERGENCY_STOP_STATES: Final = frozenset({"not_configured", "clear", "active", "unknown"})


class AdminError(RuntimeError):
    """A sanitized, user-actionable administrative error."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _AdminReadSnapshot:
    """Consistent, single-read input for one administrative list response."""

    configuration: PluginConfig | None
    auth_document: dict[str, Any]
    subject_key: bytes | None
    now: float


def _path(name: str, *, suffix: str | None = None) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or (suffix is not None and path.suffix != suffix):
        raise AdminError("plugin storage is not configured")
    return path


def _config_store() -> AtomicConfigStore:
    from mcpserver.config import AtomicConfigStore

    return AtomicConfigStore(_path("MCPSERVER_CONFIG", suffix=".json"))


def _auth_store() -> AtomicJsonAuthStore:
    from mcpserver.auth.store import AtomicJsonAuthStore

    return AtomicJsonAuthStore(_path("MCPSERVER_AUTH_STORE", suffix=".json"))


def _token_store() -> EncryptedLoxoneTokenStore:
    from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore

    return EncryptedLoxoneTokenStore(
        _path("MCPSERVER_LOXONE_TOKEN_STORE", suffix=".enc"),
        _path("MCPSERVER_INSTALL_KEY", suffix=".key"),
    )


def _loxone_client(
    endpoint: MiniserverEndpoint, *, client_uuid: UUID, timeout_seconds: float
) -> LoxoneClient:
    from mcpserver.loxone.client import LoxoneClient

    return LoxoneClient(endpoint, client_uuid=client_uuid, timeout_seconds=timeout_seconds)


def _service_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "name": _SERVICE,
        "installed": False,
        "active_state": "unknown",
        "sub_state": "unknown",
        "pid": None,
        "active": False,
        "enabled": False,
        "enable_state": "unknown",
    }
    try:
        result = subprocess.run(
            [
                "/bin/systemctl",
                "show",
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                "--property=MainPID",
                "--property=UnitFileState",
                "--no-pager",
                _SERVICE,
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return status
    if result.returncode != 0:
        return status
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    load_state = properties.get("LoadState", "unknown")
    active_state = properties.get("ActiveState", "unknown")
    sub_state = properties.get("SubState", "unknown")
    raw_pid = properties.get("MainPID", "")
    enable_state = properties.get("UnitFileState", "unknown") or "unknown"
    try:
        enabled_result = subprocess.run(
            ["/bin/systemctl", "is-enabled", "--quiet", _SERVICE],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        enabled = enabled_result.returncode == 0
        if not enabled and enable_state == "enabled":
            enable_state = "disabled"
    except (OSError, subprocess.TimeoutExpired):
        enabled = False
    pid = int(raw_pid) if raw_pid.isdecimal() and int(raw_pid) > 0 else None
    status.update(
        installed=load_state not in {"not-found", "unknown", ""},
        active_state=active_state or "unknown",
        sub_state=sub_state or "unknown",
        pid=pid,
        active=active_state == "active",
        enabled=enabled,
        enable_state=enable_state,
    )
    return status


def _service_active() -> bool:
    return bool(_service_status()["active"])


def _emergency_stop_runtime_status(service: dict[str, Any]) -> dict[str, Any]:
    """Read and validate the running service's own emergency-stop snapshot."""
    if not service.get("active"):
        return {"availability": "service_inactive"}
    try:
        request = Request(
            _INTERNAL_EMERGENCY_STOP_STATUS_URL,
            headers={"Accept": "application/json"},
        )
        with urlopen(request, timeout=1) as response:
            if response.getcode() != 200:
                raise ValueError("unexpected response status")
            body = response.read(_INTERNAL_RESPONSE_MAX_BYTES + 1)
        if len(body) > _INTERNAL_RESPONSE_MAX_BYTES:
            raise ValueError("oversized response")
        document = json.loads(body)
        snapshot = document.get("emergency_stop") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or document.get("ok") is not True
            or not isinstance(snapshot, dict)
        ):
            raise ValueError("invalid response")
        signal_uuid = snapshot.get("signal_uuid")
        signal_name = snapshot.get("signal_name")
        status = snapshot.get("status")
        if signal_uuid is not None:
            if not isinstance(signal_uuid, str):
                raise ValueError("invalid signal UUID")
            UUID(signal_uuid)
        if signal_name is not None and (not isinstance(signal_name, str) or len(signal_name) > 512):
            raise ValueError("invalid signal name")
        if not isinstance(status, str) or status not in _EMERGENCY_STOP_STATES:
            raise ValueError("invalid emergency-stop status")
        if status == "not_configured" and (signal_uuid is not None or signal_name is not None):
            raise ValueError("inconsistent unconfigured status")
        if status != "not_configured" and signal_uuid is None:
            raise ValueError("missing configured signal")
        return {
            "availability": "available",
            "signal_uuid": signal_uuid,
            "signal_name": signal_name,
            "status": status,
        }
    except (OSError, ValueError):
        return {"availability": "unavailable"}


def _run_service_command(command: str) -> None:
    if command not in _SYSTEMD_COMMANDS:
        raise AdminError("service action is invalid")
    try:
        result = subprocess.run(
            ["sudo", "-n", "/bin/systemctl", command, _SERVICE],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=65,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError("the service action failed", code="service_action_failed") from exc
    if result.returncode != 0:
        raise AdminError("the service action failed", code="service_action_failed")


def _service_response() -> dict[str, Any]:
    service = _service_status()
    return {
        "service_active": service["active"],
        "service": service,
        "emergency_stop_runtime": _emergency_stop_runtime_status(service),
    }


def _mqtt_gateway_status() -> dict[str, Any]:
    """Report gateway connection details, excluding the broker password."""
    from mcpserver.mqtt_health import MqttGateway

    home = os.getenv("LBHOMEDIR", "").strip()
    home_path = Path(home)
    gateway = MqttGateway.from_loxberry_home(home_path) if home_path.is_absolute() else None
    if gateway is None:
        return {"gateway_configured": False}
    return {
        "gateway_configured": True,
        "host": gateway.host,
        "port": gateway.port,
        "username": gateway.username,
    }


def _mqtt_password_configured() -> bool:
    """Expose only whether an optional custom broker password exists."""
    from mcpserver.mqtt_health import MqttCredentialStore, MqttCredentialStoreError

    path_value = os.getenv("MCPSERVER_MQTT_CREDENTIALS", "").strip()
    key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
    if not path_value or not key_value:
        return False
    try:
        return MqttCredentialStore(Path(path_value), Path(key_value)).load() is not None
    except (MqttCredentialStoreError, ValueError):
        return False


def request_service_restart() -> None:
    from mcpserver.mqtt_health import request_service_restart as request

    request()


def clear_service_restart() -> None:
    from mcpserver.mqtt_health import clear_service_restart as clear

    clear()


def clear_retained_topics(config: PluginConfig, *, broker: Any) -> bool:
    from mcpserver.mqtt_health import clear_retained_topics as clear

    return clear(config, broker=broker)


def _service_action(payload: object) -> dict[str, Any]:
    command = payload.get("command") if isinstance(payload, dict) else None
    if not isinstance(command, str) or command not in _SERVICE_ACTIONS:
        raise AdminError("service action is invalid")
    if command == "restart":
        # The service owns the MQTT connection.  Its graceful shutdown consumes
        # this process-local marker and publishes retained ``restarting`` before
        # systemd launches the replacement process.
        request_service_restart()
    try:
        _run_service_command(command)
    except AdminError:
        if command == "restart":
            clear_service_restart()
        raise
    return _service_response()


def _set_service_enabled(payload: object) -> dict[str, Any]:
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    if not isinstance(enabled, bool):
        raise AdminError("service enabled state is invalid")
    previous = _service_status()
    # This handler runs inside the service it controls.  Disabling first keeps
    # the process alive long enough to persist the unit-file state and return
    # an authoritative response to the Admin UI; stopping first can terminate
    # the handler before it reaches ``disable``.
    commands = ("enable", "start") if enabled else ("disable", "stop")
    try:
        for command in commands:
            _run_service_command(command)
    except AdminError as exc:
        # Restore the prior combined systemd state if the second fixed action failed.
        if command != commands[0]:
            _restore_service_state(previous)
        raise AdminError("the service state was not applied") from exc
    response = _service_response()
    service = response["service"]
    if bool(service["enabled"]) != enabled or bool(service["active"]) != enabled:
        _restore_service_state(previous)
        raise AdminError("the service state was not applied")
    return response


def _restore_service_state(previous: dict[str, Any]) -> None:
    """Best-effort restoration after a failed fixed systemd state transition."""
    commands = (
        "enable" if previous["enabled"] else "disable",
        "start" if previous["active"] else "stop",
    )
    for command in commands:
        with suppress(AdminError):
            _run_service_command(command)


def _restart_service() -> None:
    try:
        _run_service_command("restart")
    except AdminError as exc:
        raise AdminError("the service could not be restarted") from exc


def _stop_service() -> None:
    try:
        _run_service_command("stop")
    except AdminError as exc:
        raise AdminError("the service could not be stopped") from exc


def _start_service() -> None:
    try:
        _run_service_command("start")
    except AdminError as exc:
        raise AdminError("the service could not be started") from exc


def _optional_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _certificate_status(*, configuration: Any | None = None) -> dict[str, Any]:
    from mcpserver.certificates import inspect_certificate

    certificate = _optional_path("MCPSERVER_WEB_CERT")
    authority = _optional_path("MCPSERVER_CA_CERT")
    helper = _optional_path("MCPSERVER_CERT_HELPER")
    status = _optional_path("MCPSERVER_CERT_STATUS")
    if certificate is None or authority is None:
        return {
            "available": False,
            "renewal_supported": False,
            "renewal": {"state": "idle"},
        }
    config = configuration if configuration is not None else _config_store().load()
    return inspect_certificate(
        certificate,
        authority,
        public_origin=config.public_origin,
        system_hostname=socket.gethostname(),
        helper_available=helper is not None
        and helper.is_file()
        and not helper.is_symlink()
        and os.access(helper, os.X_OK),
        status_path=status,
    )


def _renew_certificate(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AdminError("certificate renewal payload is invalid")
    securepin = payload.get("securepin")
    if not isinstance(securepin, str) or re.fullmatch(r"[0-9]{4}", securepin) is None:
        raise AdminError("SecurePIN is invalid", code="securepin_invalid")
    if payload.get("confirmation") != "renew":
        raise AdminError("certificate renewal was not confirmed", code="confirmation_required")
    status = _certificate_status()
    if not status.get("renewal_supported", False):
        raise AdminError("certificate renewal is unavailable", code="certificate_unsupported")
    helper = _optional_path("MCPSERVER_CERT_HELPER")
    if helper is None:
        raise AdminError("certificate renewal is unavailable", code="certificate_unsupported")
    try:
        result = subprocess.run(
            ["sudo", "-n", str(helper)],
            input=(securepin + "\n").encode("ascii"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError(
            "certificate renewal could not be started", code="certificate_failed"
        ) from exc
    error_codes = {
        10: ("SecurePIN is incorrect", "securepin_wrong"),
        11: ("SecurePIN is locked", "securepin_locked"),
        12: ("SecurePIN could not be checked", "securepin_unavailable"),
        13: ("certificate renewal is already running", "certificate_busy"),
        14: ("certificate renewal is unavailable", "certificate_unsupported"),
    }
    if result.returncode in error_codes:
        message, code = error_codes[result.returncode]
        raise AdminError(message, code=code)
    if result.returncode != 0 or result.stdout != b"scheduled\n":
        raise AdminError("certificate renewal could not be started", code="certificate_failed")
    return {"renewal": {"state": "scheduled"}}


def _save(payload: object) -> dict[str, Any]:
    from mcpserver.auth.provider import (
        CONTROL_SCOPE,
        HISTORY_SCOPE,
        LOXBERRY_OPERATE_SCOPE,
        LOXBERRY_READ_SCOPE,
    )
    from mcpserver.config import ConfigError, PluginConfig

    if not isinstance(payload, dict):
        raise AdminError("configuration payload is invalid")
    config = PluginConfig.from_document(payload)
    store = _config_store()
    previous = store.load()
    if "logging" not in payload:
        config = replace(config, log_level=previous.log_level)
    if "policies" not in payload:
        config = replace(
            config,
            loxberry_read_bindings=previous.loxberry_read_bindings,
            loxberry_operate_bindings=previous.loxberry_operate_bindings,
        )
    control_families: list[str] = []
    if previous.loxone_control_enabled and not config.loxone_control_enabled:
        document = _auth_store().snapshot()
        control_families = [
            family_id
            for family_id, record in document["families"].items()
            if CONTROL_SCOPE in str(record.get("scope", "")).split()
            and not record.get("revoked", False)
        ]
    loxberry_families: list[str] = []
    if previous.loxberry_read_enabled and not config.loxberry_read_enabled:
        document = _auth_store().snapshot()
        loxberry_families = [
            family_id
            for family_id, record in document["families"].items()
            if LOXBERRY_READ_SCOPE in str(record.get("scope", "")).split()
            and not record.get("revoked", False)
        ]
    phase4_families: list[str] = []
    disabled_phase4_scopes = {
        scope
        for scope, was_enabled, is_enabled in (
            (HISTORY_SCOPE, previous.loxone_history_enabled, config.loxone_history_enabled),
            (
                LOXBERRY_OPERATE_SCOPE,
                previous.loxberry_operate_enabled,
                config.loxberry_operate_enabled,
            ),
        )
        if was_enabled and not is_enabled
    }
    if disabled_phase4_scopes:
        document = _auth_store().snapshot()
        phase4_families = [
            family_id
            for family_id, record in document["families"].items()
            if disabled_phase4_scopes & set(str(record.get("scope", "")).split())
            and not record.get("revoked", False)
        ]
    store.save(config)
    try:
        _restart_service()
    except AdminError as apply_error:
        try:
            store.save(previous)
            _restart_service()
        except (AdminError, ConfigError) as rollback_error:
            raise AdminError("configuration apply and rollback failed") from rollback_error
        raise AdminError(
            "configuration was not applied; previous configuration restored"
        ) from apply_error
    if control_families:
        _revoke_many(
            control_families,
            endpoint=previous.loxone_endpoint,
            timeout_seconds=previous.connection_timeout,
        )
    if loxberry_families:
        _revoke_many(
            loxberry_families,
            endpoint=previous.loxone_endpoint,
            timeout_seconds=previous.connection_timeout,
        )
    if phase4_families:
        _revoke_many(
            phase4_families,
            endpoint=previous.loxone_endpoint,
            timeout_seconds=previous.connection_timeout,
        )
    return {
        "configuration": config.to_document(),
        "applied": True,
        "sessions": _sessions(),
    } | _service_response()


def _save_mcp(payload: object) -> dict[str, Any]:
    """Atomically apply only the MCP configuration section, preserving MQTT."""
    from mcpserver.config import ConfigError, PluginConfig

    if not isinstance(payload, dict):
        raise AdminError("configuration payload is invalid")
    candidate = PluginConfig.from_document(payload)
    store = _config_store()
    fields = (
        "enabled",
        "public_origin",
        "loxone_endpoint",
        "connection_timeout",
        "loxone_read_enabled",
        "loxone_control_enabled",
        "loxberry_read_enabled",
        "loxone_history_enabled",
        "loxberry_operate_enabled",
        "requests_per_minute",
        "control_requests_per_minute",
        "loxberry_requests_per_minute",
        "history_requests_per_minute",
        "loxberry_operate_requests_per_minute",
        "explorer_binding_retention_hours",
        "max_parallel_calls",
        "statistics_memory_max_mib",
        "event_history_enabled",
        "event_history_retention_days",
        "event_history_maximum_mib",
        "structure_refresh_seconds",
        "max_active_runtime_sessions",
        "runtime_session_idle_seconds",
        "miniserver_auth_probe_initial_seconds",
        "miniserver_auth_probe_max_seconds",
        "max_structure_controls",
        "max_structure_state_references",
        "max_structure_depth",
        "max_states_per_identity",
        "emergency_stop_virtual_status_uuid",
    )

    def apply(previous: PluginConfig, save: Callable[[PluginConfig], None]) -> PluginConfig:
        was_active = _service_active()
        updated = replace(previous, **{field: getattr(candidate, field) for field in fields})
        save(updated)
        if not was_active:
            return updated
        try:
            _restart_service()
        except AdminError as apply_error:
            try:
                save(previous)
                _restart_service()
            except (AdminError, ConfigError) as rollback_error:
                raise AdminError("MCP configuration apply and rollback failed") from rollback_error
            raise AdminError(
                "MCP configuration was not applied; previous configuration restored"
            ) from apply_error
        return updated

    updated = store.transaction(apply)
    return {"configuration": updated.to_document(), "applied": True} | _service_response()


def _emergency_stop_options() -> dict[str, Any]:
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.emergency_stop import virtual_status_options
    from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
    from mcpserver.loxone.client import MiniserverEndpoint

    config = _config_store().load()
    store_path = os.getenv("MCPSERVER_AUTH_STORE", "").strip()
    coordinator = None
    if (
        Path(store_path).is_absolute()
        and Path(store_path).suffix == ".json"
        and config.loxone_endpoint
    ):
        auth_store = AtomicJsonAuthStore(Path(store_path))
        endpoint = MiniserverEndpoint.parse(config.loxone_endpoint)
        coordinator = MiniserverAuthCoordinator(
            Path(store_path).parent / "miniserver-auth-diagnostics.json",
            initial_probe_seconds=config.miniserver_auth_probe_initial_seconds,
            maximum_probe_seconds=config.miniserver_auth_probe_max_seconds,
            profile_id=auth_store.pseudonym("miniserver-auth-profile-v1", endpoint.origin),
        )
    result = asyncio.run(
        virtual_status_options(config, coordinator)
        if coordinator is not None
        else virtual_status_options(config)
    )
    response = {"status": result.status, "options": list(result.options)}
    if result.failure_code is not None:
        response["discovery_failure_code"] = result.failure_code
    return response


def _clear_event_history() -> dict[str, Any]:
    """Delete only plugin-owned local event records through the local Admin UI."""
    from mcpserver.loxone.event_history import EventHistoryStore, EventHistoryUnavailable

    config = _config_store().load()
    path = Path(os.getenv("MCPSERVER_EVENT_HISTORY_STORE", ""))
    if not path.is_absolute():
        raise AdminError("local event history is unavailable")
    was_active = _service_active()
    if was_active:
        _stop_service()
    try:
        store = EventHistoryStore(
            path,
            retention_days=config.event_history_retention_days,
            maximum_mib=config.event_history_maximum_mib,
        )
        store.initialize()
        removed = store.clear()
    except EventHistoryUnavailable as exc:
        raise AdminError("local event history is unavailable") from exc
    finally:
        if was_active:
            _start_service()
    return {"event_history_entries_removed": removed}


def _save_mqtt(payload: object) -> dict[str, Any]:
    """Atomically apply MQTT settings and separately protect an optional password."""
    from mcpserver.config import ConfigError, PluginConfig
    from mcpserver.mqtt_health import (
        MqttCredentialStore,
        MqttCredentialStoreError,
        mqtt_broker,
        mqtt_cleanup_required,
    )

    if not isinstance(payload, dict):
        raise AdminError("MQTT configuration payload is invalid")
    candidate = PluginConfig.from_document(payload)
    password = payload.get("mqtt_password")
    if password is not None and (not isinstance(password, str) or len(password) > 1024):
        raise AdminError("MQTT password is invalid")
    clear_password = payload.get("mqtt_clear_password", False)
    if not isinstance(clear_password, bool):
        raise AdminError("MQTT password clear intent is invalid")
    if clear_password and password:
        raise AdminError("MQTT password update and clear cannot be combined")
    credentials: MqttCredentialStore | None = None
    if password or clear_password:
        path_value = os.getenv("MCPSERVER_MQTT_CREDENTIALS", "").strip()
        key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
        if not path_value or not key_value:
            raise AdminError("MQTT credential storage is unavailable")
        credentials = MqttCredentialStore(Path(path_value), Path(key_value))
    store = _config_store()
    cleanup_status = "not_required"

    def apply(previous: PluginConfig, save: Callable[[PluginConfig], None]) -> PluginConfig:
        nonlocal cleanup_status
        previous_password = credentials.load() if credentials is not None else None
        was_active = _service_active()
        updated = replace(
            previous,
            mqtt_enabled=candidate.mqtt_enabled,
            mqtt_root_topic=candidate.mqtt_root_topic,
            mqtt_heartbeat_seconds=candidate.mqtt_heartbeat_seconds,
            mqtt_use_loxberry_gateway=candidate.mqtt_use_loxberry_gateway,
            mqtt_host=candidate.mqtt_host,
            mqtt_port=candidate.mqtt_port,
            mqtt_username=candidate.mqtt_username,
        )
        cleanup_required = mqtt_cleanup_required(previous, updated)
        cleanup_password: str | None = (
            "" if credentials is not None and previous_password is None else previous_password
        )
        cleanup_credentials = credentials
        if (
            cleanup_required
            and not previous.mqtt_use_loxberry_gateway
            and cleanup_credentials is None
        ):
            path_value = os.getenv("MCPSERVER_MQTT_CREDENTIALS", "").strip()
            key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
            if path_value and key_value:
                try:
                    cleanup_credentials = MqttCredentialStore(Path(path_value), Path(key_value))
                    cleanup_password = cleanup_credentials.load() or ""
                except (MqttCredentialStoreError, ValueError):
                    cleanup_credentials = None
        home_value = os.getenv("LBHOMEDIR", "").strip()
        home = Path(home_value)
        previous_broker = None
        if cleanup_required and (not previous.mqtt_use_loxberry_gateway or home.is_absolute()):
            previous_broker = mqtt_broker(previous, home=home, password=cleanup_password)
        credentials_restore_required = bool(password or clear_password)
        configuration_restore_required = True
        service_transition_attempted = False
        try:
            if password and credentials is not None:
                credentials.save(password)
            elif clear_password and credentials is not None:
                credentials.delete()
            save(updated)
            if was_active:
                service_transition_attempted = True
                if cleanup_required:
                    _stop_service()
                    cleanup_status = (
                        "completed"
                        if previous_broker is not None
                        and clear_retained_topics(previous, broker=previous_broker)
                        else "failed"
                    )
                    _start_service()
                else:
                    _restart_service()
            elif cleanup_required:
                cleanup_status = (
                    "completed"
                    if previous_broker is not None
                    and clear_retained_topics(previous, broker=previous_broker)
                    else "failed"
                )
            return updated
        except (AdminError, MqttCredentialStoreError, ValueError) as apply_error:
            rollback_error: Exception | None = None
            if configuration_restore_required:
                try:
                    save(previous)
                except ConfigError as exc:
                    rollback_error = exc
            if credentials_restore_required and credentials is not None:
                try:
                    if previous_password is None:
                        credentials.delete()
                    else:
                        credentials.save(previous_password)
                except MqttCredentialStoreError as exc:
                    rollback_error = rollback_error or exc
            if rollback_error is None and service_transition_attempted:
                try:
                    _restart_service()
                except AdminError as exc:
                    rollback_error = exc
            if rollback_error is not None:
                raise AdminError("MQTT configuration apply and rollback failed") from rollback_error
            raise AdminError(
                "MQTT configuration was not applied; previous configuration restored"
            ) from apply_error

    updated = store.transaction(apply)
    return {
        "configuration": updated.to_document(),
        "mqtt_password_configured": _mqtt_password_configured(),
        "retained_cleanup": {"status": cleanup_status},
        "applied": True,
    } | _service_response()


def _set_logging(payload: object) -> dict[str, Any]:
    from mcpserver.config import ConfigError

    if not isinstance(payload, dict) or not isinstance(payload.get("mode"), str):
        raise AdminError("logging mode is invalid")
    mode = payload["mode"]
    store = _config_store()
    previous = store.load()
    if mode not in {"off", "error", "warning", "info", "debug"}:
        raise AdminError("logging mode is invalid")
    updated = replace(previous, log_level=mode)
    store.save(updated)
    try:
        _restart_service()
    except AdminError as apply_error:
        try:
            store.save(previous)
            _restart_service()
        except (AdminError, ConfigError) as rollback_error:
            raise AdminError("logging apply and rollback failed") from rollback_error
        raise AdminError(
            "logging was not applied; previous configuration restored"
        ) from apply_error
    return {
        "configuration": updated.to_document(),
        "applied": True,
    } | _service_response()


async def _test_connection(payload: object) -> dict[str, Any]:
    from mcpserver.loxone.client import LoxoneConnectionError, MiniserverEndpoint

    if not isinstance(payload, dict) or not isinstance(payload.get("endpoint"), str):
        raise AdminError("endpoint is required")
    endpoint = MiniserverEndpoint.parse(payload["endpoint"])
    try:
        result = await _loxone_client(
            endpoint, client_uuid=_CLIENT_UUID, timeout_seconds=10
        ).probe()
    except LoxoneConnectionError as exc:
        raise AdminError(str(exc)) from None
    return {
        "reachable": True,
        "firmware": result.firmware,
        "transport": "wss" if endpoint.secure else "ws",
    }


def _admin_read_snapshot(*, require_configuration: bool = False) -> _AdminReadSnapshot:
    """Load the immutable inputs for one admin list response exactly once."""

    try:
        configuration = _config_store().load()
    except AdminError:
        if require_configuration:
            raise
        configuration = None
    document = _auth_store().snapshot()
    encoded_subject_key = document.get("subject_key")
    subject_key = (
        base64.urlsafe_b64decode(encoded_subject_key.encode("ascii"))
        if isinstance(encoded_subject_key, str)
        else None
    )
    return _AdminReadSnapshot(configuration, document, subject_key, time.time())


def _binding_pseudonym(subject_key: bytes, namespace: str, record: dict[str, Any]) -> str:
    canonical = "\0".join(
        (
            namespace,
            str(record.get("client_id", "")),
            str(record.get("identity_id", "")),
            str(record.get("miniserver_id", "")),
        )
    ).encode("utf-8")
    return hmac.new(subject_key, canonical, hashlib.sha256).hexdigest()


def _sessions(snapshot: _AdminReadSnapshot | None = None) -> list[dict[str, Any]]:
    from mcpserver.auth.provider import READ_SCOPE

    snapshot = snapshot or _admin_read_snapshot()
    document = snapshot.auth_document
    clients = document.get("clients", {})
    if not isinstance(clients, dict):
        clients = {}
    bindings = (
        set(snapshot.configuration.loxberry_read_bindings) if snapshot.configuration else set()
    )
    operate_bindings = (
        set(snapshot.configuration.loxberry_operate_bindings) if snapshot.configuration else set()
    )
    result = []
    for family_id, record in document["families"].items():
        expires_at = record.get("expires_at")
        if record.get("revoked"):
            continue
        client_id = str(record.get("client_id", ""))
        scopes = str(record.get("scope", "loxone:read"))
        scope_set = frozenset(scopes.split())
        pending_loxberry_read = (
            bool(record.get("pending_loxberry_read", False))
            and READ_SCOPE in scope_set
            and isinstance(expires_at, int | float)
            and expires_at > snapshot.now
        )
        pending_loxberry_operate = (
            bool(record.get("pending_loxberry_operate", False))
            and "loxone:history" in scope_set
            and "loxberry:operate" in scope_set
            and isinstance(expires_at, int | float)
            and expires_at > snapshot.now
        )
        read_binding = (
            _loxberry_binding(record, subject_key=snapshot.subject_key)
            if pending_loxberry_read and bindings and snapshot.subject_key is not None
            else None
        )
        operate_binding = (
            _loxberry_operate_binding(record, subject_key=snapshot.subject_key)
            if pending_loxberry_operate and operate_bindings and snapshot.subject_key is not None
            else None
        )
        client = clients.get(client_id, {})
        explorer_read_approved = False
        explorer_operate_approved = False
        if record.get("client_kind") == "tool_explorer" and snapshot.configuration is not None:
            from mcpserver.explorer_bindings import active_explorer_binding

            explorer_read_approved = (
                active_explorer_binding(
                    snapshot.configuration,
                    _auth_store(),
                    "loxberry:read",
                    str(record.get("identity_id", "")),
                    str(record.get("miniserver_id", "")),
                    str(record.get("explorer_origin", "")),
                    now=int(snapshot.now),
                )
                is not None
            )
            explorer_operate_approved = (
                active_explorer_binding(
                    snapshot.configuration,
                    _auth_store(),
                    "loxberry:operate",
                    str(record.get("identity_id", "")),
                    str(record.get("miniserver_id", "")),
                    str(record.get("explorer_origin", "")),
                    now=int(snapshot.now),
                )
                is not None
            )
        client_name = client.get("client_name", "") if isinstance(client, dict) else ""
        result.append(
            {
                "id": family_id,
                "client": client_id[:12],
                "client_name": (
                    client_name if isinstance(client_name, str) and client_name.strip() else ""
                ),
                "identity": str(record.get("identity_id", ""))[:12],
                "scopes": scopes,
                "expires_at": record.get("expires_at"),
                "revoked": bool(record.get("revoked", False)),
                "loxone_token_confirmation_required": record.get(
                    "loxone_token_confirmation_required"
                )
                is True
                and record.get("loxone_token_rejection_kind") == "token_authentication",
                "loxberry_read_eligible": pending_loxberry_read,
                "loxberry_read_approved": (
                    explorer_read_approved or (read_binding in bindings if read_binding else False)
                ),
                "loxberry_operate_eligible": pending_loxberry_operate,
                "loxberry_operate_approved": (
                    explorer_operate_approved
                    or (operate_binding in operate_bindings if operate_binding else False)
                ),
            }
        )
    return sorted(result, key=lambda item: str(item["id"]))


def _confirm_loxone_token(payload: object) -> dict[str, Any]:
    from mcpserver.auth.loxone_health import LoxoneTokenHealthStore

    family_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(family_id, str) or len(family_id) > 128:
        raise AdminError("session identifier is invalid")
    if not LoxoneTokenHealthStore(_auth_store()).confirm_retry(family_id):
        raise AdminError("Loxone token confirmation is unavailable")
    return {"sessions": _sessions()}


def _loxberry_binding(record: dict[str, Any], *, subject_key: bytes | None = None) -> str:
    if subject_key is not None:
        return _binding_pseudonym(subject_key, "loxberry-read-binding-v1", record)
    return _auth_store().pseudonym(
        "loxberry-read-binding-v1",
        str(record.get("client_id", "")),
        str(record.get("identity_id", "")),
        str(record.get("miniserver_id", "")),
    )


def _loxberry_operate_binding(record: dict[str, Any], *, subject_key: bytes | None = None) -> str:
    if subject_key is not None:
        return _binding_pseudonym(subject_key, "loxberry-operate-binding-v1", record)
    return _auth_store().pseudonym(
        "loxberry-operate-binding-v1",
        str(record.get("client_id", "")),
        str(record.get("identity_id", "")),
        str(record.get("miniserver_id", "")),
    )


def _binding_rows(binding: str, sessions: list[dict[str, str]]) -> list[dict[str, Any]]:
    if sessions:
        return [
            {
                **session,
                "binding_id": binding,
                "fingerprint": binding[:12],
                "inactive": False,
            }
            for session in sessions
        ]
    return [
        {
            "client": binding[:12],
            "client_name": "",
            "identity": "",
            "binding_id": binding,
            "fingerprint": binding[:12],
            "inactive": True,
        }
    ]


def _explorer_binding_rows(
    binding: str,
    sessions: list[dict[str, str]],
    *,
    inactive_since: int | None,
    expires_at: int | None,
) -> list[dict[str, Any]]:
    rows = _binding_rows(binding, sessions)
    for row in rows:
        row["explorer_application"] = True
        row["inactive_login_required"] = not sessions
        row["inactive_since"] = inactive_since
        row["retention_expires_at"] = expires_at
        if not sessions:
            row["client_name"] = "LoxBerry MCP Tool Explorer"
    return rows


def _loxberry_bindings(snapshot: _AdminReadSnapshot | None = None) -> list[dict[str, Any]]:
    from mcpserver.auth.provider import LOXBERRY_READ_SCOPE

    snapshot = snapshot or _admin_read_snapshot()
    bindings = snapshot.configuration.loxberry_read_bindings if snapshot.configuration else ()
    explorer_approvals = tuple(
        item
        for item in (snapshot.configuration.explorer_bindings if snapshot.configuration else ())
        if item.capability == LOXBERRY_READ_SCOPE
    )
    if not bindings and not explorer_approvals:
        return []
    document = snapshot.auth_document
    clients = document.get("clients", {})
    if not isinstance(clients, dict):
        clients = {}
    related: dict[str, list[dict[str, str]]] = {binding: [] for binding in bindings}
    for record in document.get("families", {}).values():
        if not isinstance(record, dict) or record.get("revoked", False):
            continue
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, int | float) or expires_at <= snapshot.now:
            continue
        if LOXBERRY_READ_SCOPE not in str(record.get("scope", "")).split():
            continue
        if snapshot.subject_key is None:
            continue
        binding = _loxberry_binding(record, subject_key=snapshot.subject_key)
        if binding not in related:
            continue
        client_id = str(record.get("client_id", ""))
        client = clients.get(client_id, {})
        client_name = client.get("client_name", "") if isinstance(client, dict) else ""
        related[binding].append(
            {
                "client": client_id[:12],
                "client_name": client_name
                if isinstance(client_name, str) and client_name.strip()
                else "",
                "identity": str(record.get("identity_id", ""))[:12],
                "scopes": str(record.get("scope", "")),
            }
        )
    legacy = [
        {
            "id": binding,
            "fingerprint": binding[:12],
            "active": bool(related[binding]),
            "sessions": related[binding],
            "rows": _binding_rows(binding, related[binding]),
        }
        for binding in bindings
    ]
    from mcpserver.explorer_bindings import explorer_binding_id

    explorer_related: dict[str, list[dict[str, str]]] = {
        item.binding_id: [] for item in explorer_approvals
    }
    for record in document.get("families", {}).values():
        if (
            not isinstance(record, dict)
            or record.get("client_kind") != "tool_explorer"
            or record.get("revoked", False)
            or not isinstance(record.get("expires_at"), int | float)
            or record["expires_at"] <= snapshot.now
            or LOXBERRY_READ_SCOPE not in str(record.get("scope", "")).split()
        ):
            continue
        binding = explorer_binding_id(
            _auth_store(),
            LOXBERRY_READ_SCOPE,
            str(record.get("identity_id", "")),
            str(record.get("miniserver_id", "")),
            str(record.get("explorer_origin", "")),
        )
        if binding in explorer_related:
            explorer_related[binding].append(
                {
                    "client": str(record.get("client_id", ""))[:12],
                    "client_name": "LoxBerry MCP Tool Explorer",
                    "identity": str(record.get("identity_id", ""))[:12],
                    "scopes": str(record.get("scope", "")),
                }
            )
    retention = (
        snapshot.configuration.explorer_binding_retention_hours * 3600
        if snapshot.configuration
        else 0
    )
    return legacy + [
        {
            "id": item.binding_id,
            "fingerprint": item.binding_id[:12],
            "active": bool(explorer_related[item.binding_id]),
            "legacy": False,
            "sessions": explorer_related[item.binding_id],
            "rows": _explorer_binding_rows(
                item.binding_id,
                explorer_related[item.binding_id],
                inactive_since=item.inactive_since,
                expires_at=(
                    item.inactive_since + retention if item.inactive_since is not None else None
                ),
            ),
        }
        for item in explorer_approvals
    ]


def _loxberry_operate_bindings(snapshot: _AdminReadSnapshot | None = None) -> list[dict[str, Any]]:
    from mcpserver.auth.provider import LOXBERRY_OPERATE_SCOPE

    snapshot = snapshot or _admin_read_snapshot()
    bindings = snapshot.configuration.loxberry_operate_bindings if snapshot.configuration else ()
    explorer_approvals = tuple(
        item
        for item in (snapshot.configuration.explorer_bindings if snapshot.configuration else ())
        if item.capability == LOXBERRY_OPERATE_SCOPE
    )
    if not bindings and not explorer_approvals:
        return []
    document = snapshot.auth_document
    related: dict[str, list[dict[str, str]]] = {binding: [] for binding in bindings}
    clients = document.get("clients", {})
    for record in document.get("families", {}).values():
        if not isinstance(record, dict) or record.get("revoked", False):
            continue
        if (
            not isinstance(record.get("expires_at"), int | float)
            or record["expires_at"] <= snapshot.now
        ):
            continue
        if LOXBERRY_OPERATE_SCOPE not in str(record.get("scope", "")).split():
            continue
        if snapshot.subject_key is None:
            continue
        binding = _loxberry_operate_binding(record, subject_key=snapshot.subject_key)
        if binding not in related:
            continue
        client_id = str(record.get("client_id", ""))
        client = clients.get(client_id, {}) if isinstance(clients, dict) else {}
        name = client.get("client_name", "") if isinstance(client, dict) else ""
        related[binding].append(
            {
                "client": client_id[:12],
                "client_name": name if isinstance(name, str) else "",
                "identity": str(record.get("identity_id", ""))[:12],
                "scopes": str(record.get("scope", "")),
            }
        )
    legacy = [
        {
            "id": binding,
            "fingerprint": binding[:12],
            "active": bool(related[binding]),
            "sessions": related[binding],
            "rows": _binding_rows(binding, related[binding]),
        }
        for binding in bindings
    ]
    from mcpserver.explorer_bindings import explorer_binding_id

    explorer_related: dict[str, list[dict[str, str]]] = {
        item.binding_id: [] for item in explorer_approvals
    }
    for record in document.get("families", {}).values():
        if (
            not isinstance(record, dict)
            or record.get("client_kind") != "tool_explorer"
            or record.get("revoked", False)
            or not isinstance(record.get("expires_at"), int | float)
            or record["expires_at"] <= snapshot.now
            or LOXBERRY_OPERATE_SCOPE not in str(record.get("scope", "")).split()
        ):
            continue
        binding = explorer_binding_id(
            _auth_store(),
            LOXBERRY_OPERATE_SCOPE,
            str(record.get("identity_id", "")),
            str(record.get("miniserver_id", "")),
            str(record.get("explorer_origin", "")),
        )
        if binding in explorer_related:
            explorer_related[binding].append(
                {
                    "client": str(record.get("client_id", ""))[:12],
                    "client_name": "LoxBerry MCP Tool Explorer",
                    "identity": str(record.get("identity_id", ""))[:12],
                    "scopes": str(record.get("scope", "")),
                }
            )
    retention = (
        snapshot.configuration.explorer_binding_retention_hours * 3600
        if snapshot.configuration
        else 0
    )
    return legacy + [
        {
            "id": item.binding_id,
            "fingerprint": item.binding_id[:12],
            "active": bool(explorer_related[item.binding_id]),
            "legacy": False,
            "sessions": explorer_related[item.binding_id],
            "rows": _explorer_binding_rows(
                item.binding_id,
                explorer_related[item.binding_id],
                inactive_since=item.inactive_since,
                expires_at=(
                    item.inactive_since + retention if item.inactive_since is not None else None
                ),
            ),
        }
        for item in explorer_approvals
    ]


def _allow_loxberry_read(payload: object) -> dict[str, Any]:
    from mcpserver.auth.provider import READ_SCOPE

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or len(session_id) > 128:
        raise AdminError("session identifier is invalid")
    document = _auth_store().snapshot()
    record = document.get("families", {}).get(session_id)
    if (
        not isinstance(record, dict)
        or record.get("revoked", False)
        or not isinstance(record.get("expires_at"), int | float)
        or record["expires_at"] <= time.time()
        or not bool(record.get("pending_loxberry_read", False))
        or READ_SCOPE not in str(record.get("scope", "")).split()
    ):
        raise AdminError("pending diagnostic session is unavailable")
    if record.get("client_kind") == "tool_explorer":
        from mcpserver.explorer_bindings import record_explorer_approval

        try:
            record_explorer_approval(
                _config_store(), _auth_store(), "loxberry:read", record, now=int(time.time())
            )
        except ValueError as exc:
            raise AdminError(str(exc)) from exc
        return {"loxberry_bindings": _loxberry_bindings(), "sessions": _sessions()}
    binding = _loxberry_binding(record)

    def add_binding(previous: PluginConfig) -> PluginConfig:
        if binding in previous.loxberry_read_bindings:
            return previous
        if len(previous.loxberry_read_bindings) >= 64:
            raise AdminError("LoxBerry approval capacity reached")
        return replace(
            previous,
            loxberry_read_bindings=(*previous.loxberry_read_bindings, binding),
        )

    _config_store().mutate(add_binding)
    return {"loxberry_bindings": _loxberry_bindings(), "sessions": _sessions()}


def _revoke_loxberry_read(payload: object) -> dict[str, Any]:
    from mcpserver.explorer_bindings import explorer_binding_id

    binding = payload.get("binding_id") if isinstance(payload, dict) else None
    if not isinstance(binding, str) or len(binding) != 64:
        raise AdminError("LoxBerry approval is invalid")

    def remove_binding(previous: PluginConfig) -> PluginConfig:
        explorer_matches = tuple(
            item
            for item in previous.explorer_bindings
            if not (item.capability == "loxberry:read" and item.binding_id == binding)
        )
        if binding not in previous.loxberry_read_bindings and len(explorer_matches) == len(
            previous.explorer_bindings
        ):
            raise AdminError("LoxBerry approval is unavailable")
        return replace(
            previous,
            loxberry_read_bindings=tuple(
                item for item in previous.loxberry_read_bindings if item != binding
            ),
            explorer_bindings=explorer_matches,
        )

    updated_config = _config_store().mutate(remove_binding)
    document = _auth_store().snapshot()
    families = [
        family_id
        for family_id, record in document.get("families", {}).items()
        if isinstance(record, dict)
        and not record.get("revoked", False)
        and (
            _loxberry_binding(record) == binding
            or (
                record.get("client_kind") == "tool_explorer"
                and explorer_binding_id(
                    _auth_store(),
                    "loxberry:read",
                    str(record.get("identity_id", "")),
                    str(record.get("miniserver_id", "")),
                    str(record.get("explorer_origin", "")),
                )
                == binding
            )
        )
    ]
    if families:
        _revoke_many(
            families,
            endpoint=updated_config.loxone_endpoint,
            timeout_seconds=updated_config.connection_timeout,
        )
    return {"loxberry_bindings": _loxberry_bindings(), "sessions": _sessions()}


def _allow_loxberry_operate(payload: object) -> dict[str, Any]:
    from mcpserver.auth.provider import HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or len(session_id) > 128:
        raise AdminError("session identifier is invalid")
    document = _auth_store().snapshot()
    record = document.get("families", {}).get(session_id)
    scopes = str(record.get("scope", "")).split() if isinstance(record, dict) else []
    if (
        not isinstance(record, dict)
        or record.get("revoked", False)
        or not isinstance(record.get("expires_at"), int | float)
        or record["expires_at"] <= time.time()
        or not bool(record.get("pending_loxberry_operate", False))
        or HISTORY_SCOPE not in scopes
        or LOXBERRY_OPERATE_SCOPE not in scopes
    ):
        raise AdminError("pending operation session is unavailable")
    if record.get("client_kind") == "tool_explorer":
        from mcpserver.explorer_bindings import record_explorer_approval

        try:
            record_explorer_approval(
                _config_store(), _auth_store(), "loxberry:operate", record, now=int(time.time())
            )
        except ValueError as exc:
            raise AdminError(str(exc)) from exc
        return {
            "sessions": _sessions(),
            "loxberry_operate_bindings": _loxberry_operate_bindings(),
        }
    binding = _loxberry_operate_binding(record)

    def add_binding(previous: PluginConfig) -> PluginConfig:
        if binding in previous.loxberry_operate_bindings:
            return previous
        if len(previous.loxberry_operate_bindings) >= 64:
            raise AdminError("LoxBerry operation approval capacity reached")
        return replace(
            previous,
            loxberry_operate_bindings=(*previous.loxberry_operate_bindings, binding),
        )

    _config_store().mutate(add_binding)
    return {
        "sessions": _sessions(),
        "loxberry_operate_bindings": _loxberry_operate_bindings(),
    }


def _revoke_loxberry_operate(payload: object) -> dict[str, Any]:
    from mcpserver.auth.provider import LOXBERRY_OPERATE_SCOPE
    from mcpserver.explorer_bindings import explorer_binding_id

    binding = payload.get("binding_id") if isinstance(payload, dict) else None
    if not isinstance(binding, str) or len(binding) != 64:
        raise AdminError("LoxBerry operation approval is invalid")

    def remove_binding(previous: PluginConfig) -> PluginConfig:
        explorer_matches = tuple(
            item
            for item in previous.explorer_bindings
            if not (item.capability == "loxberry:operate" and item.binding_id == binding)
        )
        if binding not in previous.loxberry_operate_bindings and len(explorer_matches) == len(
            previous.explorer_bindings
        ):
            raise AdminError("LoxBerry operation approval is unavailable")
        return replace(
            previous,
            loxberry_operate_bindings=tuple(
                item for item in previous.loxberry_operate_bindings if item != binding
            ),
            explorer_bindings=explorer_matches,
        )

    updated_config = _config_store().mutate(remove_binding)
    document = _auth_store().snapshot()
    families = [
        family_id
        for family_id, record in document.get("families", {}).items()
        if isinstance(record, dict)
        and not record.get("revoked", False)
        and LOXBERRY_OPERATE_SCOPE in str(record.get("scope", "")).split()
        and (
            _loxberry_operate_binding(record) == binding
            or (
                record.get("client_kind") == "tool_explorer"
                and explorer_binding_id(
                    _auth_store(),
                    "loxberry:operate",
                    str(record.get("identity_id", "")),
                    str(record.get("miniserver_id", "")),
                    str(record.get("explorer_origin", "")),
                )
                == binding
            )
        )
    ]
    if families:
        _revoke_many(
            families,
            endpoint=updated_config.loxone_endpoint,
            timeout_seconds=updated_config.connection_timeout,
        )
    return {
        "sessions": _sessions(),
        "loxberry_operate_bindings": _loxberry_operate_bindings(),
    }


def _revoke(
    family_id: str | None,
    *,
    endpoint: str | None = None,
    timeout_seconds: float | None = None,
) -> int:
    return _revoke_many(
        None if family_id is None else [family_id],
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )


def _revoke_many(
    family_ids: list[str] | None,
    *,
    endpoint: str | None = None,
    timeout_seconds: float | None = None,
) -> int:
    from mcpserver.auth.loxone_store import LoxoneTokenStoreError

    revoked: list[str] = []

    def mutate(document: dict[str, Any]) -> None:
        targets = (
            family_ids
            if family_ids is not None
            else [key for key, item in document["families"].items() if not item.get("revoked")]
        )
        for target in targets:
            family = document["families"].get(target)
            if family is None:
                continue
            family["revoked"] = True
            family["revoked_at"] = int(time.time())
            revoked.append(target)
            for collection in ("codes", "access_tokens", "refresh_tokens"):
                for record in document[collection].values():
                    if record.get("family_id") == target:
                        record["status"] = "revoked"

    _auth_store().mutate(mutate)
    try:
        token_store = _token_store()
    except LoxoneTokenStoreError:
        token_store = None
    if token_store is not None:
        for target in revoked:
            with suppress(LoxoneTokenStoreError):
                token_store.schedule_remote_revoke(target)
    return len(revoked)


def _diagnostic() -> dict[str, Any]:
    from mcpserver.loxone.client import MiniserverEndpoint

    config = _config_store().load()
    endpoint = MiniserverEndpoint.parse(config.loxone_endpoint) if config.loxone_endpoint else None
    return {
        "schema_version": 2,
        "plugin_version": __version__,
        "service_active": _service_active(),
        "enabled": config.enabled,
        "transport": ("wss" if endpoint is not None and endpoint.secure else "ws")
        if endpoint is not None
        else "not_configured",
        "session_count": len(_sessions()),
    }


def dispatch(request: object, *, timing: dict[str, float] | None = None) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("action"), str):
        raise AdminError("request is invalid")
    action = request["action"]
    payload = request.get("payload", {})
    if action == "page_state":
        return {
            "mqtt_gateway": _mqtt_gateway_status(),
            "mqtt_password_configured": _mqtt_password_configured(),
        }
    if action == "get_config":
        store = _config_store()
        if timing is None:
            configuration = store.load()
        else:
            configuration, config_timing = store.load_with_timing()
            timing.update(config_timing)
        return {"configuration": configuration.to_document()}
    if action == "save_config":
        return _save(payload)
    if action == "save_mcp_config":
        return _save_mcp(payload)
    if action == "save_mqtt_config":
        return _save_mqtt(payload)
    if action == "emergency_stop_options":
        return _emergency_stop_options()
    if action == "clear_event_history":
        return _clear_event_history()
    if action == "set_logging":
        return _set_logging(payload)
    if action == "status":
        return {
            "version": __version__,
            "sessions": _sessions(),
            "certificate": _certificate_status(),
        } | _service_response()
    if action == "service_status":
        return _service_response()
    if action == "service_action":
        return _service_action(payload)
    if action == "set_service_enabled":
        return _set_service_enabled(payload)
    if action == "test_connection":
        return asyncio.run(_test_connection(payload))
    if action == "list_sessions":
        snapshot = _admin_read_snapshot()
        return {
            "sessions": _sessions(snapshot),
            "loxberry_bindings": _loxberry_bindings(snapshot),
            "loxberry_operate_bindings": _loxberry_operate_bindings(snapshot),
        }
    if action == "allow_loxberry_read":
        return _allow_loxberry_read(payload)
    if action == "revoke_loxberry_read":
        return _revoke_loxberry_read(payload)
    if action == "allow_loxberry_operate":
        return _allow_loxberry_operate(payload)
    if action == "revoke_loxberry_operate":
        return _revoke_loxberry_operate(payload)
    if action == "revoke_session":
        family_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(family_id, str) or len(family_id) > 128:
            raise AdminError("session identifier is invalid")
        return {"revoked": _revoke(family_id), "sessions": _sessions()}
    if action == "confirm_loxone_token":
        return _confirm_loxone_token(payload)
    if action == "revoke_all":
        return {"revoked": _revoke(None), "sessions": _sessions()}
    if action == "diagnostic":
        return _diagnostic()
    if action == "certificate_status":
        return {"certificate": _certificate_status()}
    if action == "renew_certificate":
        return _renew_certificate(payload)
    raise AdminError("action is not supported")


def main() -> None:
    request_started = time.perf_counter_ns()
    timing: dict[str, float] = {}
    action: str | None = None
    try:
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise AdminError("request is too large")
        request = json.loads(raw)
        action = request.get("action") if isinstance(request, dict) else None
        response = {"ok": True, "data": dispatch(request, timing=timing)}
    except AdminError as exc:
        response = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except (ValueError, json.JSONDecodeError) as exc:
        response = {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
    except Exception:
        response = {
            "ok": False,
            "error": {"code": "internal_error", "message": "administrative action failed"},
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
    if action == "get_config":
        helper_started = os.getenv("MCPSERVER_ADMIN_STARTED_NS", "")
        try:
            bootstrap_ms = (int(_MODULE_IMPORT_STARTED_NS) - int(helper_started)) / 1_000_000
        except ValueError:
            bootstrap_ms = None
        timing.update(
            {
                "module_import_ms": (_MODULE_IMPORT_FINISHED_NS - _MODULE_IMPORT_STARTED_NS)
                / 1_000_000,
                "request_dispatch_ms": (time.perf_counter_ns() - request_started) / 1_000_000,
            }
        )
        if bootstrap_ms is not None and bootstrap_ms >= 0:
            timing["process_bootstrap_ms"] = bootstrap_ms
        sys.stderr.write(
            "mcpserver_admin_timing="
            + json.dumps(timing, ensure_ascii=True, separators=(",", ":"))
            + "\n"
        )


if __name__ == "__main__":
    main()
