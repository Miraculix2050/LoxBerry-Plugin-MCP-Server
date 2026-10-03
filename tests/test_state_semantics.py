from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import mcpserver.tools as tools_module
from mcpserver.loxone.models import (
    Control,
    Freshness,
    GlobalMetadata,
    LoxoneIdentity,
    LoxoneStructure,
    StateRecord,
    StatusMonitorInput,
    StatusMonitorStatus,
    WindowMonitorItem,
    WindowMonitorSummary,
)
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure
from mcpserver.tools import ControlReadTarget, register_read_tools


def control(kind="Irrigation", states=(("rainActive", "state"),), **kwargs):
    return Control("control", "Heating demand kWh", kind, None, None, None, states, **kwargs)


def structure(c):
    return LoxoneStructure(LoxoneIdentity("reader", "serial"), "17.9-fake", (), (), (c,))


def resolve(c, name, value=None, companions=None):
    return StateSemanticsResolver().resolve(structure(c), c, name, value, companions or {})


@pytest.mark.parametrize(
    "value,status,semantic",
    [(1, "known", True), (0, "known", False), (2, "invalid", None), (None, "partial", None)],
)
def test_decoder_quality_is_explicit(value, status, semantic):
    descriptor, interpreted = resolve(control(), "rainActive", value)
    assert descriptor.interpretation_status == status
    assert interpreted is semantic
    assert descriptor.sources[0].rule_id == "Irrigation.rainActive.v1"
    assert all(
        s.firmware_version is None and s.document_version is None for s in descriptor.sources
    )


def test_companion_gaps_retain_partial_interpretation():
    c = control()
    descriptor, value = resolve(c, "currentZone", 0)
    assert descriptor.reason == "companion_unavailable"
    assert value == {"status": "zone", "zone_id": 0}
    zones = '[{"id":0,"name":"Front","duration":60,"setByLogic":false}]'
    descriptor, value = resolve(c, "currentZone", 0, {"zones": zones})
    assert descriptor.interpretation_status == "known"
    assert value["zone_name"] == "Front"
    descriptor, value = resolve(control("AlarmClock"), "nextEntry", 3)
    assert descriptor.reason == "companion_unavailable"
    assert value == {"status": "entry", "entry_id": 3}


def test_formats_ranges_and_names_do_not_invent_units_or_roles():
    c = control("UpDownAnalog", format="%.2f kWh", minimum=-10, maximum=10, step=0.5)
    descriptor, value = resolve(c, "value", -2)
    assert descriptor.display_format == "%.2f kWh"
    assert descriptor.range.minimum == -10
    assert (
        descriptor.unit is None
        and descriptor.precision is None
        and descriptor.sign_convention is None
    )
    assert descriptor.interpretation_status == "partial" and value is None
    assert resolve(c, "other", 1)[0].interpretation_status == "unknown"
    assert resolve(replace(c, control_type="EFM"), "value", 1)[0].interpretation_status == "unknown"
    invalid = replace(c, semantics_invalid_fields=("format",), format=None)
    assert resolve(invalid, "value", 1)[0].reason == "invalid_structure_metadata"


def test_position_bound_statuses_expose_normalization_loss_and_limits():
    c = control(
        "StatusMonitor",
        status_monitor_statuses=tuple(
            StatusMonitorStatus(i, "Configured label", 0, None) for i in range(150)
        ),
        status_monitor_inputs=(StatusMonitorInput(0, "Input", None, None, None),),
        status_monitor_status_total=150,
        status_monitor_status_complete=True,
        status_monitor_input_total=1,
        status_monitor_input_complete=True,
    )
    descriptor, value = resolve(c, "inputStates", "[1]")
    assert value["inputs"][0]["mapping_status"] == "invalid"
    assert descriptor.interpretation_status == "invalid"
    assert len(descriptor.encoding) == 100 and descriptor.encoding_total == 150
    assert descriptor.encoding_truncated and not descriptor.encoding_complete
    assert descriptor.positions[0].index == 0 and descriptor.positions_complete
    descriptor, _ = resolve(
        replace(
            c, status_monitor_status_complete=False, semantics_invalid_fields=("status_monitor",)
        ),
        "inputStates",
    )
    assert descriptor.interpretation_status == "invalid"


class Runtime:
    def __init__(self, c):
        self.structure = structure(c)
        self.records = {
            uuid: StateRecord(uuid, 1, Freshness.CURRENT, 1_700_000_000)
            for _, uuid in c.state_uuids
        }
        self.snapshots = []
        self.reads = []
        self.slots = 0
        self.failure = None

    @asynccontextmanager
    async def call_slot(self, access):
        self.slots += 1
        yield

    async def snapshot(self, access, *, fresh_visibility=False):
        self.snapshots.append(fresh_visibility)
        if self.failure:
            raise self.failure
        return RuntimeSnapshot("family", self.structure, True)

    def state(self, snapshot, uuid):
        self.reads.append(uuid)
        return self.records[uuid]


def tool(monkeypatch, runtime):
    monkeypatch.setattr(tools_module, "_access", lambda: object())
    server = FastMCP("semantics")
    register_read_tools(server, runtime)
    return server._tool_manager.get_tool("loxone_get_state_semantics")


def read_tool(monkeypatch, runtime):
    monkeypatch.setattr(tools_module, "_access", lambda: SimpleNamespace(scopes=["loxone:read"]))
    server = FastMCP("compact")
    register_read_tools(server, runtime)
    return server, server._tool_manager.get_tool("loxone_read_controls")


