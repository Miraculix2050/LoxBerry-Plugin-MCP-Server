"""Narrow JSON stdin/stdout boundary used by the authenticated Perl UI."""

from __future__ import annotations

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
import time
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from mcpserver import __version__

if TYPE_CHECKING:
    from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.config import AtomicConfigStore, PluginConfig
    from mcpserver.loxone.client import LoxoneClient, MiniserverEndpoint

_MAX_REQUEST_BYTES: Final = 32 * 1024
_SERVICE: Final = "loxberry-mcpserver.service"
_SERVICE_ACTIONS: Final = frozenset({"restart"})
_SYSTEMD_COMMANDS: Final = frozenset({"enable", "disable", "start", "stop", "restart"})
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")


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
    return {"service_active": service["active"], "service": service}


def _mqtt_gateway_status() -> dict[str, Any]:
    """Report only availability; broker credentials never enter the admin response."""
    from mcpserver.mqtt_health import MqttGateway

    home = os.getenv("LBHOMEDIR", "").strip()
    home_path = Path(home)
    gateway = MqttGateway.from_loxberry_home(home_path) if home_path.is_absolute() else None
    if gateway is None:
        return {"gateway_configured": False}
    return {"gateway_configured": True, "host": gateway.host, "port": gateway.port}


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


def _service_action(payload: object) -> dict[str, Any]:
    command = payload.get("command") if isinstance(payload, dict) else None
    if not isinstance(command, str) or command not in _SERVICE_ACTIONS:
        raise AdminError("service action is invalid")
    _run_service_command(command)
    return _service_response()


def _set_service_enabled(payload: object) -> dict[str, Any]:
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    if not isinstance(enabled, bool):
        raise AdminError("service enabled state is invalid")
    commands = ("enable", "start") if enabled else ("stop", "disable")
    for command in commands:
        _run_service_command(command)
    return _service_response()


def _restart_service() -> None:
    try:
        _run_service_command("restart")
    except AdminError as exc:
        raise AdminError("the service could not be restarted") from exc


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
    from mcpserver.config import PluginConfig

    if not isinstance(payload, dict):
        raise AdminError("configuration payload is invalid")
    candidate = PluginConfig.from_document(payload)
    store = _config_store()
    previous = store.load()
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
        "max_parallel_calls",
        "statistics_memory_max_mib",
        "structure_refresh_seconds",
        "max_active_runtime_sessions",
        "runtime_session_idle_seconds",
        "max_structure_controls",
        "max_structure_state_references",
        "max_structure_depth",
        "max_states_per_identity",
    )

    def apply(current: PluginConfig) -> PluginConfig:
        return replace(current, **{field: getattr(candidate, field) for field in fields})

    updated = store.mutate(apply)
    try:
        if _service_active():
            _restart_service()
    except AdminError as exc:
        store.save(previous)
        raise AdminError(
            "MCP configuration was not applied; previous configuration restored"
        ) from exc
    return {"configuration": updated.to_document(), "applied": True} | _service_response()


