"""Narrow JSON stdin/stdout boundary used by the authenticated Perl UI."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from mcpserver import __version__
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, ConfigError, PluginConfig
from mcpserver.loxone.client import LoxoneClient, LoxoneConnectionError, MiniserverEndpoint
from mcpserver.loxone.events import LoxoneProtocolError

_MAX_REQUEST_BYTES: Final = 32 * 1024
_SERVICE: Final = "loxberry-mcpserver.service"
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")


class AdminError(RuntimeError):
    """A sanitized, user-actionable administrative error."""


def _path(name: str, *, suffix: str | None = None) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or (suffix is not None and path.suffix != suffix):
        raise AdminError("plugin storage is not configured")
    return path


def _config_store() -> AtomicConfigStore:
    return AtomicConfigStore(_path("MCPSERVER_CONFIG", suffix=".json"))


def _auth_store() -> AtomicJsonAuthStore:
    return AtomicJsonAuthStore(_path("MCPSERVER_AUTH_STORE", suffix=".json"))


def _token_store() -> EncryptedLoxoneTokenStore:
    return EncryptedLoxoneTokenStore(
        _path("MCPSERVER_LOXONE_TOKEN_STORE", suffix=".enc"),
        _path("MCPSERVER_INSTALL_KEY", suffix=".key"),
    )


def _service_active() -> bool:
    result = subprocess.run(
        ["sudo", "-n", "/bin/systemctl", "is-active", "--quiet", _SERVICE],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    return result.returncode == 0


def _restart_service() -> None:
    try:
        result = subprocess.run(
            ["sudo", "-n", "/bin/systemctl", "restart", _SERVICE],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError("the service could not be restarted") from exc
    if result.returncode != 0:
        raise AdminError("the service could not be restarted")


def _save(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AdminError("configuration payload is invalid")
    config = PluginConfig.from_document(payload)
    store = _config_store()
    previous = store.load()
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
    return {"configuration": config.to_document(), "applied": True}


async def _test_connection(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("endpoint"), str):
        raise AdminError("endpoint is required")
    endpoint = MiniserverEndpoint.parse(payload["endpoint"])
    try:
        result = await LoxoneClient(endpoint, client_uuid=_CLIENT_UUID, timeout_seconds=10).probe()
    except LoxoneConnectionError as exc:
        raise AdminError(str(exc)) from None
    return {
        "reachable": True,
        "firmware": result.firmware,
        "transport": "wss" if endpoint.secure else "ws",
    }


def _sessions() -> list[dict[str, Any]]:
    document = _auth_store().snapshot()
    result = []
    for family_id, record in document["families"].items():
        if record.get("revoked"):
            continue
        result.append(
            {
                "id": family_id,
                "client": str(record.get("client_id", ""))[:12],
                "identity": str(record.get("identity_id", ""))[:12],
                "expires_at": record.get("expires_at"),
                "revoked": bool(record.get("revoked", False)),
            }
        )
    return sorted(result, key=lambda item: str(item["id"]))


def _revoke(family_id: str | None) -> int:
    revoked: list[str] = []
    bindings: list[tuple[str, str, str]] = []

    def mutate(document: dict[str, Any]) -> None:
        targets = (
            [family_id]
            if family_id is not None
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
    if config.loxone_endpoint and token_store is not None:
        client = LoxoneClient(
            MiniserverEndpoint.parse(config.loxone_endpoint),
            client_uuid=_CLIENT_UUID,
            timeout_seconds=config.connection_timeout,
        )

        async def kill_tokens() -> None:
            for target, miniserver_id, identity_id in bindings:
                try:
                    token = token_store.get(target, miniserver_id, identity_id)
                except LoxoneTokenStoreError:
                    token = None
                if token is not None:
                    with suppress(LoxoneConnectionError, LoxoneProtocolError):
                        await client.kill_token(token)

        asyncio.run(kill_tokens())
    if token_store is not None:
        for target in revoked:
            with suppress(LoxoneTokenStoreError):
                token_store.delete(target)
    return len(revoked)


def _diagnostic() -> dict[str, Any]:
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
    if action == "get_config":
        return {"configuration": _config_store().load().to_document()}
    if action == "save_config":
        return _save(payload)
    if action == "status":
        return {"version": __version__, "service_active": _service_active()}
    if action == "test_connection":
        return asyncio.run(_test_connection(payload))
    if action == "list_sessions":
        return {"sessions": _sessions()}
    if action == "revoke_session":
        family_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(family_id, str) or len(family_id) > 128:
            raise AdminError("session identifier is invalid")
        return {"revoked": _revoke(family_id)}
    if action == "revoke_all":
        return {"revoked": _revoke(None)}
    if action == "diagnostic":
        return _diagnostic()
    raise AdminError("action is not supported")


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise AdminError("request is too large")
        response = {"ok": True, "data": dispatch(json.loads(raw))}
    except (AdminError, ConfigError, ValueError, json.JSONDecodeError) as exc:
        response = {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
    except Exception:
        response = {
            "ok": False,
            "error": {"code": "internal_error", "message": "administrative action failed"},
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