@pytest.mark.asyncio
async def test_compact_order_aliases_and_optional_shared_semantics(monkeypatch):
    runtime = Runtime(control(states=(("rainActive", "state"), ("alias", "state"))))
    second = replace(control("InfoOnlyAnalog", states=()), uuid="second")
    runtime.structure = replace(runtime.structure, controls=(runtime.structure.controls[0], second))
    server, t = read_tool(monkeypatch, runtime)
    result = await t.fn(
        [ControlReadTarget(control_uuid="second"), ControlReadTarget(control_uuid="control")]
    )
    assert result.ok and result.data.complete and not result.data.truncated
    assert [item.identity.uuid for item in result.data.items] == ["second", "control"]
    assert [item.name for item in result.data.items[1].values] == ["rainActive", "alias"]
    assert result.data.requested_states == result.data.returned_states == 2
    assert result.data.requested_controls == result.data.returned_controls == 2
    assert runtime.reads == ["state"] and runtime.snapshots == [True]
    assert result.data.items[0].values == []
    assert result.data.items[1].semantics is None
    enriched = await t.fn(
        [ControlReadTarget(control_uuid="control", state_names=["rainActive"])], True
    )
    legacy = await server._tool_manager.get_tool("loxone_get_state_semantics").fn(
        "control", ["rainActive"]
    )
    assert enriched.data.items[0].semantics == legacy.data.items
    assert "semantics" not in enriched.data.omitted_sections


@pytest.mark.asyncio
@pytest.mark.parametrize("private_first", [False, True])
@pytest.mark.parametrize(
    "target",
    [
        {"control_uuid": "hidden"},
        {"control_uuid": "absent"},
        {"control_uuid": "control", "state_names": ["private"]},
    ],
)
async def test_compact_batch_visibility_is_atomic(monkeypatch, target, private_first):
    runtime = Runtime(control())
    runtime.structure = replace(
        runtime.structure, hidden_controls=(replace(control(), uuid="hidden", is_hidden=True),)
    )
    _, t = read_tool(monkeypatch, runtime)
    targets = [ControlReadTarget(control_uuid="control"), ControlReadTarget(**target)]
    # Use a distinct visible control when the invalid state targets the first control.
    if target["control_uuid"] == "control":
        targets[0] = ControlReadTarget(control_uuid="other")
        runtime.structure = replace(
            runtime.structure,
            controls=(*runtime.structure.controls, replace(control(), uuid="other")),
        )
    result = await t.fn(targets[::-1] if private_first else targets)
    assert result.data.error == "not_found" and runtime.reads == []
    assert result.data.message == "One or more targets are not accessible"
    runtime.structure = replace(runtime.structure, controls=())
    assert (await t.fn([ControlReadTarget(control_uuid="control")])).data.error == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"targets": []},
        {"targets": [{"control_uuid": str(i)} for i in range(26)]},
        {"targets": [{"control_uuid": "x" * 129}]},
        {"targets": [{"control_uuid": "control", "state_names": []}]},
        {"targets": [{"control_uuid": "control", "state_names": ["x" * 129]}]},
        {"targets": [{"control_uuid": "control", "state_names": ["x"] * 101}]},
        {"targets": [{"control_uuid": "control", "include_hidden": True}]},
    ],
)
async def test_compact_schema_bounds(monkeypatch, arguments):
    runtime = Runtime(control())
    server, _ = read_tool(monkeypatch, runtime)
    with pytest.raises(ToolError):
        await server._tool_manager.call_tool("loxone_read_controls", arguments)
    assert runtime.snapshots == []


@pytest.mark.asyncio
async def test_compact_duplicates_and_total_named_state_limit(monkeypatch):
    runtime = Runtime(control(states=tuple((f"s{i}", "state") for i in range(101))))
    _, t = read_tool(monkeypatch, runtime)
    target = ControlReadTarget(control_uuid="control")
    assert (await t.fn([target, target])).data.error == "invalid_input"
    assert (
        await t.fn([ControlReadTarget(control_uuid="control", state_names=["s0", "s0"])])
    ).data.error == "invalid_input"
    assert runtime.snapshots == []
    assert (await t.fn([target])).data.error == "invalid_input" and runtime.reads == []
    result = await t.fn(
        [ControlReadTarget(control_uuid="control", state_names=[f"s{i}" for i in range(100)])]
    )
    assert result.ok and result.data.returned_states == 100 and runtime.reads == ["state"]


@pytest.mark.asyncio
@pytest.mark.parametrize("freshness", list(Freshness))
async def test_compact_preserves_quality_and_does_not_read_companions_by_default(
    monkeypatch, freshness
):
    runtime = Runtime(control(states=(("rainActive", "state"), ("zones", "zones"))))
    runtime.records["state"] = StateRecord("state", None, freshness, None)
    _, t = read_tool(monkeypatch, runtime)
    result = await t.fn([ControlReadTarget(control_uuid="control", state_names=["rainActive"])])
    value = result.data.items[0].values[0]
    assert value.value is None and value.freshness == freshness.value and value.observed_at is None
    assert result.data.complete and runtime.reads == ["state"]
    assert result.stale == (freshness is not Freshness.CURRENT)


