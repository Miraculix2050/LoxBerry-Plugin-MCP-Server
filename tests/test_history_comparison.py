import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment, statistic_summary
from mcpserver.history_comparison import ComparisonInput, compare_history
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint


def energy(
    values, *, role=None, boundary=None, start=0, end=10_800, meaning="interval_difference_sum"
):
    semantics = SeriesSemantics(
        "partial",
        meaning,
        unit="Wh",
        measurement_quantity="energy",
        timestamp_basis="unix_utc",
        timestamp_position="interval_start"
        if meaning == "interval_difference_sum"
        else "observation",
    )
    points = tuple(StatisticPoint(t, v) for t, v in values)
    summary = statistic_summary(
        "energy", semantics, points, start=start, end=end, control_uuid="c", source_id="s"
    )
    summary.binding_id = role
    return ComparisonInput(
        summary, semantics, points, profile_role=role, declared_boundary=boundary
    )


def compare(operation, inputs, *, start=0, end=10_800, confirmed=False, night_start=0, night_end=5):
    return compare_history(
        operation,
        tuple(inputs),
        start=start,
        end=end,
        timezone_name="Europe/Berlin",
        comparable_boundaries_confirmed=confirmed,
        night_start_hour=night_start,
        night_end_hour=night_end,
        deadline=time.monotonic() + 10,
    )


def test_pv_overlap_is_upper_bound_and_not_attribution():
    production = energy([(0, 1000), (3600, 0), (7200, 500)], role="production")
    load = energy([(0, 500), (3600, 200), (7200, 200)], role="house_consumption")
    result = compare("pv_load_overlap", [production, load])
    assert result.status == "partial"
    assert result.metrics["coincident_energy_upper_bound"] == 700
    assert result.metrics["positive_production_and_load_seconds"] == 7200
    assert result.metrics["exact_solar_attribution_fraction"] is None
    assert "upper_bound_is_not_measured_self_consumption" in result.limitations


def test_zero_generation_denominator_is_undefined():
    result = compare(
        "pv_load_overlap", [energy([(0, 0)], role="production"), energy([(0, 10)], role="consumer")]
    )
    assert result.metrics["production_denominator"] == 0
    assert result.metrics["exact_solar_attribution_fraction"] is None
    assert "no_generation_denominator_attribution_undefined" in result.limitations


def test_unmatched_and_partial_hours_are_never_divided():
    pv = energy([(0, 100), (3600, 200), (7200, 300)], role="production")
    load = energy([(0, 50), (7200, 70)], role="consumer")
    result = compare("pv_load_overlap", [pv, load], start=100, end=10_800)
    assert result.metrics["production_energy"] == 300
    assert result.metrics["load_energy"] == 70
    assert result.metrics["aligned_seconds"] == 3600


def test_counter_totals_cannot_be_allocated_to_pv_overlap():
    pv = energy([(0, 10), (500, 20)], role="production", meaning="cumulative_counter")
    load = energy([(0, 10)], role="consumer")
    assert compare("pv_load_overlap", [pv, load]).status == "insufficient_evidence"


def test_ranking_requires_confirmation_boundaries_and_identical_windows():
    first = energy(
        [(0, 10), (500, 12)], role="consumer", boundary="pump", meaning="cumulative_counter"
    )
    second = energy(
        [(0, 10), (500, 15)], role="consumer", boundary="heater", meaning="cumulative_counter"
    )
    second.summary.binding_id = "heater"
    first.summary.binding_id = "pump"
    assert compare("consumer_ranking", [first, second]).status == "insufficient_evidence"
    result = compare("consumer_ranking", [first, second], confirmed=True)
    assert result.status == "partial"
    assert result.items == [
        {"binding_id": "heater", "energy": 5},
        {"binding_id": "pump", "energy": 2},
    ]
    assert "total" not in result.metrics
    assert (
        compare(
            "consumer_ranking", [first, replace(second, declared_boundary="pump")], confirmed=True
        ).status
        == "insufficient_evidence"
    )
    second.summary.usable_intervals = []
    assert (
        compare("consumer_ranking", [first, second], confirmed=True).status
        == "insufficient_evidence"
    )


def state(segments):
    from mcpserver.history_analysis import duration_summary

    segments = tuple(segments)
    summary = duration_summary(
        segments, start=0, end=10_800, control_uuid="state", source_id="active"
    )
    return ComparisonInput(summary, segments=segments)


def test_ranking_uses_complete_interval_evidence_beyond_metadata_cap():
    values = [(i * 3600, 10) for i in range(150)]
    first = energy(values, role="consumer", boundary="first", end=151 * 3600)
    second = energy(values, role="consumer", boundary="second", end=151 * 3600)
    first.summary.binding_id, second.summary.binding_id = "first", "second"
    assert first.summary.usable_intervals_truncated
    result = compare("consumer_ranking", [first, second], confirmed=True, end=151 * 3600)
    assert result.status == "partial" and result.usable_intervals_truncated
    assert len(result.usable_intervals) == 128
    assert result.items[0]["energy"] == 1500
    changed = replace(second, points=second.points[:-1])
    assert (
        compare("consumer_ranking", [first, changed], confirmed=True, end=151 * 3600).status
        == "insufficient_evidence"
    )


