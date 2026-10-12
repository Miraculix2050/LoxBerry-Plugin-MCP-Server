"""Exact, live Admin delegation for local KNX data, independent of project visibility."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from mcpserver.auth.scopes import LOXBERRY_KNX_DRAFTS_SCOPE, LOXBERRY_KNX_READ_SCOPE, READ_SCOPE
from mcpserver.config import PluginConfig
from mcpserver.explorer_bindings import active_explorer_binding
from mcpserver.loxone.endpoint import MiniserverEndpoint

if TYPE_CHECKING:
    from mcpserver.auth.provider import StoredAccessToken


def read_binding_id(config: PluginConfig, auth_store: Any, family: dict[str, Any]) -> str:
    """Include the local catalog target in an independent, installation-keyed binding."""
    target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    fields = tuple(family.get(key) for key in ("client_id", "identity_id", "miniserver_id"))
    if any(not isinstance(value, str) or not value for value in fields):
        raise ValueError("KNX approval identity is incomplete")
    return str(auth_store.pseudonym("loxberry-knx-read-binding-v1", *fields, target))


def draft_binding_id(config: PluginConfig, auth_store: Any, family: dict[str, Any]) -> str:
    target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    fields = tuple(family.get(key) for key in ("client_id", "identity_id", "miniserver_id"))
    if any(not isinstance(value, str) or not value for value in fields):
        raise ValueError("KNX approval identity is incomplete")
    return str(auth_store.pseudonym("loxberry-knx-drafts-binding-v1", *fields, target))


def authorize_drafts(
    config: PluginConfig, auth_store: Any, access: StoredAccessToken, *, now: int | None = None
) -> tuple[str, str]:
    """Draft access additionally requires current, independently approved catalog reads."""
    current = int(time.time()) if now is None else now
    target = authorize_read(config, auth_store, access, now=current)
    if LOXBERRY_KNX_DRAFTS_SCOPE not in access.scopes or not config.loxberry_knx_drafts_enabled:
        raise PermissionError("Local KNX drafts are not authorized")
    family = auth_store.snapshot().get("families", {}).get(access.family_id)
    required = {READ_SCOPE, LOXBERRY_KNX_READ_SCOPE, LOXBERRY_KNX_DRAFTS_SCOPE}
    if (
        not isinstance(family, dict)
        or family.get("revoked", False)
        or family.get("expires_at", 0) <= current
        or not required <= set(str(family.get("scope", "")).split())
        or any(
            family.get(key) != getattr(access, key)
            for key in ("client_id", "identity_id", "miniserver_id")
        )
    ):
        raise PermissionError("Local KNX drafts are not authorized")
    if family.get("client_kind") == "tool_explorer":
        approved = (
            active_explorer_binding(
                config,
                auth_store,
                LOXBERRY_KNX_DRAFTS_SCOPE,
                access.identity_id,
                access.miniserver_id,
                str(family.get("explorer_origin", "")),
                now=current,
            )
            is not None
        )
    else:
        approved = (
            draft_binding_id(config, auth_store, family) in config.loxberry_knx_drafts_bindings
        )
    if not approved:
        raise PermissionError("Local KNX drafts are not authorized")
    owner = str(
        auth_store.pseudonym(
            "knx-correction-owner-v1",
            access.client_id,
            access.identity_id,
            access.miniserver_id,
            target,
        )
    )
    return target, owner


def authorize_read(
    config: PluginConfig, auth_store: Any, access: StoredAccessToken, *, now: int | None = None
) -> str:
    """Resolve fresh policy and family state; names never participate in authorization."""
    current = int(time.time()) if now is None else now
    if (
        LOXBERRY_KNX_READ_SCOPE not in access.scopes
        or READ_SCOPE not in access.scopes
        or not config.loxberry_knx_read_enabled
        or (access.expires_at is not None and access.expires_at <= current)
    ):
        raise PermissionError("Local KNX data is not authorized")
    if not config.loxone_endpoint:
        raise PermissionError("Local KNX data is not authorized")
    family = auth_store.snapshot().get("families", {}).get(access.family_id)
    if (
        not isinstance(family, dict)
        or family.get("revoked", False)
        or family.get("expires_at", 0) <= current
        or not {READ_SCOPE, LOXBERRY_KNX_READ_SCOPE} <= set(str(family.get("scope", "")).split())
        or any(
            family.get(key) != getattr(access, key)
            for key in ("client_id", "identity_id", "miniserver_id")
        )
    ):
        raise PermissionError("Local KNX data is not authorized")
    if family.get("client_kind") == "tool_explorer":
        allowed = (
            active_explorer_binding(
                config,
                auth_store,
                LOXBERRY_KNX_READ_SCOPE,
                access.identity_id,
                access.miniserver_id,
                str(family.get("explorer_origin", "")),
                now=current,
            )
            is not None
        )
    else:
        allowed = read_binding_id(config, auth_store, family) in config.loxberry_knx_read_bindings
    if not allowed:
        raise PermissionError("Local KNX data is not authorized")
    return MiniserverEndpoint.parse(config.loxone_endpoint).origin
