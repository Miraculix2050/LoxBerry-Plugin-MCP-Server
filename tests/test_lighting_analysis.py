"""Lighting declarations never replace native identity, authorization or graph evidence."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from test_lighting_relationships import CHILD, LIGHT, OTHER, SOURCE, lighting_query

import mcpserver.lighting_analysis as domain
import mcpserver.tools as tools
from mcpserver.lighting_analysis import (
    LIGHTING_ANALYSES,
    LightingAnalysisData,
    LightingContext,
    LightingSelection,
    analyze_lighting,
    prepare_lighting,
)
from mcpserver.loxone.models import Freshness, LoxoneIdentity, LoxoneStructure, Room, StateRecord
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.project.worker import process_analysis
from mcpserver.loxone.runtime import ControlOperationError, RuntimeSnapshot


@asynccontextmanager
async def slot():
    yield


def fixture(central=None):
    query = lighting_query(central)
    # Use actual native graph/mapping fixtures, not inferred relationships from names.
    from mcpserver.loxone.models import Control

    child = Control(CHILD, "Same", "Dimmer", "room", None, None, ())
    light = Control(
        LIGHT,
        "Same",
        "LightControllerV2",
        "room",
        None,
        None,
        (("moodList", "moods"),),
        subcontrols=(child,),
    )
    other = replace(
        light,
        uuid=OTHER,
        room_uuid="other",
        subcontrols=(),
        state_uuids=(("moodList", "other-moods"),),
    )
    sensor = replace(
        light,
        uuid=SOURCE,
        control_type="UserSelectedSource",
        room_uuid="outside",
        subcontrols=(),
        state_uuids=(),
    )
    structure = LoxoneStructure(
        LoxoneIdentity("reader", "synthetic"),
        "v1",
        (Room("room", "Same"), Room("other", "Same"), Room("outside", "Outside")),
        (),
        (sensor, light, other),
    )
    snapshot = RuntimeSnapshot("family", structure, True)
    project_snapshot = replace(query.view.snapshot, content_identity="fixture-v1")
    query = ProjectQuery(
        ProjectView(project_snapshot, map_runtime(project_snapshot, structure)), {}
    )
    records = {
        "moods": StateRecord(
            "moods", [{"id": 1, "name": "Same"}, {"id": 2, "name": "Other"}], Freshness.CURRENT, 100
        ),
        "other-moods": StateRecord(
            "other-moods", [{"id": 1, "name": "Same"}], Freshness.CURRENT, 100
        ),
    }
    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin="https://synthetic.invalid"),
        projects=SimpleNamespace(authorize=AsyncMock()),
        state=lambda snap, uuid: records[uuid],
        worker_slot=slot,
    )
    return runtime, snapshot, query, records


def context(**values):
    return LightingContext.model_validate(
        {"schema_version": "lighting_analysis_context.v1", **values}
    )


def declared(**values):
    return {"origin": "scenario_assumption", "rationale": "Explicit test declaration", **values}


async def prepared(central=None, ctx=None):
    runtime, snapshot, query, records = fixture(central)
    selection = LightingSelection(controller_uuids=[LIGHT, OTHER])
    return (
        runtime,
        snapshot,
        query,
        records,
        await prepare_lighting(runtime, snapshot, selection, ctx, None),
    )


async def validate_sources(source, runtime, snapshot, profile_path):
    bindings, revision = await source.current_bindings(runtime, snapshot.structure, profile_path)
    source.validate(runtime, snapshot, bindings, revision, profile_path)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"controller_uuids": []},
        {"controller_uuids": [LIGHT, LIGHT]},
        {"controller_uuids": [LIGHT], "room_uuid": "room"},
        {"room_uuid": "room", "max_depth": 17},
        {"room_uuid": "room", "max_nodes": 201},
        {"room_uuid": "room", "extra": True},
    ],
)
def test_selection_rejects_ambiguous_unbounded_or_unknown_inputs(value):
    with pytest.raises(ValidationError):
        LightingSelection.model_validate(value)


@pytest.mark.parametrize(
    "value",
    [
        {"version": "lighting_analysis_context.v1"},
        {"schema_version": "v2"},
        {"schema_version": "lighting_analysis_context.v1", "unknown": True},
        {
            "schema_version": "lighting_analysis_context.v1",
            "scenes": [declared(controller_uuid=LIGHT, binding_id="also", mood_id="1")],
        },
        {
            "schema_version": "lighting_analysis_context.v1",
            "scenes": [declared(controller_uuid=LIGHT, mood_id="../on")],
        },
        {
            "schema_version": "lighting_analysis_context.v1",
            "rooms": [{"room_uuid": "room", "origin": "user_confirmed"}],
        },
        {
            "schema_version": "lighting_analysis_context.v1",
            "rooms": [{"room_uuid": "room", "zones": [declared(value="a"), declared(value="a")]}],
        },
    ],
)
def test_context_contract_is_typed_and_per_field_provenance(value):
    with pytest.raises(ValidationError):
        LightingContext.model_validate(value)


def test_context_total_byte_bound_with_multibyte_declarations():
    with pytest.raises(ValidationError, match="64 KiB"):
        context(
            scenes=[
                declared(controller_uuid=LIGHT, mood_id=str(i), role="x" * 64, rationale="😀" * 256)
                for i in range(100)
            ]
        )


@pytest.mark.asyncio
async def test_inventory_and_naming_preserve_rooms_children_and_mood_identity():
    _, _, query, _, sources = await prepared()
    result = analyze_lighting(query, sources, frozenset(LIGHTING_ANALYSES))
    model = LightingAnalysisData.model_validate(result)
    inventory = [f for f in model.findings if f.code == "visible_lighting_inventory"]
    assert len(inventory) == 2
    first = next(f for f in inventory if f.references[0].controller_uuid == LIGHT)
    assert first.evidence["outputs"][0]["uuid"] == CHILD
    assert first.evidence["parent_runtime_control_uuid"] == LIGHT
    repeated = next(f for f in model.findings if f.code == "repeated_controller_name")
    assert {r.room_uuid for r in repeated.references} == {"room", "other"}
    repeated_mood = next(f for f in model.findings if f.code == "repeated_visible_mood_name")
    assert {(r.controller_uuid, r.mood_id) for r in repeated_mood.references} == {
        (LIGHT, "1"),
        (OTHER, "1"),
    }
    assert repeated_mood.classification == "review_candidate"
    assert all(
        f.evidence.get("operating_causation", "unverified") == "unverified" for f in model.findings
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "central,reachable", [(None, True), ("Or", True), ("UnsupportedCentral", False)]
)
async def test_declared_presence_outside_selection_uses_existing_paths_only(central, reachable):
    ctx = context(presence_sources=[declared(control_uuid=SOURCE)])
    _, _, query, _, sources = await prepared(central, ctx)
    result = analyze_lighting(query, sources, frozenset({"presence_relationships"}))
    row = next(f for f in result["findings"] if f["references"][0]["controller_uuid"] == LIGHT)
    relationship = row["evidence"]["relationships"][0]
    assert (relationship["status"] == "configured_upstream_reachability") == reachable
    assert relationship["declared_presence_origin"] == "scenario_assumption"
    assert row["evidence"]["operating_causation"] == "unverified"
    if not reachable:
        assert row["evidence"]["semantic_gaps"]


@pytest.mark.asyncio
async def test_derived_child_presence_is_not_an_association_with_its_parent():
    ctx = context(presence_sources=[declared(control_uuid=CHILD)])
    _, _, query, _, sources = await prepared(ctx=ctx)
    row = analyze_lighting(query, sources, frozenset({"presence_relationships"}))["findings"][0]
    relation = row["evidence"]["relationships"][0]
    assert relation["control_uuid"] == CHILD
    assert relation["status"] == "shared_anchor_not_an_association"
    assert relation["runtime_target_mapping"]["parent_runtime_control_uuid"] == LIGHT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,rows",
    [
        ("scenes", [declared(controller_uuid=LIGHT, mood_id="1")] * 2),
        ("presence_sources", [declared(control_uuid=SOURCE)] * 2),
        ("rooms", [{"room_uuid": "room"}] * 2),
        ("naming_rules", [declared(controller_uuid=LIGHT, value="A")] * 2),
        (
            "naming_rules",
            [declared(controller_uuid=LIGHT, value="A"), declared(room_uuid="room", value="B")],
        ),
    ],
)
async def test_all_resolved_duplicates_and_overlapping_prefixes_are_rejected(field, rows):
    runtime, snapshot, _, _ = fixture()
    with pytest.raises(ValueError):
        await prepare_lighting(
            runtime,
            snapshot,
            LightingSelection(controller_uuids=[LIGHT]),
            context(**{field: rows}),
            None,
        )


@pytest.mark.asyncio
async def test_profile_confirmation_never_upgrades_scene_role_or_presence_declaration(monkeypatch):
    runtime, snapshot, query, _ = fixture()
    bindings = {
        "light": {"status": "confirmed", "role": "lighting_intent", "control_uuid": LIGHT},
        "sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE},
    }
    read = AsyncMock(return_value=(bindings, 7))
    monkeypatch.setattr(domain, "read_profile_bindings", read)
    ctx = context(
        scenes=[declared(binding_id="light", mood_id="1", role="Task")],
        presence_sources=[declared(binding_id="sensor")],
    )
    source = await prepare_lighting(
        runtime, snapshot, LightingSelection(controller_uuids=[LIGHT]), ctx, None
    )
    assert read.call_args.kwargs["required"] is True
    assert source.normalized["scenes"][0]["source_origin"] == "user_confirmed"
    assert source.normalized["scenes"][0]["origin"] == "scenario_assumption"
    assert source.normalized["presence_sources"][0]["origin"] == "scenario_assumption"
    await validate_sources(source, runtime, snapshot, None)
    bindings["light"] = {**bindings["light"], "rationale": "same revision mutation"}
    with pytest.raises(ControlOperationError, match="changed"):
        await validate_sources(source, runtime, snapshot, None)
    # Also reject two references resolving to the same controller+mood identity.
    with pytest.raises(ValueError, match="duplicate"):
        await prepare_lighting(
            runtime,
            snapshot,
            source.selection,
            context(
                scenes=[
                    declared(binding_id="light", mood_id="1"),
                    declared(controller_uuid=LIGHT, mood_id="1"),
                ]
            ),
            None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,role", [("draft", "lighting_intent"), ("confirmed", "room_sensor")]
)
async def test_unusable_or_wrong_role_profile_reference_rejected(monkeypatch, status, role):
    runtime, snapshot, _, _ = fixture()
    monkeypatch.setattr(
        domain,
        "read_profile_bindings",
        AsyncMock(return_value=({"b": {"status": status, "role": role, "control_uuid": LIGHT}}, 1)),
    )
    with pytest.raises(ControlOperationError):
        await prepare_lighting(
            runtime,
            snapshot,
            LightingSelection(controller_uuids=[LIGHT]),
            context(scenes=[declared(binding_id="b", mood_id="1")]),
            None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stale", "missing", "invalid", "wrong_id"])
async def test_scene_requires_fresh_exact_native_membership(kind):
    runtime, snapshot, _, records = fixture()
    if kind == "stale":
        records["moods"] = replace(records["moods"], freshness=Freshness.STALE)
    if kind == "missing":
        records["moods"] = replace(records["moods"], value=None)
    if kind == "invalid":
        records["moods"] = replace(records["moods"], value="[")
    with pytest.raises(ControlOperationError):
        await prepare_lighting(
            runtime,
            snapshot,
            LightingSelection(controller_uuids=[LIGHT]),
            context(
                scenes=[
                    declared(controller_uuid=LIGHT, mood_id="99" if kind == "wrong_id" else "1")
                ]
            ),
            None,
        )


@pytest.mark.asyncio
async def test_explicit_scene_after_inventory_projection_limit_is_valid_without_invented_name():
    runtime, snapshot, query, records = fixture()
    records["moods"] = replace(
        records["moods"], value=[{"id": i, "name": "Mood"} for i in range(105)]
    )
    source = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT]),
        context(scenes=[declared(controller_uuid=LIGHT, mood_id="104", role="Selected")]),
        None,
    )
    result = analyze_lighting(query, source, frozenset({"scene_roles"}))
    assert result["findings"][0]["references"][0]["mood_id"] == "104"
    assert result["findings"][0]["evidence"]["name"] is None


@pytest.mark.asyncio
async def test_room_selection_is_exact_deterministic_partial_and_empty_is_not_whole_house():
    runtime, snapshot, _, _ = fixture()
    light = snapshot.structure.controls[1]
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(replace(light, uuid=f"light-{i:02d}") for i in reversed(range(20))),
    )
    sources = await prepare_lighting(
        runtime, snapshot, LightingSelection(room_uuid="room"), None, None
    )
    assert len(sources.controls) == 16 and sources.excluded == 4
    assert [c.uuid for c in sources.controls] == [f"light-{i:02d}" for i in range(16)]
    empty = await prepare_lighting(
        runtime, snapshot, LightingSelection(room_uuid="outside"), None, None
    )
    assert empty.controls == ()
    await validate_sources(empty, runtime, snapshot, None)
    with pytest.raises(ControlOperationError):
        await prepare_lighting(runtime, snapshot, LightingSelection(room_uuid="Same"), None, None)


@pytest.mark.asyncio
async def test_typed_room_context_keeps_independent_origins_and_never_proves_fixtures():
    ctx = context(
        rooms=[
            {
                "room_uuid": "room",
                "usage": declared(value="Desk", origin="user_confirmed"),
                "intent": declared(value="Read"),
                "tunable_white_installed": declared(value=True),
                "zones": [declared(value="Desk")],
            }
        ]
    )
    _, _, query, _, source = await prepared(ctx=ctx)
    rows = analyze_lighting(query, source, frozenset({"planning_context"}))["findings"]
    row = next(r for r in rows if r["references"][0]["room_uuid"] == "room")
    d = row["evidence"]["declarations"]
    assert (
        d["usage"]["origin"] == "user_confirmed" and d["intent"]["origin"] == "scenario_assumption"
    )
    assert row["evidence"]["controller_kelvin_defaults_prove_fixtures"] is False


def runner_fixture(monkeypatch):
    runtime, snapshot, query, records = fixture()
    access = SimpleNamespace(family_id="family", miniserver_id="installation", identity_id="reader")
    reads = []

    async def project(_runtime):
        reads.append(True)
        return getattr(runtime, "final_query", query), snapshot

    monkeypatch.setattr(tools, "_project_query", project)
    monkeypatch.setattr(tools, "_access", lambda: access)

    async def worker(view, checks, **kwargs):
        return analyze_lighting(query, kwargs["lighting_sources"], checks)

    compute = AsyncMock(side_effect=worker)
    monkeypatch.setattr(tools, "process_analysis", compute)
    return (
        tools._ProjectAnalysisRunner(runtime),
        runtime,
        snapshot,
        query,
        records,
        access,
        reads,
        compute,
    )


@pytest.mark.asyncio
async def test_existing_cache_pagination_reauthorizes_every_page_and_isolated_family(monkeypatch):
    runner, runtime, _, _, _, access, reads, compute = runner_fixture(monkeypatch)
    args = {"lighting_selection": LightingSelection(controller_uuids=[LIGHT, OTHER])}
    first = await runner.run("lighting", None, limit=1, **args)
    assert first.ok and first.data.next_cursor and len(first.data.findings) == 1
    second = await runner.run("lighting", None, cursor=first.data.next_cursor, limit=1, **args)
    assert second.ok and compute.await_count == 1 and len(reads) == 4
    assert first.data.findings[0].finding_id != second.data.findings[0].finding_id
    access.family_id = "another"
    assert not (await runner.run("lighting", None, cursor=first.data.next_cursor, **args)).ok
    assert runtime.projects.authorize.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["mood", "room", "visibility", "source", "project", "connection"]
)
async def test_publication_rejects_same_revision_mutations_and_revoked_visibility(
    monkeypatch, change
):
    runner, runtime, snapshot, query, records, _, _, compute = runner_fixture(monkeypatch)

    async def worker(*args, **kwargs):
        result = analyze_lighting(query, kwargs["lighting_sources"], args[1])
        if change == "mood":
            records["moods"] = replace(records["moods"], value=[{"id": 1, "name": "Changed"}])
        if change == "room":
            snapshot.structure = replace(snapshot.structure, rooms=(Room("room", "Changed"),))
        if change == "visibility":
            snapshot.structure = replace(snapshot.structure, controls=())
        if change == "source":
            snapshot.structure = replace(
                snapshot.structure,
                controls=tuple(
                    replace(c, name="Changed") if c.uuid == LIGHT else c
                    for c in snapshot.structure.controls
                ),
            )
        if change == "project":
            runtime.final_query = replace(
                query,
                view=replace(
                    query.view, snapshot=replace(query.view.snapshot, content_identity="changed")
                ),
            )
        if change == "connection":
            snapshot.connected = False
        return result

    compute.side_effect = worker
    result = await runner.run(
        "lighting", None, lighting_selection=LightingSelection(controller_uuids=[LIGHT])
    )
    assert not result.ok and result.data.error == "temporarily_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["context", "mood", "room", "selection"])
async def test_cursor_is_bound_to_context_and_current_sources(monkeypatch, change):
    runner, _, snapshot, _, records, _, _, _ = runner_fixture(monkeypatch)
    selection = LightingSelection(controller_uuids=[LIGHT, OTHER])
    first = await runner.run("lighting", None, limit=1, lighting_selection=selection)
    kwargs = {"lighting_selection": selection}
    if change == "context":
        kwargs["lighting_context"] = context(presence_sources=[declared(control_uuid=SOURCE)])
    if change == "mood":
        records["moods"] = replace(records["moods"], value=[{"id": 1, "name": "Changed"}])
    if change == "room":
        snapshot.structure = replace(snapshot.structure, rooms=(Room("room", "Changed"),))
    if change == "selection":
        kwargs["lighting_selection"] = LightingSelection(controller_uuids=[LIGHT])
    assert not (await runner.run("lighting", None, cursor=first.data.next_cursor, **kwargs)).ok


@pytest.mark.asyncio
async def test_legacy_arguments_and_ets_options_do_not_leak_into_lighting_scope(monkeypatch):
    runner, *_ = runner_fixture(monkeypatch)
    selection = LightingSelection(controller_uuids=[LIGHT])
    assert not (await runner.run("lighting", None)).ok
    assert not (await runner.run("knx", None, lighting_selection=selection)).ok
    assert not (await runner.run("modbus", None, lighting_context=context())).ok
    assert not (await runner.run("lighting", None, lighting_selection=selection, view="summary")).ok
    assert not (await runner.run("lighting", ["address_patterns"], lighting_selection=selection)).ok


@pytest.mark.asyncio
async def test_isolated_worker_and_mcp_schema_use_the_existing_surface(monkeypatch):
    _, _, query, _, source = await prepared()
    actual = await process_analysis(
        query.view, frozenset(LIGHTING_ANALYSES), scope="lighting", lighting_sources=source
    )
    assert actual == analyze_lighting(query, source, frozenset(LIGHTING_ANALYSES))
    runner, runtime, *_ = runner_fixture(monkeypatch)
    del runner
    server = FastMCP("lighting-analysis")
    tools.register_project_tools(server, runtime)
    tool = server._tool_manager.get_tool("loxone_analyze_project")
    assert tool.parameters["properties"]["scope"]["default"] == "knx"
    assert tool.parameters["properties"]["analyses"]["x-analyses-by-scope"]["lighting"] == list(
        LIGHTING_ANALYSES
    )
    assert "lighting_selection" in tool.parameters["properties"]
    result = await tool.fn(
        scope="lighting", lighting_selection=LightingSelection(controller_uuids=[LIGHT])
    )
    assert result.ok and result.data.scope == "lighting"


@pytest.mark.asyncio
async def test_large_inventory_pages_fit_existing_byte_budget_without_losing_findings(monkeypatch):
    runner, runtime, snapshot, query, records, _, _, _ = runner_fixture(monkeypatch)
    light = snapshot.structure.controls[1]
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(
            replace(light, uuid=f"controller-{i:02d}", subcontrols=()) for i in range(16)
        ),
    )
    records["moods"] = replace(
        records["moods"], value=[{"id": i, "name": "x" * 200} for i in range(100)]
    )
    selection = LightingSelection(room_uuid="room")
    cursor = None
    ids = []
    while True:
        page = await runner.run(
            "lighting", ["inventory"], cursor=cursor, limit=50, lighting_selection=selection
        )
        assert page.ok and len(page.model_dump_json().encode()) <= 65_536
        ids.extend(f.finding_id for f in page.data.findings)
        cursor = page.data.next_cursor
        if cursor is None:
            break
    assert len(ids) == 16 and len(set(ids)) == 16
    assert len(runner.cache) == 1


@pytest.mark.asyncio
async def test_cache_hit_requires_fresh_final_visibility_and_authorization(monkeypatch):
    runner, runtime, snapshot, query, _, _, _, compute = runner_fixture(monkeypatch)
    selection = LightingSelection(controller_uuids=[LIGHT])
    assert (await runner.run("lighting", None, lighting_selection=selection)).ok
    calls = 0

    async def project(_runtime):
        nonlocal calls
        calls += 1
        return query, replace(
            snapshot, structure=replace(snapshot.structure, controls=())
        ) if calls == 2 else snapshot

    monkeypatch.setattr(tools, "_project_query", project)
    result = await runner.run("lighting", None, lighting_selection=selection)
    assert not result.ok and compute.await_count == 1
    monkeypatch.setattr(tools, "_project_query", AsyncMock(return_value=(query, snapshot)))
    runtime.projects.authorize.side_effect = PermissionError()
    result = await runner.run("lighting", None, lighting_selection=selection)
    assert not result.ok and result.data.error == "unauthenticated"


@pytest.mark.asyncio
async def test_profile_revision_installation_and_companion_mutations_are_publication_guards(
    monkeypatch,
):
    runtime, snapshot, _, _ = fixture()
    bindings = {"sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE}}
    read = AsyncMock(return_value=(bindings, 1))
    monkeypatch.setattr(domain, "read_profile_bindings", read)
    source = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT]),
        context(presence_sources=[declared(binding_id="sensor")]),
        None,
    )
    read.return_value = (bindings, 2)
    with pytest.raises(ControlOperationError):
        await validate_sources(source, runtime, snapshot, None)
    read.return_value = (bindings, 1)
    runtime.endpoint.origin = "https://other.invalid"
    with pytest.raises(ControlOperationError):
        await validate_sources(source, runtime, snapshot, None)
    runtime.endpoint.origin = "https://synthetic.invalid"
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(
            replace(c, control_type="Changed") if c.uuid == SOURCE else c
            for c in snapshot.structure.controls
        ),
    )
    with pytest.raises(ControlOperationError):
        await validate_sources(source, runtime, snapshot, None)


@pytest.mark.asyncio
async def test_exact_hidden_and_unsupported_sources_keep_unknown_evidence():
    runtime, snapshot, query, _ = fixture()
    child = await prepare_lighting(
        runtime, snapshot, LightingSelection(controller_uuids=[CHILD]), None, None
    )
    result = analyze_lighting(query, child, frozenset({"inventory"}))
    assert result["findings"][0]["references"][0]["controller_uuid"] == CHILD
    assert result["findings"][0]["code"] == "unsupported_controller_type"
    assert not result["coverage"]["naming_comparison_complete"]
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(
            replace(c, is_hidden=True) if c.uuid == LIGHT else c
            for c in snapshot.structure.controls
        ),
    )
    with pytest.raises(ControlOperationError):
        await prepare_lighting(
            runtime, snapshot, LightingSelection(controller_uuids=[LIGHT]), None, None
        )
    # A hidden parent does not grant or revoke a separately visible child's identity.
    # The normalized hidden corpus, unlike explicit visible controls, is excluded.
    snapshot.structure = replace(
        snapshot.structure,
        hidden_controls=tuple(c for c in snapshot.structure.controls if c.uuid == LIGHT),
        controls=tuple(c for c in snapshot.structure.controls if c.uuid != LIGHT),
    )
    with pytest.raises(ControlOperationError):
        await prepare_lighting(
            runtime, snapshot, LightingSelection(controller_uuids=[CHILD]), None, None
        )


@pytest.mark.asyncio
async def test_duplicate_mood_ids_and_truncated_names_do_not_create_complete_naming_evidence():
    runtime, snapshot, query, records = fixture()
    records["moods"] = replace(
        records["moods"], value=[{"id": 1, "name": "a"}, {"id": 1, "name": "b"}]
    )
    source = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT]),
        context(scenes=[declared(controller_uuid=LIGHT, mood_id="1", role="Task")]),
        None,
    )
    result = analyze_lighting(query, source, frozenset(LIGHTING_ANALYSES))
    assert not result["coverage"]["naming_comparison_complete"]
    role = next(r for r in result["findings"] if r["code"] == "declared_scene_role")
    assert role["evidence"]["name"] is None
    records["moods"] = replace(records["moods"], value=[{"id": 1, "name": "x" * 201}])
    source = await prepare_lighting(runtime, snapshot, source.selection, None, None)
    assert not analyze_lighting(query, source, frozenset({"naming_consistency"}))["coverage"][
        "naming_comparison_complete"
    ]


@pytest.mark.asyncio
async def test_context_order_normalizes_to_the_same_identity():
    runtime, snapshot, _, _ = fixture()
    rows = [
        declared(controller_uuid=LIGHT, mood_id="1"),
        declared(controller_uuid=OTHER, mood_id="1"),
    ]
    a = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT, OTHER]),
        context(scenes=rows),
        None,
    )
    b = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[OTHER, LIGHT]),
        context(scenes=rows[::-1]),
        None,
    )
    assert (
        a.selection == b.selection and a.normalized == b.normalized and a.source_key == b.source_key
    )


@pytest.mark.asyncio
async def test_cache_key_includes_mapping_changes_outside_selected_control_signature(monkeypatch):
    runner, runtime, _, query, _, _, _, compute = runner_fixture(monkeypatch)
    selection = LightingSelection(controller_uuids=[LIGHT])
    assert (await runner.run("lighting", None, lighting_selection=selection)).ok
    runtime.final_query = replace(
        query,
        view=replace(
            query.view,
            mapping=replace(query.view.mapping, structure_fingerprint="changed-visible-mapping"),
        ),
    )
    assert (await runner.run("lighting", None, lighting_selection=selection)).ok
    assert compute.await_count == 2


@pytest.mark.asyncio
async def test_revocation_during_publication_profile_recheck_is_not_published(monkeypatch):
    runner, runtime, *_ = runner_fixture(monkeypatch)
    runtime.projects.authorize.side_effect = [None, PermissionError()]
    result = await runner.run(
        "lighting", None, lighting_selection=LightingSelection(controller_uuids=[LIGHT])
    )
    assert not result.ok and result.data.error == "unauthenticated"


@pytest.mark.asyncio
async def test_reachable_child_reports_only_its_parent_anchor_not_an_exact_config_block():
    runtime, snapshot, query, _ = fixture()
    from mcpserver.loxone.models import Control

    source_child = Control(
        SOURCE + "/AI1", "Declared source child", "Switch", "outside", None, None, ()
    )
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(
            replace(c, subcontrols=(source_child,)) if c.uuid == SOURCE else c
            for c in snapshot.structure.controls
        ),
    )
    query = ProjectQuery(
        ProjectView(query.view.snapshot, map_runtime(query.view.snapshot, snapshot.structure)), {}
    )
    source = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT]),
        context(presence_sources=[declared(control_uuid=source_child.uuid)]),
        None,
    )
    row = analyze_lighting(query, source, frozenset({"presence_relationships"}))["findings"][0]
    relation = row["evidence"]["relationships"][0]
    assert relation["status"] == "parent_anchor_upstream_reachability"
    assert relation["control_uuid"] == source_child.uuid
    assert relation["runtime_target_mapping"]["parent_runtime_control_uuid"] == SOURCE


@pytest.mark.parametrize("field", ["scenes", "presence_sources"])
@pytest.mark.parametrize("binding", [" ", "../binding", "bad/ref"])
def test_profile_reference_grammar_matches_existing_identifiers(field, binding):
    row = declared(binding_id=binding)
    if field == "scenes":
        row["mood_id"] = "1"
    with pytest.raises(ValidationError):
        context(**{field: [row]})


@pytest.mark.asyncio
async def test_naming_only_does_not_publish_stale_mood_name_collisions():
    runtime, snapshot, query, records = fixture()
    for key in records:
        records[key] = replace(records[key], freshness=Freshness.STALE)
    source = await prepare_lighting(
        runtime, snapshot, LightingSelection(controller_uuids=[LIGHT, OTHER]), None, None
    )
    result = analyze_lighting(query, source, frozenset({"naming_consistency"}))
    assert not any(f["code"] == "repeated_visible_mood_name" for f in result["findings"])
    assert not result["coverage"]["naming_comparison_complete"]


@pytest.mark.asyncio
async def test_selected_scene_without_role_reports_exact_missing_context():
    ctx = context(
        scenes=[
            declared(controller_uuid=LIGHT, mood_id="1"),
            declared(controller_uuid=OTHER, mood_id="1", role="Task"),
        ]
    )
    _, _, query, _, sources = await prepared(ctx=ctx)
    result = analyze_lighting(query, sources, frozenset({"scene_roles"}))
    missing = next(f for f in result["findings"] if f["code"] == "scene_roles_missing")
    assert missing["references"] == [
        {"controller_uuid": LIGHT, "room_uuid": "room", "mood_id": "1"}
    ]
    assert not any(
        f["code"] == "declared_scene_role" and f["references"][0]["controller_uuid"] == LIGHT
        for f in result["findings"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepare", "publication"])
async def test_profile_operational_failure_is_unavailability(monkeypatch, phase):
    from mcpserver.installation_profile import ProfileError

    runner, *_ = runner_fixture(monkeypatch)
    bindings = {"sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE}}
    read = AsyncMock(
        side_effect=[ProfileError("profile_corrupt")]
        if phase == "prepare"
        else [(bindings, 1), ProfileError("profile_busy")]
    )
    monkeypatch.setattr(domain, "read_profile_bindings", read)
    result = await runner.run(
        "lighting",
        None,
        lighting_selection=LightingSelection(controller_uuids=[LIGHT]),
        lighting_context=context(presence_sources=[declared(binding_id="sensor")]),
    )
    assert not result.ok and result.data.error == "temporarily_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["visibility", "room", "source"])
async def test_profile_await_cannot_publish_a_pre_await_runtime_snapshot(monkeypatch, change):
    runner, runtime, snapshot, query, _, _, reads, _ = runner_fixture(monkeypatch)
    bindings = {"sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE}}
    count = 0

    async def read(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            # Simulate a change while the asynchronous publication profile read runs.
            if change == "visibility":
                snapshot.structure = replace(snapshot.structure, controls=())
            if change == "room":
                snapshot.structure = replace(snapshot.structure, rooms=(Room("room", "Changed"),))
            if change == "source":
                snapshot.structure = replace(
                    snapshot.structure,
                    controls=tuple(
                        replace(c, state_uuids=()) if c.uuid == LIGHT else c
                        for c in snapshot.structure.controls
                    ),
                )
        return bindings, 1

    monkeypatch.setattr(domain, "read_profile_bindings", read)
    result = await runner.run(
        "lighting",
        None,
        lighting_selection=LightingSelection(controller_uuids=[LIGHT]),
        lighting_context=context(presence_sources=[declared(binding_id="sensor")]),
    )
    assert not result.ok and result.data.error == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_unresolved_trace_truncation_is_exposed_with_its_partial_count():
    runtime, snapshot, query, _ = fixture()
    key = query.resolve(LIGHT, "runtime_control_uuid").key
    graph = replace(
        query.view.snapshot.graph, unresolved=tuple((key, "fixture_unresolved") for _ in range(10))
    )
    project = replace(query.view.snapshot, graph=graph)
    query = ProjectQuery(ProjectView(project, map_runtime(project, snapshot.structure)), {})
    sources = await prepare_lighting(
        runtime, snapshot, LightingSelection(controller_uuids=[LIGHT], max_nodes=2), None, None
    )
    row = analyze_lighting(query, sources, frozenset({"presence_relationships"}))["findings"][0]
    assert row["evidence"]["unresolved_relationships"] == 2
    assert row["evidence"]["unresolved_truncated"] is True


@pytest.mark.asyncio
async def test_selected_lighting_child_retains_target_mapping_provenance():
    runtime, snapshot, query, _ = fixture()
    light = snapshot.structure.controls[1]
    child = replace(light, uuid=CHILD, subcontrols=())
    snapshot.structure = replace(
        snapshot.structure,
        controls=tuple(
            replace(c, subcontrols=(child,)) if c.uuid == LIGHT else c
            for c in snapshot.structure.controls
        ),
    )
    query = ProjectQuery(
        ProjectView(query.view.snapshot, map_runtime(query.view.snapshot, snapshot.structure)), {}
    )
    sources = await prepare_lighting(
        runtime, snapshot, LightingSelection(controller_uuids=[CHILD]), None, None
    )
    row = analyze_lighting(query, sources, frozenset({"presence_relationships"}))["findings"][0]
    provenance = row["evidence"]["runtime_target_mapping"]
    assert row["references"][0]["controller_uuid"] == CHILD
    assert provenance["runtime_control_uuid"] == CHILD
    assert provenance["parent_runtime_control_uuid"] == LIGHT
    assert provenance["mapping_status"] == "derived_from_parent"


@pytest.mark.asyncio
async def test_direct_sources_do_not_require_profile_serial_or_identity(monkeypatch):
    runtime, snapshot, query, _ = fixture()
    snapshot.structure = replace(
        snapshot.structure, identity=replace(snapshot.structure.identity, miniserver_serial="")
    )

    def forbidden(*args):
        raise AssertionError("profile identity must not be constructed")

    monkeypatch.setattr(domain, "installation_identity", forbidden)
    monkeypatch.setattr(domain, "_profile_digest", forbidden)
    source = await prepare_lighting(
        runtime,
        snapshot,
        LightingSelection(controller_uuids=[LIGHT]),
        context(scenes=[declared(controller_uuid=LIGHT, mood_id="1", role="Task")]),
        None,
    )
    assert analyze_lighting(query, source, frozenset({"inventory"}))["findings"]
    await validate_sources(source, runtime, snapshot, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["authorization", "final_project"])
@pytest.mark.parametrize("change", ["rewrite", "delete", "replace"])
async def test_profile_file_changes_across_later_awaits_are_rejected(
    monkeypatch, tmp_path, when, change
):
    runner, runtime, snapshot, query, _, _, _, _ = runner_fixture(monkeypatch)
    path = tmp_path / "installation-profile.json"
    path.write_text('{"content":"initial"}', encoding="utf-8")
    runner.profile_path = path
    bindings = {"sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE}}
    monkeypatch.setattr(domain, "read_profile_bindings", AsyncMock(return_value=(bindings, 1)))
    calls = 0

    def mutate():
        if change == "rewrite":
            path.write_text('{"content":"changed"}', encoding="utf-8")
        elif change == "delete":
            path.unlink()
        else:
            other = tmp_path / "replacement.json"
            other.write_text('{"content":"changed"}', encoding="utf-8")
            other.replace(path)

    async def authorization(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            mutate()

    async def project(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            mutate()
        return query, snapshot

    if when == "authorization":
        runtime.projects.authorize = AsyncMock(side_effect=authorization)
    else:
        monkeypatch.setattr(tools, "_project_query", project)
    result = await runner.run(
        "lighting",
        None,
        lighting_selection=LightingSelection(controller_uuids=[LIGHT]),
        lighting_context=context(presence_sources=[declared(binding_id="sensor")]),
    )
    assert not result.ok and result.data.error == "temporarily_unavailable"


def test_shared_snapshot_keeps_strict_legacy_defaults_and_refuses_profile_bypass():
    from mcpserver.analysis_context import SourceSnapshot
    from mcpserver.installation_profile import ProfileError, installation_identity

    runtime, snapshot, _, _ = fixture()
    guard = SourceSnapshot.capture(
        runtime.endpoint.origin, snapshot.structure, {LIGHT}, {}, None, set()
    )
    assert guard.source_identity is None
    assert guard.installation == installation_identity(runtime.endpoint.origin, snapshot.structure)
    guard.validate(runtime.endpoint.origin, snapshot.structure, {}, None)
    missing = replace(
        snapshot.structure, identity=replace(snapshot.structure.identity, miniserver_serial="")
    )
    with pytest.raises(ProfileError):
        SourceSnapshot.capture(runtime.endpoint.origin, missing, {LIGHT}, {}, None, set())
    with pytest.raises(ValueError, match="Profile references"):
        SourceSnapshot.capture(
            runtime.endpoint.origin,
            missing,
            {LIGHT},
            {},
            1,
            {"binding"},
            require_profile_identity=False,
        )


@pytest.mark.asyncio
async def test_unchanged_profile_checksum_allows_valid_reference_publication(monkeypatch, tmp_path):
    runner, *_ = runner_fixture(monkeypatch)
    path = tmp_path / "installation-profile.json"
    path.write_text('{"content":"stable"}', encoding="utf-8")
    runner.profile_path = path
    bindings = {"sensor": {"status": "confirmed", "role": "room_sensor", "control_uuid": SOURCE}}
    monkeypatch.setattr(domain, "read_profile_bindings", AsyncMock(return_value=(bindings, 1)))
    result = await runner.run(
        "lighting",
        None,
        lighting_selection=LightingSelection(controller_uuids=[LIGHT]),
        lighting_context=context(presence_sources=[declared(binding_id="sensor")]),
    )
    assert result.ok
