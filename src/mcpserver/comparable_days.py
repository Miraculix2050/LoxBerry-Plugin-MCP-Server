"""Deterministic comparable-day method; source evidence is supplied by adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from itertools import pairwise
from math import fsum, hypot, isfinite
from statistics import fmean, median
from typing import Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo

from mcpserver.history_analysis import HistoryAnalysisDeadline

PVEvidence = Literal[
    "qualified",
    "rule_unverified",
    "rule_changed",
    "intervals_incomplete",
    "values_invalid",
    "derived_numeric_overflow",
]


class DaySummary(TypedDict):
    radiation_wh_m2: float
    matched_sample_mean_c: float
    pv_wh: float | None
    pv_evidence: PVEvidence


class DayCandidate(DaySummary):
    day: str
    seasonal_distance_days: int
    radiation_relative_difference: float
    temperature_difference_c: float
    pv_absolute_difference_wh: float | None
    pv_relative_difference: float | None
    normalized_weather_distance: float


class DayExclusion(TypedDict):
    day: str
    reason: str


class DayGroup(TypedDict):
    count: int
    median_pv_wh: float
    minimum_pv_wh: float
    maximum_pv_wh: float
    absolute_difference_wh: float
    relative_difference: float | None
    check_candidate: bool


class DaysResult(TypedDict):
    method_version: Literal["comparable_days.v1"]
    status: Literal["partial", "insufficient_evidence"]
    reference_day: str
    timezone: str
    common_hour_positions: list[int]
    options: dict[str, float | int]
    candidates: list[DayCandidate]
    exclusions: list[DayExclusion]
    group: DayGroup | None
    group_minimum_days: int
    advisory_relative_threshold: float
    advisory_threshold_comparison: Literal["strictly_less_than"]
    limitations: list[str]
    reference: NotRequired[DaySummary]


class RadiationRule(Enum):
    """Closed adapter contract: proven hourly radiation energy, never a raw delivery."""

    HOURLY_ENERGY_WH_M2 = "radiation.hourly_interval_energy_wh_m2.v1"
    ESTIMATED_SAMPLE_ENERGY = "radiation.bounded_trapezoidal_irradiance.v1"


class TemperatureRule(Enum):
    """Closed adapter contract: Celsius sample at each matching hour start."""

    CELSIUS_HOUR_START = "temperature.celsius_hour_start_sample.v1"
    CELSIUS_NEAR_HOUR_START = "temperature.celsius_within_60s_of_hour_start.v1"


class PVRule(Enum):
    """Closed adapter contract: isolated PV energy over each complete hour."""

    HOURLY_ENERGY_WH = "pv.isolated_hourly_interval_energy_wh.v1"


def _decimal(value: float) -> Decimal:
    """Use the source decimal representation consistently at exact thresholds."""
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class HourEvidence:
    start: float
    end: float
    radiation_wh_m2: float | None
    temperature_c: float | None
    pv_wh: float | None


@dataclass(frozen=True, slots=True)
class DayEvidence:
    day: date
    hours: tuple[HourEvidence, ...]
    radiation_rule: RadiationRule | None = None
    temperature_rule: TemperatureRule | None = None
    pv_rule: PVRule | None = None
    installation_ref: str | None = None
    source_generation: str | None = None
    exclusions: tuple[str, ...] = ()
    temperature_position: str | None = None


@dataclass(frozen=True, slots=True)
class Options:
    start_hour: int = 0
    end_hour: int = 24
    maximum_seasonal_days: int = 30
    radiation_relative_tolerance: float = 0.15
    temperature_tolerance_c: float = 3.0

    def validate(self) -> None:
        if not 0 <= self.start_hour < self.end_hour <= 24:
            raise ValueError("invalid common local window")
        if not 0 <= self.maximum_seasonal_days <= 30:
            raise ValueError("invalid seasonal tolerance")
        if not 0 < self.radiation_relative_tolerance <= 0.15:
            raise ValueError("invalid radiation tolerance")
        if not 0 < self.temperature_tolerance_c <= 3:
            raise ValueError("invalid temperature tolerance")


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()


def _boundary(day: date, hour: int, zone: ZoneInfo) -> float:
    local = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
    choices = {
        value.timestamp()
        for fold in (0, 1)
        if (value := local.replace(tzinfo=zone, fold=fold).astimezone(UTC))
        .astimezone(zone)
        .replace(tzinfo=None)
        == local
    }
    if len(choices) != 1:
        raise ValueError("ambiguous_or_nonexistent_local_window")
    return choices.pop()


def _summary(
    source: DayEvidence, positions: tuple[int, ...], zone: ZoneInfo, deadline: float
) -> tuple[DaySummary | None, str | None]:
    if source.exclusions:
        return None, source.exclusions[0]
    if not isinstance(source.radiation_rule, RadiationRule):
        return None, "radiation_quantity_unit_interval_unverified"
    if not isinstance(source.temperature_rule, TemperatureRule):
        return None, "temperature_observation_position_unverified"
    expected_temperature_position = (
        "within_60s_of_hour_start"
        if source.temperature_rule is TemperatureRule.CELSIUS_NEAR_HOUR_START
        else "hour_start"
    )
    if source.temperature_position != expected_temperature_position:
        return None, "temperature_observation_position_unverified"
    if not source.source_generation or not source.installation_ref:
        return None, "source_identity_unverified"
    try:
        expected = [
            (_boundary(source.day, h, zone), _boundary(source.day, h + 1, zone)) for h in positions
        ]
    except ValueError:
        return None, "ambiguous_or_nonexistent_local_window"
    if any(end - start != 3600 for start, end in expected):
        return None, "non_hourly_local_window"
    index = {}
    for item in source.hours:
        _check(deadline)
        if item.end <= expected[0][0] or item.start >= expected[-1][1]:
            continue
        if item.start in index:
            return None, "duplicate_or_overlapping_intervals"
        index[item.start] = item
    selected = []
    for start, end in expected:
        _check(deadline)
        matching = index.get(start)
        if matching is None or matching.end != end:
            return None, "shared_interval_coverage_incomplete"
        selected.append(matching)
    # Extra overlapping records invalidate coverage instead of being silently discarded.
    for item in source.hours:
        _check(deadline)
        if any(
            item.start < end and item.end > start and (item.start, item.end) != (start, end)
            for start, end in expected
        ):
            return None, "duplicate_or_overlapping_intervals"
    radiation = [item.radiation_wh_m2 for item in selected]
    temperature = [item.temperature_c for item in selected]
    if any(v is None or isinstance(v, bool) or not isfinite(v) or v < 0 for v in radiation):
        return None, "radiation_values_invalid"
    if any(v is None or isinstance(v, bool) or not isfinite(v) for v in temperature):
        return None, "temperature_values_invalid"
    pv = [item.pv_wh for item in selected]
    pv_evidence: PVEvidence = (
        "rule_unverified"
        if not isinstance(source.pv_rule, PVRule)
        else "values_invalid"
        if any(
            value is not None and (isinstance(value, bool) or not isfinite(value) or value < 0)
            for value in pv
        )
        else "intervals_incomplete"
        if any(value is None for value in pv)
        else "qualified"
    )
    pv_total = None
    if pv_evidence == "qualified":
        try:
            pv_total = fsum(value for value in pv if value is not None)
        except OverflowError:
            pv_evidence = "derived_numeric_overflow"
        if pv_total is not None and not isfinite(pv_total):
            pv_total = None
            pv_evidence = "derived_numeric_overflow"
    try:
        values: DaySummary = {
            "radiation_wh_m2": fsum(value for value in radiation if value is not None),
            "matched_sample_mean_c": fmean(value for value in temperature if value is not None),
            "pv_wh": pv_total,
            "pv_evidence": pv_evidence,
        }
    except OverflowError:
        return None, "derived_numeric_overflow"
    if any(
        value is not None and not isfinite(value)
        for value in (values["radiation_wh_m2"], values["matched_sample_mean_c"], values["pv_wh"])
    ):
        return None, "derived_numeric_overflow"
    return values, None


def compare_days(
    days: tuple[DayEvidence, ...],
    *,
    reference: date,
    timezone_name: str,
    now: datetime,
    options: Options,
    deadline: float,
) -> DaysResult:
    _check(deadline)
    options.validate()
    zone = ZoneInfo(timezone_name)
    if now.tzinfo is None:
        raise ValueError("aware current time required")
    ordered = sorted(days, key=lambda item: item.day)
    if sum(len(item.hours) for item in days) > 100_000:
        raise ValueError("analysis input point limit exceeded")
    if not 1 <= len(ordered) <= 31 or len({item.day for item in ordered}) != len(ordered):
        raise ValueError("one to 31 unique contiguous local days required")
    if any(right.day - left.day != timedelta(days=1) for left, right in pairwise(ordered)):
        raise ValueError("contiguous local days required")
    current = now.astimezone(zone)
    if ordered[-1].day > current.date():
        raise ValueError("future days are not historical inputs")
    ref = next((item for item in ordered if item.day == reference), None)
    if ref is None:
        raise ValueError("reference must lie inside the selected range")
    # Freeze the reference window before examining candidates. No coverage-dependent shrinking.
    positions = tuple(
        range(
            options.start_hour,
            min(options.end_hour, current.hour)
            if reference == current.date()
            else options.end_hour,
        )
    )
    result: DaysResult = {
        "method_version": "comparable_days.v1",
        "status": "insufficient_evidence",
        "reference_day": reference.isoformat(),
        "timezone": timezone_name,
        "common_hour_positions": list(positions),
        "options": {
            "start_hour": options.start_hour,
            "end_hour": options.end_hour,
            "maximum_seasonal_days": options.maximum_seasonal_days,
            "radiation_relative_tolerance": options.radiation_relative_tolerance,
            "temperature_tolerance_c": options.temperature_tolerance_c,
        },
        "candidates": [],
        "exclusions": [],
        "group": None,
        "group_minimum_days": 3,
        "advisory_relative_threshold": -0.20,
        "advisory_threshold_comparison": "strictly_less_than",
        "limitations": [
            "seasonal_distance_does_not_prove_equal_solar_geometry",
            "low_yield_is_a_check_candidate_not_a_defect_diagnosis",
        ],
    }
    if not positions:
        result["limitations"].append("no_completed_reference_intervals")
        return result
    ref_values, reason = _summary(ref, positions, zone, deadline)
    if ref_values is None:
        assert reason is not None
        result["limitations"].append(reason)
        return result
    result["reference"] = ref_values
    for item in ordered:
        _check(deadline)
        if item.day == reference:
            continue
        try:
            completed = all(
                _boundary(item.day, hour + 1, zone) <= now.timestamp() for hour in positions
            )
        except ValueError:
            completed = True  # The detailed source summary reports the DST exclusion.
        if not completed:
            result["exclusions"].append(
                {"day": item.day.isoformat(), "reason": "common_candidate_intervals_not_completed"}
            )
            continue
        distance = abs((item.day - reference).days)
        values, reason = _summary(item, positions, zone, deadline)
        if distance > options.maximum_seasonal_days:
            reason = "seasonal_distance_exceeded"
        elif item.source_generation != ref.source_generation:
            reason = "source_generation_changed"
        elif item.installation_ref != ref.installation_ref:
            reason = "installation_changed"
        elif (item.radiation_rule, item.temperature_rule, item.temperature_position) != (
            ref.radiation_rule,
            ref.temperature_rule,
            ref.temperature_position,
        ):
            reason = "source_semantics_or_observation_position_changed"
        if reason:
            result["exclusions"].append({"day": item.day.isoformat(), "reason": reason})
            continue
        assert values is not None
        rref, rcandidate = ref_values["radiation_wh_m2"], values["radiation_wh_m2"]
        relative_decimal = (
            abs(_decimal(rcandidate) - _decimal(rref)) / _decimal(rref)
            if rref > 0
            else Decimal(0)
            if rcandidate == 0
            else None
        )
        delta_temp_decimal = abs(
            _decimal(values["matched_sample_mean_c"])
            - _decimal(ref_values["matched_sample_mean_c"])
        )
        relative = float(relative_decimal) if relative_decimal is not None else None
        delta_temp = float(delta_temp_decimal)
        if (relative is not None and not isfinite(relative)) or not isfinite(delta_temp):
            result["exclusions"].append(
                {"day": item.day.isoformat(), "reason": "derived_numeric_overflow"}
            )
            continue
        reason = (
            "radiation_tolerance_exceeded"
            if relative_decimal is None
            or relative_decimal > _decimal(options.radiation_relative_tolerance)
            else "temperature_tolerance_exceeded"
            if delta_temp_decimal > _decimal(options.temperature_tolerance_c)
            else None
        )
        if reason:
            result["exclusions"].append({"day": item.day.isoformat(), "reason": reason})
            continue
        assert relative is not None
        if item.pv_rule != ref.pv_rule:
            values = values.copy()
            values["pv_wh"] = None
            values["pv_evidence"] = "rule_changed"
        reference_pv, candidate_pv = ref_values["pv_wh"], values["pv_wh"]
        paired_absolute_decimal = (
            _decimal(reference_pv) - _decimal(candidate_pv)
            if reference_pv is not None and candidate_pv is not None
            else None
        )
        paired_absolute = (
            float(paired_absolute_decimal) if paired_absolute_decimal is not None else None
        )
        paired_relative = (
            float(paired_absolute_decimal / _decimal(candidate_pv))
            if paired_absolute_decimal is not None and candidate_pv is not None and candidate_pv > 0
            else None
        )
        if any(
            value is not None and not isfinite(value)
            for value in (paired_absolute, paired_relative)
        ):
            paired_absolute = paired_relative = None
        result["candidates"].append(
            {
                "day": item.day.isoformat(),
                **values,
                "seasonal_distance_days": distance,
                "radiation_relative_difference": relative,
                "temperature_difference_c": delta_temp,
                "pv_absolute_difference_wh": paired_absolute,
                "pv_relative_difference": paired_relative,
                "normalized_weather_distance": hypot(
                    relative / options.radiation_relative_tolerance,
                    delta_temp / options.temperature_tolerance_c,
                ),
            }
        )
    result["candidates"].sort(
        key=lambda item: (
            item["normalized_weather_distance"],
            item["seasonal_distance_days"],
            item["day"],
        )
    )
    if result["candidates"]:
        result["status"] = "partial"
    pv = [value for candidate in result["candidates"] if (value := candidate["pv_wh"]) is not None]
    reference_pv = ref_values["pv_wh"]
    if len(pv) >= 3 and reference_pv is not None:
        central = median(pv)
        absolute_decimal = _decimal(reference_pv) - _decimal(central)
        relative_decimal = absolute_decimal / _decimal(central) if central > 0 else None
        absolute = float(absolute_decimal)
        relative = float(relative_decimal) if relative_decimal is not None else None
        if (
            not isfinite(central)
            or not isfinite(absolute)
            or (relative is not None and not isfinite(relative))
        ):
            result["limitations"].append("derived_numeric_overflow")
            return result
        result["group"] = {
            "count": len(pv),
            "median_pv_wh": central,
            "minimum_pv_wh": min(pv),
            "maximum_pv_wh": max(pv),
            "absolute_difference_wh": absolute,
            "relative_difference": relative,
            "check_candidate": bool(
                rref > 0 and relative_decimal is not None and relative_decimal < Decimal("-0.20")
            ),
        }
    elif len(pv) < 3:
        result["limitations"].append("fewer_than_three_complete_pv_comparison_days")
    else:
        result["limitations"].append("reference_pv_intervals_incomplete_or_invalid")
    return result
