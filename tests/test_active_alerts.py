from dataclasses import replace

import pytest
from mcp.server.fastmcp import FastMCP
from test_state_semantics import Runtime, control, resolve

import mcpserver.loxone.active_alerts as alerts
import mcpserver.tools as tools
from mcpserver.loxone.models import Freshness, StateRecord
from mcpserver.loxone.runtime import RuntimeUnavailable


def make_tool(monkeypatch, runtime):
    monkeypatch.setattr(tools, "_access", lambda: object())
    server = FastMCP("alerts")
    tools.register_read_tools(server, runtime)
    return server._tool_manager.get_tool("loxone_get_active_alerts")


@pytest.mark.parametrize(
    "value,active", [(0, False), (1, True), (2, False), (3, False), (1.0, True)]
)
def test_documented_emergency_enum(value, active):
    semantics, decoded = resolve(control("AalEmergency"), "status", value)
    assert semantics.interpretation_status == "known"
    assert decoded["alert_active"] is active
    assert semantics.sources[0].document_version == "17.1"
    assert semantics.sources[0].firmware_version is None


@pytest.mark.parametrize("value", [True, "1", 4, -1, float("nan"), {}, []])
def test_invalid_emergency_enum(value):
    semantics, decoded = resolve(control("AalEmergency"), "status", value)
    assert semantics.interpretation_status == "invalid" and decoded is None


@pytest.mark.parametrize("code", range(16))
def test_chain_bitmask_and_acknowledgement(code):
    semantics, value = resolve(control("AlarmChain"), "activeAlarmType", code)
    assert semantics.interpretation_status == "known"
    assert value["alert_active"] is bool(code & 14)
    assert value["context"]["acknowledged"] is bool(code & 1)
    assert value["context"]["test_alarm"] is None
    assert len(value["alarm_types"]) == (code & 14).bit_count()


@pytest.mark.parametrize("code", (0, 1, 2, 2.0))
def test_smart_alarm_enum(code):
    semantics, value = resolve(control("AalSmartAlarm"), "alarmLevel", code)
    assert semantics.interpretation_status == "known"
    assert value["alert_active"] is (code != 0)
    assert value["context"] == {
        "test_alarm": None,
        "acknowledged": None,
        "signals_suppressed": None,
    }


@pytest.mark.parametrize(
    "family,state", [("AalSmartAlarm", "alarmLevel"), ("AlarmChain", "activeAlarmType")]
)
@pytest.mark.parametrize("raw", [True, "1", -1, 16, 1.5, float("nan"), float("inf"), {}, []])
def test_additional_family_invalid_formats(family, state, raw):
    semantics, value = resolve(control(family), state, raw)
    assert semantics.interpretation_status == "invalid" and value is None


@pytest.mark.asyncio
@pytest.mark.parametrize("freshness", list(Freshness))
async def test_optional_companions_never_suppress_active_alarm(monkeypatch, freshness):
    runtime = Runtime(
        control("AalSmartAlarm", states=(("alarmLevel", "level"), ("isLocked", "lock")))
    )
    runtime.records = {
        "level": StateRecord("level", 1, Freshness.CURRENT, 1700000000),
        "lock": StateRecord("lock", 1, freshness, 1700000001),
    }
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.known_active == 1 and result.data.coverage.complete
    finding = result.data.findings[0]
    assert finding.context.test_alarm is None and finding.context.acknowledged is None
    assert finding.context.source_states[0].freshness == freshness.value
    assert finding.source_state.name == "alarmLevel"


@pytest.mark.asyncio
async def test_mixed_families_deduplicate_and_preserve_acknowledged_alarm(monkeypatch):
    runtime = Runtime(control("AlarmChain", states=(("activeAlarmType", "shared"),)))
    chain = replace(runtime.structure.controls[0], uuid="b")
    smart = replace(control("AalSmartAlarm", states=(("alarmLevel", "shared"),)), uuid="a")
    runtime.structure = replace(runtime.structure, controls=(chain, smart))
    runtime.records = {"shared": StateRecord("shared", 1, Freshness.CURRENT, 1700000000)}
    result = await make_tool(monkeypatch, runtime).fn()
    assert runtime.reads == ["shared"] and result.data.known_active == 1
    runtime.records["shared"] = replace(runtime.records["shared"], value=3)
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.known_active == 1 and result.data.findings[0].context.acknowledged is True
    assert result.data.total_active is None  # SmartAlarm rejects 3; Chain keeps its active bit.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,state", [("AalSmartAlarm", "alarmLevel"), ("AlarmChain", "activeAlarmType")]
)
@pytest.mark.parametrize("freshness", [Freshness.STALE, Freshness.UNKNOWN, Freshness.UNAVAILABLE])
async def test_new_families_primary_quality_remains_a_gap(monkeypatch, family, state, freshness):
    runtime = Runtime(control(family, states=((state, "state"),)))
    runtime.records["state"] = StateRecord("state", 2, freshness, 1700000000)
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.known_active == 0 and result.data.total_active is None
    assert result.data.coverage.reasons[0].reason == freshness.value