@pytest.mark.asyncio
@pytest.mark.parametrize("semantics", [False, True])
async def test_compact_byte_limit_rejects_without_partial_values(monkeypatch, semantics):
    runtime = Runtime(control("InfoOnlyText"))
    runtime.records["state"] = StateRecord("state", "ä" * 33000, Freshness.CURRENT, None)
    _, t = read_tool(monkeypatch, runtime)
    result = await t.fn([ControlReadTarget(control_uuid="control")], semantics)
    assert not result.ok and result.data.error == "response_too_large"
    assert len(result.model_dump_json().encode("utf-8")) < 65536
    assert "ä" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_compact_exact_byte_boundary_and_maximum_control_batch(monkeypatch):
    monkeypatch.setattr(tools_module, "_now", lambda: "2026-10-01T00:00:00.000000Z")
    runtime = Runtime(control("InfoOnlyText"))
    _, t = read_tool(monkeypatch, runtime)
    target = [ControlReadTarget(control_uuid="control")]
    runtime.records["state"] = StateRecord("state", "", Freshness.CURRENT, None)
    base = await t.fn(target)
    size = len(base.model_dump_json().encode("utf-8"))
    runtime.records["state"] = StateRecord("state", "x" * (65536 - size), Freshness.CURRENT, None)
    result = await t.fn(target)
    assert result.ok and len(result.model_dump_json().encode("utf-8")) == 65536
    runtime.records["state"] = replace(runtime.records["state"], value="x" * (65537 - size))
    assert (await t.fn(target)).data.error == "response_too_large"
    runtime.structure = replace(
        runtime.structure,
        controls=tuple(
            replace(control(states=()), uuid=f"c{i}", is_user_linked=True) for i in range(25)
        ),
    )
    result = await t.fn([ControlReadTarget(control_uuid=f"c{i}") for i in range(25)])
    assert result.ok and result.data.returned_controls == 25 and result.data.returned_states == 0
    assert all(item.identity.visibility == "linked" for item in result.data.items)


@pytest.mark.asyncio
async def test_compact_shared_semantics_does_not_label_from_stale_companions(monkeypatch):
    runtime = Runtime(control(states=(("currentZone", "state"), ("zones", "zones"))))
    runtime.records["state"] = StateRecord("state", 0, Freshness.CURRENT, None)
    runtime.records["zones"] = StateRecord(
        "zones", '[{"id":0,"name":"Stale label"}]', Freshness.STALE, None
    )
    _, t = read_tool(monkeypatch, runtime)
    result = await t.fn(
        [ControlReadTarget(control_uuid="control", state_names=["currentZone"])], True
    )
    semantics = result.data.items[0].semantics[0]
    assert semantics.semantics.reason == "companion_unavailable"
    assert semantics.semantic_value == {"status": "zone", "zone_id": 0}
    assert not result.stale and result.data.complete
    assert set(runtime.reads) == {"state", "zones"} and len(runtime.reads) == 2


@pytest.mark.asyncio
async def test_compact_authentication_availability_and_cancellation(monkeypatch):
    runtime = Runtime(control())
    _, t = read_tool(monkeypatch, runtime)
    targets = [ControlReadTarget(control_uuid="control")]

    def denied():
        raise PermissionError()

    monkeypatch.setattr(tools_module, "_access", denied)
    assert (await t.fn(targets)).data.error == "unauthenticated"
    assert runtime.snapshots == []
    monkeypatch.setattr(tools_module, "_access", lambda: object())
    runtime.failure = RuntimeUnavailable("offline")
    assert not (await t.fn(targets)).ok and runtime.reads == []
    runtime.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await t.fn(targets)


@pytest.mark.asyncio
@pytest.mark.parametrize("relationships", [0, 100])
async def test_compact_serialized_payload_measurement(monkeypatch, relationships):
    monkeypatch.setattr(tools_module, "_now", lambda: "2026-10-01T00:00:00.000000Z")
    c = control("InfoOnlyAnalog", states=(("value", "state"),))
    if relationships:
        c = replace(
            c,
            control_type="StatusMonitor",
            state_uuids=(("inputStates", "state"),),
            status_monitor_inputs=tuple(
                StatusMonitorInput(i, f"Input {i:03}", None, f"related-{i:03}", None)
                for i in range(relationships)
            ),
            status_monitor_statuses=tuple(
                StatusMonitorStatus(i, f"Status {i:03}", 0, None) for i in range(10)
            ),
        )
    related = tuple(
        replace(c, uuid=f"related-{i:03}", name=f"Related control {i:03}", state_uuids=())
        for i in range(relationships)
    )
    c = replace(
        c, name="Measured control", linked_control_uuids=tuple(item.uuid for item in related)
    )
    runtime = Runtime(c)
    runtime.structure = replace(runtime.structure, controls=(c, *related))
    server, t = read_tool(monkeypatch, runtime)
    calls = [
        await server._tool_manager.get_tool("loxone_find_controls").fn(query="Measured control"),
        await server._tool_manager.get_tool("loxone_describe_control").fn("control"),
        await server._tool_manager.get_tool("loxone_get_states").fn(["state"]),
    ]
    refs = await server._tool_manager.get_tool("loxone_describe_control").fn(
        "control", view="state_refs"
    )
    compact = await t.fn([ControlReadTarget(control_uuid="control")])
    assert all(call.ok for call in [*calls, refs, compact])
    sizes = [len(call.model_dump_json().encode("utf-8")) for call in calls]
    compact_size = len(compact.model_dump_json().encode("utf-8"))
    refs_size = len(refs.model_dump_json().encode("utf-8"))
    assert compact_size < sum(sizes)
    print(
        f"relationships={relationships}: find/describe/states={sizes}, total={sum(sizes)}, "
        f"compact={compact_size}, describe-state_refs+states={refs_size + sizes[2]}"
    )


@pytest.mark.asyncio
async def test_paging_aliases_and_selection_use_one_fresh_snapshot(monkeypatch):
    c = control(states=(*((f"state-{i}", f"uuid-{i}") for i in range(101)), ("alias", "uuid-0")))
    runtime = Runtime(c)
    t = tool(monkeypatch, runtime)
    first = await t.fn("control")
    assert first.ok and first.data.returned == 100 and first.data.total == 102
    assert first.data.next_offset == 100 and first.data.truncated
    assert runtime.snapshots == [True] and runtime.slots == 1
    runtime.reads.clear()
    second = await t.fn("control", offset=100)
    assert second.data.returned == 2 and second.data.next_offset is None
    assert not second.data.complete
    selected = await t.fn("control", ["state-0", "alias"])
    assert selected.data.complete and selected.data.items[0].uuid == selected.data.items[1].uuid
    assert runtime.reads.count("uuid-0") == 2  # Once in each of the last two calls.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"state_names": []},
        {"state_names": ["a", "a"]},
        {"state_names": ["x"] * 101},
        {"offset": -1},
        {"offset": True},
        {"limit": 0},
        {"limit": 101},
        {"control_uuid": "x" * 201},
    ],
)
async def test_invalid_selection_rejected_before_snapshot(monkeypatch, kwargs):
    runtime = Runtime(control())
    result = await tool(monkeypatch, runtime).fn(**({"control_uuid": "control"} | kwargs))
    assert result.data.error == "invalid_input" and runtime.snapshots == []