def test_mixed_pv_load_enable_signal_uses_only_whole_active_hours():
    pv = energy([(0, 100), (3600, 200), (7200, 300)], role="production")
    load = energy([(0, 50), (3600, 50), (7200, 50)], role="consumer")
    enabled = state([StateSegment(100, 7200, True)])
    result = compare("pv_load_overlap", [pv, load, enabled])
    assert result.metrics["production_energy"] == 200
    assert result.metrics["load_energy"] == 50
    assert result.metrics["aligned_seconds"] == 3600
    assert compare("pv_load_overlap", [pv, load, state([])]).status == "insufficient_evidence"


def test_operating_energy_never_uses_unknown_or_partial_state_windows():
    values = energy([(0, 10), (3600, 20), (7200, 30)])
    enabled = state([StateSegment(100, 7200, True), StateSegment(7200, 10_800, False)])
    result = compare("operating_phases", [values, enabled])
    assert result.metrics["energy_in_complete_active_intervals_Wh"] == 20
    assert result.metrics["active_seconds"] == 7100
    assert "state_duration_is_not_measured_energy" in result.limitations


def test_operating_temperature_is_sample_mean_with_exclusive_state_endpoint():
    semantics = SeriesSemantics(
        "partial",
        "sample",
        unit="°C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    points = tuple(StatisticPoint(t, v) for t, v in [(2, 10), (4, 100), (7, 30)])
    summary = statistic_summary(
        "temperature_summary", semantics, points, start=0, end=10, control_uuid="c", source_id="s"
    )
    values = ComparisonInput(summary, semantics, points)
    enabled = state([StateSegment(0, 4, True), StateSegment(6, 10, True)])
    result = compare("operating_phases", [values, enabled], end=10)
    assert result.metrics["temperature_active_sample_mean"] == 20
    assert result.metrics["temperature_sample_count"] == 2
    assert result.metric_units["temperature_active_sample_mean"] == "°C"


@pytest.mark.parametrize(
    "start,end,hours",
    [
        ("2026-03-28T23:00:00", "2026-03-29T03:00:00", 4),
        ("2026-10-24T22:00:00", "2026-10-25T04:00:00", 6),
    ],
)
def test_baseload_weights_real_dst_hours_and_labels_daily_estimate(start, end, hours):
    begin = datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp()
    finish = datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()
    values = energy([(begin + i * 3600, 100) for i in range(hours)], start=begin, end=finish)
    result = compare("baseload", [values], start=begin, end=finish)
    assert result.metrics["nighttime_median_power"] == 100
    assert result.metrics["usable_night_seconds"] == hours * 3600
    assert result.metrics["estimated_24_hour_energy_Wh"] == 2400
    assert result.status == "partial"
    assert "24_hour_extrapolation_is_an_estimate" in result.limitations


def test_ambiguous_custom_night_boundary_rejected():
    begin = datetime(2026, 10, 24, 22, tzinfo=UTC).timestamp()
    with pytest.raises(ValueError, match="ambiguous"):
        compare(
            "baseload",
            [energy([(begin, 100)], start=begin, end=begin + 6 * 3600)],
            start=begin,
            end=begin + 6 * 3600,
            night_start=2,
            night_end=3,
        )


def test_exclusive_end_midnight_does_not_validate_following_dst_day():
    begin = datetime(2026, 10, 23, 22, tzinfo=UTC).timestamp()
    finish = begin + 24 * 3600
    values = energy([(begin + 2 * 3600, 100)], start=begin, end=finish)
    result = compare("baseload", [values], start=begin, end=finish, night_start=2, night_end=3)
    assert result.metrics["nighttime_median_power"] == 100
    assert result.metrics["usable_night_seconds"] == 3600


def test_operating_temperature_preserves_duplicate_sample_rejection():
    semantics = SeriesSemantics(
        "partial",
        "sample",
        unit="C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    points = (StatisticPoint(2, 10), StatisticPoint(2, 100))
    summary = statistic_summary(
        "temperature_summary",
        semantics,
        points,
        start=0,
        end=10,
        control_uuid="c",
        source_id="s",
    )
    assert summary.status == "insufficient_evidence"
    result = compare(
        "operating_phases",
        [ComparisonInput(summary, semantics, points), state([StateSegment(0, 10, True)])],
        end=10,
    )
    assert result.status == "insufficient_evidence"
    assert "temperature_active_sample_mean" not in result.metrics


def test_deadline_and_unverified_power_samples_are_not_estimates():
    source = energy([(0, 100)])
    source = replace(
        source,
        semantics=replace(source.semantics, measurement_quantity="power", value_meaning="sample"),
    )
    assert compare("baseload", [source]).status == "insufficient_evidence"
    with pytest.raises(HistoryAnalysisDeadline):
        compare_history(
            "baseload",
            (source,),
            start=0,
            end=10_800,
            timezone_name="Europe/Berlin",
            comparable_boundaries_confirmed=False,
            night_start_hour=0,
            night_end_hour=5,
            deadline=0,
        )
