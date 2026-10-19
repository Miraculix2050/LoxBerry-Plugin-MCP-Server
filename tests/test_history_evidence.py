"""Time boundaries and source evidence are independent of names and samples."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from mcpserver.loxone.history_evidence import (
    capture_evidence,
    legacy_local_timestamp,
    local_day_window,
    statistic_evidence,
)
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint


@pytest.mark.parametrize(("day", "hours"), [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_local_calendar_days_follow_dst(day, hours):
    from datetime import timedelta

    start, end = local_day_window(day, day + timedelta(days=1), "Europe/Berlin")
    assert end - start == hours * 3600


@pytest.mark.parametrize("wall", [datetime(2026, 3, 29, 2, 30), datetime(2026, 10, 25, 2, 30)])
def test_legacy_fold_or_gap_is_not_guessed(wall):
    seconds = int((wall - datetime(2009, 1, 1)).total_seconds())
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        legacy_local_timestamp(seconds, "Europe/Berlin")


def test_explicit_legacy_timezone_converts_normal_observation():
    wall = datetime(2026, 1, 4, 12)
    seconds = int((wall - datetime(2009, 1, 1)).total_seconds())
    assert (
        legacy_local_timestamp(seconds, "Europe/Berlin")
        == datetime(2026, 1, 4, 11, tzinfo=UTC).timestamp()
    )


def test_invalid_or_skipped_local_calendar_boundaries():
    with pytest.raises(ValueError):
        local_day_window(date(2026, 1, 1), date(2026, 2, 2), "Europe/Berlin")
    with pytest.raises(ValueError):
        local_day_window(date(2026, 1, 1), date(2026, 1, 2), "not-a-zone")
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        local_day_window(date(2011, 12, 30), date(2011, 12, 31), "Pacific/Apia")


def test_samples_never_become_continuous_coverage():
    semantics = SeriesSemantics(
        interpretation_status="partial", timestamp_basis="unix_utc", value_meaning="sample"
    )
    evidence = statistic_evidence(
        (StatisticPoint(100, 1), StatisticPoint(300, 2)), semantics, has_more=True
    )
    assert evidence.intervals == []
    assert evidence.point_count == 2
    assert evidence.first_point_at != evidence.last_point_at
    assert evidence.truncated


def test_existing_two_hundred_point_page_has_compact_evidence():
    points = tuple(StatisticPoint(i * 60, 1) for i in range(200))
    semantics = SeriesSemantics(
        interpretation_status="partial", value_meaning="sample", timestamp_basis="unix_utc"
    )
    evidence = statistic_evidence(points, semantics, has_more=False)
    assert evidence.point_count == 200
    assert not evidence.truncated
    assert len(evidence.model_dump_json()) < 512


def test_hourly_evidence_bounds_do_not_reduce_existing_statistic_page():
    points = tuple(StatisticPoint(i * 3600, 1) for i in range(200))
    semantics = SeriesSemantics(
        interpretation_status="partial",
        value_meaning="interval_difference_sum",
        timestamp_basis="unix_utc",
        timestamp_position="interval_start",
    )
    evidence = statistic_evidence(points, semantics, has_more=False)
    assert len(evidence.intervals) == 128
    assert evidence.truncated
    assert len(points) == 200


def test_only_documented_hourly_difference_interval_is_exposed():
    semantics = SeriesSemantics(
        interpretation_status="partial",
        timestamp_basis="unix_utc",
        value_meaning="interval_difference_sum",
        timestamp_position="interval_start",
    )
    evidence = statistic_evidence(
        (StatisticPoint(0, 1), StatisticPoint(7200, 2)), semantics, has_more=False
    )
    assert len(evidence.intervals) == 2
    assert evidence.intervals[0].end == "1970-01-01T01:00:00Z"
    assert evidence.intervals[1].start == "1970-01-01T02:00:00Z"
    assert evidence.point_count == 0
    uncertain = statistic_evidence(
        (StatisticPoint(0, 1),), replace(semantics, timestamp_position=None), has_more=False
    )
    assert uncertain.intervals == []


def test_legacy_public_compatibility_shape_is_not_utc_evidence():
    semantics = SeriesSemantics(
        interpretation_status="partial",
        value_meaning=None,
        timestamp_basis="local_miniserver_seconds_since_2009",
    )
    evidence = statistic_evidence((StatisticPoint(100, 1),), semantics, has_more=False)
    assert evidence.time_basis == "unverified_legacy_local"
    assert evidence.first_point_at is None


def test_invalid_semantics_with_unknown_timestamp_basis_are_not_legacy():
    semantics = SeriesSemantics(
        interpretation_status="invalid", value_meaning=None, timestamp_basis=None
    )
    evidence = statistic_evidence((StatisticPoint(100, 1),), semantics, has_more=False)
    assert evidence.time_basis == "unknown"
    assert evidence.limitations == ["timestamp_basis_not_established"]
    assert evidence.first_point_at is None


def test_capture_intervals_keep_gap_and_initial_phase_boundary():
    phases, evidence = capture_evidence(
        ((0, 100, 0, False), (200, None, None, None)),
        start=50,
        end=400,
        now=300,
        truncated=False,
    )
    assert len(evidence.intervals) == 2
    assert evidence.intervals[0].start == "1970-01-01T00:00:50Z"
    assert evidence.intervals[0].end == "1970-01-01T00:01:40Z"
    assert evidence.intervals[1].start == "1970-01-01T00:03:20Z"
    assert evidence.intervals[1].end == "1970-01-01T00:05:00Z"
    assert phases[0].start == "1970-01-01T00:00:00Z"
    assert phases[0].initial_value is False
    assert phases[0].initial_value_known
    assert not phases[1].initial_value_known
