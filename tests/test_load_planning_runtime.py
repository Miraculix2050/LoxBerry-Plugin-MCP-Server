from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.fastmcp import FastMCP
from test_load_flexibility import flexibility
from test_load_planning import START, forecast, options
from test_native_efm import ACTION, SERIAL, TARGET, access

import mcpserver.load_planning_runtime as module
import mcpserver.load_planning_tools as tool_module
from mcpserver.installation_profile import ProfileError
from mcpserver.load_planning_runtime import calculate_load_plan
from mcpserver.load_planning_tools import register_load_planning_tool
from mcpserver.loxone.models import Control, Freshness, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import ControlOperationError, RuntimeSnapshot


@pytest.fixture(autouse=True)
def planning_wall_clock(monkeypatch):
    """Keep fixture forecasts in the future without changing real deadline clocks."""
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: START - 3600))


@pytest.mark.parametrize("freshness", list(Freshness))
@pytest.mark.parametrize("value", [0, 1, None, True, -1])
def test_current_lock_retains_unknown_freshness(freshness, value):
    control = Control(TARGET, "Fixture", "Switch", None, None, None, (("lockedOn", "lock"),))
    runtime = SimpleNamespace(
        cache=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(value=value, freshness=freshness))
        )
    )
    expected = (
        bool(value)
        if freshness is Freshness.CURRENT and type(value) is int and value in (0, 1)
        else None
    )
    assert module._known_lock(runtime, "subject", (control,)) is expected
    assert module._known_lock(runtime, "subject", (replace(control, state_uuids=()),)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("observed", [False, True])
async def test_one_forecast_and_no_history_for_declared_cycle(
    tmp_path, monkeypatch, changed, nested, locked, observed
):
    pv = Control(TARGET, "Forecast", "PvProductionForecast", None, None, ACTION, ())
    consumer = Control(
        "00000000-0000-0000-0000000000000003", "Consumer", "Switch", None, None, None, ()
    )
    parent = replace(consumer, uuid="00000000-0000-0000-0000000000000004", subcontrols=(consumer,))
    operating_control = replace(
        consumer,
        uuid="00000000-0000-0000-0000000000000005",
        state_uuids=(("lockedOn", "lock-state"),),
    )
    structure = LoxoneStructure(
        LoxoneIdentity("reader", SERIAL),
        "current",
        (),
        (),
        (pv, parent if nested else consumer, operating_control),
    )
    snapshot = RuntimeSnapshot("family", structure, True)

    single_slot = asyncio.Semaphore(1)

    @asynccontextmanager
    async def context(_access):
        async with single_slot:
            yield snapshot

    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin="http://synthetic.local"),
        snapshot_context=context,
        _snapshot_admitted=AsyncMock(return_value=snapshot),
        cache=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(value=int(locked), freshness=Freshness.CURRENT))
        ),
    )
    document = SimpleNamespace(revision=1)
    reader = Mock(side_effect=[document, SimpleNamespace(revision=2) if changed else document])
    monkeypatch.setattr(module, "ProfileStore", lambda _: SimpleNamespace(read=reader))
    flex = flexibility(
        energy_profile_origin="observed_intervals" if observed else "user_declared",
        declared_cycle_energy_wh=None if observed else 2000.0,
        cycle_identity="user_confirmed_cycle",
    )
    binding = {
        "binding_id": "a",
        "role": "consumer",
        "control_uuid": consumer.uuid,
        "load_constraints_usable": True,
        "load_flexibility": flex.model_dump(),
    }
    operating = {
        "binding_id": "load-active",
        "role": "operating_state",
        "control_uuid": operating_control.uuid,
        "state_uuid": "active",
    }
    monkeypatch.setattr(
        module, "project_profile", lambda *_args, **_kwargs: {"bindings": [binding, operating]}
    )
    source = AsyncMock(return_value=(pv, structure, forecast()))

    async def load_history(*_args):
        async with single_slot:
            return {"a": ((7200, 2000.0),)}

    history = AsyncMock(side_effect=load_history)
    monkeypatch.setattr(module, "read_pv_forecast", source)
    monkeypatch.setattr(module, "_observed_profiles", history)
    if changed:
        with pytest.raises(ControlOperationError, match="changed"):
            await calculate_load_plan(
                runtime,
                None,
                tmp_path / "profile.json",
                access(),
                options(),
                deadline=time.monotonic() + 5,
            )
    else:
        result = await calculate_load_plan(
            runtime,
            None,
            tmp_path / "profile.json",
            access(),
            options(),
            deadline=time.monotonic() + 5,
        )
        if locked:
            assert not result.allocations and result.unplanned["a"] == "known_native_lock"
        else:
            assert result.allocations and result.allocations[0].energy_origin == (
                "observed_intervals" if observed else "user_declared_uniform"
            )
        assert result.profile_revision == 1
    source.assert_awaited_once()
    assert history.await_count == int(observed)
    assert reader.call_count == 2


