"""Admin-only local catalog delegation, with target and policy revision checks."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from mcpserver.auth.scopes import LOXBERRY_KNX_READ_SCOPE, READ_SCOPE
from mcpserver.auth.store import lifecycle_event
from mcpserver.config import ExplorerBindingApproval, PluginConfig, binding_application_name
from mcpserver.explorer_bindings import (
    TOOL_EXPLORER_APPLICATION_ID,
    active_explorer_binding,
    explorer_binding_id,
)

from .delegation import read_binding_id
from .model import KnxError


def policy_revision(config: PluginConfig, target: str) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                target,
                config.loxberry_knx_read_enabled,
                config.loxberry_knx_read_bindings,
                [
                    asdict(item)
                    for item in config.explorer_bindings
                    if item.capability == LOXBERRY_KNX_READ_SCOPE
                ],
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _candidates(config: PluginConfig, auth: Any, target: str) -> dict[str, dict[str, Any]]:
    document = auth.snapshot()
    now = int(time.time())
    candidates: dict[str, dict[str, Any]] = {}
    for family in document.get("families", {}).values():
        scopes = str(family.get("scope", "")).split()
        if (
            family.get("revoked", False)
            or family.get("expires_at", 0) <= now
            or not {READ_SCOPE, LOXBERRY_KNX_READ_SCOPE} <= set(scopes)
        ):
            continue
        explorer = family.get("client_kind") == "tool_explorer"
        if explorer:
            origin = family.get("explorer_origin")
            if not isinstance(origin, str) or not origin:
                continue
            binding = explorer_binding_id(
                auth,
                LOXBERRY_KNX_READ_SCOPE,
                family["identity_id"],
                family["miniserver_id"],
                origin,
                target_origin=target,
            )
        else:
            binding = read_binding_id(config, auth, family)
        existing = candidates.get(binding)
        if existing is None or family["expires_at"] > existing["expires_at"]:
            candidates[binding] = family
    return candidates


def snapshot(config: PluginConfig, auth: Any, target: str) -> dict[str, Any]:
    candidates = _candidates(config, auth, target)
    clients = auth.snapshot().get("clients", {})
    approvals = set(config.loxberry_knx_read_bindings)
    approvals.update(
        item.binding_id
        for item in config.explorer_bindings
        if item.capability == LOXBERRY_KNX_READ_SCOPE
    )
    rows = []
    for binding in sorted(approvals | candidates.keys()):
        family = candidates.get(binding)
        approved = binding in config.loxberry_knx_read_bindings
        if family and family.get("client_kind") == "tool_explorer":
            approved = (
                active_explorer_binding(
                    config,
                    auth,
                    LOXBERRY_KNX_READ_SCOPE,
                    family["identity_id"],
                    family["miniserver_id"],
                    family["explorer_origin"],
                )
                is not None
            )
        elif not family:
            approved = binding in approvals
        client = clients.get(family["client_id"], {}) if family else {}
        rows.append(
            {
                "binding": binding,
                "client_name": binding_application_name(client.get("client_name", "")),
                "client": family["client_id"] if family else "",
                "identity": str(auth.pseudonym("knx-read-identity-v1", family["identity_id"]))[:12]
                if family
                else "",
                "miniserver": str(
                    auth.pseudonym("knx-read-miniserver-v1", family["miniserver_id"])
                )[:12]
                if family
                else "",
                "eligible": family is not None,
                "approved": approved,
                "retained": binding in approvals,
            }
        )
    if len(rows) > 128:
        raise KnxError("knx_delegation_capacity")
    return {
        "enabled": config.loxberry_knx_read_enabled,
        "policy_revision": policy_revision(config, target),
        "bindings": rows,
    }


def dispatch(
    action: str,
    payload: dict[str, Any],
    config: PluginConfig,
    save: Callable[[PluginConfig], None],
    auth: Any,
    target: str,
) -> dict[str, Any]:
    allowed = {
        "knx_read_page": {"target"},
        "knx_read_enable": {"target", "policy_revision", "enabled"},
        "knx_read_grant": {"target", "policy_revision", "binding"},
        "knx_read_revoke": {"target", "policy_revision", "binding"},
    }
    if action not in allowed or not payload.keys() <= allowed[action]:
        raise KnxError("knx_delegation_invalid")
    if action == "knx_read_page":
        return snapshot(config, auth, target)
    if payload.get("policy_revision") != policy_revision(config, target):
        raise KnxError("knx_revision_conflict")
    if action == "knx_read_enable":
        if type(payload.get("enabled")) is not bool:
            raise KnxError("knx_delegation_invalid")
        updated = replace(config, loxberry_knx_read_enabled=payload["enabled"])
        save(updated)
        lifecycle_event(
            "approval_match",
            reason="knx_read",
            capability="knx_read",
            source="admin",
            outcome="committed",
        )
        return snapshot(updated, auth, target)
    binding = payload.get("binding")
    if not isinstance(binding, str) or len(binding) != 64:
        raise KnxError("knx_delegation_invalid")
    if action == "knx_read_revoke":
        retained = set(config.loxberry_knx_read_bindings) | {
            item.binding_id
            for item in config.explorer_bindings
            if item.capability == LOXBERRY_KNX_READ_SCOPE
        }
        if binding not in retained:
            raise KnxError("knx_delegation_invalid")
        updated = replace(
            config,
            loxberry_knx_read_bindings=tuple(
                item for item in config.loxberry_knx_read_bindings if item != binding
            ),
            explorer_bindings=tuple(
                item
                for item in config.explorer_bindings
                if not (item.capability == LOXBERRY_KNX_READ_SCOPE and item.binding_id == binding)
            ),
            loxberry_binding_names=tuple(
                item for item in config.loxberry_binding_names if item[0] != binding
            ),
        )
    else:
        family = _candidates(config, auth, target).get(binding)
        if family is None:
            raise KnxError("knx_delegation_unavailable")
        current = snapshot(config, auth, target)
        if sum(item["retained"] for item in current["bindings"]) >= 64 and not any(
            item["binding"] == binding and item["retained"] for item in current["bindings"]
        ):
            raise KnxError("knx_delegation_capacity")
        if family.get("client_kind") == "tool_explorer":
            now = int(time.time())
            entries = list(config.explorer_bindings)
            old = next(
                (
                    item
                    for item in entries
                    if item.binding_id == binding and item.capability == LOXBERRY_KNX_READ_SCOPE
                ),
                None,
            )
            replacement = ExplorerBindingApproval(
                binding,
                LOXBERRY_KNX_READ_SCOPE,
                TOOL_EXPLORER_APPLICATION_ID,
                1,
                old.created_at if old else now,
                now,
                int(family["expires_at"]),
                None,
            )
            if old:
                entries[entries.index(old)] = replacement
            else:
                entries.append(replacement)
            updated = replace(config, explorer_bindings=tuple(entries))
        else:
            updated = replace(
                config,
                loxberry_knx_read_bindings=tuple(
                    dict.fromkeys((*config.loxberry_knx_read_bindings, binding))
                ),
            )
    save(updated)
    lifecycle_event(
        "approval_removed" if action == "knx_read_revoke" else "approval_granted",
        binding_id=binding,
        reason="knx_read",
        capability="knx_read",
        source="admin",
        outcome="committed",
    )
    return snapshot(updated, auth, target)
