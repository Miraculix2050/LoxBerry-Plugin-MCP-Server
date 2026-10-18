from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from test_analysis_context import LOAD, METER, PV, context_document, controls
from test_load_planning import forecast, options
from test_native_efm import SERIAL, access

import mcpserver.context_planning as module
from mcpserver.analysis_context import EnergyAnalysisContext
from mcpserver.context_planning import calculate_context_plan, combine_forecasts
from mcpserver.load_planning import LoadPlanningOptions
from mcpserver.loxone.models import Freshness, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import ControlOperationError, RuntimeSnapshot


def context_options(doc=None, **changes):
    return LoadPlanningOptions.model_validate(
        {
            **options().model_dump(exclude={"forecast_control_uuid", "consumer_binding_ids"}),
            "analysis_context": context_document() if doc is None else doc,
            **changes,
        }
    )


def test_legacy_contract_and_exclusive_new_mode():
    assert options().analysis_context is None
    assert context_options().forecast_control_uuid is None
    with pytest.raises(ValidationError):
        context_options(forecast_control_uuid=PV)
    with pytest.raises(ValidationError):
        context_options(consumer_binding_ids=["legacy"])


def test_forecasts_only_sum_common_complete_intervals_and_do_not_fill_gaps():
    first = forecast()
    second = first.model_copy(deep=True)
    second.hours = second.hours[1:]
    result = combine_forecasts([first, second])
    assert len(result.hours) == len(second.hours)
    assert result.hours[0].energy_wh == 2 * second.hours[0].energy_wh
    second.status = "not_ready"
    assert combine_forecasts([first, second]).status == "incomplete"
    assert not combine_forecasts([first, second]).hours
    assert first.hours


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["real", "hypothetical"])
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("source_count", [1, 2])
async def test_profileless_plan_authorization_publication_and_zero_history(
    monkeypatch, kind, changed, locked, source_count
):
    doc = context_document()
    doc["loads"][0]["kind"] = kind
    if kind == "hypothetical":
        del doc["loads"][0]["control_uuid"]
        doc["loads"][0]["cycle"]["origin"] = "scenario_assumption"
    visible = controls()
    visible[PV] = replace(visible[LOAD], uuid=PV, control_type="PvProductionForecast")
    second_uuid = "00000000-0000-0000-0000000000000008"
    if source_count == 2:
        visible[second_uuid] = replace(visible[PV], uuid=second_uuid)
        doc["assets"].append(
            {"asset_id": "shed", "description": "Shed", "association_origin": "user_confirmed"}
        )
        doc["forecasts"].append(
            {
                "control_uuid": second_uuid,
                "asset_ids": ["shed"],
                "coverage_origin": "user_confirmed",
            }
        )
    visible[LOAD] = replace(visible[LOAD], state_uuids=(("lockedOn", "lock-state"),))
    initial = LoxoneStructure(
        LoxoneIdentity("reader", SERIAL), "current", (), (), tuple(visible.values())
    )
    altered = replace(initial, controls=tuple(c for c in initial.controls if c.uuid != METER))
    count = 0

    @asynccontextmanager
    async def snapshots(_access):
        nonlocal count
        count += 1
        yield RuntimeSnapshot("family", altered if changed and count > 1 else initial, True)

    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin="http://synthetic.local"),
        snapshot_context=snapshots,
        cache=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(value=int(locked), freshness=Freshness.CURRENT))
        ),
    )
    f = forecast()
    f.prediction_at = int(time.time())
    batch = [(visible[PV], initial, f)]
    if source_count == 2:
        batch.append(
            (visible[second_uuid], initial, f.model_copy(update={"control_uuid": second_uuid}))
        )
    source = AsyncMock(return_value=batch)
    monkeypatch.setattr(module, "read_pv_forecasts", source)
    reader = Mock(side_effect=AssertionError("no profile access for request-local loads"))
    monkeypatch.setattr(module, "ProfileStore", reader)
    history = AsyncMock(side_effect=AssertionError("no history for declared models"))
    monkeypatch.setattr(module, "_observed_profiles", history)
    if changed:
        with pytest.raises((ValueError, ControlOperationError)):
            await calculate_context_plan(
                runtime, None, None, access(), context_options(doc), deadline=time.monotonic() + 5
            )
    else:
        result = await calculate_context_plan(
            runtime, None, None, access(), context_options(doc), deadline=time.monotonic() + 5
        )
        assert result.method_version == "conditional_context_planning.v1"
        assert len(result.forecasts) == source_count
        assert bool(result.allocations) == (kind == "hypothetical" or not locked)
        if result.allocations:
            assert result.allocations[0].load_kind == kind
            assert result.allocations[0].load_id == "pump"
        assert result.profile_revision is None
    reader.assert_not_called()
    history.assert_not_called()
    source.assert_awaited_once()
    assert count == 2


def test_four_source_limit_and_unknown_common_supply_are_rejected():
    doc = context_document()
    for n in range(1, 5):
        doc["assets"].append(
            {"asset_id": f"asset{n}", "description": "PV", "association_origin": "user_confirmed"}
        )
        doc["forecasts"].append(
            {
                "control_uuid": f"00000000-0000-0000-0000-{n + 4:012x}",
                "asset_ids": [f"asset{n}"],
                "coverage_origin": "user_confirmed",
            }
        )
    with pytest.raises(ValidationError):
        context_options(doc)
    doc["assets"].pop()
    doc["forecasts"].pop()
    doc["scope"]["common_supply_origin"] = "scenario_assumption"
    with pytest.raises(ValidationError, match="confirmation"):
        context_options(doc)


def test_distinct_real_sources_cannot_share_an_energy_contribution():
    doc = context_document()
    doc["loads"][0]["control_uuid"] = METER
    value = EnergyAnalysisContext.model_validate(doc)
    with pytest.raises(ValueError, match="duplicate"):
        module.resolve_membership(value, controls(), {"pump": METER})


def test_maximum_load_and_window_context_is_bounded_without_changing_legacy():
    assert options().consumer_binding_ids == ["a"]
    doc = context_document()
    doc["loads"] = []
    for n in range(16):
        load = context_document()["loads"][0]
        load.update(load_id=f"scenario{n}", kind="hypothetical")
        del load["control_uuid"]
        load["cycle"]["origin"] = "scenario_assumption"
        load["cycle"]["rationale"] = chr(0x1F600) * 256
        load["cycle"]["windows"] *= 16
        doc["loads"].append(load)
    doc["assets"] = [
        {
            "asset_id": f"asset{n}",
            "description": chr(0x1F600) * 256,
            "association_origin": "user_confirmed",
        }
        for n in range(16)
    ]
    doc["forecasts"][0]["asset_ids"] = [f"asset{n}" for n in range(16)]
    doc["scope"]["description"] = chr(0x1F600) * 256
    value = context_options(doc)
    assert len(value.model_dump_json().encode()) <= 65_536
    doc["loads"].append(doc["loads"][0])
    with pytest.raises(ValidationError):
        context_options(doc)
