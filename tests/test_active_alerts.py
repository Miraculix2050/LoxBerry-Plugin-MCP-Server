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
async def test_visibility_and_unsupported_families(monkeypatch):
    runtime = Runtime(control("StatusMonitor"))
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
