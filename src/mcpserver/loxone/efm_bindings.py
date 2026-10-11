"""Exact firmware-gated EFM UUID metadata joins; no state/value requests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .efm import Projection, valid_uuid

if TYPE_CHECKING:
    from .models import Control

RULE = "efm_actual_state_uuid_17_2_8_28_v1"
FIRMWARE = "17.2.8.28"
MAX_MAP_ENTRIES = 1000
MAX_CANDIDATES = 100
MAX_BINDING_BYTES = 32768


def bind(
    projection: Projection,
    monitor: Control,
    firmware: str | None,
    *,
    verification: str | None = None,
    occurrence_limit: int | None = None,
) -> dict[str, Any]:
    """Join by exact UUID equality only; preserve aliases and repeated references."""
    verified = firmware == FIRMWARE and verification in {None, "verified"}
    retained = projection.participants[:occurrence_limit]
    map_limited = len(monitor.state_uuids) > MAX_MAP_ENTRIES
    rows: list[dict[str, Any]] = []
    remaining = MAX_CANDIDATES
    for participant in retained:
        kind = participant.binding_kind
        status = kind
        candidates = []
        omitted = 0
        if kind == "uuid":
            if not verified:
                status = "unsupported_version"
            elif map_limited:
                status = "state_map_limit"
            else:
                matches = [
                    (name, state_uuid)
                    for name, state_uuid in monitor.state_uuids
                    if state_uuid == participant.binding_reference and valid_uuid(state_uuid)
                ]
                names = {name for name, _uuid in matches}
                facts = [
                    (name, state_uuid) for name, state_uuid in monitor.state_uuids if name in names
                ]
                conflict = any(
                    state_uuid != participant.binding_reference for _, state_uuid in facts
                )
                candidates = [
                    {"name": name, "uuid": state_uuid}
                    for name, state_uuid in facts[:remaining]
                    if 0 < len(name) <= 128 and valid_uuid(state_uuid)
                ]
                remaining -= len(candidates)
                omitted = len(facts) - len(candidates)
                status = (
                    "conflict"
                    if conflict
                    else "partial"
                    if omitted
                    else "resolved"
                    if candidates
                    else "reference_missing"
                )
        rows.append(
            {
                "path": list(participant.path),
                "source_wire_type": participant.binding_wire_type,
                "source_field": "actualEfmState" if kind != "absent" else None,
                "encoding": "state_uuid" if kind == "uuid" and verified else None,
                "status": status,
                "states": candidates,
                "candidates_omitted": omitted,
            }
        )
    result: dict[str, Any] = {
        "rule_id": RULE if verified else None,
        "firmware_version": firmware,
        "firmware_verification": verification or ("verified" if verified else "unverified"),
        "document_version": "17.1",
        "config_version": None,
        "projection_omitted": len(projection.participants) - len(retained),
        "reference_complete": len(retained) == len(projection.participants)
        and not any(
            set(p.diagnostics) & {"invalid_participant", "invalid_child_collection"}
            for p in projection.participants
        )
        and not projection.omitted_subtrees
        and not map_limited
        and "invalid_nodes_collection" not in projection.diagnostics
        and all(row["status"] in {"resolved", "absent"} for row in rows),
        "semantic_complete": False,
        "observation_complete": False,
        "max_map_entries": MAX_MAP_ENTRIES,
        "max_candidates": MAX_CANDIDATES,
        "max_response_bytes": MAX_BINDING_BYTES,
        "source_property_uniqueness": "not_checked",
        "participants": rows,
    }

    # Bound the serialized binding projection independently from full Describe.
    for row in reversed(rows):
        while (
            row["states"]
            and len(json.dumps(result, ensure_ascii=True).encode()) > MAX_BINDING_BYTES
        ):
            row["states"].pop()
            row["candidates_omitted"] += 1
            if row["status"] == "resolved":
                row["status"] = "partial"
            result["reference_complete"] = False
    return result
