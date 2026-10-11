"""Bounded EFM occurrence metadata; no values, inferred roles or remote reads."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcpserver.loxone.models import Control

MAX_NODES = 100
MAX_DEPTH = 8
MAX_BYTES = 32768
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{16}\Z")


def valid_uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Participant:
    path: tuple[int, ...]
    node_uuid: str | None = None
    control_uuid: str | None = None
    reference_status: str = "absent"
    role_token: str | int | None = None
    title: str | None = None
    diagnostics: tuple[str, ...] = ()
    icon: str | None = None
    residual: tuple[tuple[str, str | bool], ...] = ()


@dataclass(frozen=True, slots=True)
class Projection:
    participants: tuple[Participant, ...]
    residual: tuple[tuple[str, str | bool], ...] = ()
    omitted_subtrees: int = 0
    diagnostics: tuple[str, ...] = ()


def residual_metadata(
    source: Mapping[str, object], diagnostics: list[str]
) -> tuple[tuple[str, str | bool], ...]:
    residual: list[tuple[str, str | bool]] = []
    for key in ("rest", "restName", "restIcon"):
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, bool) or (isinstance(value, str) and len(value) <= 200):
            residual.append((key, value))
        else:
            diagnostics.append("invalid_residual_metadata")
    return tuple(residual)


def normalize(details: Mapping[str, object]) -> Projection:
    """Keep source indices, including malformed positions; bound retained metadata."""
    rows: list[Participant] = []
    diagnostics: list[str] = []
    omitted = 0
    residual = residual_metadata(details, diagnostics)
    used = len(json.dumps(residual, ensure_ascii=True).encode())
    nodes = details.get("nodes")
    if not isinstance(nodes, list):
        return Projection((), residual, diagnostics=(*diagnostics, "invalid_nodes_collection"))

    def visit(items: list[object], parent: tuple[int, ...]) -> None:
        nonlocal omitted, used
        for index, item in enumerate(items):
            path = (*parent, index)
            if len(path) > MAX_DEPTH or len(rows) >= MAX_NODES or used >= MAX_BYTES:
                omitted += len(items) - index
                return
            issues: list[str] = []
            node_uuid = control_uuid = title = None
            role: str | int | None = None
            status = "absent"
            children = None
            icon = None
            residual: tuple[tuple[str, str | bool], ...] = ()
            if not isinstance(item, Mapping):
                issues.append("invalid_participant")
                status = "malformed"
            else:
                node_uuid = item.get("uuid") if valid_uuid(item.get("uuid")) else None
                if node_uuid is None:
                    issues.append("invalid_node_identity")
                if "ctrlUuid" in item:
                    if valid_uuid(item["ctrlUuid"]):
                        control_uuid = item["ctrlUuid"]
                        status = "advertised"
                    else:
                        status = "malformed"
                        issues.append("invalid_control_reference")
                raw_role = item.get("nodeType")
                if (isinstance(raw_role, str) and len(raw_role) <= 64) or (
                    isinstance(raw_role, int)
                    and not isinstance(raw_role, bool)
                    and abs(raw_role) <= 2147483647
                ):
                    role = raw_role
                else:
                    issues.append("invalid_role_token")
                raw_title = item.get("title")
                if isinstance(raw_title, str) and len(raw_title) <= 200:
                    title = raw_title
                elif "title" in item:
                    issues.append("invalid_title")
                raw_icon = item.get("icon")
                if isinstance(raw_icon, str) and len(raw_icon) <= 200:
                    icon = raw_icon
                elif "icon" in item:
                    issues.append("invalid_icon")
                residual = residual_metadata(item, issues)
                children = item.get("nodes")
                if "nodes" in item and not isinstance(children, list):
                    issues.append("invalid_child_collection")
            row = Participant(
                path, node_uuid, control_uuid, status, role, title, tuple(issues), icon, residual
            )
            cost = len(
                json.dumps(
                    [path, node_uuid, control_uuid, role, title, issues, icon, residual],
                    ensure_ascii=True,
                ).encode()
            )
            if used + cost > MAX_BYTES:
                omitted += len(items) - index
                return
            used += cost
            rows.append(row)
            if isinstance(children, list):
                visit(children, path)

    visit(nodes, ())
    identities = Counter(row.node_uuid for row in rows if row.node_uuid is not None)
    if any(count > 1 for count in identities.values()):
        diagnostics.append("repeated_node_identity")
    if omitted:
        diagnostics.append("participant_limit")
    return Projection(tuple(rows), tuple(residual), omitted, tuple(diagnostics))


def describe(projection: Projection, visible: Mapping[str, Control]) -> dict[str, object]:
    """Never expose unresolved control identities, even to hidden-control diagnosis."""
    participants = []
    for row in projection.participants:
        target = visible.get(row.control_uuid) if row.control_uuid else None
        status = (
            "resolved"
            if target is not None
            else "unavailable"
            if row.reference_status == "advertised"
            else row.reference_status
        )
        participants.append(
            {
                "path": list(row.path),
                "parent_path": list(row.path[:-1]) or None,
                "node_uuid": row.node_uuid,
                "title": row.title,
                "icon": row.icon,
                "residual_display": dict(row.residual),
                "role_token": row.role_token,
                "role": None,
                "role_status": "unknown",
                "reference_status": status,
                "control": {
                    "uuid": target.uuid,
                    "name": target.name[:200],
                    "type": target.control_type[:64],
                }
                if target is not None
                else None,
                "control_metadata_truncated": target is not None
                and (len(target.name) > 200 or len(target.control_type) > 64),
                "diagnostics": list(row.diagnostics),
            }
        )
    result: dict[str, Any] = {
        "source": "LoxAPP3.details.nodes",
        "participants": participants,
        "residual_display": dict(projection.residual),
        "returned": len(participants),
        "projection_omitted": 0,
        "omitted_subtrees": projection.omitted_subtrees,
        "omitted_descendants": None if projection.omitted_subtrees else 0,
        "topology_complete": not projection.omitted_subtrees
        and not set(projection.diagnostics) & {"invalid_nodes_collection", "repeated_node_identity"}
        and all(
            not set(r.diagnostics)
            & {"invalid_participant", "invalid_node_identity", "invalid_child_collection"}
            for r in projection.participants
        ),
        "references_complete": "invalid_nodes_collection" not in projection.diagnostics
        and not projection.omitted_subtrees
        and all(r["reference_status"] in {"resolved", "absent"} for r in participants)
        and all("invalid_child_collection" not in r.diagnostics for r in projection.participants),
        "roles_complete": not participants
        and not projection.omitted_subtrees
        and "invalid_nodes_collection" not in projection.diagnostics,
        "max_nodes": MAX_NODES,
        "max_depth": MAX_DEPTH,
        "max_metadata_bytes": MAX_BYTES,
        "diagnostics": list(projection.diagnostics),
    }

    # Resolved display metadata must fit the same serialized projection budget.
    # Remove only a DFS suffix, preserving every retained parent and source path.
    while participants and len(json.dumps(result, ensure_ascii=True).encode()) > MAX_BYTES:
        participants.pop()
        result["returned"] = len(participants)
        result["projection_omitted"] += 1
        result["topology_complete"] = False
        result["references_complete"] = False
        result["roles_complete"] = False
    return result