@pytest.mark.asyncio
async def test_unknown_states_atomic_and_hidden_controls_never_exposed(monkeypatch):
    runtime = Runtime(control())
    t = tool(monkeypatch, runtime)
    result = await t.fn("control", ["rainActive", "private-marker"])
    assert result.data.error == "not_found" and runtime.reads == []
    runtime.structure = replace(
        runtime.structure, controls=(), hidden_controls=(replace(control(), is_hidden=True),)
    )
    result = await t.fn("control")
    assert result.data.error == "not_found" and runtime.reads == []
    runtime.structure = structure(replace(control(), is_user_linked=True))
    assert (await t.fn("control")).ok
    runtime.structure = replace(runtime.structure, controls=())
    assert (await t.fn("control")).data.error == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "freshness,value",
    [
        (Freshness.CURRENT, 1),
        (Freshness.STALE, 1),
        (Freshness.UNKNOWN, None),
        (Freshness.UNAVAILABLE, None),
    ],
)
async def test_observation_quality_independent_of_interpretation(monkeypatch, freshness, value):
    runtime = Runtime(control())
    runtime.records["state"] = StateRecord("state", value, freshness, None)
    result = await tool(monkeypatch, runtime).fn("control")
    item = result.data.items[0]
    assert item.value == value and item.quality.freshness == freshness.value
    assert item.semantics.interpretation_status == ("partial" if value is None else "known")
    assert item.quality.observed_at is None


@pytest.mark.asyncio
async def test_stale_companion_cannot_label_current_state(monkeypatch):
    c = control(states=(("currentZone", "current"), ("zones", "zones")))
    runtime = Runtime(c)
    runtime.records["current"] = StateRecord("current", 0, Freshness.CURRENT, None)
    runtime.records["zones"] = StateRecord(
        "zones", '[{"id":0,"name":"Stale","duration":60,"setByLogic":false}]', Freshness.STALE, None
    )
    result = await tool(monkeypatch, runtime).fn("control", ["currentZone"])
    assert result.data.items[0].semantics.reason == "companion_unavailable"
    assert "Stale" not in result.model_dump_json()
    assert sorted(runtime.reads) == ["current", "zones"]


@pytest.mark.asyncio
async def test_denial_availability_and_cancellation_keep_runtime_contract(monkeypatch):
    runtime = Runtime(control())
    t = tool(monkeypatch, runtime)
    runtime.failure = PermissionError()
    assert (await t.fn("control")).data.error == "unauthenticated"
    runtime.failure = RuntimeUnavailable("not ready")
    assert (await t.fn("control")).data.error == "temporarily_unavailable"
    runtime.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await t.fn("control")


def test_tool_contract_is_additive_read_only_and_has_no_hidden_argument(monkeypatch):
    t = tool(monkeypatch, Runtime(control()))
    assert set(t.parameters["properties"]) == {"control_uuid", "state_names", "offset", "limit"}
    assert t.annotations.readOnlyHint and not t.annotations.destructiveHint
    assert "StateSemantics" in t.output_schema["$defs"]
    schema = t.output_schema["$defs"]["StateSemantics"]["properties"]
    assert schema["encoding"]["maxItems"] == 100
    assert schema["sources"]["maxItems"] == 8


def test_normalization_retains_invalid_source_and_collection_coverage():
    raw = {
        "msInfo": {"serialNr": "serial"},
        "controls": {
            "analog": {
                "name": "Analog",
                "type": "UpDownAnalog",
                "states": {"value": "value"},
                "details": {"format": "x" * 65, "min": 10, "max": 0, "step": 1},
            },
            "monitor": {
                "name": "Monitor",
                "type": "StatusMonitor",
                "states": {"inputStates": "input"},
                "details": {
                    "inputs": [{"name": "Input"}] * 101,
                    "status": {
                        "good": {"id": 1, "name": "Configured", "prio": 0},
                        "bad": {"id": "invalid", "name": "Dropped", "prio": 0},
                    },
                },
            },
        },
    }
    normalized = normalize_structure(raw, username="reader")
    analog, monitor = normalized.controls
    assert analog.semantics_invalid_fields == ("range",)
    assert resolve(analog, "value", 0)[0].interpretation_status == "invalid"
    descriptor, _ = resolve(monitor, "inputStates")
    assert descriptor.encoding_total == 2 and descriptor.encoding_returned == 1
    assert not descriptor.encoding_complete and descriptor.encoding_truncated
    assert descriptor.positions_total == 101 and descriptor.positions_returned == 100
    assert not descriptor.positions_complete and descriptor.positions_truncated
    assert descriptor.interpretation_status == "invalid"


def test_oversized_format_is_omitted_with_length_evidence_not_invalid():
    raw = {
        "msInfo": {"serialNr": "serial"},
        "controls": {
            "analog": {
                "name": "Analog",
                "type": "InfoOnlyAnalog",
                "states": {"value": "value"},
                "details": {"format": "x" * 65},
            }
        },
    }
    c = normalize_structure(raw, username="reader").controls[0]
    descriptor, _ = resolve(c, "value", 1)
    assert descriptor.display_format is None
    assert descriptor.display_format_total_length == 65
    assert descriptor.display_format_returned_length == 0
    assert descriptor.display_format_truncated and not descriptor.display_format_complete
    assert descriptor.reason == "metadata_truncated"
    assert descriptor.interpretation_status == "partial"


