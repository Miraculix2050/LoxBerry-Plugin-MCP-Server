from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

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
)
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure
from mcpserver.tools import register_read_tools


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
    assert value is None and descriptor.interpretation_status == "partial"
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
