from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from test_load_flexibility import flexibility

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment
from mcpserver.load_cycles import CycleEnergyInterval, describe_load_cycles
from mcpserver.retrospective_shift import ShiftLoad, _boundary, conditional_retrospective_shift

START = datetime(2026, 10, 12, tzinfo=UTC).timestamp()
END = START + 86400


def load(name="load", original_hour=1, **changes):
    flex = flexibility(
        **{
            "timezone": "UTC",
            "operating_binding_id": name + "-active",
            "cycle_identity": "user_confirmed_cycle",
            **changes,
        }
    )
    segments = (
        StateSegment(START, START + original_hour * 3600, False, 0),
        StateSegment(START + original_hour * 3600, START + (original_hour + 2) * 3600, True, 0),
        StateSegment(START + (original_hour + 2) * 3600, END, False, 0),
    )
    cycles = describe_load_cycles(
        segments,
        {START + original_hour * 3600: 1000.0, START + (original_hour + 1) * 3600: 500.0},
        flex,
        name,
        start=START,
        end=END,
        deadline=time.monotonic() + 5,
    )
    return ShiftLoad(name, flex, cycles, segments)


def analyze(loads=None, export=None):
    return conditional_retrospective_shift(
        loads if loads is not None else (load(),),
        export if export is not None else {START + 10 * 3600: 600.0, START + 11 * 3600: 800.0},
        start=START,
        end=END,
        deadline=time.monotonic() + 5,
    )


def test_owner_confirmed_complete_cycle_yields_only_explicitly_conditional_example():
    result = analyze()
    assert result.status == "partial"
    assert result.conditional_export_absorption_upper_bound_wh == 1100
    example = result.examples[0]
    assert example.admissibility == "not_proven" and example.native_lock_status == "not_checked"
    assert example.blocking_conditions == ["historical_native_lock_coverage_missing"]
    assert [h.energy_wh for h in example.hourly_absorption] == [600, 500]
    assert result.qualification == "conditional_only"


def test_all_loads_share_export_budget_and_ties_are_input_order_independent():
    first = analyze((load("b"), load("a")))
    second = analyze((load("a"), load("b")))
    assert first == second
    assert [e.binding_id for e in first.examples] == ["a", "b"]
    assert first.conditional_export_absorption_upper_bound_wh == 1400
    sums = {}
    for example in first.examples:
        for hour in example.hourly_absorption:
            sums[hour.start] = sums.get(hour.start, 0) + hour.energy_wh
    assert list(sums.values()) == [600, 800]


@pytest.mark.parametrize(
    "changes",
    [
        {"cycle_identity": "active_episode_only"},
        {"duration_seconds": 10800},
        {"energy_profile_origin": "user_declared", "declared_cycle_energy_wh": 1500.0},
    ],
)
def test_unqualified_cycle_identity_duration_or_declared_energy_never_invents_shape(changes):
    result = analyze((load(**changes),))
    assert not result.examples and result.excluded_cycles == 1


def test_missing_export_hour_and_other_day_do_not_qualify():
    assert not analyze(export={START + 10 * 3600: 600.0}).examples
    assert not analyze(
        (load(windows=[{"weekdays": [1], "start": "10:00", "end": "16:00"}]),)
    ).examples


def test_other_activity_capture_restart_or_unknown_gap_prevents_alternative():
    base = load()
    for bad in (
        (StateSegment(START + 10800, END, True, 0),),
        (
            StateSegment(START + 10800, START + 11 * 3600, False, 0),
            StateSegment(START + 11 * 3600, END, False, 1),
        ),
        (
            StateSegment(START + 10800, START + 10 * 3600, False, 0),
            StateSegment(START + 11 * 3600, END, False, 0),
        ),
    ):
        assert not analyze((replace(base, segments=base.segments[:2] + bad),)).examples


def test_completion_and_minimum_off_time_are_binding():
    assert not analyze((load(latest_completion="11:00"),)).examples
    base = load()
    # Candidate starts at 10:00 but inactive evidence begins at 09:30, not 09:00.
    assert not analyze(
        (replace(base, segments=(StateSegment(START + 9.5 * 3600, END, False, 0),)),)
    ).examples


def test_truncated_cycle_inventory_does_not_choose_from_partial_inventory():
    base = load()
    cycles = base.cycles.model_copy(update={"truncated": True})
    result = analyze((replace(base, cycles=cycles),))
    assert not result.examples
    assert "complete_cycle_inventory_output_budget_missing" in result.limitations


