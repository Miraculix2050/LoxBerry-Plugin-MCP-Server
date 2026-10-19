"""Bounded lighting observations on the existing project graph; never physical advice."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

from mcpserver.analysis_context import (
    ContextContract,
    Declaration,
    SourceSnapshot,
    read_profile_bindings,
    resolve_source_association,
)
from mcpserver.installation_profile import installation_identity, visible_controls
from mcpserver.loxone.lighting import (
    MOOD_ID_PATTERN,
    project_lighting_outputs,
    project_moods,
    visible_mood_ids,
    visible_mood_items,
)
from mcpserver.loxone.models import Control, Freshness, LoxoneStructure, StateRecord
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError
from mcpserver.loxone.runtime import ControlOperationError

LIGHTING_ANALYSES = (
    "inventory",
    "naming_consistency",
    "presence_relationships",
    "scene_roles",
    "planning_context",
)
LIGHTING_ANALYSIS_VERSION = 1
LightingCheck = Literal[
    "inventory", "naming_consistency", "presence_relationships", "scene_roles", "planning_context"
]


class LightingSelection(ContextContract):
    controller_uuids: list[str] | None = Field(default=None, min_length=1, max_length=16)
    room_uuid: str | None = Field(default=None, min_length=1, max_length=200)
    max_depth: int = Field(default=6, ge=1, le=16)
    max_nodes: int = Field(default=200, ge=1, le=200)

    @model_validator(mode="after")
    def exact_selection(self) -> LightingSelection:
        if (self.controller_uuids is None) == (self.room_uuid is None):
            raise ValueError("choose exact lighting controller IDs or one exact room ID")
        if self.controller_uuids is not None and (
            len(set(self.controller_uuids)) != len(self.controller_uuids)
            or any(not value or len(value) > 200 for value in self.controller_uuids)
        ):
            raise ValueError("lighting controller IDs must be unique exact bounded IDs")
        return self


class LightingDeclaration(ContextContract):
    origin: Declaration
    rationale: str = Field(min_length=1, max_length=256)


class LightingScene(LightingDeclaration):
    controller_uuid: str | None = Field(default=None, min_length=1, max_length=200)
    binding_id: str | None = Field(default=None, min_length=1, max_length=64)
    mood_id: str = Field(min_length=1, max_length=10)
    role: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def exact_scene(self) -> LightingScene:
        if (self.controller_uuid is None) == (self.binding_id is None):
            raise ValueError("choose a scene controller or profile reference")
        if not MOOD_ID_PATTERN.fullmatch(self.mood_id):
            raise ValueError("scene mood_id must be an exact native mood ID")
        return self


class LightingPresence(LightingDeclaration):
    control_uuid: str | None = Field(default=None, min_length=1, max_length=200)
    binding_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def exact_source(self) -> LightingPresence:
        if (self.control_uuid is None) == (self.binding_id is None):
            raise ValueError("choose a presence source or profile reference")
        return self


class LightingText(LightingDeclaration):
    value: str = Field(min_length=1, max_length=256)


class LightingZone(LightingDeclaration):
    value: str = Field(min_length=1, max_length=80)


class LightingFixture(LightingDeclaration):
    value: bool


class LightingRoom(ContextContract):
    room_uuid: str = Field(min_length=1, max_length=200)
    usage: LightingText | None = None
    intent: LightingText | None = None
    tunable_white_installed: LightingFixture | None = None
    zones: list[LightingZone] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_zones(self) -> LightingRoom:
        if len({zone.value for zone in self.zones}) != len(self.zones):
            raise ValueError("duplicate zone declaration")
        return self


class LightingNaming(LightingDeclaration):
    controller_uuid: str | None = Field(default=None, min_length=1, max_length=200)
    room_uuid: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["prefix"] = "prefix"
    value: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def one_target(self) -> LightingNaming:
        if (self.controller_uuid is None) == (self.room_uuid is None):
            raise ValueError("choose one naming target")
        return self


class LightingContext(ContextContract):
    schema_version: Literal["lighting_analysis_context.v1"]
    scenes: list[LightingScene] = Field(default_factory=list, max_length=100)
    presence_sources: list[LightingPresence] = Field(default_factory=list, max_length=16)
    rooms: list[LightingRoom] = Field(default_factory=list, max_length=16)
    naming_rules: list[LightingNaming] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def byte_bound(self) -> LightingContext:
        if len(self.model_dump_json().encode()) > 65_536:
            raise ValueError("lighting context exceeds 64 KiB")
        return self


class LightingReference(BaseModel):
    controller_uuid: str
    room_uuid: str | None = None
    mood_id: str | None = None


class LightingFinding(BaseModel):
    finding_id: str
    analysis: LightingCheck
    code: str
    classification: Literal[
        "technical_observation", "review_candidate", "context_gap", "conditional"
    ]
    references: list[LightingReference] = Field(max_length=16)
    evidence: dict[str, JsonValue]


class LightingCoverage(BaseModel):
    selected: int
    excluded: int
    selection_complete: bool
    supported: int
    naming_comparison_complete: bool
    scope: Literal["selected_visible_controllers"] = "selected_visible_controllers"


class LightingAnalysisData(BaseModel):
    scope: Literal["lighting"] = "lighting"
    analysis_version: int = LIGHTING_ANALYSIS_VERSION
    project_fingerprint: str
    model_version: int
    runtime_version: str
    analyses: list[LightingCheck]
    coverage: LightingCoverage
    findings: list[LightingFinding]
    next_cursor: str | None = None
    analysis_truncated: bool
    truncation_reasons: list[str]
    limitations: list[str]
    page_truncated: bool = False
    page_truncation_reason: Literal["max_response_bytes"] | None = None


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mood_state(runtime: Any, snapshot: Any, control: Control) -> StateRecord | None:
    uuid = dict(control.state_uuids).get("moodList")
    return (
        runtime.state(snapshot, uuid)
        if uuid and control.control_type == "LightControllerV2"
        else None
    )


def _mood_metadata(record: StateRecord | None) -> dict[str, Any]:
    projection = (
        project_moods(record.value) if record is not None and record.value is not None else None
    )
    rows = (
        visible_mood_items(record.value)
        if record is not None and projection is not None and projection.status == "available"
        else None
    )
    ambiguous_ids = sorted(
        key for key, count in Counter(str(r["id"]) for r in rows or ()).items() if count > 1
    )
    return {
        "status": projection.status if projection is not None else "unavailable",
        "freshness": record.freshness.value if record is not None else "unavailable",
        "observed_at": record.observed_at if record is not None else None,
        "moods": [
            {"id": row.id, "name": row.name, "name_truncated": row.name_truncated}
            for row in projection.moods
        ]
        if projection
        else [],
        "total": projection.total if projection else None,
        "omitted": projection.omitted if projection else None,
        "names_complete": projection.names_complete if projection else False,
        "visible_ids": sorted(visible_mood_ids(record.value) or ())
        if record is not None and projection is not None and projection.status == "available"
        else [],
        "ambiguous_ids": ambiguous_ids,
    }


@dataclass
class LightingSources:
    selection: LightingSelection
    controls: tuple[Control, ...]
    excluded: int
    normalized: dict[str, Any]
    moods: dict[str, dict[str, Any]]
    room_metadata: tuple[object, ...]
    guard: SourceSnapshot
    source_key: str
    binding_ids: set[str]

    async def validate(self, runtime: Any, snapshot: Any, profile_path: Path | None) -> None:
        structure = snapshot.structure
        bindings, revision = await read_profile_bindings(
            profile_path,
            installation_identity(runtime.endpoint.origin, structure),
            structure,
            required=bool(self.binding_ids),
        )
        self.guard.validate(runtime.endpoint.origin, structure, bindings, revision)
        current = select_controllers(structure, self.selection)
        room_ids = {c.room_uuid for c in current[0]} | {self.selection.room_uuid}
        rooms = tuple(room for room in structure.rooms if room.uuid in room_ids)
        moods = {c.uuid: _mood_metadata(_mood_state(runtime, snapshot, c)) for c in current[0]}
        if (
            current != (self.controls, self.excluded)
            or rooms != self.room_metadata
            or moods != self.moods
        ):
            raise ControlOperationError(
                "temporarily_unavailable", "Lighting sources changed; start a new analysis"
            )


def select_controllers(
    structure: LoxoneStructure, selection: LightingSelection
) -> tuple[tuple[Control, ...], int]:
    visible = {
        key: value for key, value in visible_controls(structure).items() if not value.is_hidden
    }
    if selection.controller_uuids is not None:
        if not set(selection.controller_uuids) <= visible.keys():
            raise ControlOperationError("not_found", "Lighting selection is not accessible")
        return tuple(visible[key] for key in sorted(selection.controller_uuids)), 0
    if selection.room_uuid not in {room.uuid for room in structure.rooms}:
        raise ControlOperationError("not_found", "Lighting room is not accessible")
    selected = sorted(
        (
            c
            for c in visible.values()
            if c.room_uuid == selection.room_uuid and c.control_type == "LightControllerV2"
        ),
        key=lambda c: c.uuid,
    )
    return tuple(selected[:16]), max(0, len(selected) - 16)


async def prepare_lighting(
    runtime: Any,
    snapshot: Any,
    selection: LightingSelection,
    context: LightingContext | None,
    profile_path: Path | None,
) -> LightingSources:
    if selection.controller_uuids is not None:
        selection = selection.model_copy(
            update={"controller_uuids": sorted(selection.controller_uuids)}
        )
    structure = snapshot.structure
    controls, excluded = select_controllers(structure, selection)
    selected = {c.uuid for c in controls}
    selected_rooms = {c.room_uuid for c in controls if c.room_uuid is not None}
    if selection.room_uuid is not None:
        selected_rooms.add(selection.room_uuid)
    context = context or LightingContext(schema_version="lighting_analysis_context.v1")
    declarations: list[LightingScene | LightingPresence] = [
        *context.scenes,
        *context.presence_sources,
    ]
    binding_ids = {row.binding_id for row in declarations if row.binding_id is not None}
    bindings, revision = await read_profile_bindings(
        profile_path,
        installation_identity(runtime.endpoint.origin, structure),
        structure,
        required=bool(binding_ids),
    )
    visible = {key: c for key, c in visible_controls(structure).items() if not c.is_hidden}
    moods = {c.uuid: _mood_metadata(_mood_state(runtime, snapshot, c)) for c in controls}
    scenes = []
    presence = []
    for index, row in enumerate(declarations):
        scene = isinstance(row, LightingScene)
        resolved = resolve_source_association(
            str(index),
            visible,
            bindings=bindings,
            binding_id=row.binding_id,
            control_uuid=row.controller_uuid
            if isinstance(row, LightingScene)
            else row.control_uuid,
            origin=row.origin,
            expected_role="lighting_intent" if scene else "room_sensor",
        )
        uuid = resolved.association.control_uuid
        assert uuid is not None
        data = row.model_dump(exclude_none=True)
        data.update(control_uuid=uuid, source_origin=resolved.association.origin)
        if isinstance(row, LightingScene):
            if uuid not in selected:
                raise ValueError("scene controller is outside the lighting selection")
            mood = moods[uuid]
            if mood["status"] != "available" or mood["freshness"] != Freshness.CURRENT.value:
                raise ControlOperationError(
                    "temporarily_unavailable", "Current visible mood membership is required"
                )
            if row.mood_id not in mood["visible_ids"]:
                raise ControlOperationError(
                    "not_found", "Selected mood is not in the bounded visible source"
                )
            scenes.append(data)
        else:
            presence.append(data)

    def unique(keys: list[object]) -> None:
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate resolved lighting declaration")

    unique([(row["control_uuid"], row["mood_id"]) for row in scenes])
    unique([row["control_uuid"] for row in presence])
    unique([row.room_uuid for row in context.rooms])
    unique([(row.controller_uuid, row.room_uuid) for row in context.naming_rules])
    if any(row.room_uuid not in selected_rooms for row in context.rooms):
        raise ValueError("room declaration is outside the lighting selection")
    covered: set[str] = set()
    for rule in context.naming_rules:
        if rule.controller_uuid is not None:
            if rule.controller_uuid not in selected:
                raise ValueError("naming controller is outside the lighting selection")
            targets = {rule.controller_uuid}
        else:
            if rule.room_uuid not in selected_rooms:
                raise ValueError("naming room is outside the lighting selection")
            targets = {c.uuid for c in controls if c.room_uuid == rule.room_uuid}
        if covered & targets:
            raise ValueError("overlapping lighting prefixes have no precedence")
        covered |= targets
    normalized = {
        "scenes": sorted(scenes, key=lambda r: (r["control_uuid"], r["mood_id"])),
        "presence_sources": sorted(presence, key=lambda r: r["control_uuid"]),
        "rooms": [r.model_dump() for r in sorted(context.rooms, key=lambda r: r.room_uuid)],
        "naming_rules": [
            r.model_dump()
            for r in sorted(
                context.naming_rules, key=lambda r: (r.controller_uuid or "", r.room_uuid or "")
            )
        ],
    }
    for room in normalized["rooms"]:
        room["zones"] = sorted(room["zones"], key=lambda r: r["value"])
    source_ids = selected | {r["control_uuid"] for r in presence}
    guard = SourceSnapshot.capture(
        runtime.endpoint.origin, structure, source_ids, bindings, revision, binding_ids
    )
    rooms = tuple(room for room in structure.rooms if room.uuid in selected_rooms)
    source_key = digest(
        [
            repr(guard.signature),
            guard.installation,
            guard.bindings,
            revision,
            moods,
            repr(rooms),
            excluded,
        ]
    )
    return LightingSources(
        selection, controls, excluded, normalized, moods, rooms, guard, source_key, binding_ids
    )


def analyze_lighting(
    project: ProjectQuery, sources: LightingSources, analyses: frozenset[str]
) -> dict[str, Any]:
    """Emit bounded review candidates and declarations, never infer physical semantics."""
    findings: list[dict[str, Any]] = []
    controls = sources.controls
    by_id = {c.uuid: c for c in controls}

    def add(
        check: str,
        code: str,
        classification: str,
        refs: list[dict[str, Any]],
        evidence: dict[str, Any],
    ) -> None:
        findings.append(
            {
                "finding_id": digest([check, code, refs, evidence])[:24],
                "analysis": check,
                "code": code,
                "classification": classification,
                "references": refs[:16],
                "evidence": evidence,
            }
        )

    def ref(c: Control, mood_id: str | None = None) -> dict[str, Any]:
        return {"controller_uuid": c.uuid, "room_uuid": c.room_uuid, "mood_id": mood_id}

    def full_name(value: str | None) -> bool:
        return bool(value) and len(value or "") <= 200

    for control in controls:
        supported = control.control_type == "LightControllerV2"
        if not supported:
            add(
                sorted(analyses)[0],
                "unsupported_controller_type",
                "context_gap",
                [ref(control)],
                {"control_type": control.control_type[:80], "interpreted_as_empty": False},
            )
            continue
        mood = sources.moods[control.uuid]
        outputs = project_lighting_outputs(control)
        if "inventory" in analyses:
            add(
                "inventory",
                "visible_lighting_inventory",
                "technical_observation",
                [ref(control)],
                {
                    "name": control.name[:200],
                    "name_complete": full_name(control.name),
                    "mood_source": "cached_moodList",
                    "freshness": mood["freshness"],
                    "observed_at": mood["observed_at"],
                    "moods": mood["moods"][:20],
                    "mood_status": mood["status"],
                    "mood_total": mood["total"],
                    "moods_omitted": None
                    if mood["total"] is None
                    else mood["total"] - min(20, len(mood["moods"])),
                    "outputs": [
                        {
                            "uuid": o.uuid,
                            "name": o.name,
                            "type": o.type,
                            "name_truncated": o.name_truncated,
                        }
                        for o in outputs.entries[:20]
                    ],
                    "output_total": outputs.total,
                    "outputs_omitted": None
                    if outputs.total is None
                    else outputs.total - min(20, len(outputs.entries)),
                    "parent_runtime_control_uuid": control.uuid,
                    "physical_connector_identity": "unverified",
                    "source_version": project.view.mapping.structure_fingerprint,
                    "mood_state_uuid": dict(control.state_uuids).get("moodList"),
                    "ambiguous_mood_ids": mood["ambiguous_ids"][:20],
                    "output_unsupported_types": outputs.unsupported_types,
                },
            )
        if "presence_relationships" in analyses:
            refs = [ref(control)]
            try:
                target = project.resolve(control.uuid, "runtime_control_uuid")
                trace = project.trace(
                    target,
                    direction="upstream",
                    max_depth=sources.selection.max_depth,
                    max_nodes=sources.selection.max_nodes,
                    include_internal_flow_gaps=True,
                )
            except ProjectQueryError as exc:
                add(
                    "presence_relationships",
                    "lighting_mapping_unresolved",
                    "context_gap",
                    refs,
                    {"association": "unresolved", "diagnostic_code": str(exc)},
                )
            else:
                nodes = trace["nodes"]
                assert isinstance(nodes, list)
                reached = {
                    key
                    for n in nodes
                    for key in [n["project_node_id"], *n.get("source_project_node_ids", [])]
                }
                gaps = trace["semantic_gaps"]
                assert isinstance(gaps, list)
                relationships = []
                for source in sources.normalized["presence_sources"]:
                    uuid = source["control_uuid"]
                    status = "unresolved"
                    anchor = None
                    provenance = None
                    try:
                        source_node = project.resolve(uuid, "runtime_control_uuid")
                        anchor = source_node.key
                        provenance = project.derived_target(uuid, "runtime_control_uuid")
                        if anchor == target.key:
                            status = "shared_anchor_not_an_association"
                        elif anchor in reached:
                            status = "configured_upstream_reachability"
                        else:
                            status = "not_reached_in_bounded_trace"
                    except ProjectQueryError as exc:
                        status = (
                            "ambiguous_mapping"
                            if str(exc) == "project_mapping_ambiguous"
                            else "unmapped_source"
                        )
                    relationships.append(
                        {
                            "control_uuid": uuid,
                            "declared_presence_origin": source["origin"],
                            "source_origin": source["source_origin"],
                            "status": status,
                            "project_anchor": anchor,
                            "runtime_target_mapping": provenance,
                        }
                    )
                add(
                    "presence_relationships",
                    "configured_lighting_trace",
                    "technical_observation",
                    refs,
                    {
                        "start_project_node_id": target.key,
                        "reached_nodes": len(nodes),
                        "relationships": relationships,
                        "presence_role_missing": not bool(relationships),
                        "semantic_gaps": gaps[:16],
                        "semantic_gaps_omitted": max(0, len(gaps) - 16),
                        "trace_truncated": trace["truncated"],
                        "semantic_truncated": trace["semantic_truncated"],
                        "unresolved_relationships": len(trace["unresolved_relationships"])
                        if isinstance(trace["unresolved_relationships"], list)
                        else 0,
                        "operating_causation": "unverified",
                        "no_path_does_not_prove_no_association": True,
                    },
                )
    if "naming_consistency" in analyses:
        names: defaultdict[str, list[Control]] = defaultdict(list)
        mood_names: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in controls:
            if full_name(c.name):
                names[c.name.casefold()].append(c)
            for mood in sources.moods[c.uuid]["moods"]:
                if (
                    full_name(mood["name"])
                    and not mood["name_truncated"]
                    and mood["id"] not in sources.moods[c.uuid]["ambiguous_ids"]
                ):
                    mood_names[mood["name"].casefold()].append(ref(c, mood["id"]))
        for group in names.values():
            if len(group) > 1:
                add(
                    "naming_consistency",
                    "repeated_controller_name",
                    "review_candidate",
                    [ref(c) for c in group],
                    {"name": group[0].name, "physical_duplicate": "not_established"},
                )
        for group_refs in mood_names.values():
            identities = {(r["controller_uuid"], r["mood_id"]) for r in group_refs}
            if len(identities) > 1:
                add(
                    "naming_consistency",
                    "repeated_visible_mood_name",
                    "review_candidate",
                    group_refs[:16],
                    {
                        "scenes": len(identities),
                        "references_omitted": max(0, len(group_refs) - 16),
                        "physical_duplicate": "not_established",
                        "comparison_scope": "bounded_visible_moods",
                    },
                )
        for rule in sources.normalized["naming_rules"]:
            targets = [
                c
                for c in controls
                if c.uuid == rule["controller_uuid"]
                or (rule["room_uuid"] is not None and c.room_uuid == rule["room_uuid"])
            ]
            for c in targets:
                if full_name(c.name) and not c.name.startswith(rule["value"]):
                    add(
                        "naming_consistency",
                        "declared_prefix_difference",
                        "review_candidate",
                        [ref(c)],
                        {"name": c.name, "rule": rule, "fault": "not_established"},
                    )
    if "scene_roles" in analyses:
        roles: defaultdict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for scene in sources.normalized["scenes"]:
            c = by_id[scene["control_uuid"]]
            matching = [m for m in sources.moods[c.uuid]["moods"] if m["id"] == scene["mood_id"]]
            mood = (
                matching[0]
                if len(matching) == 1
                and scene["mood_id"] not in sources.moods[c.uuid]["ambiguous_ids"]
                else {"name": None, "name_truncated": True}
            )
            add(
                "scene_roles",
                "declared_scene_role",
                "conditional",
                [ref(c, scene["mood_id"])],
                {
                    "declaration": scene,
                    "name": mood["name"],
                    "technical_source_does_not_confirm_role": True,
                },
            )
            if scene.get("role") and mood["name"] and not mood["name_truncated"]:
                roles[scene["role"]].append((scene, mood))
        for role, rows in roles.items():
            if len({m["name"] for _, m in rows}) > 1:
                add(
                    "scene_roles",
                    "declared_role_name_variation",
                    "review_candidate",
                    [ref(by_id[s["control_uuid"]], s["mood_id"]) for s, _ in rows[:16]],
                    {
                        "role": role,
                        "scene_count": len(rows),
                        "references_omitted": max(0, len(rows) - 16),
                        "origins": sorted({s["origin"] for s, _ in rows}),
                        "fault": "not_established",
                    },
                )
        if not sources.normalized["scenes"]:
            add(
                "scene_roles",
                "scene_roles_missing",
                "context_gap",
                [],
                {"inferred_from_names": False},
            )
    if "planning_context" in analyses:
        rooms = {r["room_uuid"]: r for r in sources.normalized["rooms"]}
        for room_id in sorted({c.room_uuid for c in controls}, key=lambda x: x or ""):
            declaration = rooms.get(room_id, {})
            missing = [
                key
                for key in ("usage", "intent", "tunable_white_installed", "zones")
                if declaration.get(key) is None or declaration.get(key) == []
            ]
            add(
                "planning_context",
                "conditional_room_review",
                "conditional",
                [ref(c) for c in controls if c.room_uuid == room_id],
                {
                    "declarations": declaration,
                    "missing_context": missing,
                    "installed_luminaires": "not_technically_verified",
                    "controller_kelvin_defaults_prove_fixtures": False,
                    "advice": (
                        "Confirm room use, intent, installed fixtures and zones "
                        "before design recommendations."
                    ),
                },
            )
    return {
        "scope": "lighting",
        "analysis_version": LIGHTING_ANALYSIS_VERSION,
        "project_fingerprint": project.view.snapshot.fingerprint,
        "model_version": project.view.snapshot.model_version,
        "runtime_version": project.view.mapping.structure_fingerprint,
        "analyses": sorted(analyses),
        "coverage": {
            "selected": len(controls),
            "excluded": sources.excluded,
            "selection_complete": sources.excluded == 0,
            "supported": sum(c.control_type == "LightControllerV2" for c in controls),
            "naming_comparison_complete": sources.excluded == 0
            and all(
                c.control_type == "LightControllerV2"
                and full_name(c.name)
                and sources.moods[c.uuid]["status"] == "available"
                and sources.moods[c.uuid]["freshness"] == "current"
                and sources.moods[c.uuid]["names_complete"]
                and sources.moods[c.uuid]["omitted"] == 0
                and not sources.moods[c.uuid]["ambiguous_ids"]
                for c in controls
            ),
        },
        "findings": findings,
        "analysis_truncated": sources.excluded > 0,
        "truncation_reasons": ["max_selected_controllers"] if sources.excluded else [],
        "limitations": [
            "selected_visible_evidence_only",
            "naming_candidates_are_not_faults",
            "declared_roles_are_not_measured_causation",
            "controller_capability_does_not_prove_installed_luminaires",
            "conditional_review_not_professional_physical_audit",
        ],
    }
