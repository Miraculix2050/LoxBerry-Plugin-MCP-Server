from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from test_installation_profile_flexibility import ACTOR, C2, S1
from test_load_cycles_tools import setup as cycle_setup
from test_load_flexibility import flexibility

from mcpserver.config import PluginConfig
from mcpserver.history_analysis_tools import (
    AnalysisSource,
    ComparisonOptions,
    register_history_analysis_tool,
)
from mcpserver.installation_profile import BindingInput, ProfileSources
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.runtime import RuntimeAuthorizationError
from mcpserver.loxone.statistics import StatisticPoint


def setup(monkeypatch, tmp_path, *, identity="user_confirmed_cycle", direction="export"):
    runtime, _, args, profile, previous_sources, op = cycle_setup(monkeypatch, tmp_path)
    meter, operating = runtime.structure.controls
    export = replace(meter, uuid=C2, name="Fixture export")
    runtime.structure = replace(runtime.structure, controls=(meter, operating, export))
    sources = ProfileSources.from_structure(previous_sources.installation, runtime.structure)
    flex = flexibility(
        timezone="UTC",
        cycle_identity=identity,
        latest_completion="00:00",
        completion_day_offset=1,
        windows=[
            {"weekdays": list(range(7)), "start": "00:00", "end": "00:00", "end_day_offset": 1}
        ],
    )
    profile.put(
        sources.installation,
        2,
        BindingInput(
            binding_id="load",
            role="consumer",
            control_uuid=meter.uuid,
            source_kind="statistic",
            series_id=meter.statistic_series[0].series_id,
            confirmed=True,
            load_flexibility=flex,
            measurement_boundary="fixture-grid",
        ),
        sources,
        origin="local_admin",
        actor_ref=ACTOR,
    )
    profile.put(
        sources.installation,
        3,
        BindingInput(
            binding_id="export",
            role="grid_export",
            control_uuid=C2,
            source_kind="statistic",
            series_id=export.statistic_series[0].series_id,
            confirmed=True,
            declared_direction=direction,
            measurement_boundary="fixture-grid",
        ),
        sources,
        origin="local_admin",
        actor_ref=ACTOR,
    )
    start = datetime.fromisoformat(args["start"]).timestamp()
    store = EventHistoryStore(tmp_path / "shift-events.sqlite3", retention_days=90, maximum_mib=128)
    store.initialize()
    store.begin_coverage(
        ((operating.uuid, S1),), started_at=start, initial_values={(operating.uuid, S1): (start, 0)}
    )
    store.record_transition(operating.uuid, S1, observed_at=start + 3600, old_value=0, new_value=1)
    store.record_transition(operating.uuid, S1, observed_at=start + 10800, old_value=1, new_value=0)
    store.end_coverage(((operating.uuid, S1),), ended_at=start + 86400, outcome="disabled")

    def statistics(access, control, *rest, **kwargs):
        values = (
            (StatisticPoint(start + 10 * 3600, 600.0), StatisticPoint(start + 11 * 3600, 800.0))
            if control.uuid == C2
            else (
                StatisticPoint(start + 3600, 1000.0),
                StatisticPoint(start + 7200, 500.0),
            )
        )
        return control, control.statistic_series[0], values

    runtime.authorized_statistics.side_effect = statistics
    config = PluginConfig(
        loxone_history_enabled=True,
        event_history_enabled=True,
        event_history_sources=((operating.uuid, S1),),
    )
    event = SimpleNamespace(
        _config_store=SimpleNamespace(load=lambda: config), _store_path=store.path
    )
    server = FastMCP("retrospective-fixture")
    register_history_analysis_tool(server, runtime, event, profile.path)
    args.update(
        operation="retrospective_shift",
        end=datetime.fromtimestamp(start + 86400, UTC).isoformat(),
        comparison_options=ComparisonOptions(comparable_boundaries_confirmed=True),
    )
    args["sources"].append(AnalysisSource(binding_id="export", granularity="hour"))
    return (
        runtime,
        server._tool_manager.get_tool("loxone_analyze_history"),
        args,
        profile,
        sources,
        op,
    )


@pytest.mark.asyncio
async def test_profile_native_statistics_sqlite_and_one_admission_produce_conditional_examples(
    monkeypatch, tmp_path
):
    runtime, tool, args, profile, sources, _ = setup(monkeypatch, tmp_path)
    result = await tool.fn(**args)
    assert result.ok
    shift = result.data.comparison.retrospective_shift
    assert shift.profile_revision == profile.read(sources.installation).revision
    assert shift.examples[0].admissibility == "not_proven"
    assert shift.conditional_export_absorption_upper_bound_wh == 1100
    assert runtime.contexts == 1 and runtime.authorized_statistics.await_count == 2


