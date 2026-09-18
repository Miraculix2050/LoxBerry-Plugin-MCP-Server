"""Evidence-based UUID mapping; names never identify a project node."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

from mcpserver.loxone.models import Control, LoxoneStructure

from .graph import ProjectSnapshot, normalize_id


@dataclass(frozen=True, slots=True)
class ControlMapping:
    control_uuid: str = field(repr=False)
    status: str
    node_keys: tuple[str, ...]
    rule: str


@dataclass(frozen=True, slots=True)
class RuntimeMapping:
    project_fingerprint: str
    structure_fingerprint: str
    entries: tuple[ControlMapping, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProjectView:
    snapshot: ProjectSnapshot = field(repr=False)
    mapping: RuntimeMapping = field(repr=False)


def map_runtime(snapshot: ProjectSnapshot, structure: LoxoneStructure) -> RuntimeMapping:
    index: dict[str, list[str]] = defaultdict(list)
    for node in snapshot.graph.nodes:
        if node.kind == "block" and node.source_id:
            index[normalize_id(node.source_id)].append(node.key)
    entries: list[ControlMapping] = []
    identity_material: list[tuple[str, str | None, str | None]] = []
    pending: list[tuple[Control, str | None]] = [
        (control, None) for control in reversed(structure.controls)
    ]
    while pending:
        control, parent = pending.pop()
        identity_material.append((control.uuid, control.action_uuid, parent))
        uuid_candidates = set(index.get(normalize_id(control.uuid), ()))
        action_candidates = set(index.get(normalize_id(control.action_uuid), ()))
        candidates = uuid_candidates | action_candidates
        rules = []
        if uuid_candidates:
            rules.append("control_uuid")
        if action_candidates:
            rules.append("action_uuid")
        entries.append(
            ControlMapping(
                control.uuid,
                "exact" if len(candidates) == 1 else "ambiguous" if candidates else "unmapped",
                tuple(sorted(candidates)),
                "+".join(rules) if rules else "none",
            )
        )
        pending.extend((child, control.uuid) for child in reversed(control.subcontrols))
    marker = hashlib.sha256(
        json.dumps([structure.last_modified, identity_material], separators=(",", ":")).encode()
    ).hexdigest()
    return RuntimeMapping(snapshot.fingerprint, marker, tuple(entries))
