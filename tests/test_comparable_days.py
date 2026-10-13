import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mcpserver.comparable_days import DayEvidence, HourEvidence, Options, compare_days
from mcpserver.history_analysis import HistoryAnalysisDeadline


def day(offset=0, *, radiation=100, temperature=20, pv=1000, base=date(2026, 7, 1)):
    selected = base + timedelta(days=offset)
    zone = ZoneInfo("Europe/Berlin")
    hours = tuple(
        HourEvidence(
            datetime(selected.year, selected.month, selected.day, h, tzinfo=zone).timestamp(),
            datetime(selected.year, selected.month, selected.day, h + 1, tzinfo=zone).timestamp(),
            radiation,
            temperature,
            pv,
        )
        for h in range(10, 14)
    )
    return DayEvidence(
        selected,
        hours,
        "fixture_radiation_interval.v1",
        "fixture_temperature_observation.v1",
        "fixture_pv_interval.v1",
        None,
        "fixture_generation",
        temperature_position="hour_start",
    )


def compare(days, *, reference=None, now=datetime(2026, 7, 10, tzinfo=UTC), options=None):
    return compare_days(
        tuple(days),
        reference=reference or days[0].day,
        timezone_name="Europe/Berlin",
        now=now,
        options=options or Options(start_hour=10, end_hour=14),
        deadline=time.monotonic() + 10,
    )


def test_three_complete_comparison_days_and_strict_anomaly_threshold():
    days = [day(0, pv=800), day(1), day(2), day(3)]
    result = compare(days)
    assert result["group"]["count"] == 3
    assert result["group"]["median_pv_wh"] == 4000
    assert result["group"]["relative_difference"] == -0.20
    assert result["group"]["check_candidate"] is False
    assert compare([day(0, pv=799), *days[1:]])["group"]["check_candidate"] is True


def test_two_days_do_not_create_group_or_diagnosis():
    result = compare([day(0, pv=0), day(1), day(2)])
    assert result["status"] == "partial"
    assert result["group"] is None
    assert "fewer_than_three_complete_pv_comparison_days" in result["limitations"]


def test_unknown_radiation_never_evaluates_values():
    result = compare([replace(day(), radiation_rule=None), day(1)])
    assert result["status"] == "insufficient_evidence"
    assert result["candidates"] == []
    assert "radiation_quantity_unit_interval_unverified" in result["limitations"]


def test_missing_hour_never_shrinks_the_reference_window():
    bad = replace(day(1), hours=day(1).hours[:2])
    result = compare([day(), bad, day(2)])
    assert result["common_hour_positions"] == [10, 11, 12, 13]
    assert result["exclusions"] == [
        {"day": bad.day.isoformat(), "reason": "shared_interval_coverage_incomplete"}
    ]
    assert len(result["candidates"]) == 1


def test_normalized_distance_sort_is_deterministic():
    result = compare(
        [
            day(),
            day(1, radiation=110),
            day(2, temperature=20.3),
            day(3, radiation=100, temperature=20.3),
        ]
    )
    assert [item["day"] for item in result["candidates"]] == [
        "2026-07-03",
        "2026-07-04",
        "2026-07-02",
    ]


def test_tolerance_limits_include_exact_boundaries():
    result = compare(
        [
            day(),
            day(1, radiation=115, temperature=23),
            day(2, radiation=116),
            day(3, temperature=23.1),
        ]
    )
    assert [item["day"] for item in result["candidates"]] == ["2026-07-02"]
    assert [item["reason"] for item in result["exclusions"]] == [
        "radiation_tolerance_exceeded",
        "temperature_tolerance_exceeded",
    ]


def test_zero_radiation_and_zero_median_do_not_create_anomaly():
    result = compare(
        [
            day(0, radiation=0, pv=0),
            day(1, radiation=0, pv=0),
            day(2, radiation=0, pv=0),
            day(3, radiation=0, pv=0),
        ]
    )
    assert result["group"]["relative_difference"] is None
    assert result["group"]["check_candidate"] is False