@pytest.mark.asyncio
async def test_optional_budget_does_not_invalidate_primary(monkeypatch):
    monkeypatch.setattr(tools, "MAX_STATES", 1)
    runtime = Runtime(
        control("AalSmartAlarm", states=(("isLocked", "lock"), ("alarmLevel", "level")))
    )
    runtime.records = {"level": StateRecord("level", 2, Freshness.CURRENT, 1700000000)}
    result = await make_tool(monkeypatch, runtime).fn()
    assert runtime.reads == ["level"] and result.data.coverage.complete
    assert result.data.findings[0].semantic_value["isLocked"] is None
    assert result.data.findings[0].context.source_states == []


@pytest.mark.asyncio
async def test_optional_reads_do_not_starve_later_primary_states(monkeypatch):
    runtime = Runtime(control("AalSmartAlarm"))
    controls = tuple(
        replace(
            control(
                "AalSmartAlarm",
                states=(
                    ("alarmLevel", f"p{i}"),
                    ("isLocked", f"l{i}"),
                    ("isLeaveActive", f"v{i}"),
                    ("disableEndTime", f"d{i}"),
                ),
            ),
            uuid=f"c{i:03}",
        )
        for i in range(30)
    )
    runtime.structure = replace(runtime.structure, controls=controls)
    runtime.records = {
        uuid: StateRecord(uuid, 1, Freshness.CURRENT, 1700000000)
        for c in controls
        for _name, uuid in c.state_uuids
    }
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.total_active == 30 and result.data.coverage.complete
    assert runtime.reads[:30] == [f"p{i}" for i in range(30)]
    assert len(runtime.reads) == 100


@pytest.mark.parametrize("raw", [None, "1", 2, float("nan"), {}, []])
def test_invalid_optional_context_does_not_override_activity(raw):
    c = control("AalSmartAlarm")
    semantics, value = resolve(c, "alarmLevel", 1, {"isLocked": raw})
    assert semantics.interpretation_status == "known" and value["alert_active"]
    assert value["isLocked"] is None


@pytest.mark.asyncio
async def test_shared_semantics_path_receives_same_current_context(monkeypatch):
    runtime = Runtime(
        control("AalSmartAlarm", states=(("alarmLevel", "level"), ("isLocked", "lock")))
    )
    runtime.records = {
        "level": StateRecord("level", 1, Freshness.CURRENT, 1700000000),
        "lock": StateRecord("lock", 1, Freshness.CURRENT, 1700000001),
    }
    make_tool(monkeypatch, runtime)
    server = FastMCP("shared-alert-semantics")
    tools.register_read_tools(server, runtime)
    result = await server._tool_manager.get_tool("loxone_get_state_semantics").fn(
        control_uuid="control", state_names=["alarmLevel"]
    )
    assert result.data.items[0].semantic_value["isLocked"] is True
    assert result.data.items[0].semantics.sources[-1].state_uuid == "lock"


@pytest.mark.asyncio
async def test_new_families_hidden_controls_never_leak(monkeypatch):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.records["state"] = StateRecord("state", 0, Freshness.CURRENT, 1700000000)
    runtime.structure = replace(
        runtime.structure,
        hidden_controls=(
            replace(
                control("AlarmChain", states=(("activeAlarmType", "secret-state"),)),
                uuid="secret-control",
            ),
        ),
    )
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.total_active == 0 and result.data.coverage.candidate_controls == 1
    assert "secret" not in result.model_dump_json() and runtime.reads == ["state"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value,count", [(0, 0), (1, 1), (2, 0), (3, 0)])
async def test_complete_snapshot(monkeypatch, value, count):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.records["state"] = StateRecord("state", value, Freshness.CURRENT, 1700000000)
    t = make_tool(monkeypatch, runtime)
    result = await t.fn()
    assert result.ok and result.data.complete and result.data.coverage.complete
    assert result.data.total_active == count and len(result.data.findings) == count
    assert runtime.snapshots == [True] and runtime.reads == ["state"]
    if count:
        finding = result.data.findings[0]
        assert finding.source_state.uuid == "state" and finding.source_state.value == value
        assert finding.classification == "alarm_triggered"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,freshness,reason",
    [
        (None, Freshness.UNAVAILABLE, "unavailable"),
        (1, Freshness.STALE, "stale"),
        (9, Freshness.CURRENT, "invalid"),
        (1, Freshness.UNKNOWN, "unknown"),
    ],
)
async def test_gaps_never_mean_inactive(monkeypatch, value, freshness, reason):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.records["state"] = StateRecord("state", value, freshness, 1700000000)
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.ok and not result.data.complete and result.data.total_active is None
    assert not result.data.findings and result.data.coverage.reasons[0].reason == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["StatusMonitor", "WindowMonitor"])