def test_legacy_status_mapping_retains_valid_status_after_large_malformed_prefix():
    statuses = {f"invalid-{i}": "malformed" for i in range(270)}
    statuses["valid"] = {"id": 4, "name": "Retained", "prio": 0}
    raw = {
        "msInfo": {"serialNr": "serial"},
        "controls": {
            "monitor": {
                "name": "Monitor",
                "type": "StatusMonitor",
                "states": {"inputStates": "input"},
                "details": {"inputs": [], "status": statuses},
            }
        },
    }
    c = normalize_structure(raw, username="reader").controls[0]
    assert len(c.status_monitor_statuses) == 1
    assert c.status_monitor_statuses[0].status_id == 4
    descriptor, _ = resolve(c, "inputStates")
    assert descriptor.encoding[0].code == 4 and descriptor.encoding[0].label == "Retained"
    assert descriptor.encoding_total == 271 and not descriptor.encoding_complete


def test_enriched_mode_and_companion_labels_identify_their_sources():
    c = control("AlarmClock")
    s = replace(
        structure(c), global_metadata=(GlobalMetadata("operating_mode", "3", "Configured mode"),)
    )
    descriptor, value = StateSemanticsResolver().resolve(s, c, "nextEntryMode", 3, {})
    assert value["mode_name"] == "Configured mode"
    assert any(
        source.kind == "structure_file" and "semantic_value.mode_name" in source.fields
        for source in descriptor.sources
    )
    c = control(states=(("currentZone", "current"), ("zones", "zones")))
    descriptor, _ = resolve(
        c, "currentZone", 0, {"zones": '[{"id":0,"name":"Front","duration":60,"setByLogic":false}]'}
    )
    assert any(
        source.kind == "runtime_state" and source.state_uuid == "zones"
        for source in descriptor.sources
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("parameter", ["offset", "limit"])
async def test_wire_call_rejects_boolean_page_parameters(monkeypatch, parameter):
    runtime = Runtime(control())
    monkeypatch.setattr(tools_module, "_access", lambda: object())
    server = FastMCP("strict-semantics")
    register_read_tools(server, runtime)
    with pytest.raises(ToolError):
        await server._tool_manager.call_tool(
            "loxone_get_state_semantics", {"control_uuid": "control", parameter: True}
        )
    assert runtime.snapshots == []


def status_control(**kwargs):
    return control(
        "StatusMonitor",
        states=(("inputStates", "inputs"), ("numState1", "count")),
        status_monitor_statuses=(
            StatusMonitorStatus(4, "Ready", 2, "#00FF00", "status-four"),
            StatusMonitorStatus(1, "Busy", 0, "#FF0000", "status-one"),
        ),
        status_monitor_inputs=(
            StatusMonitorInput(0, "First", "Office", "referenced", "room"),
            StatusMonitorInput(1, "Second", None, None, None),
        ),
        status_monitor_status_total=2,
        status_monitor_status_complete=True,
        status_monitor_input_total=2,
        status_monitor_input_complete=True,
        **kwargs,
    )


def window_control(count=2):
    return control(
        "WindowMonitor",
        states=(("windowStates", "windows"), ("numOpen", "count")),
        window_monitor_items=tuple(
            WindowMonitorItem(i, f"Contact {i}", "room", f"reference-{i}", "Place")
            for i in range(count)
        ),
        window_monitor_summary=WindowMonitorSummary(count, count),
    )


@pytest.mark.parametrize("mask", range(32))
def test_window_masks_preserve_all_documented_bits(mask):
    descriptor, decoded = resolve(window_control(1), "windowStates", str(mask))
    assert descriptor.interpretation_status == "known"
    item = decoded["contacts"][0]
    assert item["bitmask"] == mask and item["raw_token"] == str(mask)
    bits = [(1, "closed"), (2, "tilted"), (4, "open"), (8, "locked"), (16, "unlocked")]
    assert item["states"] == [name for bit, name in bits if mask & bit]
    assert item["decoding_status"] == ("unknown_or_offline" if mask == 0 else "decoded")
    assert decoded["mapping_complete"] and "alert_active" not in decoded
    assert decoded["provenance"]["state_uuid"] == "windows"


@pytest.mark.parametrize("raw", ["32", "63", "-1", "1.0", "true", "\uff11", "", "99999999999"])
def test_window_invalid_or_empty_tokens_never_become_closed(raw):
    descriptor, decoded = resolve(window_control(), "windowStates", "1," + raw)
    assert descriptor.interpretation_status == "invalid"
    assert decoded["contacts"][1]["bitmask"] is None
    assert decoded["contacts"][1]["index"] == 1
    assert not decoded["decoding_complete"]


def test_window_join_keeps_gaps_and_unmatched_positions():
    c = window_control()
    _, missing = resolve(c, "windowStates", "1")
    assert missing["alignment"] == "mismatch"
    assert missing["contacts"][1]["decoding_status"] == "missing"
    _, extra = resolve(c, "windowStates", "1, 18 ,4")
    assert extra["contacts"][1]["raw_token"] == " 18 "
    assert extra["contacts"][1]["states"] == ["tilted", "unlocked"]
    assert extra["contacts"][2]["mapping_status"] == "missing_metadata"
    assert not extra["mapping_complete"]
    c = replace(c, window_monitor_items=(c.window_monitor_items[1],))
    _, sparse = resolve(c, "windowStates", "1,4")
    assert sparse["contacts"][0]["contact"] is None
    assert sparse["contacts"][1]["contact"]["control_uuid"] == "reference-1"
    _, unknown = resolve(replace(c, window_monitor_summary=None), "windowStates", "1,4")
    assert unknown["alignment"] == "unknown" and not unknown["mapping_complete"]
    bad = replace(c.window_monitor_items[0], diagnostics=("invalid_window_monitor_entry",))
    _, malformed = resolve(replace(c, window_monitor_items=(bad,)), "windowStates", "1,4")
    assert malformed["contacts"][1]["mapping_status"] == "invalid_metadata"
    _, duplicate = resolve(replace(c, window_monitor_items=(bad, bad)), "windowStates", "1,4")
    assert duplicate["contacts"][1]["mapping_status"] == "ambiguous"
    assert duplicate["contacts"][1]["contact"] is None


@pytest.mark.parametrize("entry", [{"name": "Orphan"}, {"uuid": "contact"}, {"room": "room"}])
def test_window_missing_references_are_incomplete_even_without_normalization_diagnostics(entry):
    c = normalize_structure(
        {
            "msInfo": {"serialNr": "fixture"},
            "controls": {
                "monitor": {
                    "name": "Monitor",
                    "type": "WindowMonitor",
                    "states": {"windowStates": "state"},
                    "details": {"windows": [entry]},
                }
            },
        },
        username="reader",
    ).controls[0]
    assert not c.window_monitor_items[0].diagnostics
    descriptor, decoded = resolve(c, "windowStates", "1")
    assert decoded["contacts"][0]["mapping_status"] == "missing_reference"
    assert not decoded["mapping_complete"] and decoded["decoding_complete"]
    assert descriptor.interpretation_status == "partial"


def test_window_bounds_are_independent_of_raw_and_metadata_size():
    import json

    c = window_control(101)
    _, many = resolve(c, "windowStates", ",".join(["1"] * 101))
    assert many["values_total"] == 101 and many["truncated"]
    assert many["positions_returned"] <= 100 and not many["mapping_complete"]
    c = replace(
        c,
        window_monitor_items=tuple(
            replace(i, name="X" * 200, room_uuid="R" * 200, install_place="P" * 200)
            for i in c.window_monitor_items
        ),
    )
    _, bounded = resolve(c, "windowStates", ",".join(["1"] * 101))
    assert len(json.dumps(bounded, ensure_ascii=False).encode()) <= 16_384
    assert bounded["positions_returned"] < 100
    descriptor, decoded = resolve(c, "windowStates", "1" * 65_536)
    assert descriptor.interpretation_status == "invalid" and decoded is not None
    descriptor, decoded = resolve(c, "windowStates", "1" * 65_537)
    assert descriptor.interpretation_status == "invalid" and decoded is None
    assert resolve(replace(c, control_type="Other"), "windowStates", "1")[1] is None
    descriptor, decoded = resolve(window_control(1), "windowStates", "1" + " " * 65_535)
    assert descriptor.interpretation_status == "known"
    assert decoded["contacts"][0]["raw_token_truncated"]
    assert decoded["contacts"][0]["bitmask"] == 1
    unknown_total = replace(
        window_control(), window_monitor_summary=WindowMonitorSummary(None, 2, None, True)
    )
    assert resolve(unknown_total, "windowStates", "1,4")[1]["truncated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("freshness", list(Freshness))
async def test_window_readers_share_decode_without_reference_or_count_reads(monkeypatch, freshness):
    runtime = Runtime(window_control())
    raw = None if freshness is Freshness.UNAVAILABLE else "1,18"
    runtime.records["windows"] = StateRecord("windows", raw, freshness, 1700000000)
    server, compact = read_tool(monkeypatch, runtime)
    semantics = await server._tool_manager.get_tool("loxone_get_state_semantics").fn(
        "control", ["windowStates"]
    )
    states = await server._tool_manager.get_tool("loxone_get_states").fn(["windows"])
    enriched = await compact.fn(
        [ControlReadTarget(control_uuid="control", state_names=["windowStates"])], True
    )
    assert semantics.ok and states.ok and enriched.ok
    item = semantics.data.items[0]
    assert item.semantic_value == states.data.states[0].semantic_value
    assert item == enriched.data.items[0].semantics[0]
    assert item.quality.freshness == freshness.value and item.value == raw
    assert runtime.snapshots == [True, True, True]
    assert set(runtime.reads) == {"windows"}


@pytest.mark.asyncio
async def test_window_hidden_control_is_not_read_by_any_shared_reader(monkeypatch):
    runtime = Runtime(window_control())
    runtime.structure = replace(runtime.structure, controls=(), hidden_controls=(window_control(),))
    server, compact = read_tool(monkeypatch, runtime)
    results = [
        await server._tool_manager.get_tool("loxone_get_state_semantics").fn(
            "control", ["windowStates"]
        ),
        await server._tool_manager.get_tool("loxone_get_states").fn(["windows"]),
        await compact.fn([ControlReadTarget(control_uuid="control")], True),
    ]
    assert all(not result.ok for result in results) and runtime.reads == []


def test_status_monitor_maps_multiple_tuples_without_global_status():
    c = status_control()
    descriptor, value = resolve(c, "inputStates", "4,1")
    assert descriptor.interpretation_status == "known"
    assert value["decoding_complete"] and value["mapping_complete"]
    assert [v["configured_status"]["name"] for v in value["inputs"]] == ["Ready", "Busy"]
    assert value["inputs"][0]["input"]["uuid"] == "referenced"
    assert value["inputs"][1]["configured_status"] == {
        "status_id": 1,
        "name": "Busy",
        "priority": 0,
        "color": "#FF0000",
        "uuid": "status-one",
    }
    assert "alert_active" not in value and "current_status" not in value
    assert any(
        s.document_version == "17.1" and "#page=130" in s.reference for s in descriptor.sources
    )
    assert any(s.state_uuid == "inputs" for s in descriptor.sources)


@pytest.mark.parametrize("raw", ["1,,4", "1,1.0", "1,-1", "1,true", "1,256", "1, 4", "1,[4]"])
def test_status_monitor_invalid_tokens_keep_positions(raw):
    _, value = resolve(status_control(), "inputStates", raw)
    assert value["invalid_values"] and not value["decoding_complete"]
    assert value["inputs"][1]["index"] == 1
    assert value["inputs"][1]["raw_token"] == raw.split(",")[1]
    assert value["inputs"][1]["mapping_status"] == "invalid"


@pytest.mark.parametrize("raw", ["1,255", "1,3"])
def test_status_monitor_unmatched_is_not_alarm_or_unconfigured_claim(raw):
    descriptor, value = resolve(status_control(), "inputStates", raw)
    assert descriptor.interpretation_status == "partial"
    assert value["decoding_complete"] and not value["mapping_complete"]
    assert value["inputs"][1]["mapping_status"] == "unmatched"
    assert value["inputs"][1]["is_aggregated"] is None


def test_status_monitor_missing_extra_and_duplicate_metadata():
    c = status_control()
    _, missing = resolve(c, "inputStates", "1")
    assert missing["inputs"][1]["mapping_status"] == "missing_value"
    assert missing["inputs"][1]["raw_token"] is None and not missing["mapping_complete"]
    _, extra = resolve(c, "inputStates", "1,4,1")
    assert len(extra["inputs"]) == 3 and not extra["inputs"][2]["input_resolved"]
    duplicate = replace(
        c, status_monitor_statuses=(*c.status_monitor_statuses, c.status_monitor_statuses[1])
    )
    _, value = resolve(duplicate, "inputStates", "1,4")
    assert value["inputs"][0]["mapping_status"] == "ambiguous"
    assert value["inputs"][0]["configured_status"] is None
    _, value = resolve(
        replace(c, status_monitor_statuses=(), status_monitor_status_complete=False),
        "inputStates",
        "1,4",
    )
    assert all(i["mapping_status"] == "unmatched" for i in value["inputs"])
    assert not value["mapping_complete"]


def test_status_monitor_bounds_and_visible_aggregation():
    c = status_control()
    descriptor, value = resolve(c, "inputStates", ",".join(["1"] * 101))
    assert descriptor.interpretation_status == "partial"
    assert value["values_total"] == 101 and 0 < value["positions_returned"] <= 100
    assert value["truncated"] and not value["decoding_complete"]
    assert resolve(c, "inputStates", "x" * 65537)[1] is None
    _, invalid = resolve(c, "inputStates", "x" * 201 + ",1")
    assert len(invalid["inputs"][0]["raw_token"]) == 200
    assert invalid["inputs"][0]["raw_token_truncated"]
    visible = replace(c, uuid="referenced")
    hidden = replace(visible, is_hidden=True)
    for controls, is_aggregated in [((visible,), True), ((hidden,), None), ((), None)]:
        snapshot = replace(structure(c), controls=(c, *controls))
        _, value = StateSemanticsResolver().resolve(snapshot, c, "inputStates", "4,1", {})
        assert value["inputs"][0]["is_aggregated"] is is_aggregated


@pytest.mark.parametrize("name,code", [(f"numState{i}", i) for i in range(10)] + [("numDef", 10)])
def test_status_monitor_counts_are_counts_not_global_states(name, code):
    c = status_control()
    descriptor, value = resolve(c, name, 2)
    assert value["kind"] == "status_count" and value["count"] == 2
    assert value["status_id"] == code and "alert_active" not in value
    assert descriptor.interpretation_status == ("known" if code in {1, 4} else "partial")
    assert resolve(c, name, -1)[0].interpretation_status == "invalid"
    assert resolve(c, name, True)[1] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "freshness", [Freshness.CURRENT, Freshness.STALE, Freshness.UNAVAILABLE, Freshness.UNKNOWN]
)
async def test_status_monitor_shared_readers_preserve_quality_and_no_reference_reads(
    monkeypatch, freshness
):
    c = status_control()
    runtime = Runtime(c)
    raw = None if freshness is Freshness.UNAVAILABLE else "4,1"
    runtime.records["inputs"] = StateRecord("inputs", raw, freshness, 1700000000)
    server, compact = read_tool(monkeypatch, runtime)
    semantics = await server._tool_manager.get_tool("loxone_get_state_semantics").fn(
        "control", ["inputStates"]
    )
    states = await server._tool_manager.get_tool("loxone_get_states").fn(["inputs"])
    enriched = await compact.fn(
        [ControlReadTarget(control_uuid="control", state_names=["inputStates"])], True
    )
    assert states.ok and semantics.ok and enriched.ok
    item = semantics.data.items[0]
    assert item.semantic_value == states.data.states[0].semantic_value
    assert item == enriched.data.items[0].semantics[0]
    assert item.quality.freshness == freshness.value
    assert item.value == raw and states.data.states[0].value == raw
    assert runtime.snapshots == [True, True, True]
    assert set(runtime.reads) <= {
        "inputs",
        "count",
    }  # existing get_states reads same-control companions
    assert "referenced" not in runtime.reads
    if raw is not None:
        assert item.semantic_value["provenance"]["state_uuid"] == "inputs"
        assert item.semantic_value["provenance"]["document_version"] == "17.1"


@pytest.mark.asyncio
async def test_status_monitor_description_keeps_uuid_and_source_coverage(monkeypatch):
    runtime = Runtime(status_control())
    server, _ = read_tool(monkeypatch, runtime)
    result = await server._tool_manager.get_tool("loxone_describe_control").fn("control")
    mapping = result.data.capabilities.status_monitor
    assert mapping.statuses[0].uuid == "status-four"
    state_schema = server._tool_manager.get_tool("loxone_get_states").output_schema
    assert (
        "StatusMonitor"
        in state_schema["$defs"]["StateData"]["properties"]["semantic_value"]["description"]
    )
    assert mapping.statuses_total == mapping.statuses_returned == 2
    assert mapping.statuses_complete and not mapping.statuses_truncated
    assert mapping.inputs_total == mapping.inputs_returned == 2
    assert mapping.inputs_complete and not mapping.inputs_truncated


@pytest.mark.asyncio
async def test_status_monitor_long_tuples_obey_compact_bytes(monkeypatch):
    c = replace(
        status_control(),
        status_monitor_inputs=tuple(
            StatusMonitorInput(i, "N" * 200, "P" * 200, "U" * 128, "R" * 128) for i in range(100)
        ),
        status_monitor_statuses=(StatusMonitorStatus(1, "S" * 200, 0, "#FF0000"),),
        status_monitor_input_total=100,
        status_monitor_status_total=1,
    )
    runtime = Runtime(c)
    runtime.records["inputs"] = StateRecord(
        "inputs", ",".join(["1"] * 100), Freshness.CURRENT, 1700000000
    )
    _, compact = read_tool(monkeypatch, runtime)
    result = await compact.fn(
        [ControlReadTarget(control_uuid="control", state_names=["inputStates"])], True
    )
    assert result.ok and len(result.model_dump_json().encode("utf-8")) <= 65536
    assert result.data.items[0].semantics[0].semantic_value["truncated"]
    assert not result.data.items[0].semantics[0].semantic_value["mapping_complete"]


@pytest.mark.asyncio
async def test_state_batch_requires_fresh_visibility_without_cached_fallback(monkeypatch):
    runtime = Runtime(status_control())
    runtime.failure = RuntimeUnavailable("fresh visibility failed")
    server, _ = read_tool(monkeypatch, runtime)
    result = await server._tool_manager.get_tool("loxone_get_states").fn(["inputs"])
    assert not result.ok and runtime.snapshots == [True] and runtime.reads == []


@pytest.mark.parametrize(
    "state,value", [("inputStates", "4,1"), ("numState1", 1), ("numDef", None)]
)
def test_status_monitor_invalid_metadata_survives_decodable_or_missing_values(state, value):
    c = replace(status_control(), semantics_invalid_fields=("status_monitor",))
    descriptor, decoded = resolve(c, state, value)
    assert descriptor.interpretation_status == "invalid"
    assert descriptor.reason == "invalid_structure_metadata"
    if value is not None:
        assert decoded is not None and not decoded["mapping_complete"]


@pytest.mark.parametrize(
    "collection,field,value",
    [
        ("inputs", "uuid", 42),
        ("inputs", "room", True),
        ("inputs", "installPlace", []),
        ("inputs", "uuid", "x" * 201),
        ("status", "color", "red"),
        ("status", "uuid", False),
        ("status", "uuid", "x" * 201),
    ],
)
def test_status_monitor_malformed_optional_metadata_is_not_complete(collection, field, value):
    input_entry = {"name": "Input"}
    status_entry = {"id": 1, "name": "Configured", "prio": 0}
    (input_entry if collection == "inputs" else status_entry)[field] = value
    raw = {
        "msInfo": {"serialNr": "fixture"},
        "controls": {
            "monitor": {
                "name": "Monitor",
                "type": "StatusMonitor",
                "states": {"inputStates": "input"},
                "details": {"inputs": [input_entry], "status": {"one": status_entry}},
            }
        },
    }
    c = normalize_structure(raw, username="reader").controls[0]
    descriptor, decoded = resolve(c, "inputStates", "1")
    assert c.semantics_invalid_fields == ("status_monitor",)
    assert descriptor.reason == "invalid_structure_metadata"
    assert not decoded["mapping_complete"]
    if field == "uuid":
        assert (
            c.status_monitor_inputs[0].uuid
            if collection == "inputs"
            else c.status_monitor_statuses[0].uuid
        ) is None


@pytest.mark.parametrize(
    "optional", [{}, {"uuid": None, "room": "", "installPlace": "", "color": None}]
)
def test_status_monitor_absent_optional_metadata_can_be_complete(optional):
    raw = {
        "msInfo": {"serialNr": "fixture"},
        "controls": {
            "monitor": {
                "name": "Monitor",
                "type": "StatusMonitor",
                "states": {"inputStates": "input"},
                "details": {
                    "inputs": [{"name": "Input", **optional}],
                    "status": {"one": {"id": 1, "name": "Configured", "prio": 0, **optional}},
                },
            }
        },
    }
    c = normalize_structure(raw, username="reader").controls[0]
    descriptor, decoded = resolve(c, "inputStates", "1")
    assert not c.semantics_invalid_fields and descriptor.interpretation_status == "known"
    assert decoded["mapping_complete"]


@pytest.mark.parametrize("normalized", [False, True])
def test_status_monitor_reserved_255_never_matches_a_configured_definition(normalized):
    if normalized:
        raw = {
            "msInfo": {"serialNr": "fixture"},
            "controls": {
                "monitor": {
                    "name": "Monitor",
                    "type": "StatusMonitor",
                    "states": {"inputStates": "input"},
                    "details": {
                        "inputs": [{"name": "Input"}],
                        "status": {"reserved": {"id": 255, "name": "Arbitrary", "prio": 0}},
                    },
                }
            },
        }
        c = normalize_structure(raw, username="reader").controls[0]
        assert c.status_monitor_statuses == ()
        assert c.status_monitor_status_total == 1 and not c.status_monitor_status_complete
    else:
        c = replace(
            status_control(),
            status_monitor_statuses=(StatusMonitorStatus(255, "Arbitrary", 0, "#FF0000"),),
            status_monitor_status_total=1,
        )
    descriptor, decoded = resolve(c, "inputStates", "255")
    assert decoded["inputs"][0]["status_id"] == 255
    assert decoded["inputs"][0]["mapping_status"] == "unmatched"
    assert decoded["inputs"][0]["configured_status"] is None
    assert not decoded["mapping_complete"] and descriptor.interpretation_status != "known"