def test_current_day_uses_completed_hours_before_candidate_filtering():
    current = datetime(2026, 7, 3, 10, 25, tzinfo=UTC)  # 12:25 local
    result = compare([day(), day(1), day(2)], reference=day(2).day, now=current)
    assert result["common_hour_positions"] == [10, 11]
    assert result["reference"]["pv_wh"] == 2000


def test_duplicate_and_partial_intervals_are_rejected():
    candidate = day(1)
    duplicate = replace(candidate, hours=(*candidate.hours, candidate.hours[0]))
    result = compare([day(), duplicate])
    assert result["exclusions"][0]["reason"] == "duplicate_or_overlapping_intervals"
    partial = replace(
        candidate,
        hours=(replace(candidate.hours[0], end=candidate.hours[0].end - 1), *candidate.hours[1:]),
    )
    assert (
        compare([day(), partial])["exclusions"][0]["reason"]
        == "shared_interval_coverage_incomplete"
    )


def test_dst_window_is_not_silently_normalized():
    ref = replace(day(), day=date(2026, 10, 25))
    result = compare(
        [ref],
        reference=ref.day,
        now=datetime(2026, 11, 1, tzinfo=UTC),
        options=Options(start_hour=1, end_hour=4),
    )
    assert result["status"] == "insufficient_evidence"
    assert "ambiguous_or_nonexistent_local_window" in result["limitations"]


def test_unknown_installation_geometry_does_not_block_comparison():
    result = compare([day(), day(1)])
    assert result["status"] == "partial"
    changed = replace(day(1), installation_ref="changed_installation")
    assert compare([day(), changed])["exclusions"][0]["reason"] == "installation_changed"


def test_deadline_and_noncontiguous_inputs_fail():
    with pytest.raises(ValueError, match="contiguous"):
        compare([day(), day(2)])
    with pytest.raises(HistoryAnalysisDeadline):
        compare_days(
            (day(),),
            reference=day().day,
            timezone_name="Europe/Berlin",
            now=datetime(2026, 7, 10, tzinfo=UTC),
            options=Options(),
            deadline=0,
        )


def test_past_reference_cannot_consume_future_candidate_hours():
    result = compare([day(), day(1), day(2)], now=datetime(2026, 7, 3, 10, 25, tzinfo=UTC))
    assert result["common_hour_positions"] == [10, 11, 12, 13]
    assert result["exclusions"][-1]["reason"] == "common_candidate_intervals_not_completed"


def test_output_explains_strict_group_thresholds():
    result = compare([day(), day(1)])
    assert result["group_minimum_days"] == 3
    assert result["advisory_relative_threshold"] == -0.20
    assert result["advisory_threshold_comparison"] == "strictly_less_than"


def test_temperature_position_change_is_an_exclusion():
    changed = replace(day(1), temperature_position="hour_end")
    assert (
        compare([day(), changed])["exclusions"][0]["reason"]
        == "source_semantics_or_observation_position_changed"
    )


def test_overflow_and_invalid_radiation_fail_closed():
    result = compare([day(radiation=1e308), day(1)])
    assert "derived_numeric_overflow" in result["limitations"]
    for invalid in (-1, float("nan"), float("inf")):
        assert "radiation_values_invalid" in compare([day(radiation=invalid)])["limitations"]


def test_zero_radiation_does_not_match_positive_candidate():
    result = compare([day(radiation=0), day(1, radiation=1)])
    assert result["exclusions"][0]["reason"] == "radiation_tolerance_exceeded"


def test_positive_radiation_zero_median_is_not_anomaly():
    result = compare([day(pv=0), day(1, pv=0), day(2, pv=0), day(3, pv=0)])
    assert result["group"]["relative_difference"] is None
    assert result["group"]["check_candidate"] is False


def test_overlap_scan_checks_deadline(monkeypatch):
    from mcpserver import comparable_days

    calls = 0

    def bounded_check(deadline):
        nonlocal calls
        calls += 1
        if calls == 9:
            raise HistoryAnalysisDeadline()

    monkeypatch.setattr(comparable_days, "_check", bounded_check)
    with pytest.raises(HistoryAnalysisDeadline):
        comparable_days._summary(day(), (10, 11, 12, 13), ZoneInfo("Europe/Berlin"), 100)
    assert calls == 9