def test_dst_ambiguous_and_nonexistent_clock_boundaries_are_rejected():
    assert _boundary(date(2026, 3, 29), "02:30", 0, "Europe/Berlin") is None
    assert _boundary(date(2026, 10, 25), "02:30", 0, "Europe/Berlin") is None
    assert _boundary(date(2026, 10, 25), "03:30", 0, "Europe/Berlin") is not None


@pytest.mark.parametrize(
    "export",
    [
        {START + 36000: float("nan")},
        {START + 36000: -1.0},
        {START + 36000: 1.0, START + 36001: 1.0},
    ],
)
def test_invalid_or_overlapping_export_intervals_fail_closed(export):
    with pytest.raises(ValueError, match="export interval"):
        analyze(export=export)


def test_duplicate_load_associations_fail_closed_and_deadline_is_enforced():
    with pytest.raises(ValueError, match="duplicate"):
        analyze((load(), load()))
    with pytest.raises(HistoryAnalysisDeadline):
        conditional_retrospective_shift((load(),), {}, start=START, end=END, deadline=0)


def test_candidate_ranking_keeps_small_terms_beside_large_finite_energy():
    base = load()
    episode = base.cycles.episodes[0].model_copy(
        update={
            "energy_intervals": [
                CycleEnergyInterval(offset_seconds=0, energy_wh=1e100),
                CycleEnergyInterval(offset_seconds=3600, energy_wh=1.0),
            ],
            "observed_energy_wh": 1e100,
        }
    )
    base = replace(base, cycles=base.cycles.model_copy(update={"episodes": [episode]}))
    result = analyze(
        (base,),
        {
            START + 10 * 3600: 1e100,
            START + 11 * 3600: 1e-10,
            START + 12 * 3600: 1e100,
            START + 13 * 3600: 2e-10,
        },
    )
    assert result.examples[0].alternative_start == datetime.fromtimestamp(
        START + 12 * 3600, UTC
    ).isoformat().replace("+00:00", "Z")


def test_search_budget_exhaustion_publishes_no_greedily_selected_partial_search():
    end = START + 31 * 86400
    state = []
    energy = {}
    position = START
    for day in range(16):
        active = START + day * 86400 + 3600
        state.extend(
            (StateSegment(position, active, False, 0), StateSegment(active, active + 7200, True, 0))
        )
        energy[active], energy[active + 3600] = 1.0, 1.0
        position = active + 7200
    state.append(StateSegment(position, end, False, 0))
    loads = []
    for index in range(7):
        flex = flexibility(
            timezone="UTC",
            operating_binding_id=f"load-{index}-active",
            cycle_identity="user_confirmed_cycle",
            windows=[
                {"weekdays": list(range(7)), "start": "00:00", "end": "00:00", "end_day_offset": 1},
                {"weekdays": list(range(7)), "start": "23:00", "end": "23:00", "end_day_offset": 1},
            ],
            latest_completion="23:00",
            completion_day_offset=1,
        )
        cycles = describe_load_cycles(
            tuple(state),
            energy,
            flex,
            f"load-{index}",
            start=START,
            end=end,
            deadline=time.monotonic() + 10,
        )
        loads.append(ShiftLoad(f"load-{index}", flex, cycles, tuple(state)))
    result = conditional_retrospective_shift(
        tuple(loads),
        {START + hour * 3600: 1.0 for hour in range(744)},
        start=START,
        end=end,
        deadline=time.monotonic() + 10,
    )
    assert result.evaluated_alternatives == 4096 and not result.examples
    assert "alternative_search_budget_exceeded_no_partial_allocation" in result.limitations


@pytest.mark.parametrize("hour", [0, 22])
def test_zero_off_time_allows_complete_alternative_at_request_start_or_end(hour):
    base = load(
        original_hour=3,
        minimum_off_seconds=0,
        windows=[{"weekdays": [0], "start": "00:00", "end": "00:00", "end_day_offset": 1}],
        latest_completion="00:00",
        completion_day_offset=1,
    )
    result = analyze((base,), {START + hour * 3600: 600.0, START + (hour + 1) * 3600: 800.0})
    assert len(result.examples) == 1
    assert result.examples[0].conditional_export_absorption_upper_bound_wh == 1100
