"""Evidence-based UUID mapping; names never identify a project node."""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from mcpserver.loxone.models import Control, LoxoneStructure

from .graph import ProjectSnapshot, normalize_id

_UUID = re.compile(r"[0-9a-f]{32}")
PARENT_MAPPING_RULE = "explicit_runtime_parent_v1"
MAX_PARENT_DEPTH = 16


@dataclass(frozen=True, slots=True)
class ParentMapping:
    """Runtime containment evidence, never an independent block or connector mapping."""

    status: str
    parent_runtime_control_uuid: str | None = field(repr=False)
    parent_mapping_status: str
    subcontrol_key: str = field(repr=False)
    anchor_runtime_control_uuid: str | None = field(default=None, repr=False)
    parent_project_node_ids: tuple[str, ...] = ()
    model_source_ids: tuple[str, ...] = ()
    runtime_parent_chain: tuple[str, ...] = field(default=(), repr=False)
    reason: str | None = None
    mapping_rule: str = PARENT_MAPPING_RULE


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
    parent: ParentMapping | None = field(default=None, repr=False)

    @property
    def mapping_status(self) -> str:
        return self.parent.status if self.parent is not None else self.status


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
    parents: Mapping[str, tuple[str | None, ...]] = field(repr=False)


def prepare_runtime_mapping(structure: LoxoneStructure) -> _RuntimeMappingInputs:
    rooms = {room.uuid: room.name for room in getattr(structure, "rooms", ())}
    categories = {category.uuid: category.name for category in getattr(structure, "categories", ())}
    controls: list[Control] = []
    parents: dict[str, dict[str | None, None]] = defaultdict(dict)
    visited: set[int] = set()
    identity_material: list[tuple[object, ...]] = []
    pending: list[tuple[Control, str | None]] = [
        (control, None) for control in reversed(structure.controls)
    ]
    while pending:
        control, parent = pending.pop()
        parents[control.uuid][parent] = None
        if id(control) in visited:
            continue
        visited.add(id(control))
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
        json.dumps(
            [
                PARENT_MAPPING_RULE,
                structure.last_modified,
                identity_material,
                [(key, list(values)) for key, values in parents.items()],
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return _RuntimeMappingInputs(
        structure,
        marker,
        tuple(controls),
        MappingProxyType(rooms),
        MappingProxyType(categories),
        MappingProxyType({key: tuple(values) for key, values in parents.items()}),
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
    by_uuid: dict[str, list[ControlMapping]] = defaultdict(list)
    for entry in entries:
        by_uuid[entry.control_uuid].append(entry)
    unique_parents = {
        uuid: items[0] if len({(item.status, item.node_keys) for item in items}) == 1 else None
        for uuid, items in by_uuid.items()
    }

    def derive(entry: ControlMapping) -> ParentMapping | None:
        relationships = inputs.parents.get(entry.control_uuid, ())
        if entry.status != "unmapped" or not any(parent is not None for parent in relationships):
            return None
        immediate = relationships[0] if len(relationships) == 1 else None
        key = entry.control_uuid
        if immediate is not None and key.startswith(immediate + "/"):
            key = key[len(immediate) + 1 :]
        chain: list[str] = []
        seen = {entry.control_uuid}
        current = entry.control_uuid
        parent_status = "unmapped" if immediate is not None else "ambiguous"
        status = "derived_parent_unmapped"
        reason: str | None = "parent_unmapped"
        anchor: ControlMapping | None = None
        parent_nodes: tuple[str, ...] = ()
        for depth in range(MAX_PARENT_DEPTH):
            parents = inputs.parents.get(current, ())
            if len(parents) != 1:
                status, reason = "derived_parent_ambiguous", "conflicting_runtime_parents"
                break
            parent_uuid = parents[0]
            if parent_uuid is None:
                break
            if parent_uuid in seen:
                status, reason = "derived_parent_ambiguous", "runtime_parent_cycle"
                break
            chain.append(parent_uuid)
            seen.add(parent_uuid)
            parent = unique_parents.get(parent_uuid)
            if parent is None:
                status, reason = "derived_parent_ambiguous", "conflicting_parent_mappings"
                break
            if depth == 0:
                parent_status = parent.status
            if parent.status == "ambiguous":
                parent_nodes = parent.node_keys
                status, reason = "derived_parent_ambiguous", "parent_mapping_ambiguous"
                break
            if parent.status == "exact":
                anchor = parent
                parent_nodes = parent.node_keys
                if depth:
                    parent_status = "derived_from_parent"
                status, reason = "derived_from_parent", None
                break
            current = parent_uuid
        else:
            reason = "parent_depth_limit"
        return ParentMapping(
            status,
            immediate,
            parent_status,
            key,
            anchor.control_uuid if anchor is not None else None,
            parent_nodes,
            tuple(
                sorted(
                    {
                        source
                        for node in anchor.node_keys
                        for source in snapshot.source_ids_for(node)
                    }
                )
            )
            if anchor
            else (),
            tuple(chain),
            reason,
        )

    derived = [replace(entry, parent=derive(entry)) for entry in entries]
    parent_statuses: dict[str, set[str]] = defaultdict(set)
    for entry in derived:
        parent_statuses[entry.control_uuid].add(entry.mapping_status)
    effective_parent_status = {
        uuid: next(iter(statuses)) if len(statuses) == 1 else "ambiguous"
        for uuid, statuses in parent_statuses.items()
    }
    return RuntimeMapping(
        snapshot.fingerprint,
        inputs.fingerprint,
        tuple(
            replace(
                entry,
                parent=replace(
                    entry.parent,
                    parent_mapping_status=effective_parent_status.get(
                        entry.parent.parent_runtime_control_uuid, "ambiguous"
                    ),
                ),
            )
            if entry.parent is not None and entry.parent.parent_runtime_control_uuid is not None
            else entry
            for entry in derived
        ),
    )
