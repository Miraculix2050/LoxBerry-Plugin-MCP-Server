from dataclasses import replace

import pytest

from mcpserver.history_analysis import (
    StateSegment,
    duration_summary,
    reconstruct_segments,
    statistic_summary,
)
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint


def summary(operation, semantics, values, start=0, end=10_000):
    return statistic_summary(
        operation,
        semantics,
        tuple(StatisticPoint(t, v) for t, v in values),
        start=start,
        end=end,
        control_uuid="control",
        source_id="series",
    )


def test_temperature_sample_mean_does_not_claim_time_weighting():
    semantic = SeriesSemantics(
        "partial",
        "sample",
        unit="°C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    result = summary("temperature_summary", semantic, [(0, 10), (2, 20), (900, 30), (10000, 500)])
    assert result.metrics == {"sample_count": 3, "mean": 20, "minimum": 10, "maximum": 30}
    assert result.status == "partial"
    assert "sample_mean_is_not_time_weighted" in result.limitations
    assert result.usable_intervals == []


@pytest.mark.parametrize("values", [[(0, 8), (1, 7), (2, 10)], [(0, 8)], [(0, 8), (0, 9)]])
def test_counter_reset_or_insufficient_observations_cannot_be_reported_as_energy(values):
    semantic = SeriesSemantics(
        "partial",
        "cumulative_counter",
        unit="kWh",
        measurement_quantity="energy",
        timestamp_basis="unix_utc",
    )
    result = summary("energy", semantic, values)
    assert result.status == "insufficient_evidence" and "energy" not in result.metrics


def test_counter_difference_applies_only_between_observations():
    semantic = SeriesSemantics(
        "partial",
        "cumulative_counter",
        unit="kWh",
        measurement_quantity="energy",
        timestamp_basis="unix_utc",
    )
    result = summary("energy", semantic, [(100, 8), (500, 10)])
    assert result.metrics["energy"] == 2
    assert result.usable_intervals[0].start.endswith("00:01:40Z")
    assert result.status == "partial"


def test_hourly_energy_never_proportionally_allocates_partial_records():
    semantic = SeriesSemantics(
        "partial",
        "interval_difference_sum",
        unit="Wh",
        measurement_quantity="energy",
        timestamp_basis="unix_utc",
        timestamp_position="interval_start",
    )
    result = summary("energy", semantic, [(0, 2), (3600, 3), (7200, 4)], start=100, end=8000)
    assert result.metrics["energy"] == 3
    assert result.metrics["interval_count"] == 1
    overlapping = summary("energy", semantic, [(0, 2), (20, 3)], end=5000)
    assert overlapping.status == "insufficient_evidence"


@pytest.mark.parametrize(
    "change",
    [
        dict(unit=None),
        dict(timestamp_basis=None),
        dict(timestamp_basis="local_miniserver_seconds_since_2009"),
    ],
)
def test_unverified_unit_or_time_blocks_numerical_claim(change):
    semantic = SeriesSemantics(
        "partial",
        "sample",
        unit="°C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    assert (
        summary("temperature_summary", replace(semantic, **change), [(0, 20)]).status
        == "insufficient_evidence"
    )


def test_event_gaps_missing_baseline_and_invalid_values_remain_unknown():
    phases = ((0, 4, True, ((2, None), (3, False))), (6, 10, None, ((8, True),)))
    segments = reconstruct_segments(phases, start=0, end=10)
    assert segments == (
        StateSegment(0, 2, True),
        StateSegment(3, 4, False),
        StateSegment(8, 10, True),
    )
    result = duration_summary(segments, start=0, end=10, control_uuid="control", source_id="state")
    assert result.metrics == {"active_seconds": 4, "inactive_seconds": 1, "unknown_seconds": 5}
    assert result.status == "partial"


def test_no_events_with_known_phase_baseline_is_duration_but_without_it_is_unknown():
    known = reconstruct_segments(((0, 10, False, ()),), start=0, end=10)
    assert (
        duration_summary(known, start=0, end=10, control_uuid="control", source_id="state").status
        == "supported"
    )
    missing = duration_summary((), start=0, end=10, control_uuid="control", source_id="state")
    assert missing.status == "insufficient_evidence" and missing.metrics["inactive_seconds"] is None


def test_overlapping_capture_phases_are_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        reconstruct_segments(((0, 5, True, ()), (3, 8, False, ())), start=0, end=10)


@pytest.mark.parametrize(
    ("operation", "meaning", "quantity", "position", "values"),
    [
        ("temperature_summary", "sample", "temperature", "observation", [(0, 1e308), (1, 1e308)]),
        ("energy", "cumulative_counter", "energy", "observation", [(0, -1e308), (1, 1e308)]),
        (
            "energy",
            "interval_difference_sum",
            "energy",
            "interval_start",
            [(0, 1e308), (3600, 1e308)],
        ),
    ],
)
def test_finite_extreme_inputs_never_produce_null_or_infinite_numeric_claim(
    operation, meaning, quantity, position, values
):
    semantic = SeriesSemantics(
        "partial",
        meaning,
        unit="kWh",
        measurement_quantity=quantity,
        timestamp_basis="unix_utc",
        timestamp_position=position,
    )
    result = summary(operation, semantic, values)
    assert result.status == "insufficient_evidence" and result.metrics == {}
    assert result.limitations == ["derived_numeric_overflow"]