def test_spring_dst_gap_is_rejected_but_later_window_remains_usable():
    source = day(base=date(2026, 3, 29))
    now = datetime(2026, 4, 1, tzinfo=UTC)
    bad = compare([source], now=now, options=Options(start_hour=1, end_hour=4))
    assert "ambiguous_or_nonexistent_local_window" in bad["limitations"]
    good = compare([source, day(1, base=source.day)], now=now)
    assert good["status"] == "partial"


def test_negative_pv_remains_unknown_and_never_enters_group():
    result = compare([day(), day(1, pv=-1), day(2), day(3)])
    assert result["candidates"][0]["pv_wh"] is None
    assert result["group"] is None


def test_source_generation_change_excludes_the_candidate():
    changed = replace(day(1), source_generation="changed_generation")
    result = compare([day(), changed])
    assert result["exclusions"][0]["reason"] == "source_generation_changed"


def test_duplicate_outside_common_window_does_not_change_comparison():
    candidate = day(1)
    outside = replace(
        candidate.hours[0], start=candidate.hours[0].start - 7200, end=candidate.hours[0].end - 7200
    )
    candidate = replace(candidate, hours=(*candidate.hours, outside, outside))
    assert compare([day(), candidate])["status"] == "partial"


def test_boolean_measurements_are_not_numeric_evidence():
    assert "radiation_values_invalid" in compare([day(radiation=True)])["limitations"]
    assert "temperature_values_invalid" in compare([day(temperature=False)])["limitations"]
    assert compare([day(), day(1, pv=True)])["candidates"][0]["pv_wh"] is None


def test_individual_pv_comparison_does_not_require_three_days():
    result = compare([day(pv=800), day(1)])
    assert result["group"] is None
    assert result["candidates"][0]["pv_absolute_difference_wh"] == -800
    assert result["candidates"][0]["pv_relative_difference"] == -0.20


def test_zero_candidate_pv_has_no_relative_pair_denominator():
    item = compare([day(), day(1, pv=0)])["candidates"][0]
    assert item["pv_absolute_difference_wh"] == 4000
    assert item["pv_relative_difference"] is None


def test_changed_pv_rule_retains_weather_comparison_without_pv_claims():
    changed = replace(day(1), pv_rule="different_interval_rule")
    item = compare([day(), changed])["candidates"][0]
    assert item["pv_wh"] is None
    assert item["pv_evidence"] == "rule_changed"
    assert item["pv_absolute_difference_wh"] is None


def test_missing_reference_pv_is_not_misreported_as_too_few_candidates():
    result = compare([day(pv=None), day(1), day(2), day(3)])
    assert result["group"] is None
    assert "reference_pv_intervals_incomplete_or_invalid" in result["limitations"]
    assert "fewer_than_three_complete_pv_comparison_days" not in result["limitations"]


@pytest.mark.parametrize(
    "value,reason",
    [
        (None, "intervals_incomplete"),
        (-1, "values_invalid"),
        (True, "values_invalid"),
        (float("nan"), "values_invalid"),
        (float("inf"), "values_invalid"),
        (1e308, "derived_numeric_overflow"),
    ],
)
def test_pv_unknown_reason_preserves_weather_comparison(value, reason):
    result = compare([day(), day(1, pv=value)])
    candidate = result["candidates"][0]
    assert candidate["pv_evidence"] == reason
    assert candidate["pv_wh"] is None
    assert candidate["pv_absolute_difference_wh"] is None
    assert candidate["pv_relative_difference"] is None
    assert result["status"] == "partial"


def test_reference_pv_unverified_rule_is_explicit_without_false_group():
    result = compare([replace(day(), pv_rule=None), day(1), day(2), day(3)])
    assert result["reference"]["pv_evidence"] == "rule_unverified"
    assert result["reference"]["pv_wh"] is None
    assert result["group"] is None
    assert all(candidate["pv_evidence"] == "rule_changed" for candidate in result["candidates"])
