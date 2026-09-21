"""Reusable local approvals for the strictly validated Tool Explorer."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Final

from mcpserver.config import AtomicConfigStore, ExplorerBindingApproval, PluginConfig

TOOL_EXPLORER_APPLICATION_ID: Final = "tool-explorer-v1"
_NAMESPACES: Final = {
    "loxberry:read": "loxberry-read-explorer-binding-v1",
    "loxberry:operate": "loxberry-operate-explorer-binding-v1",
}


def explorer_binding_id(
    auth_store: Any, capability: str, identity_id: str, miniserver_id: str
) -> str:
    """Derive the installation-local application binding without retaining identifiers."""
    return str(
        auth_store.pseudonym(
            _NAMESPACES[capability], TOOL_EXPLORER_APPLICATION_ID, identity_id, miniserver_id
        )
    )


def active_explorer_binding(
    config: PluginConfig,
    auth_store: Any,
    capability: str,
    identity_id: str,
    miniserver_id: str,
    *,
    now: int | None = None,
) -> ExplorerBindingApproval | None:
    binding_id = explorer_binding_id(auth_store, capability, identity_id, miniserver_id)
    current = int(time.time()) if now is None else now
    retention = config.explorer_binding_retention_hours * 3600
    for approval in config.explorer_bindings:
        if approval.capability != capability or approval.binding_id != binding_id:
            continue
        inactive_since = approval.inactive_since
        if inactive_since is None and approval.last_active_until <= current:
            inactive_since = approval.last_active_until
        if inactive_since is not None and inactive_since + retention <= current:
            return None
        return approval
    return None


def record_explorer_approval(
    config_store: AtomicConfigStore,
    auth_store: Any,
    capability: str,
    family: dict[str, Any],
    *,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else now
    expires_at = int(family.get("expires_at", current))
    binding_id = explorer_binding_id(
        auth_store,
        capability,
        str(family.get("identity_id", "")),
        str(family.get("miniserver_id", "")),
    )

    def update(config: PluginConfig) -> PluginConfig:
        entries = list(config.explorer_bindings)
        for index, item in enumerate(entries):
            if item.capability == capability and item.binding_id == binding_id:
                entries[index] = replace(
                    item,
                    last_active_at=max(item.last_active_at, current),
                    last_active_until=max(item.last_active_until, expires_at),
                    inactive_since=None,
                )
                break
        else:
            legacy_count = len(
                config.loxberry_read_bindings
                if capability == "loxberry:read"
                else config.loxberry_operate_bindings
            )
            if legacy_count + sum(item.capability == capability for item in entries) >= 64:
                raise ValueError("LoxBerry approval capacity reached")
            entries.append(
                ExplorerBindingApproval(
                    binding_id=binding_id,
                    capability=capability,
                    application_id=TOOL_EXPLORER_APPLICATION_ID,
                    version=1,
                    created_at=current,
                    last_active_at=current,
                    last_active_until=expires_at,
                    inactive_since=None,
                )
            )
        return replace(config, explorer_bindings=tuple(entries))

    config_store.mutate(update)
    return binding_id


def maintain_explorer_bindings(
    config_store: AtomicConfigStore, auth_store: Any, *, now: int | None = None
) -> int:
    """Reconcile active families and remove Explorer approvals past retention."""
    current = int(time.time()) if now is None else now
    document = auth_store.snapshot()
    active: set[tuple[str, str]] = set()
    ended: dict[tuple[str, str], int] = {}
    for family in document.get("families", {}).values():
        if not isinstance(family, dict) or family.get("client_kind") != "tool_explorer":
            continue
        scopes = set(str(family.get("scope", "")).split())
        end = min(int(family.get("expires_at", 0)), int(family.get("revoked_at", 2**63 - 1)))
        for capability in _NAMESPACES:
            if capability not in scopes:
                continue
            binding_id = explorer_binding_id(
                auth_store,
                capability,
                str(family.get("identity_id", "")),
                str(family.get("miniserver_id", "")),
            )
            key = (capability, binding_id)
            ended[key] = max(ended.get(key, 0), end)
            if not family.get("revoked", False) and int(family.get("expires_at", 0)) > current:
                active.add(key)

    removed = 0

    def update(config: PluginConfig) -> PluginConfig:
        nonlocal removed
        retention = config.explorer_binding_retention_hours * 3600
        entries: list[ExplorerBindingApproval] = []
        for item in config.explorer_bindings:
            key = (item.capability, item.binding_id)
            if key in active:
                entries.append(replace(item, inactive_since=None))
                continue
            inactive_since = ended.get(key, item.inactive_since or item.last_active_until)
            if inactive_since + retention <= current:
                removed += 1
                continue
            entries.append(replace(item, inactive_since=inactive_since))
        updated = tuple(entries)
        return (
            config
            if updated == config.explorer_bindings
            else replace(config, explorer_bindings=updated)
        )

    config_store.mutate(update)
    return removed
