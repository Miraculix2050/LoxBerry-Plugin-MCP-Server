"""Local Admin grants for exact MCP installation-profile identities."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any

from mcpserver.admin_errors import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig, binding_application_name
from mcpserver.installation_profile_write import PROFILE_CAPABILITY

_LOGGER = logging.getLogger(__name__)


def dispatch_permissions(
    action: str, payload: dict[str, Any], store: AtomicConfigStore
) -> dict[str, Any]:
    from mcpserver.admin import _auth_store, _loxberry_operate_binding, _sessions

    auth = _auth_store()
    config = store.load()

    def active() -> list[dict[str, Any]]:
        return [
            session
            for session in _sessions()
            if session["loxberry_operate_approved"]
            and "loxone:read" in session["scopes"].split()
            and isinstance(session["expires_at"], int | float)
            and session["expires_at"] > time.time()
        ]

    if action != "profile_permissions":
        if payload.get("confirm") is not True:
            raise AdminError("Explicit confirmation is required")
        eligible_ids = (
            {item["id"] for item in active()} if action == "profile_permission_allow" else set()
        )

        def change(current: PluginConfig) -> PluginConfig:
            if action == "profile_permission_enable":
                if set(payload) != {"enabled", "confirm"} or type(payload["enabled"]) is not bool:
                    raise AdminError("Profile permission request is invalid")
                return replace(current, installation_profile_write_enabled=payload["enabled"])
            if action == "profile_permission_allow":
                if set(payload) != {"session_id", "confirm"}:
                    raise AdminError("Profile permission request is invalid")
                session_id = payload["session_id"]
                if not isinstance(session_id, str) or len(session_id) > 128:
                    raise AdminError("Profile session is unavailable")
                if session_id not in eligible_ids:
                    raise AdminError("Profile session is unavailable")
                record = auth.snapshot()["families"].get(session_id, {})
                if record.get("revoked") or record.get("expires_at", 0) <= time.time():
                    raise AdminError("Profile session is unavailable")
                parts = [record.get(key) for key in ("client_id", "identity_id", "miniserver_id")]
                if not all(isinstance(value, str) and value for value in parts):
                    raise AdminError("Profile session is unavailable")
                scopes = str(record.get("scope", "")).split()
                if (
                    not {"loxone:read", "loxone:history", "loxberry:operate"}.issubset(scopes)
                    or not current.loxberry_operate_enabled
                ):
                    raise AdminError("Profile session is unavailable")
                if record.get("client_kind") == "tool_explorer":
                    from mcpserver.explorer_bindings import active_explorer_binding

                    approved = (
                        active_explorer_binding(
                            current,
                            auth,
                            "loxberry:operate",
                            parts[1],
                            parts[2],
                            str(record.get("explorer_origin", "")),
                        )
                        is not None
                    )
                else:
                    approved = (
                        _loxberry_operate_binding(record) in current.loxberry_operate_bindings
                    )
                if not approved:
                    raise AdminError("Profile session is unavailable")
                binding = auth.pseudonym(PROFILE_CAPABILITY, *parts)
                bindings = current.installation_profile_write_bindings
                if binding in bindings:
                    return current
                if len(bindings) >= 64:
                    raise AdminError("Profile approval capacity reached")
                return replace(current, installation_profile_write_bindings=(*bindings, binding))
            if action == "profile_permission_revoke":
                revoke_binding = payload.get("binding_id")
                if (
                    set(payload) != {"binding_id", "confirm"}
                    or not isinstance(revoke_binding, str)
                    or revoke_binding not in current.installation_profile_write_bindings
                ):
                    raise AdminError("Profile approval is unavailable")
                return replace(
                    current,
                    installation_profile_write_bindings=tuple(
                        value
                        for value in current.installation_profile_write_bindings
                        if value != revoke_binding
                    ),
                )
            raise AdminError("Profile permission request is invalid")

        config = store.mutate(change)
        _LOGGER.warning(
            "event=installation_profile_permission action=%s outcome=committed",
            action,
            extra={"mcp_audit": True},
        )
    elif payload:
        raise AdminError("Profile permission request is invalid")

    document = auth.snapshot()
    sessions = []
    for session in active()[:128]:
        record = document["families"].get(session["id"], {})
        if not all(
            isinstance(record.get(key), str) and record[key]
            for key in ("client_id", "identity_id", "miniserver_id")
        ):
            continue
        binding = auth.pseudonym(
            PROFILE_CAPABILITY, record["client_id"], record["identity_id"], record["miniserver_id"]
        )
        sessions.append(
            {
                "id": session["id"],
                "label": (
                    f"{binding_application_name(session['client_name']) or session['client']} "
                    f"({record['client_id'][:12]} / {record['identity_id'][:12]} / "
                    f"{record['miniserver_id'][:12]})"
                ),
                "approved": binding in config.installation_profile_write_bindings,
            }
        )
    return {
        "enabled": config.installation_profile_write_enabled,
        "sessions": sessions,
        "bindings": list(config.installation_profile_write_bindings),
    }