def _save_mqtt(payload: object) -> dict[str, Any]:
    """Atomically apply MQTT settings and separately protect an optional password."""
    from mcpserver.config import PluginConfig
    from mcpserver.mqtt_health import MqttCredentialStore, MqttCredentialStoreError

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
    previous_password: str | None = None
    if password or clear_password:
        path_value = os.getenv("MCPSERVER_MQTT_CREDENTIALS", "").strip()
        key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
        if not path_value or not key_value:
            raise AdminError("MQTT credential storage is unavailable")
        credentials = MqttCredentialStore(Path(path_value), Path(key_value))
        previous_password = credentials.load()
    store = _config_store()
    previous = store.load()
    updated = store.mutate(
        lambda current: replace(
            current,
            mqtt_enabled=candidate.mqtt_enabled,
            mqtt_root_topic=candidate.mqtt_root_topic,
            mqtt_heartbeat_seconds=candidate.mqtt_heartbeat_seconds,
            mqtt_use_loxberry_gateway=candidate.mqtt_use_loxberry_gateway,
            mqtt_host=candidate.mqtt_host,
            mqtt_port=candidate.mqtt_port,
            mqtt_username=candidate.mqtt_username,
        )
    )
    try:
        if password and credentials is not None:
            credentials.save(password)
        elif clear_password and credentials is not None:
            credentials.delete()
        if _service_active():
            _restart_service()
    except (AdminError, MqttCredentialStoreError, ValueError) as exc:
        store.save(previous)
        if credentials is not None:
            try:
                if previous_password is None:
                    credentials.delete()
                else:
                    credentials.save(previous_password)
            except MqttCredentialStoreError:
                pass
        raise AdminError(
            "MQTT configuration was not applied; previous configuration restored"
        ) from exc
    return {
        "configuration": updated.to_document(),
        "mqtt_password_configured": _mqtt_password_configured(),
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
                "loxberry_read_approved": read_binding in bindings if read_binding else False,
                "loxberry_operate_eligible": pending_loxberry_operate,
                "loxberry_operate_approved": (
                    operate_binding in operate_bindings if operate_binding else False
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


def _loxberry_bindings(snapshot: _AdminReadSnapshot | None = None) -> list[dict[str, Any]]:
    from mcpserver.auth.provider import LOXBERRY_READ_SCOPE

    snapshot = snapshot or _admin_read_snapshot()
    bindings = snapshot.configuration.loxberry_read_bindings if snapshot.configuration else ()
    if not bindings:
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
    return [
        {
            "id": binding,
            "fingerprint": binding[:12],
            "active": bool(related[binding]),
            "sessions": related[binding],
            "rows": _binding_rows(binding, related[binding]),
        }
        for binding in bindings
    ]


def _loxberry_operate_bindings(snapshot: _AdminReadSnapshot | None = None) -> list[dict[str, Any]]:
    from mcpserver.auth.provider import LOXBERRY_OPERATE_SCOPE

    snapshot = snapshot or _admin_read_snapshot()
    bindings = snapshot.configuration.loxberry_operate_bindings if snapshot.configuration else ()
    if not bindings:
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
    return [
        {
            "id": binding,
            "fingerprint": binding[:12],
            "active": bool(related[binding]),
            "sessions": related[binding],
            "rows": _binding_rows(binding, related[binding]),
        }
        for binding in bindings
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
    binding = payload.get("binding_id") if isinstance(payload, dict) else None
    if not isinstance(binding, str) or len(binding) != 64:
        raise AdminError("LoxBerry approval is invalid")

    def remove_binding(previous: PluginConfig) -> PluginConfig:
        if binding not in previous.loxberry_read_bindings:
            raise AdminError("LoxBerry approval is unavailable")
        return replace(
            previous,
            loxberry_read_bindings=tuple(
                item for item in previous.loxberry_read_bindings if item != binding
            ),
        )

    updated_config = _config_store().mutate(remove_binding)
    document = _auth_store().snapshot()
    families = [
        family_id
        for family_id, record in document.get("families", {}).items()
        if isinstance(record, dict)
        and not record.get("revoked", False)
        and _loxberry_binding(record) == binding
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

    binding = payload.get("binding_id") if isinstance(payload, dict) else None
    if not isinstance(binding, str) or len(binding) != 64:
        raise AdminError("LoxBerry operation approval is invalid")

    def remove_binding(previous: PluginConfig) -> PluginConfig:
        if binding not in previous.loxberry_operate_bindings:
            raise AdminError("LoxBerry operation approval is unavailable")
        return replace(
            previous,
            loxberry_operate_bindings=tuple(
                item for item in previous.loxberry_operate_bindings if item != binding
            ),
        )

    updated_config = _config_store().mutate(remove_binding)
    document = _auth_store().snapshot()
    families = [
        family_id
        for family_id, record in document.get("families", {}).items()
        if isinstance(record, dict)
        and not record.get("revoked", False)
        and LOXBERRY_OPERATE_SCOPE in str(record.get("scope", "")).split()
        and _loxberry_operate_binding(record) == binding
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


def dispatch(request: object) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("action"), str):
        raise AdminError("request is invalid")
    action = request["action"]
    payload = request.get("payload", {})
    if action == "page_state":
        snapshot = _admin_read_snapshot(require_configuration=True)
        if snapshot.configuration is None:
            raise AdminError("plugin storage is not configured")
        return {
            "configuration": snapshot.configuration.to_document(),
            "version": __version__,
            "sessions": _sessions(snapshot),
            "loxberry_bindings": _loxberry_bindings(snapshot),
            "loxberry_operate_bindings": _loxberry_operate_bindings(snapshot),
            "certificate": _certificate_status(configuration=snapshot.configuration),
            "mqtt_gateway": _mqtt_gateway_status(),
            "mqtt_password_configured": _mqtt_password_configured(),
        } | _service_response()
    if action == "get_config":
        return {"configuration": _config_store().load().to_document()}
    if action == "save_config":
        return _save(payload)
    if action == "save_mcp_config":
        return _save_mcp(payload)
    if action == "save_mqtt_config":
        return _save_mqtt(payload)
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
    try:
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise AdminError("request is too large")
        response = {"ok": True, "data": dispatch(json.loads(raw))}
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


if __name__ == "__main__":
    main()
