from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from test_history_analysis_tools import configured
from test_installation_profile_flexibility import ACTOR, C0, C1, S1
from test_load_flexibility import flexibility

from mcpserver.config import PluginConfig
from mcpserver.history_analysis_tools import AnalysisSource, register_history_analysis_tool
from mcpserver.installation_profile import (
    BindingInput,
    ProfileSources,
    ProfileStore,
    installation_identity,
)
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.models import Control
from mcpserver.loxone.runtime import RuntimeAuthorizationError
from mcpserver.loxone.statistics import StatisticPoint


def setup(monkeypatch, tmp_path):
    runtime, _tool = configured(monkeypatch)
    series = replace(
        runtime.control.statistic_series[0], output="total", format="%.1fWh", accumulated=True
    )
    meter = replace(
        runtime.control,
        uuid=C0,
        control_type="Meter",
        statistic_series=(series,),
        state_uuids=(),
        format="%.1fWh",
    )
    operating = Control(
        C1, "Fixture operating state", "InfoOnlyDigital", None, None, None, (("active", S1),)
    )
    runtime.structure = replace(runtime.structure, controls=(meter, operating))
    installation = installation_identity(runtime.endpoint.origin, runtime.structure)
    sources = ProfileSources.from_structure(installation, runtime.structure)
    profile = ProfileStore(tmp_path / "profile.json")
    op_binding = BindingInput(
        binding_id="load-active",
        role="operating_state",
        control_uuid=C1,
        source_kind="state",
        state_uuid=S1,
        confirmed=True,
    )
    profile.put(installation, 0, op_binding, sources, origin="local_admin", actor_ref=ACTOR)
    profile.put(
        installation,
        1,
        BindingInput(
            binding_id="load",
            role="consumer",
            control_uuid=C0,
            source_kind="statistic",
            series_id=series.series_id,
            confirmed=True,
            load_flexibility=flexibility(),
        ),
        sources,
        origin="local_admin",
        actor_ref=ACTOR,
    )
    config = PluginConfig(
        loxone_history_enabled=True, event_history_enabled=True, event_history_sources=((C1, S1),)
    )
    store = EventHistoryStore(tmp_path / "events.sqlite3", retention_days=90, maximum_mib=128)
    store.initialize()
    first = datetime.combine(datetime.now(UTC).date() - timedelta(days=1), datetime.min.time(), UTC)
    start = first.timestamp()
    store.begin_coverage(((C1, S1),), started_at=start, initial_values={(C1, S1): (start, 0)})
    store.record_transition(C1, S1, observed_at=start + 3600, old_value=0, new_value=1)
    store.record_transition(C1, S1, observed_at=start + 10800, old_value=1, new_value=0)
    store.end_coverage(((C1, S1),), ended_at=start + 14400, outcome="disabled")
    runtime.authorized_statistics.return_value = (
        meter,
        series,
        tuple(StatisticPoint(start + i * 3600, v) for i, v in enumerate((0, 1000, 500, 0))),
    )
    event = SimpleNamespace(
        _config_store=SimpleNamespace(load=lambda: config), _store_path=store.path
    )
    server = FastMCP("load-cycle-fixture")
    register_history_analysis_tool(server, runtime, event, profile.path)
    tool = server._tool_manager.get_tool("loxone_analyze_history")
    args = dict(
        operation="operating_phases",
        sources=[
            AnalysisSource(binding_id="load", granularity="hour"),
            AnalysisSource(binding_id="load-active"),
        ],
        start=first.isoformat(),
        end=(first + timedelta(hours=4)).isoformat(),
        timezone="UTC",
    )
    return runtime, tool, args, profile, sources, op_binding


@pytest.mark.asyncio
async def test_cycle_runtime_uses_confirmed_profile_native_semantics_and_one_admission(
    monkeypatch, tmp_path
):
    runtime, tool, args, profile, sources, _op = setup(monkeypatch, tmp_path)
    result = await tool.fn(**args)
    assert result.ok
    cycles = result.data.comparison.load_cycles
    assert cycles.profile_revision == 2 and cycles.episode_count == 1
    assert cycles.episodes[0].energy_profile_complete
    assert cycles.episodes[0].observed_energy_wh == 1500
    assert cycles.native_lock_status == "not_checked"
    assert cycles.episodes[0].cycle_identity == "active_episode_only"
    assert runtime.contexts == 1 and runtime.authorized_statistics.await_count == 1
    assert tool.annotations.readOnlyHint


@pytest.mark.asyncio
async def test_profile_change_during_cycle_read_fails_before_result(monkeypatch, tmp_path):
    runtime, tool, args, profile, sources, op = setup(monkeypatch, tmp_path)
    original = runtime.authorized_statistics.return_value

    async def changed(*_args, **_kwargs):
        profile.put(
            sources.installation,
            2,
            op.model_copy(update={"confirmed": False}),
            sources,
            origin="local_admin",
            actor_ref=ACTOR,
        )
        return original

    runtime.authorized_statistics.side_effect = changed
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "temporarily_unavailable"
    assert result.data.message == "Installation profile changed during cycle analysis"
    assert "energy_intervals" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_hidden_companion_and_final_revocation_never_return_cycle_evidence(
    monkeypatch, tmp_path
):
    runtime, tool, args, profile, sources, op = setup(monkeypatch, tmp_path)
    original = runtime.structure
    runtime.structure = replace(original, controls=(original.controls[0],))
    hidden = await tool.fn(**args)
    assert not hidden.ok and hidden.data.error == "not_found"
    runtime.structure = original
    runtime._require_access.side_effect = RuntimeAuthorizationError()
    revoked = await tool.fn(**args)
    assert not revoked.ok and revoked.data.error == "permission_denied"
    assert "energy_intervals" not in revoked.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("granularity", ["day", "month", "year"])
async def test_non_hourly_energy_never_qualifies_an_hourly_cycle(
    monkeypatch, tmp_path, granularity
):
    runtime, tool, args, profile, sources, op = setup(monkeypatch, tmp_path)
    args["sources"][0] = AnalysisSource(binding_id="load", granularity=granularity)
    result = await tool.fn(**args, include_raw=True)
    assert result.ok
    numeric = result.data.sources[0]
    assert numeric.status == "insufficient_evidence"
    assert numeric.limitations == ["non_hourly_interval_energy_not_supported"]
    episode = result.data.comparison.load_cycles.episodes[0]
    assert episode.observed_energy_wh is None and not episode.energy_profile_complete
    assert (
        result.data.raw
    )  # Preserve explicitly requested values without relabelling their interval.