@pytest.mark.asyncio
async def test_unavailable_forecast_skips_profile_and_history(tmp_path, monkeypatch):
    source = forecast()
    source.status = "not_ready"
    monkeypatch.setattr(module, "read_pv_forecast", AsyncMock(return_value=(None, None, source)))
    reader = Mock()
    monkeypatch.setattr(module, "ProfileStore", reader)
    result = await calculate_load_plan(
        object(),
        None,
        tmp_path / "profile.json",
        access(),
        options(),
        deadline=time.monotonic() + 5,
    )
    assert result.status == "unavailable" and not result.allocations
    reader.assert_not_called()


@pytest.mark.asyncio
async def test_planning_cancellation_keeps_two_slot_admission_until_work_stops(
    tmp_path, monkeypatch
):
    gate = asyncio.Event()
    started = asyncio.Event()

    async def calculate(*_args, **_kwargs):
        started.set()
        await gate.wait()
        from mcpserver.load_planning import plan_loads

        return plan_loads(
            forecast(), (), options(), now=START - 3600, deadline=time.monotonic() + 5
        )

    monkeypatch.setattr(tool_module, "calculate_load_plan", calculate)
    monkeypatch.setattr(tool_module, "_access", access)
    server = FastMCP("planning")
    pending = set()
    register_load_planning_tool(server, object(), None, tmp_path / "profile.json", pending=pending)
    tool = server._tool_manager.get_tool("loxone_plan_loads")
    first = asyncio.create_task(tool.fn(options()))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(tool.fn(options()))
    await asyncio.sleep(0)
    assert len(pending) == 2
    rejected = await tool.fn(options())
    assert not rejected.ok and rejected.data.error == "temporarily_unavailable"
    gate.set()
    assert (await second).ok
    await asyncio.sleep(0)
    assert not pending


def test_shared_operating_source_cannot_be_planned_as_independent_consumers():
    control = Control(TARGET, "Switch", "Switch", None, None, ACTION, ())
    selected = [
        {"binding_id": key, "load_flexibility": {"operating_binding_id": "shared"}}
        for key in ("a", "b")
    ]
    bindings = {
        "shared": {"control_uuid": TARGET, "state_uuid": "active", "role": "operating_state"}
    }
    with pytest.raises(ValueError, match="distinct"):
        module._operating_sources(selected, bindings, {TARGET: control})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [OSError("private path"), ProfileError("private path")])
async def test_storage_failure_is_a_sanitized_availability_result(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(tool_module, "calculate_load_plan", AsyncMock(side_effect=failure))
    monkeypatch.setattr(tool_module, "_access", access)
    server = FastMCP("planning-storage")
    register_load_planning_tool(server, object(), None, tmp_path / "profile.json")
    result = await server._tool_manager.get_tool("loxone_plan_loads").fn(options())
    assert not result.ok and result.data.error == "temporarily_unavailable"
    assert "private path" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_past_request_is_rejected_before_forecast_access(tmp_path, monkeypatch):
    reader = AsyncMock()
    monkeypatch.setattr(module, "read_pv_forecast", reader)
    request = options(start="2000-01-01T10:00:00Z", end="2000-01-01T16:00:00Z")
    with pytest.raises(ValueError, match="future"):
        await calculate_load_plan(
            object(),
            None,
            tmp_path / "profile.json",
            access(),
            request,
            deadline=time.monotonic() + 5,
        )
    reader.assert_not_awaited()
