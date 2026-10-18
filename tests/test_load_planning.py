from __future__ import annotations

import time
from datetime import datetime

import pytest
from pydantic import ValidationError
from test_load_flexibility import flexibility

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.load_planning import LoadPlanningOptions, PlanningLoad, plan_loads
from mcpserver.loxone.pv_forecast_hours import PvForecastHour, PvForecastResult

START = int(datetime.fromisoformat("2026-10-19T10:00:00+02:00").timestamp())


def options(**changes):
    return LoadPlanningOptions.model_validate(
        {
            "forecast_control_uuid": "00000000-0000-0000-0000000000000001",
            "start": "2026-10-19T10:00:00+02:00",
            "end": "2026-10-19T16:00:00+02:00",
            "timezone": "Europe/Berlin",
            "consumer_binding_ids": ["a"],
            "baseload": {"origin": "user_estimate", "constant_w": 0.0},
            "storage_reserve": {"origin": "user_confirmed", "constant_w": 0.0},
            **changes,
        }
    )


def forecast(values=(1000, 1000, 1000, 1000, 0, 0)):
    return PvForecastResult(
        status="available",
        control_uuid=options().forecast_control_uuid,
        retrieved_at="2026-10-18T10:00:00Z",
        prediction_at=START - 3600,
        hours=[
            PvForecastHour(start=START + i * 3600, end=START + (i + 1) * 3600, energy_wh=v)
            for i, v in enumerate(values)
        ],
    )


def load(binding="a", **changes):
    return PlanningLoad(
        binding,
        flexibility(cycle_identity="user_confirmed_cycle", **changes),
        ((3600, 1000.0), (3600, 1000.0)),
        "observed_intervals",
    )


def calculate(loads=None, opts=None, source=None, deadline=None):
    return plan_loads(
        source or forecast(),
        loads or (load(),),
        opts or options(),
        now=START - 3600,
        deadline=deadline if deadline is not None else time.monotonic() + 5,
    )


def test_shared_budget_moves_second_load_without_double_allocation():
    result = calculate((load("a"), load("b")), options(consumer_binding_ids=["a", "b"]))
    assert [a.start for a in result.allocations] == [START, START + 7200]
    assert sum(a.conditional_pv_wh for a in result.allocations) == 4000
    assert all(a.additional_grid_wh == 0 and a.conditions for a in result.allocations)


def test_explicit_baseload_and_storage_are_subtracted_first():
    opts = options(
        baseload={"origin": "user_estimate", "constant_w": 200.0},
        storage_reserve={"origin": "user_confirmed", "constant_w": 300.0},
    )
    allocation = calculate(opts=opts).allocations[0]
    assert allocation.conditional_pv_wh == allocation.additional_grid_wh == 1000


def test_equal_pv_uses_the_actual_load_completion_deadline():
    result = calculate(
        (load("a"), load("b", latest_completion="13:00")),
        options(consumer_binding_ids=["a", "b"]),
    )
    assert result.allocations[0].binding_id == "b"


def test_known_lock_excluded_and_missing_hours_not_filled():
    from dataclasses import replace

    assert not calculate((replace(load(), native_locked=True),)).allocations
    source = forecast((1000, 1000))
    source.hours.pop()
    assert not calculate(source=source).allocations


def test_unknown_current_lock_is_an_explicit_condition():
    from dataclasses import replace

    unresolved = calculate((replace(load(), native_locked=None),)).allocations[0]
    cleared = calculate((replace(load(), native_locked=False),)).allocations[0]
    assert "native_current_lock_unresolved" in unresolved.conditions
    assert "native_current_lock_unresolved" not in cleared.conditions


def test_finite_high_energy_does_not_overflow_during_proration():
    import math
    from dataclasses import replace

    value = replace(load(), profile=((3600, 1e308), (3600, 0.0)))
    allocation = calculate((value,)).allocations[0]
    assert allocation.cycle_energy_wh == 1e308
    assert math.isfinite(allocation.additional_grid_wh)
    invalid = replace(value, profile=((3600, 1e308), (3600, 1e308)))
    assert not calculate((invalid,)).allocations


def test_source_unavailable_does_not_generate_schedule():
    source = forecast()
    source.status = "not_ready"
    result = calculate(source=source)
    assert result.status == "unavailable" and not result.allocations


def test_past_only_source_hours_do_not_establish_future_planning_availability():
    source = forecast()
    source.hours = [PvForecastHour(start=START - 3600, end=START, energy_wh=1000)]
    result = calculate(source=source)
    assert result.status == "unavailable"
    assert "requested_future_forecast_hours_unavailable" in result.limitations


def test_missing_hourly_scenario_and_full_cycle_are_required():
    opts = options(
        baseload={"origin": "user_estimate", "hours": [{"start": START, "power_w": 0.0}]}
    )
    assert not calculate(opts=opts).allocations


def test_deadline_and_past_interval_are_rejected():
    with pytest.raises(HistoryAnalysisDeadline):
        calculate(deadline=0)
    with pytest.raises(ValueError, match="future"):
        plan_loads(forecast(), (load(),), options(), now=START + 1, deadline=time.monotonic() + 5)


@pytest.mark.parametrize(
    "changes",
    [
        {"consumer_binding_ids": ["a", "a"]},
        {"consumer_binding_ids": []},
        {"storage_reserve": {"origin": "user_estimate"}},
        {"start": "2026-10-19T10:00:00"},
        {"end": "2026-10-23T10:00:00+02:00"},
        {"baseload": {"origin": "user_estimate", "constant_w": float("nan")}},
    ],
)
def test_invalid_models(changes):
    with pytest.raises(ValidationError):
        options(**changes)


def test_hourly_budget_requires_no_positive_surplus_claim_for_negative_residual():
    opts = options(storage_reserve={"origin": "user_confirmed", "constant_w": 2000.0})
    assert calculate(opts=opts).status == "no_matching_windows"