async def test_visibility_and_unsupported_families(monkeypatch, kind):
    runtime = Runtime(control(kind))
    runtime.structure = replace(runtime.structure, hidden_controls=(control("AalEmergency"),))
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.coverage.candidate_controls == 1
    assert result.data.coverage.unsupported_controls == 1 and result.data.total_active is None
    assert runtime.reads == []


@pytest.mark.asyncio
async def test_scan_state_reason_and_delivery_budgets(monkeypatch):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.structure = replace(
        runtime.structure,
        controls=tuple(
            replace(
                runtime.structure.controls[0], uuid=f"c{i:03}", state_uuids=(("status", f"s{i}"),)
            )
            for i in range(110)
        ),
    )
    runtime.records = {
        f"s{i}": StateRecord(f"s{i}", 1, Freshness.CURRENT, 1700000000) for i in range(110)
    }
    t = make_tool(monkeypatch, runtime)
    result = await t.fn(2)
    assert len(runtime.reads) == 100 and result.data.known_active == 100
    assert result.data.returned == 2 and result.data.truncated and not result.data.complete
    assert result.data.coverage.unavailable_controls == 10 and result.data.total_active is None
    monkeypatch.setattr(alerts, "MAX_SCAN", 5)
    result = await t.fn()
    assert (
        result.data.coverage.candidate_controls is None and not result.data.coverage.scan_complete
    )


@pytest.mark.asyncio
async def test_byte_limit_retains_coverage(monkeypatch):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.structure = replace(
        runtime.structure,
        controls=tuple(
            replace(runtime.structure.controls[0], uuid=f"c{i:03}", name="漢" * 200)
            for i in range(50)
        ),
    )
    result = await make_tool(monkeypatch, runtime).fn()
    assert result.data.coverage.complete and result.data.total_active == 50
    assert len(result.model_dump_json().encode("utf-8")) <= 65536
    assert result.data.returned < 50 and result.data.truncated and not result.data.complete
    assert [f.source_control.uuid for f in result.data.findings] == sorted(
        f.source_control.uuid for f in result.data.findings
    )


@pytest.mark.asyncio
async def test_fail_closed_refresh_and_input(monkeypatch):
    runtime = Runtime(control("AalEmergency"))
    t = make_tool(monkeypatch, runtime)
    for limit in [0, 51, True]:
        result = await t.fn(limit)
        assert not result.ok and result.data.error == "invalid_input"
    runtime.failure = RuntimeUnavailable("structure refresh failed")
    result = await t.fn()
    assert not result.ok and result.data.error == "temporarily_unavailable" and not runtime.reads


@pytest.mark.asyncio
async def test_permission_failure_has_no_reads(monkeypatch):
    runtime = Runtime(control("AalEmergency"))
    t = make_tool(monkeypatch, runtime)

    def denied():
        raise PermissionError

    monkeypatch.setattr(tools, "_access", denied)
    result = await t.fn()
    assert not result.ok and result.data.error == "unauthenticated"
    assert not runtime.snapshots and not runtime.reads


@pytest.mark.asyncio
async def test_missing_and_oversized_refs(monkeypatch):
    runtime = Runtime(control("AalEmergency", states=()))
    t = make_tool(monkeypatch, runtime)
    assert (await t.fn()).data.coverage.reasons[0].reason == "missing_state"
    runtime.structure = replace(
        runtime.structure,
        controls=(
            control("AalEmergency", states=tuple((f"s{i}", f"uuid{i}") for i in range(101))),
        ),
    )
    assert (await t.fn()).data.coverage.reasons[0].reason == "reference_budget"
    assert not runtime.reads


@pytest.mark.asyncio
async def test_shared_uuid_decoder_budget_and_reason_truncation(monkeypatch):
    runtime = Runtime(control("AalEmergency", states=(("status", "state"),)))
    runtime.structure = replace(
        runtime.structure,
        controls=tuple(replace(runtime.structure.controls[0], uuid=f"c{i:03}") for i in range(151)),
    )
    result = await make_tool(monkeypatch, runtime).fn()
    assert runtime.reads == ["state"]
    assert result.data.coverage.evaluated_controls == 100
    assert result.data.coverage.unavailable_controls == 51
    assert result.data.coverage.reasons_truncated and len(result.data.coverage.reasons) == 50
    assert result.data.coverage.reasons[0].reason == "decoder_budget"


def test_nested_hidden_controls_do_not_enter_scan_counts(monkeypatch):
    monkeypatch.setattr(alerts, "MAX_SCAN", 1)
    visible = control("AalEmergency")
    hidden = replace(visible, uuid="hidden", is_hidden=True)
    sources, complete = alerts.select_sources((hidden, visible))
    assert sources == [visible] and complete
