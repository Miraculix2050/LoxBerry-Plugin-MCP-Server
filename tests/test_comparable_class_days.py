import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from mcpserver.comparable_class_days import ClassDay, ClassPoint, ClassRule, compare_class_days
from mcpserver.comparable_days import Options
from mcpserver.comparable_days_models import ClassComparableDayOptions, ClassComparableDaysResult
from mcpserver.history_analysis import HistoryAnalysisDeadline


def day(offset=0, values=(0, 1, 2, 3)):
    selected = date(2026, 7, 1) + timedelta(days=offset)
    points = tuple(
        ClassPoint(datetime(2026, 7, selected.day, hour, tzinfo=UTC).timestamp(), value)
        for hour, value in zip(range(10, 14), values, strict=True)
    )
    return ClassDay(selected, points, ClassRule.REVIEWED_RISK_CLASS, "installation", "generation")


def compare(days, **kwargs):
    return compare_class_days(
        tuple(days),
        reference=date(2026, 7, 1),
        timezone_name="UTC",
        now=datetime(2026, 7, 10, tzinfo=UTC),
        options=Options(start_hour=10, end_hour=14),
        deadline=time.monotonic() + 10,
        **kwargs,
    )


def test_class_sequences_select_peers_without_numeric_radiation_or_yield():
    result = compare([day(), day(1), day(2, (3, 2, 1, 0))])
    typed = ClassComparableDaysResult.model_validate(result)
    assert len(typed.candidates) == 1
    assert typed.candidates[0].day == "2026-07-02"
    assert typed.exclusions[0].reason == "radiation_class_sequence_differs"
    assert "radiation_wh_m2" not in str(result)
    assert "group" not in result
    assert "no_radiation_energy_or_15_percent_tolerance" in typed.limitations


@pytest.mark.parametrize("value", [True, -1, 4, 1.5, float("nan"), float("inf"), "1", None])
def test_invalid_classes_are_not_coerced(value):
    result = compare([day(values=(value, 1, 2, 3)), day(1)])
    assert result["status"] == "insufficient_evidence"
    assert "radiation_class_invalid" in result["limitations"]


def test_assumed_mapping_remains_explicit_and_cannot_mix_with_reviewed_source():
    result = compare([replace(day(), rule=ClassRule.OWNER_ASSUMED_RISK_CLASS), day(1)])
    assert result["classification_origin"] == "owner_assumed_risk_class_0_3"
    assert "native_class_mapping_is_owner_assumed_not_verified" in result["limitations"]
    assert result["exclusions"][0]["reason"] == "source_identity_or_classification_changed"


def test_missing_positions_are_not_shrunk_to_make_a_peer():
    candidate = replace(day(1), points=day(1).points[:2])
    result = compare([day(), candidate])
    assert result["common_hour_positions"] == [10, 11, 12, 13]
    assert result["exclusions"][0]["reason"] == "shared_source_positions_incomplete"


def test_duplicate_positions_and_unknown_rules_do_not_qualify():
    duplicate = replace(day(), points=(*day().points, day().points[0]))
    assert "duplicate_source_points" in compare([duplicate])["limitations"]
    assert (
        "radiation_class_mapping_unverified" in compare([replace(day(), rule="raw")])["limitations"]
    )


def test_caller_cannot_supply_mapping_or_radiation_tolerance():
    for extra in ({"rule": "owner_assumed"}, {"radiation_relative_tolerance": 0.15}):
        with pytest.raises(ValidationError):
            ClassComparableDayOptions.model_validate({"reference_day": "2026-07-01", **extra})


def test_class_method_checks_deadline():
    with pytest.raises(HistoryAnalysisDeadline):
        compare_class_days(
            (day(),),
            reference=day().day,
            timezone_name="UTC",
            now=datetime.now(UTC),
            options=Options(),
            deadline=time.monotonic() - 1,
        )


def test_unexpected_values_are_retained_with_bounded_diagnostics():
    extra = tuple(ClassPoint(day().points[0].at + i * 60, 99) for i in range(20))
    result = compare([replace(day(), points=(*day().points, *extra)), day(1)])
    typed = ClassComparableDaysResult.model_validate(result)
    assert typed.invalid_source_point_count == 20
    assert len(typed.invalid_points) == 16
    assert typed.invalid_points_truncated
    assert typed.invalid_points[0].raw_value == 99
    assert typed.invalid_points[0].issue == "out_of_range"


def test_bad_value_outside_required_positions_does_not_discard_valid_peer():
    extra = ClassPoint(day(1).points[-1].at + 3600, 5)
    result = compare([day(), replace(day(1), points=(*day(1).points, extra))])
    assert len(result["candidates"]) == 1
    assert result["invalid_points"][0]["raw_value"] == 5
    assert "unexpected_values_need_class_mapping_review" in result["limitations"]


def test_nonfinite_diagnostics_preserve_fixed_json_compatible_representation():
    import json

    result = compare([day(values=(float("nan"), 1, 2, 3)), day(1)])
    typed = ClassComparableDaysResult.model_validate(result)
    assert typed.invalid_points[0].raw_value is None
    assert typed.invalid_points[0].raw_value_repr == "NaN"
    json.dumps(typed.model_dump(), allow_nan=False)
