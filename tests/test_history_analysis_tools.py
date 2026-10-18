import asyncio
import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.history_analysis_tools import (
    AnalysisSource,
    ComparisonOptions,
    register_history_analysis_tool,
)
from mcpserver.installation_profile import BindingInput, ProfileStore, installation_identity
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, StatisticSeries
from mcpserver.loxone.runtime import RuntimeAuthorizationError
from mcpserver.loxone.statistics import StatisticPoint


def configured(monkeypatch, *, points=3):
    series = StatisticSeries("series", "statistic_v2", "1", "tempActual", "Actual", "%.1f°C")
    control = Control(
        "control",
        "Room",
        "IRoomControllerV2",
        None,
        None,
        None,
        (("tempActual", "state"),),
        statistic_series=(series,),
        format="%.1f°C",
    )
    structure = LoxoneStructure(LoxoneIdentity("user", "serial"), "v1", (), (), (control,))
    semaphore = asyncio.Semaphore(1)
    runtime = SimpleNamespace(
        contexts=0,
        structure=structure,
        control=control,
        _require_access=AsyncMock(),
        endpoint=SimpleNamespace(origin="http://synthetic.local"),
    )

    @asynccontextmanager
    async def context(_access):
        async with semaphore:
            runtime.contexts += 1
            yield runtime.structure, object()

    async def forbidden_slot():
        raise AssertionError("already admitted; must not reacquire the same semaphore")

    runtime.history_context = context
    runtime.worker_slot = forbidden_slot
    runtime.authorized_statistics = AsyncMock(
        return_value=(
            control,
            series,
            tuple(StatisticPoint(100 + i, 20 + i) for i in range(points)),
        )
    )
    monkeypatch.setattr(
        "mcpserver.history_analysis_tools._access", lambda: SimpleNamespace(family_id="family")
    )
    server = FastMCP("analysis-test")
    register_history_analysis_tool(server, runtime, None, None)
    tool = server._tool_manager.get_tool("loxone_analyze_history")
    return runtime, tool


ARGS = dict(
    operation="temperature_summary",
    sources=[AnalysisSource(control_uuid="control", series_id="series")],
    start="1970-01-01T00:01:40Z",
    end="1970-01-01T01:00:00Z",
    timezone="Europe/Berlin",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "source", "revoked"])
async def test_profileless_context_keeps_semantics_and_checks_publication(monkeypatch, change):
    from unittest.mock import Mock

    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool = configured(monkeypatch)
    fresh = runtime.structure
    if change == "source":
        fresh = replace(fresh, controls=(replace(runtime.control, control_type="Other"),))
    runtime._history_visible_structure = AsyncMock(return_value=fresh)
    if change == "revoked":
        runtime._require_access.side_effect = [None, RuntimeAuthorizationError("Access revoked")]
    store = Mock(side_effect=AssertionError("no profile access for direct associations"))
    monkeypatch.setattr("mcpserver.installation_profile.ProfileStore", store)
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "Explicit test scope",
                "common_supply_origin": "user_confirmed",
            },
            "associations": [
                {
                    "association_id": "selected",
                    "source_index": 0,
                    "role": "consumer",
                    "measurement_boundary": "single-channel",
                    "origin": "user_confirmed",
                }
            ],
        }
    )
    result = await asyncio.wait_for(
        tool.fn(**{**ARGS, "operation": "baseload", "analysis_context": ctx}), 3
    )
    assert runtime.contexts == 1
    assert runtime.authorized_statistics.await_count == 1
    store.assert_not_called()
    if change == "none":
        assert result.ok
        assert result.data.sources[0].binding_id is None
        assert result.data.comparison.status == "insufficient_evidence"
        assert result.data.comparison.context_analysis.associations[0].identifier == "selected"
        # Calling a temperature channel a consumer never manufactures energy semantics.
        assert not result.data.comparison.metrics
    else:
        assert not result.ok


@pytest.mark.asyncio
async def test_context_invalid_indices_are_rejected_before_source_context(monkeypatch):
    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool = configured(monkeypatch)
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "Test",
                "common_supply_origin": "scenario_assumption",
            },
            "associations": [
                {"association_id": "missing", "source_index": 1, "origin": "scenario_assumption"}
            ],
        }
    )
    result = await tool.fn(**{**ARGS, "operation": "baseload", "analysis_context": ctx})
    assert not result.ok and runtime.contexts == 0


@pytest.mark.asyncio
async def test_context_profile_revision_change_prevents_publication(monkeypatch):
    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool = configured(monkeypatch)
    runtime._history_visible_structure = AsyncMock(return_value=runtime.structure)
    saved = {
        "binding_id": "saved",
        "status": "confirmed",
        "role": "consumer",
        "source_kind": "statistic",
        "control_uuid": "control",
        "series_id": "series",
        "state_uuid": None,
        "measurement_boundary": "single",
        "declared_direction": None,
    }
    reader = AsyncMock(side_effect=[({"saved": saved}, 7), ({"saved": saved}, 8)])
    monkeypatch.setattr("mcpserver.history_analysis_tools.read_profile_bindings", reader)
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "One budget",
                "common_supply_origin": "user_confirmed",
            },
            "associations": [
                {"association_id": "load", "source_index": 0, "origin": "user_confirmed"}
            ],
        }
    )
    result = await tool.fn(
        **{
            **ARGS,
            "operation": "baseload",
            "sources": [AnalysisSource(binding_id="saved")],
            "analysis_context": ctx,
        }
    )
    assert not result.ok and result.data.error == "temporarily_unavailable"
    assert reader.await_count == 2 and runtime.authorized_statistics.await_count == 1


