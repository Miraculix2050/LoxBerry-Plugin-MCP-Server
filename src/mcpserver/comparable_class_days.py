"""Coarse class comparisons of recorded source points, never radiation energy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from itertools import pairwise
from math import isfinite
from typing import Any

from mcpserver.comparable_days import Options, _boundary, _check
from mcpserver.loxone.history_evidence import timezone


class ClassRule(Enum):
    """Only an adapter may assign a reviewed or explicitly assumed mapping."""

    REVIEWED_RISK_CLASS = "reviewed_risk_class_0_3"
    OWNER_ASSUMED_RISK_CLASS = "owner_assumed_risk_class_0_3"


@dataclass(frozen=True, slots=True)
class ClassPoint:
    at: float
    radiation_class: float | int | None


@dataclass(frozen=True, slots=True)
class ClassDay:
    day: date
    points: tuple[ClassPoint, ...]
    rule: ClassRule | None
    installation: str | None
    generation: str | None


def _class_issue(value: object) -> str | None:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "boolean"
    if not isinstance(value, int | float):
        return "not_numeric"
    if not isfinite(value):
        return "not_finite"
    if not 0 <= value <= 3:
        return "out_of_range"
    if value not in (0, 1, 2, 3):
        return "fractional"
    return None


def compare_class_days(
    days: tuple[ClassDay, ...],
    *,
    reference: date,
    timezone_name: str,
    now: datetime,
    options: Options,
    deadline: float,
) -> dict[str, Any]:
    """Compare the same completed hour-start source positions with identical classes.

    Sampling points establish neither an interval integral nor continuous coverage.
    Numerical temperature, PV, self-consumption and normalized yield are omitted.
    """
    _check(deadline)
    options.validate()
    zone = timezone(timezone_name)
    if now.tzinfo is None:
        raise ValueError("aware current time required")
    ordered = sorted(days, key=lambda item: item.day)
    if not 1 <= len(ordered) <= 31 or len({item.day for item in ordered}) != len(ordered):
        raise ValueError("one to 31 unique contiguous local days required")
    if any(b.day - a.day != timedelta(days=1) for a, b in pairwise(ordered)):
        raise ValueError("contiguous local days required")
    if sum(len(item.points) for item in ordered) > 100_000:
        raise ValueError("analysis input point limit exceeded")
    current = now.astimezone(zone)
    if ordered[-1].day > current.date():
        raise ValueError("future days are not historical inputs")
    ref = next((item for item in ordered if item.day == reference), None)
    if ref is None:
        raise ValueError("reference must lie inside the selected range")
    positions = tuple(
        range(
            options.start_hour,
            min(options.end_hour, current.hour)
            if reference == current.date()
            else options.end_hour,
        )
    )
    result: dict[str, Any] = {
        "method_version": "comparable_days.radiation_classes.v1",
        "status": "insufficient_evidence",
        "reference_day": reference.isoformat(),
        "timezone": timezone_name,
        "common_hour_positions": list(positions),
        "options": {
            "start_hour": options.start_hour,
            "end_hour": options.end_hour,
            "maximum_seasonal_days": options.maximum_seasonal_days,
            "class_match_policy": "identical_sequence",
        },
        "classification_origin": ref.rule.value if isinstance(ref.rule, ClassRule) else None,
        "reference_classes": None,
        "candidates": [],
        "exclusions": [],
        "coverage": "matched_hour_start_source_points_only",
        "invalid_source_point_count": 0,
        "invalid_points": [],
        "invalid_points_truncated": False,
        "limitations": [
            "coarse_classes_do_not_prove_equal_irradiance",
            "no_radiation_energy_or_15_percent_tolerance",
            "no_normalized_yield_or_self_consumption_claim",
            "source_points_do_not_prove_continuous_measurements",
            "temperature_and_pv_are_not_used_by_class_method",
            "seasonal_distance_does_not_prove_equal_solar_geometry",
        ],
    }
    if ref.rule is ClassRule.OWNER_ASSUMED_RISK_CLASS:
        result["limitations"].append("native_class_mapping_is_owner_assumed_not_verified")
    # Retain bounded, authorized diagnostics even outside the comparison hours.
    # Values never become valid classes merely because they can be coerced.
    for item in ordered:
        if not isinstance(item.rule, ClassRule):
            continue
        for point in item.points:
            _check(deadline)
            value = point.radiation_class
            issue = _class_issue(value)
            if issue is None:
                continue
            result["invalid_source_point_count"] += 1
            if len(result["invalid_points"]) < 16:
                finite = (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and isfinite(value)
                )
                nonfinite = (
                    "NaN"
                    if isinstance(value, float) and value != value
                    else "Infinity"
                    if isinstance(value, float) and value > 0
                    else "-Infinity"
                )
                result["invalid_points"].append(
                    {
                        "day": item.day.isoformat(),
                        "point_at": point.at,
                        "raw_value": value if finite or isinstance(value, bool) else None,
                        "raw_value_repr": nonfinite if issue == "not_finite" else None,
                        "issue": issue,
                        "classification_origin": item.rule.value,
                        "action": "not_used_as_a_valid_class",
                    }
                )
    result["invalid_points_truncated"] = result["invalid_source_point_count"] > len(
        result["invalid_points"]
    )
    if result["invalid_source_point_count"]:
        result["limitations"].append("unexpected_values_need_class_mapping_review")
    if not positions:
        result["limitations"].append("no_completed_reference_intervals")
        return result

    def sequence(item: ClassDay) -> tuple[list[int] | None, str | None]:
        if not isinstance(item.rule, ClassRule):
            return None, "radiation_class_mapping_unverified"
        if not item.installation or not item.generation:
            return None, "source_identity_unverified"
        expected = []
        try:
            for hour in positions:
                _check(deadline)
                start, end = _boundary(item.day, hour, zone), _boundary(item.day, hour + 1, zone)
                if end - start != 3600:
                    return None, "non_hourly_local_window"
                if end > now.astimezone(UTC).timestamp():
                    return None, "common_candidate_intervals_not_completed"
                expected.append(start)
        except ValueError:
            return None, "ambiguous_or_nonexistent_local_window"
        index = {}
        for point in item.points:
            _check(deadline)
            if point.at not in expected:
                continue
            if point.at in index:
                return None, "duplicate_source_points"
            value = point.radiation_class
            if _class_issue(value) is not None:
                return None, "radiation_class_invalid"
            assert isinstance(value, int | float)
            index[point.at] = int(value)
        if any(at not in index for at in expected):
            return None, "shared_source_positions_incomplete"
        return [index[at] for at in expected], None

    ref_classes, reason = sequence(ref)
    if reason:
        result["limitations"].append(reason)
        return result
    result["reference_classes"] = ref_classes
    for item in ordered:
        _check(deadline)
        if item.day == reference:
            continue
        distance = abs((item.day - reference).days)
        classes, reason = sequence(item)
        if distance > options.maximum_seasonal_days:
            reason = "seasonal_distance_exceeded"
        elif (item.installation, item.generation, item.rule) != (
            ref.installation,
            ref.generation,
            ref.rule,
        ):
            reason = "source_identity_or_classification_changed"
        if reason is None and classes != ref_classes:
            reason = "radiation_class_sequence_differs"
        if reason:
            result["exclusions"].append({"day": item.day.isoformat(), "reason": reason})
        else:
            result["candidates"].append(
                {
                    "day": item.day.isoformat(),
                    "seasonal_distance_days": distance,
                    "radiation_classes": classes,
                    "selection_reason": "identical_class_sequence",
                }
            )
    result["candidates"].sort(key=lambda item: (item["seasonal_distance_days"], item["day"]))
    if result["candidates"]:
        result["status"] = "partial"
    return result