@pytest.mark.asyncio
async def test_unknown_cycle_identity_does_not_create_conditional_energy(monkeypatch, tmp_path):
    _, tool, args, *_ = setup(monkeypatch, tmp_path, identity="active_episode_only")
    result = await tool.fn(**args)
    assert result.ok and not result.data.comparison.retrospective_shift.examples


@pytest.mark.asyncio
async def test_missing_export_direction_does_not_qualify(monkeypatch, tmp_path):
    _, tool, args, *_ = setup(monkeypatch, tmp_path, direction=None)
    result = await tool.fn(**args)
    assert result.ok and result.data.comparison.retrospective_shift is None
    assert "confirmed_export_direction" in result.data.comparison.limitations[0]


@pytest.mark.asyncio
async def test_final_access_revocation_and_duplicate_sources_fail_closed(monkeypatch, tmp_path):
    runtime, tool, args, *_ = setup(monkeypatch, tmp_path)
    duplicate = await tool.fn(**{**args, "sources": args["sources"] + [args["sources"][0]]})
    assert not duplicate.ok and duplicate.data.error == "invalid_input"
    runtime._require_access.side_effect = RuntimeAuthorizationError()
    denied = await tool.fn(**args)
    assert not denied.ok and denied.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_profile_change_during_reads_denies_result(monkeypatch, tmp_path):
    runtime, tool, args, profile, sources, op = setup(monkeypatch, tmp_path)
    statistics = runtime.authorized_statistics.side_effect
    changed = False

    def mutate(*values, **kwargs):
        nonlocal changed
        if not changed:
            profile.put(
                sources.installation,
                4,
                op.model_copy(update={"confirmed": False}),
                sources,
                origin="local_admin",
                actor_ref=ACTOR,
            )
            changed = True
        return statistics(*values, **kwargs)

    runtime.authorized_statistics.side_effect = mutate
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "temporarily_unavailable"
    assert "conditional_export_absorption" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_hidden_operating_source_is_not_revealed(monkeypatch, tmp_path):
    runtime, tool, args, *_ = setup(monkeypatch, tmp_path)
    runtime.structure = replace(
        runtime.structure,
        controls=tuple(
            c for c in runtime.structure.controls if c.control_type != "InfoOnlyDigital"
        ),
    )
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "not_found"
    assert "alternative_start" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("granularity", ["day", "month", "year"])
async def test_nonhourly_export_never_becomes_hourly_budget_and_raw_is_retained(
    monkeypatch, tmp_path, granularity
):
    _, tool, args, *_ = setup(monkeypatch, tmp_path)
    args["sources"][-1] = AnalysisSource(binding_id="export", granularity=granularity)
    result = await tool.fn(**args, include_raw=True)
    assert result.ok and result.data.comparison.retrospective_shift is None
    assert result.data.raw
    assert result.data.sources[-1].limitations == ["non_hourly_interval_energy_not_supported"]


@pytest.mark.asyncio
async def test_new_operation_keeps_historical_time_gate_and_explicit_boundary_gate(
    monkeypatch, tmp_path
):
    runtime, tool, args, *_ = setup(monkeypatch, tmp_path)
    future = await tool.fn(**{**args, "end": "2100-01-01T00:00:00Z"})
    assert not future.ok and future.data.error == "invalid_input" and runtime.contexts == 0
    unconfirmed = await tool.fn(**{**args, "comparison_options": ComparisonOptions()})
    assert unconfirmed.ok and unconfirmed.data.comparison.retrospective_shift is None


@pytest.mark.asyncio
async def test_exact_sources_without_confirmed_profile_are_rejected_before_native_reads(
    monkeypatch, tmp_path
):
    runtime, tool, args, *_ = setup(monkeypatch, tmp_path)
    args["sources"][0] = AnalysisSource(
        control_uuid=runtime.structure.controls[0].uuid, series_id="series", granularity="hour"
    )
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "invalid_input"
    assert runtime.contexts == 0 and runtime.authorized_statistics.await_count == 0


@pytest.mark.asyncio
async def test_changed_measurement_boundary_remains_unqualified(monkeypatch, tmp_path):
    _, tool, args, profile, sources, _ = setup(monkeypatch, tmp_path)
    export = next(c for c in sources.controls.values() if c.uuid == C2)
    profile.put(
        sources.installation,
        4,
        BindingInput(
            binding_id="export",
            role="grid_export",
            control_uuid=C2,
            source_kind="statistic",
            series_id=export.statistic_series[0].series_id,
            confirmed=True,
            declared_direction="export",
            measurement_boundary="different-boundary",
        ),
        sources,
        origin="local_admin",
        actor_ref=ACTOR,
    )
    result = await tool.fn(**args)
    assert result.ok and result.data.comparison.retrospective_shift is None
    assert result.data.comparison.limitations == [
        "matching_declared_export_consumer_boundary_required"
    ]
