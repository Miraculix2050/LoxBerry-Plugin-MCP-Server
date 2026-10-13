from __future__ import annotations

import time
from dataclasses import replace

import pytest
from test_load_flexibility import flexibility

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment, reconstruct_segments
from mcpserver.load_cycles import describe_load_cycles


def segments():
    return (
        StateSegment(0, 3600, False, 0),
        StateSegment(3600, 10800, True, 0),
        StateSegment(10800, 14400, False, 0),
    )


def describe(state=None, energy=None, **options):
    return describe_load_cycles(
        state if state is not None else segments(),
        energy if energy is not None else {3600: 1000.0, 7200: 500.0},
        flexibility(),
        "load",
        start=0,
        end=14400,
        deadline=time.monotonic() + 10,
        **options,
    )


def test_complete_activity_edges_and_energy_do_not_claim_native_program_identity_or_locks():
    result = describe()
    assert result.status == "partial" and result.episode_count == 1
    episode = result.episodes[0]
    assert episode.boundaries_complete and episode.energy_profile_complete
    assert episode.observed_energy_wh == 1500
    assert [i.energy_wh for i in episode.energy_intervals] == [1000, 500]
    assert episode.cycle_identity == "active_episode_only"
    assert "complete_program_cycle_identity_not_confirmed" in episode.limitations
    assert result.native_lock_status == "not_checked" and result.planning_status == "not_evaluated"


@pytest.mark.parametrize(
    "state",
    [
        segments()[1:],
        segments()[:2],
        tuple(replace(s, capture_index=None) for s in segments()),
        (segments()[0], segments()[1], replace(segments()[2], capture_index=1)),
        (replace(segments()[0], end=3500), segments()[1], segments()[2]),
        (segments()[0], segments()[1], replace(segments()[2], start=10900)),
    ],
)
def test_missing_edges_capture_restart_or_gap_remain_incomplete_episodes(state):
    result = describe(state)
    episode = result.episodes[0]
    assert not episode.boundaries_complete and not episode.energy_profile_complete
    assert episode.observed_energy_wh is None
    assert "both_edges_in_one_continuous_capture_not_proven" in episode.limitations


def test_repeated_true_values_merge_only_inside_one_capture():
    state = (
        segments()[0],
        StateSegment(3600, 7200, True, 0),
        StateSegment(7200, 10800, True, 0),
        segments()[2],
    )
    assert describe(state).episode_count == 1
    changed = (*state[:2], replace(state[2], capture_index=1), replace(state[3], capture_index=1))
    result = describe(changed)
    assert result.episode_count == 2
    assert all(not e.boundaries_complete for e in result.episodes)


@pytest.mark.parametrize("energy", [{}, {3600: 1000.0}, {3601: 1000.0, 7201: 500.0}])
def test_missing_or_offset_hours_never_become_interpolated_cycle_energy(energy):
    episode = describe(energy=energy).episodes[0]
    assert episode.boundaries_complete and not episode.energy_profile_complete
    assert episode.observed_energy_wh is None and episode.energy_intervals == []


def test_fractional_cycle_does_not_allocate_fractional_hour_energy():
    state = (segments()[0], replace(segments()[1], end=10000), replace(segments()[2], start=10000))
    episode = describe(state).episodes[0]
    assert episode.boundaries_complete and not episode.energy_profile_complete
    assert "observed_duration_differs_from_declared_duration" in episode.constraint_discrepancies


def test_overflow_stays_json_finite_with_explicit_limitation():
    episode = describe(energy={3600: 1e308, 7200: 1e308}).episodes[0]
    assert episode.observed_energy_wh is None and not episode.energy_profile_complete
    assert "derived_numeric_overflow" in episode.limitations


def test_input_deadline_and_overlap_are_enforced():
    with pytest.raises(HistoryAnalysisDeadline):
        describe_load_cycles(
            segments(), {}, flexibility(), "load", start=0, end=14400, deadline=time.monotonic() - 1
        )
    with pytest.raises(ValueError, match="overlapping"):
        describe((segments()[0], replace(segments()[1], start=3000), segments()[2]))


def test_reconstruction_retains_capture_provenance_without_merging_adjacent_restarts():
    state = reconstruct_segments(
        ((0, 7200, False, ((3600, True),)), (7200, 14400, True, ((10800, False),))),
        start=0,
        end=14400,
    )
    assert [s.capture_index for s in state] == [0, 0, 1, 1]
    result = describe(state)
    assert result.episode_count == 2 and all(not e.boundaries_complete for e in result.episodes)


def test_episode_output_bound_preserves_count_and_truncation():
    state = tuple(StateSegment(i * 3600, (i + 1) * 3600, bool(i % 2), 0) for i in range(40))
    result = describe_load_cycles(
        state, {}, flexibility(), "load", start=0, end=40 * 3600, deadline=time.monotonic() + 10
    )
    assert result.episode_count == 20 and len(result.episodes) == 16 and result.truncated


def test_energy_output_budget_does_not_publish_a_partial_cycle_profile():
    state = tuple(
        segment
        for i in range(6)
        for segment in (
            StateSegment(i * 26 * 3600, (i * 26 + 1) * 3600, False, i),
            StateSegment((i * 26 + 1) * 3600, (i * 26 + 25) * 3600, True, i),
            StateSegment((i * 26 + 25) * 3600, (i * 26 + 26) * 3600, False, i),
        )
    )
    hours = {(i * 26 + 1 + h) * 3600: 100.0 for i in range(6) for h in range(24)}
    result = describe_load_cycles(
        state,
        hours,
        flexibility(),
        "load",
        start=0,
        end=6 * 26 * 3600,
        deadline=time.monotonic() + 10,
    )
    assert len(result.episodes) == 6 and not result.truncated
    assert result.energy_intervals_truncated
    assert sum(len(e.energy_intervals) for e in result.episodes) == 120
    assert not result.episodes[-1].energy_profile_complete
    assert result.episodes[-1].observed_energy_wh is None
    assert "energy_profile_output_budget_exceeded" in result.episodes[-1].limitations


def test_declared_cycle_energy_does_not_create_observed_energy_without_intervals():
    result = describe_load_cycles(
        segments(),
        {},
        flexibility(energy_profile_origin="user_declared", declared_cycle_energy_wh=999.0),
        "load",
        start=0,
        end=14400,
        deadline=time.monotonic() + 10,
    )
    assert result.energy_profile_origin == "user_declared"
    assert result.episodes[0].declared_cycle_energy_wh == 999
    assert result.episodes[0].observed_energy_wh is None
    assert not result.episodes[0].energy_profile_complete
