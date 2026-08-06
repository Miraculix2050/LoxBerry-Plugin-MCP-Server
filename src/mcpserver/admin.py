"""Narrow JSON stdin/stdout boundary used by the authenticated Perl UI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from mcpserver import __version__

if TYPE_CHECKING:
    from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.config import AtomicConfigStore
    from mcpserver.loxone.client import LoxoneClient, MiniserverEndpoint

_MAX_REQUEST_BYTES: Final = 32 * 1024
_SERVICE: Final = "loxberry-mcpserver.service"
_SERVICE_ACTIONS: Final = frozenset({"start", "stop", "restart"})
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")


class AdminError(RuntimeError):
    """A sanitized, user-actionable administrative error."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


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
    pid = int(raw_pid) if raw_pid.isdecimal() and int(raw_pid) > 0 else None
    status.update(
        installed=load_state not in {"not-found", "unknown", ""},
        active_state=active_state or "unknown",
        sub_state=sub_state or "unknown",
        pid=pid,
        active=active_state == "active",
    )
    return status


def _service_active() -> bool:
    return bool(_service_status()["active"])


def _run_service_command(command: str) -> None:
    if command not in _SERVICE_ACTIONS:
        raise AdminError("service action is invalid")
    try:
        result = subprocess.run(
            ["sudo", "-n", "/bin/systemctl", command, _SERVICE],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError("the service action failed", code="service_action_failed") from exc
    if result.returncode != 0:
        raise AdminError("the service action failed", code="service_action_failed")


def _service_response() -> dict[str, Any]:
    service = _service_status()
    return {"service_active": service["active"], "service": service}


def _service_action(payload: object) -> dict[str, Any]:
    command = payload.get("command") if isinstance(payload, dict) else None
    if not isinstance(command, str) or command not in _SERVICE_ACTIONS:
        raise AdminError("service action is invalid")
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


def _certificate_status() -> dict[str, Any]:
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
    config = _config_store().load()
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
    from mcpserver.auth.provider import CONTROL_SCOPE
    from mcpserver.config import ConfigError, PluginConfig

    if not isinstance(payload, dict):
        raise AdminError("configuration payload is invalid")
    config = PluginConfig.from_document(payload)
    store = _config_store()
    previous = store.load()
    control_families: list[str] = []
    if previous.loxone_control_enabled and not config.loxone_control_enabled:
        document = _auth_store().snapshot()
        control_families = [
            family_id
            for family_id, record in document["families"].items()
            if CONTROL_SCOPE in str(record.get("scope", "")).split()
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
    return {
        "configuration": config.to_document(),
        "applied": True,
        "sessions": _sessions(),
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


def _sessions() -> list[dict[str, Any]]:
    document = _auth_store().snapshot()
    clients = document.get("clients", {})
    if not isinstance(clients, dict):
        clients = {}
    result = []
    for family_id, record in document["families"].items():
        if record.get("revoked"):
            continue
        client_id = str(record.get("client_id", ""))
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
                "scopes": str(record.get("scope", "loxone:read")),
                "expires_at": record.get("expires_at"),
                "revoked": bool(record.get("revoked", False)),
            }
        )
    return sorted(result, key=lambda item: str(item["id"]))


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
    from mcpserver.loxone.client import LoxoneConnectionError, MiniserverEndpoint
    from mcpserver.loxone.events import LoxoneProtocolError

    revoked: list[str] = []
    bindings: list[tuple[str, str, str]] = []

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
            bindings.append(
                (
                    target,
                    str(family.get("miniserver_id", "")),
                    str(family.get("identity_id", "")),
                )
            )
            for collection in ("codes", "access_tokens", "refresh_tokens"):
                for record in document[collection].values():
                    if record.get("family_id") == target:
                        record["status"] = "revoked"

    _auth_store().mutate(mutate)
    try:
        token_store = _token_store()
    except LoxoneTokenStoreError:
        token_store = None
    config = _config_store().load()
    selected_endpoint = endpoint if endpoint is not None else config.loxone_endpoint
    selected_timeout = timeout_seconds if timeout_seconds is not None else config.connection_timeout
    if selected_endpoint and token_store is not None:
        client = _loxone_client(
            MiniserverEndpoint.parse(selected_endpoint),
            client_uuid=_CLIENT_UUID,
            timeout_seconds=selected_timeout,
        )

        async def kill_token(binding: tuple[str, str, str]) -> None:
            target, miniserver_id, identity_id = binding
            try:
                token = token_store.get(target, miniserver_id, identity_id)
            except LoxoneTokenStoreError:
                token = None
            if token is not None:
                with suppress(
                    TimeoutError,
                    LoxoneConnectionError,
                    LoxoneProtocolError,
                ):
                    await asyncio.wait_for(
                        client.kill_token(token),
                        timeout=selected_timeout + 5,
                    )

        async def kill_tokens() -> None:
            async with asyncio.TaskGroup() as group:
                for binding in bindings:
                    group.create_task(kill_token(binding))

        asyncio.run(kill_tokens())
    if token_store is not None:
        for target in revoked:
            with suppress(LoxoneTokenStoreError):
                token_store.delete(target)
    return len(revoked)


def _diagnostic() -> dict[str, Any]:
    from mcpserver.loxone.client import MiniserverEndpoint

    config = _config_store().load()
    endpoint = MiniserverEndpoint.parse(config.loxone_endpoint) if config.loxone_endpoint else None
    return {
        "schema_version": 1,
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
        return {
            "configuration": _config_store().load().to_document(),
            "version": __version__,
            "sessions": _sessions(),
            "certificate": _certificate_status(),
        } | _service_response()
    if action == "get_config":
        return {"configuration": _config_store().load().to_document()}
    if action == "save_config":
        return _save(payload)
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
    if action == "test_connection":
        return asyncio.run(_test_connection(payload))
    if action == "list_sessions":
        return {"sessions": _sessions()}
    if action == "revoke_session":
        family_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(family_id, str) or len(family_id) > 128:
            raise AdminError("session identifier is invalid")
        return {"revoked": _revoke(family_id), "sessions": _sessions()}
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