@pytest.mark.asyncio
async def test_raw_cursor_binds_context_even_when_comparison_values_are_unchanged(monkeypatch):
    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool = configured(monkeypatch, points=101)
    runtime._history_visible_structure = AsyncMock(return_value=runtime.structure)
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "First assumption",
                "common_supply_origin": "user_confirmed",
            },
            "associations": [
                {"association_id": "channel", "source_index": 0, "origin": "scenario_assumption"}
            ],
        }
    )
    args = {**ARGS, "operation": "baseload", "analysis_context": ctx, "include_raw": True}
    first = await tool.fn(**args)
    assert first.ok and first.data.next_cursor
    ctx.scope.description = "Changed assumption"
    rejected = await tool.fn(**args, cursor=first.data.next_cursor)
    assert not rejected.ok and rejected.data.error == "invalid_input"


@pytest.mark.asyncio
async def test_baseload_is_reachable_with_documented_hourly_energy(monkeypatch):
    runtime, tool = configured(monkeypatch)
    series = replace(
        runtime.control.statistic_series[0], output="totalNeg", format="%.1fWh", accumulated=True
    )
    control = replace(
        runtime.control,
        control_type="Meter",
        statistic_series=(series,),
        state_uuids=(("totalNeg", "state"),),
        format="%.1fWh",
    )
    runtime.structure = replace(runtime.structure, controls=(control,))
    runtime.authorized_statistics.return_value = (
        control,
        series,
        tuple(StatisticPoint(i * 3600, value) for i, value in enumerate((100, 200, 300))),
    )
    args = {
        **ARGS,
        "operation": "baseload",
        "start": "1970-01-01T00:00:00Z",
        "end": "1970-01-01T03:00:00Z",
        "sources": [AnalysisSource(control_uuid="control", series_id="series", granularity="hour")],
    }
    first = await tool.fn(**args)
    assert first.ok and first.data.comparison.status == "partial"
    assert first.data.comparison.metrics["nighttime_median_power"] == 200
    assert first.data.raw == []
    assert runtime.contexts == 1 and runtime.authorized_statistics.await_count == 1


@pytest.mark.asyncio
async def test_comparison_options_cannot_change_old_operations(monkeypatch):
    runtime, tool = configured(monkeypatch)
    result = await tool.fn(**ARGS, comparison_options=ComparisonOptions())
    assert not result.ok and result.data.error == "invalid_input"
    assert runtime.contexts == 0


@pytest.mark.asyncio
async def test_changed_comparison_options_invalidate_raw_cursor(monkeypatch):
    runtime, tool = configured(monkeypatch, points=101)
    args = {**ARGS, "operation": "baseload", "include_raw": True}
    first = await tool.fn(**args)
    assert first.ok and first.data.next_cursor
    changed = await tool.fn(
        **args,
        cursor=first.data.next_cursor,
        comparison_options=ComparisonOptions(night_end_hour=6),
    )
    assert not changed.ok and changed.data.error == "invalid_input"
    assert runtime.contexts == 2


@pytest.mark.asyncio
async def test_single_fresh_context_deduplicates_and_works_with_one_runtime_slot(monkeypatch):
    runtime, tool = configured(monkeypatch)
    result = await asyncio.wait_for(tool.fn(**{**ARGS, "sources": ARGS["sources"] * 2}), 2)
    assert result.ok and result.data.sources[0].metrics["mean"] == 21
    assert len(result.data.sources) == 1 and result.data.raw == []
    assert runtime.contexts == 1 and runtime.authorized_statistics.await_count == 1
    assert tool.annotations.readOnlyHint is True


@pytest.mark.asyncio
async def test_every_raw_page_authorizes_and_binds_to_current_source_content(monkeypatch):
    runtime, tool = configured(monkeypatch, points=101)
    first = await tool.fn(**ARGS, include_raw=True)
    assert first.ok and len(first.data.raw) == 100 and first.data.next_cursor
    second = await tool.fn(**ARGS, include_raw=True, cursor=first.data.next_cursor)
    assert second.ok and len(second.data.raw) == 1 and runtime.contexts == 2
    runtime.structure = replace(runtime.structure, controls=())
    denied = await tool.fn(**ARGS, include_raw=True, cursor=first.data.next_cursor)
    assert not denied.ok and denied.data.error == "not_found"
    assert "Room" not in denied.model_dump_json()


