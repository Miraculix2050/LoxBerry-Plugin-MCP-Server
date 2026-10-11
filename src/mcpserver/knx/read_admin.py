"""Admin-only local catalog delegation, with target and policy revision checks."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

from mcpserver.auth.scopes import LOXBERRY_KNX_DRAFTS_SCOPE, LOXBERRY_KNX_READ_SCOPE, READ_SCOPE
from mcpserver.auth.store import lifecycle_event
from mcpserver.config import ExplorerBindingApproval, PluginConfig, binding_application_name
from mcpserver.explorer_bindings import (
    TOOL_EXPLORER_APPLICATION_ID,
    active_explorer_binding,
    explorer_binding_id,
)

from .delegation import draft_binding_id, read_binding_id
from .model import KnxError


@dataclass(frozen=True)
class DelegationPolicy:
    scope: str
    prefix: str
    enabled_field: str
    bindings_field: str
    binding_id: Callable[[PluginConfig, Any, dict[str, Any]], str]

    @property
    def required_scopes(self) -> set[str]:
        return {READ_SCOPE, LOXBERRY_KNX_READ_SCOPE, self.scope}

    def binding_updates(self, values: tuple[str, ...]) -> dict[str, Any]:
        return {self.bindings_field: values}


READ_POLICY = DelegationPolicy(
    LOXBERRY_KNX_READ_SCOPE,
    "knx_read",
    "loxberry_knx_read_enabled",
    "loxberry_knx_read_bindings",
    read_binding_id,
)
DRAFT_POLICY = DelegationPolicy(
    LOXBERRY_KNX_DRAFTS_SCOPE,
    "knx_drafts",
    "loxberry_knx_drafts_enabled",
    "loxberry_knx_drafts_bindings",
    draft_binding_id,
)


def policy_revision(
    config: PluginConfig, target: str, policy: DelegationPolicy = READ_POLICY
) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                target,
                getattr(config, policy.enabled_field),
                getattr(config, policy.bindings_field),
                [
                    asdict(item)
                    for item in config.explorer_bindings
                    if item.capability == policy.scope
                ],
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _candidates(
    config: PluginConfig, auth: Any, target: str, policy: DelegationPolicy = READ_POLICY
) -> dict[str, dict[str, Any]]:
    document = auth.snapshot()
    now = int(time.time())
    candidates: dict[str, dict[str, Any]] = {}
    for family in document.get("families", {}).values():
        scopes = str(family.get("scope", "")).split()
        if (
            family.get("revoked", False)
            or family.get("expires_at", 0) <= now
            or not policy.required_scopes <= set(scopes)
        ):
            continue
        explorer = family.get("client_kind") == "tool_explorer"
        if explorer:
            origin = family.get("explorer_origin")
            if not isinstance(origin, str) or not origin:
                continue
            binding = explorer_binding_id(
                auth,
                policy.scope,
                family["identity_id"],
                family["miniserver_id"],
                origin,
                target_origin=target,
            )
        else:
            binding = policy.binding_id(config, auth, family)
        existing = candidates.get(binding)
        if existing is None or family["expires_at"] > existing["expires_at"]:
            candidates[binding] = family
    return candidates


def snapshot(
    config: PluginConfig, auth: Any, target: str, policy: DelegationPolicy = READ_POLICY
) -> dict[str, Any]:
    candidates = _candidates(config, auth, target, policy)
    clients = auth.snapshot().get("clients", {})
    approvals = set(getattr(config, policy.bindings_field))
    approvals.update(
        item.binding_id for item in config.explorer_bindings if item.capability == policy.scope
    )
    rows = []
    for binding in sorted(approvals | candidates.keys()):
        family = candidates.get(binding)
        approved = binding in getattr(config, policy.bindings_field)
        if family and family.get("client_kind") == "tool_explorer":
            approved = (
                active_explorer_binding(
                    config,
                    auth,
                    policy.scope,
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
                "identity": str(
                    auth.pseudonym(
                        policy.prefix.replace("_", "-") + "-identity-v1", family["identity_id"]
                    )
                )[:12]
                if family
                else "",
                "miniserver": str(
                    auth.pseudonym(
                        policy.prefix.replace("_", "-") + "-miniserver-v1", family["miniserver_id"]
                    )
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
        "enabled": getattr(config, policy.enabled_field),
        "policy_revision": policy_revision(config, target, policy),
        "bindings": rows,
    }


def dispatch(
    action: str,
    payload: dict[str, Any],
    config: PluginConfig,
    save: Callable[[PluginConfig], None],
    auth: Any,
    target: str,
    policy: DelegationPolicy = READ_POLICY,
) -> dict[str, Any]:
    allowed = {
        f"{policy.prefix}_page": {"target"},
        f"{policy.prefix}_enable": {"target", "policy_revision", "enabled"},
        f"{policy.prefix}_grant": {"target", "policy_revision", "binding"},
        f"{policy.prefix}_revoke": {"target", "policy_revision", "binding"},
    }
    if action not in allowed or not payload.keys() <= allowed[action]:
        raise KnxError("knx_delegation_invalid")
    if action == f"{policy.prefix}_page":
        return snapshot(config, auth, target, policy)
    if payload.get("policy_revision") != policy_revision(config, target, policy):
        raise KnxError("knx_revision_conflict")
    if action == f"{policy.prefix}_enable":
        if type(payload.get("enabled")) is not bool:
            raise KnxError("knx_delegation_invalid")
        updated = replace(config, **{policy.enabled_field: payload["enabled"]})
        save(updated)
        lifecycle_event(
            "approval_match",
            reason=policy.prefix,
            capability=policy.prefix,
            source="admin",
            outcome="committed",
        )
        return snapshot(updated, auth, target, policy)
    binding = payload.get("binding")
    if not isinstance(binding, str) or len(binding) != 64:
        raise KnxError("knx_delegation_invalid")
    if action == f"{policy.prefix}_revoke":
        retained = set(getattr(config, policy.bindings_field)) | {
            item.binding_id for item in config.explorer_bindings if item.capability == policy.scope
        }
        if binding not in retained:
            raise KnxError("knx_delegation_invalid")
        updated = replace(
            config,
            **policy.binding_updates(
                tuple(item for item in getattr(config, policy.bindings_field) if item != binding)
            ),
            explorer_bindings=tuple(
                item
                for item in config.explorer_bindings
                if not (item.capability == policy.scope and item.binding_id == binding)
            ),
            loxberry_binding_names=tuple(
                item for item in config.loxberry_binding_names if item[0] != binding
            ),
        )
    else:
        family = _candidates(config, auth, target, policy).get(binding)
        if family is None:
            raise KnxError("knx_delegation_unavailable")
        current = snapshot(config, auth, target, policy)
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
                    if item.binding_id == binding and item.capability == policy.scope
                ),
                None,
            )
            replacement = ExplorerBindingApproval(
                binding,
                policy.scope,
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
                **policy.binding_updates(
                    tuple(dict.fromkeys((*getattr(config, policy.bindings_field), binding)))
                ),
            )
    save(updated)
    lifecycle_event(
        "approval_removed" if action == f"{policy.prefix}_revoke" else "approval_granted",
        binding_id=binding,
        reason=policy.prefix,
        capability=policy.prefix,
        source="admin",
        outcome="committed",
    )
    return snapshot(updated, auth, target, policy)
