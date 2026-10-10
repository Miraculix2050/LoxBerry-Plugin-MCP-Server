"""Evidence-based UUID mapping; names never identify a project node."""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mcpserver.loxone.models import Control, LoxoneStructure

from .graph import ProjectSnapshot, normalize_id

_UUID = re.compile(r"[0-9a-f]{32}")


def _uuid_id(value: str | None) -> str | None:
    normalized = normalize_id(value)
    return normalized if _UUID.fullmatch(normalized) else None


@dataclass(frozen=True, slots=True)
class ControlMapping:
    control_uuid: str = field(repr=False)
    status: str
    node_keys: tuple[str, ...]
    rule: str
    evidence: "RuntimeEvidence | None" = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    """Visible runtime metadata attached only to an exact project mapping."""

    name: str
    control_type: str
    room_uuid: str | None
    room_name: str | None
    category_uuid: str | None
    category_name: str | None


@dataclass(frozen=True, slots=True)
class RuntimeMapping:
    project_fingerprint: str
    structure_fingerprint: str
    entries: tuple[ControlMapping, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProjectView:
    snapshot: ProjectSnapshot = field(repr=False)
    mapping: RuntimeMapping = field(repr=False)
    marker: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class _RuntimeMappingInputs:
    """Ephemeral immutable inputs; never an authority or retained cache."""

    structure: LoxoneStructure = field(repr=False)
    fingerprint: str
    controls: tuple[Control, ...] = field(repr=False)
    rooms: Mapping[str, str] = field(repr=False)
    categories: Mapping[str, str] = field(repr=False)


def prepare_runtime_mapping(structure: LoxoneStructure) -> _RuntimeMappingInputs:
    rooms = {room.uuid: room.name for room in getattr(structure, "rooms", ())}
    categories = {category.uuid: category.name for category in getattr(structure, "categories", ())}
    controls: list[Control] = []
    identity_material: list[tuple[object, ...]] = []
    pending: list[tuple[Control, str | None]] = [
        (control, None) for control in reversed(structure.controls)
    ]
    while pending:
        control, parent = pending.pop()
        controls.append(control)
        identity_material.append(
            (
                control.uuid,
                control.action_uuid,
                parent,
                getattr(control, "name", ""),
                getattr(control, "control_type", ""),
                getattr(control, "room_uuid", None),
                rooms.get(getattr(control, "room_uuid", None)),
                getattr(control, "category_uuid", None),
                categories.get(getattr(control, "category_uuid", None)),
            )
        )
        pending.extend((child, control.uuid) for child in reversed(control.subcontrols))
    marker = hashlib.sha256(
        json.dumps([structure.last_modified, identity_material], separators=(",", ":")).encode()
    ).hexdigest()
    return _RuntimeMappingInputs(
        structure, marker, tuple(controls), MappingProxyType(rooms), MappingProxyType(categories)
    )


def map_runtime(
    snapshot: ProjectSnapshot,
    structure: LoxoneStructure,
    *,
    prepared: _RuntimeMappingInputs | None = None,
) -> RuntimeMapping:
    inputs = prepared if prepared is not None else prepare_runtime_mapping(structure)
    if inputs.structure is not structure:
        raise ValueError("Runtime mapping inputs belong to another structure")
    index: dict[str, list[str]] = defaultdict(list)
    for node in snapshot.graph.nodes:
        if node.kind != "block":
            continue
        source_id = _uuid_id(node.source_id)
        if source_id is not None:
            index[source_id].append(snapshot.canonical_node_key(node.key))
    entries: list[ControlMapping] = []
    for control in inputs.controls:
        room_uuid = getattr(control, "room_uuid", None)
        category_uuid = getattr(control, "category_uuid", None)
        control_id = _uuid_id(control.uuid)
        action_id = _uuid_id(control.action_uuid)
        uuid_candidates = set(index.get(control_id, ())) if control_id is not None else set()
        action_candidates = set(index.get(action_id, ())) if action_id is not None else set()
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
                RuntimeEvidence(
                    getattr(control, "name", ""),
                    getattr(control, "control_type", ""),
                    room_uuid,
                    inputs.rooms.get(room_uuid) if room_uuid is not None else None,
                    category_uuid,
                    inputs.categories.get(category_uuid) if category_uuid is not None else None,
                )
                if len(candidates) == 1
                else None,
            )
        )
    return RuntimeMapping(snapshot.fingerprint, inputs.fingerprint, tuple(entries))