@pytest.mark.asyncio
async def test_revocation_before_result_release_hides_prepared_values(monkeypatch):
    runtime, tool = configured(monkeypatch)
    runtime._require_access.side_effect = [None, RuntimeAuthorizationError("secret-marker")]
    result = await tool.fn(**ARGS)
    assert not result.ok and result.data.error == "permission_denied"
    assert "secret-marker" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_cancelled_request_keeps_two_analysis_admissions_until_completion(monkeypatch):
    runtime, tool = configured(monkeypatch)
    gate = asyncio.Event()
    started = asyncio.Event()
    original = runtime.authorized_statistics.return_value

    async def blocked(*_args, **_kwargs):
        started.set()
        await gate.wait()
        return original

    runtime.authorized_statistics.side_effect = blocked
    one = asyncio.create_task(tool.fn(**ARGS))
    await started.wait()
    two = asyncio.create_task(tool.fn(**ARGS))
    await asyncio.sleep(0)
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    third = await tool.fn(**ARGS)
    assert not third.ok and third.data.error == "temporarily_unavailable"
    gate.set()
    assert (await two).ok
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_near_limit_raw_preparation_keeps_event_loop_responsive(monkeypatch):
    runtime, tool = configured(monkeypatch, points=100_000)
    arguments = {**ARGS, "end": "1970-01-03T00:00:00Z"}
    ticks = 0
    task = asyncio.create_task(tool.fn(**arguments, include_raw=True))
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.005)
    result = await task
    assert result.ok and len(result.data.raw) == 100 and result.data.input_points == 100_000
    assert ticks >= 3


@pytest.mark.parametrize(
    "source",
    [
        {},
        dict(control_uuid="control"),
        dict(control_uuid="control", series_id="series", state_uuid="state"),
        dict(binding_id="binding", control_uuid="control"),
        dict(control_uuid="control", state_uuid="state", granularity="hour"),
    ],
)
def test_selector_cannot_mix_bindings_or_source_kinds(source):
    with pytest.raises(ValidationError):
        AnalysisSource(**source)


@pytest.mark.asyncio
async def test_invalid_window_or_zone_does_not_open_source_context(monkeypatch):
    runtime, tool = configured(monkeypatch)
    for changed in (
        {"timezone": "not/a/zone"},
        {"end": "1970-01-01T00:01:40Z"},
        {"end": "1970-03-03T00:00:00Z"},
        {"end": "2099-01-01T00:00:00Z"},
    ):
        result = await tool.fn(**{**ARGS, **changed})
        assert not result.ok and result.data.error == "invalid_input"
    assert runtime.contexts == 0


@pytest.mark.asyncio
async def test_computation_deadline_is_not_a_miniserver_connection_failure(monkeypatch):
    _runtime, tool = configured(monkeypatch)

    def expired(*_args):
        raise HistoryAnalysisDeadline()

    monkeypatch.setattr("mcpserver.history_analysis_tools._statistic_calculation", expired)
    result = await tool.fn(**ARGS)
    assert not result.ok and result.data.error == "deadline_exceeded"


@pytest.mark.asyncio
async def test_revocation_during_cursor_proof_blocks_raw_release(monkeypatch):
    import mcpserver.history_analysis_tools as module

    runtime, tool = configured(monkeypatch)
    original = module._raw_scope

    def revoke(*args):
        proof = original(*args)
        runtime._require_access.side_effect = RuntimeAuthorizationError("private-marker")
        return proof

    monkeypatch.setattr(module, "_raw_scope", revoke)
    result = await tool.fn(**ARGS, include_raw=True)
    assert not result.ok and result.data.error == "permission_denied"
    assert "private-marker" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_profile_binding_requires_confirmation_current_fingerprint_and_visibility(
    tmp_path, monkeypatch
):
    runtime, _tool = configured(monkeypatch)
    runtime.control = replace(runtime.control, uuid="00000001-0000-0000-0000000000000001")
    runtime.structure = replace(runtime.structure, controls=(runtime.control,))
    path = (tmp_path / "profile.json").resolve()
    identity = installation_identity(runtime.endpoint.origin, runtime.structure)
    binding = BindingInput(
        binding_id="room",
        role="actual_temperature",
        control_uuid=runtime.control.uuid,
        source_kind="statistic",
        series_id="series",
        confirmed=True,
    )
    ProfileStore(path).put(
        identity,
        0,
        binding,
        runtime.control,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"actor").hexdigest(),
    )
    server = FastMCP("bound-analysis")
    register_history_analysis_tool(server, runtime, None, path)
    tool = server._tool_manager.get_tool("loxone_analyze_history")
    args = {**ARGS, "sources": [AnalysisSource(binding_id="room")]}
    assert (await tool.fn(**args)).ok
    runtime.structure = replace(
        runtime.structure,
        controls=(
            replace(
                runtime.control,
                statistic_series=(replace(runtime.control.statistic_series[0], accumulated=True),),
            ),
        ),
    )
    changed = await tool.fn(**args)
    assert not changed.ok and changed.data.error == "not_found"
    runtime.structure = replace(runtime.structure, controls=())
    hidden = await tool.fn(**args)
    assert not hidden.ok and hidden.data.error == "not_found"
