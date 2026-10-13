"""Source-preserving comparisons of independently evidenced historical inputs."""

from __future__ import annotations

import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, Field

from mcpserver.history_analysis import HistoryAnalysisDeadline, SourceAnalysis, StateSegment
from mcpserver.load_cycles import LoadCyclesResult, describe_load_cycles
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.loxone.history_evidence import HistoryInterval, timezone, utc_timestamp
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint

ComparisonOperation = Literal["consumer_ranking", "pv_load_overlap", "operating_phases", "baseload"]


@dataclass(frozen=True, slots=True)
class ComparisonInput:
    summary: SourceAnalysis
    semantics: SeriesSemantics | None = None
    points: tuple[StatisticPoint, ...] = ()
    segments: tuple[StateSegment, ...] = ()
    profile_role: str | None = None
    declared_boundary: str | None = None
    load_flexibility: LoadFlexibility | None = None


class ComparisonResult(BaseModel):
    status: Literal["partial", "insufficient_evidence"] = "insufficient_evidence"
    method: str = "unavailable"
    method_version: Literal["history_comparison.v1"] = "history_comparison.v1"
    unit: str | None = None
    metrics: dict[str, float | int | None] = Field(default_factory=dict, max_length=16)
    metric_units: dict[str, str] = Field(default_factory=dict, max_length=16)
    items: list[dict[str, str | float | int | None]] = Field(default_factory=list, max_length=16)
    usable_intervals: list[HistoryInterval] = Field(default_factory=list, max_length=128)
    usable_intervals_truncated: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=16)
    load_cycles: LoadCyclesResult | None = None


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()


def _hours(
    source: ComparisonInput, start: float, end: float, deadline: float
) -> dict[float, float]:
    """Return whole documented hourly energies in Wh; never allocate partial hours."""
    semantic = source.semantics
    if (
        source.summary.status == "insufficient_evidence"
        or semantic is None
        or semantic.interpretation_status == "invalid"
        or semantic.measurement_quantity != "energy"
        or semantic.timestamp_basis != "unix_utc"
        or semantic.timestamp_position != "interval_start"
        or semantic.value_meaning != "interval_difference_sum"
        or semantic.unit not in {"Wh", "kWh"}
    ):
        return {}
    values: dict[float, float] = {}
    previous = None
    for point in sorted(source.points, key=lambda p: p.timestamp):
        _check(deadline)
        if not start <= point.timestamp or point.timestamp + 3600 > end:
            continue
        value = point.value * (1000 if semantic.unit == "kWh" else 1)
        if (
            not isfinite(value)
            or value < 0
            or (previous is not None and point.timestamp < previous + 3600)
        ):
            return {}
        values[point.timestamp] = value
        previous = point.timestamp
    return values


def _coverage(result: ComparisonResult, hours: list[float]) -> None:
    result.usable_intervals = [
        HistoryInterval(start=utc_timestamp(t), end=utc_timestamp(t + 3600)) for t in hours[:128]
    ]
    result.usable_intervals_truncated = len(hours) > 128


def _finite(result: ComparisonResult) -> ComparisonResult:
    values = list(result.metrics.values()) + [v for item in result.items for v in item.values()]
    if any(isinstance(v, int | float) and not isfinite(v) for v in values):
        return ComparisonResult(limitations=["derived_numeric_overflow"])
    return result


def compare_history(
    operation: ComparisonOperation,
    inputs: tuple[ComparisonInput, ...],
    *,
    start: float,
    end: float,
    timezone_name: str,
    comparable_boundaries_confirmed: bool,
    night_start_hour: int,
    night_end_hour: int,
    deadline: float,
) -> ComparisonResult:
    _check(deadline)
    result = ComparisonResult()
    if operation == "consumer_ranking":
        if not comparable_boundaries_confirmed:
            result.limitations = ["explicit_comparable_boundary_confirmation_required"]
            return result
        boundaries = [source.declared_boundary for source in inputs]
        if (
            len(inputs) < 2
            or any(s.profile_role != "consumer" or not s.summary.binding_id for s in inputs)
            or any(not boundary for boundary in boundaries)
            or len(set(boundaries)) != len(boundaries)
        ):
            result.limitations = ["distinct_confirmed_consumer_boundaries_required"]
            return result
        reference = inputs[0].summary
        if any(
            s.summary.status == "insufficient_evidence"
            or s.summary.unit not in {"Wh", "kWh"}
            or s.summary.method != reference.method
            or (
                reference.method != "whole_hourly_interval_sum"
                and s.summary.usable_intervals != reference.usable_intervals
            )
            or not s.summary.usable_intervals
            or "energy" not in s.summary.metrics
            for s in inputs
        ):
            result.limitations = ["compatible_complete_energy_observation_windows_required"]
            return result
        reference_hours = _hours(inputs[0], start, end, deadline)
        if reference.method == "whole_hourly_interval_sum" and any(
            _hours(source, start, end, deadline).keys() != reference_hours.keys()
            for source in inputs[1:]
        ):
            result.limitations = ["identical_whole_energy_interval_coverage_required"]
            return result
        result.method, result.status, result.unit = (
            "individual_declared_consumer_ranking",
            "partial",
            "Wh",
        )
        result.items = sorted(
            (
                {
                    "binding_id": s.summary.binding_id,
                    "energy": float(s.summary.metrics["energy"] or 0)
                    * (1000 if s.summary.unit == "kWh" else 1),
                }
                for s in inputs
            ),
            key=lambda item: float(item["energy"] or 0),
            reverse=True,
        )
        if reference.method == "whole_hourly_interval_sum":
            _coverage(result, sorted(reference_hours))
        else:
            result.usable_intervals = reference.usable_intervals
        result.limitations = [
            "boundary_compatibility_is_user_declared",
            "individual_counters_are_not_summed_parent_child_overlap_must_be_excluded",
            "source_energy_limits_and_unobserved_resets_still_apply",
        ]
        return _finite(result)
    if operation == "pv_load_overlap":
        production = [s for s in inputs if s.profile_role == "production"]
        load = [s for s in inputs if s.profile_role in {"consumer", "house_consumption"}]
        states = [s for s in inputs if s.summary.source_kind == "event_history"]
        if (
            len(inputs) not in {2, 3}
            or len(production) != 1
            or len(load) != 1
            or len(states) != len(inputs) - 2
            or any(not s.summary.binding_id for s in production + load)
        ):
            result.limitations = ["one_confirmed_production_and_one_load_binding_required"]
            return result
        pv, consumption = (
            _hours(production[0], start, end, deadline),
            _hours(load[0], start, end, deadline),
        )
        common = sorted(pv.keys() & consumption.keys())
        if states:
            active = [segment for segment in states[0].segments if segment.active]
            starts = [segment.start for segment in active]
            gated_hours = []
            for timestamp in common:
                _check(deadline)
                index = bisect_right(starts, timestamp) - 1
                if index >= 0 and timestamp + 3600 <= active[index].end:
                    gated_hours.append(timestamp)
            common = gated_hours
        if not common:
            result.limitations = ["aligned_whole_energy_intervals_required"]
            return result
        result.status, result.method, result.unit = (
            "partial",
            "coincident_hourly_energy_windows",
            "Wh",
        )
        result.metrics = {
            "production_energy": sum(pv[t] for t in common),
            "load_energy": sum(consumption[t] for t in common),
            "coincident_energy_upper_bound": sum(min(pv[t], consumption[t]) for t in common),
            "positive_production_and_load_seconds": 3600
            * sum(pv[t] > 0 and consumption[t] > 0 for t in common),
            "aligned_seconds": 3600 * len(common),
            "production_denominator": sum(pv[t] for t in common),
            "exact_solar_attribution_fraction": None,
        }
        result.metric_units = {
            "production_energy": "Wh",
            "load_energy": "Wh",
            "coincident_energy_upper_bound": "Wh",
            "production_denominator": "Wh",
            "positive_production_and_load_seconds": "s",
            "aligned_seconds": "s",
            "exact_solar_attribution_fraction": "1",
        }
        _coverage(result, common)
        result.limitations = [
            "profile_roles_are_user_declared",
            "hourly_coincidence_is_not_simultaneity_or_exact_solar_attribution",
            "upper_bound_is_not_measured_self_consumption",
            "unmatched_or_partial_intervals_excluded",
            "native_efm_balance_requires_its_separate_supported_contract",
        ]
        if not result.metrics["production_denominator"]:
            result.limitations.append("no_generation_denominator_attribution_undefined")
        if states:
            result.limitations.append("only_whole_energy_intervals_inside_evidenced_active_phases")
        return _finite(result)
    if operation == "operating_phases":
        states = [s for s in inputs if s.summary.source_kind == "event_history"]
        numeric = [s for s in inputs if s.summary.source_kind == "statistic"]
        if len(inputs) != 2 or len(states) != 1 or len(numeric) != 1 or not states[0].segments:
            result.limitations = ["one_evidenced_state_and_one_numeric_source_required"]
            return result
        intervals = _hours(numeric[0], start, end, deadline)
        flexibility = numeric[0].load_flexibility
        if (
            flexibility is not None
            and numeric[0].profile_role == "consumer"
            and states[0].profile_role == "operating_state"
            and states[0].summary.binding_id == flexibility.operating_binding_id
            and numeric[0].summary.binding_id is not None
        ):
            result.load_cycles = describe_load_cycles(
                states[0].segments,
                intervals,
                flexibility,
                numeric[0].summary.binding_id,
                start=start,
                end=end,
                deadline=deadline,
            )
        active = [s for s in states[0].segments if s.active]
        active_starts = [s.start for s in active]

        def in_active(first: float, last: float, *, observation: bool = False) -> bool:
            index = bisect_right(active_starts, first) - 1
            return index >= 0 and (
                last < active[index].end if observation else last <= active[index].end
            )

        inside = [t for t in intervals if in_active(t, t + 3600)]
        semantic = numeric[0].semantics
        samples = []
        if (
            numeric[0].summary.status != "insufficient_evidence"
            and semantic
            and semantic.measurement_quantity == "temperature"
            and semantic.timestamp_basis == "unix_utc"
            and semantic.value_meaning == "sample"
            and semantic.unit is not None
            and semantic.interpretation_status != "invalid"
        ):
            for point in numeric[0].points:
                _check(deadline)
                if start <= point.timestamp < end and in_active(
                    point.timestamp, point.timestamp, observation=True
                ):
                    samples.append(point.value)
        if not inside and not samples:
            result.limitations = ["no_complete_active_energy_intervals_or_temperature_samples"]
            return result
        result.status, result.method = "partial", "observations_inside_evidenced_active_phases"
        try:
            mean = fmean(samples) if samples else None
        except OverflowError:
            return ComparisonResult(limitations=["derived_numeric_overflow"])
        result.metrics = {
            "active_seconds": sum(s.end - s.start for s in active),
            "energy_in_complete_active_intervals_Wh": sum(intervals[t] for t in inside)
            if inside
            else None,
            "temperature_active_sample_mean": mean,
            "temperature_sample_count": len(samples),
        }
        result.metric_units = {
            "active_seconds": "s",
            "energy_in_complete_active_intervals_Wh": "Wh",
        }
        if samples and semantic and semantic.unit:
            result.metric_units["temperature_active_sample_mean"] = semantic.unit
        _coverage(result, sorted(inside))
        result.limitations = [
            "state_duration_is_not_measured_energy",
            "partial_energy_intervals_not_allocated",
            "temperature_mean_is_not_time_weighted",
            "association_is_not_causation_or_exact_solar_attribution",
            "source_gaps_remain_unknown",
        ]
        return _finite(result)
    if len(inputs) != 1:
        result.limitations = ["baseload_requires_one_selected_channel"]
        return result
    if not 0 <= night_start_hour < night_end_hour <= 24:
        raise ValueError("night window requires ordered whole local hours")
    zone = timezone(timezone_name)
    intervals = _hours(inputs[0], start, end, deadline)
    day = datetime.fromtimestamp(start, UTC).astimezone(zone).date()
    local_end = datetime.fromtimestamp(end, UTC).astimezone(zone)
    last_day = local_end.date()
    if local_end.time().replace(tzinfo=None) == datetime.min.time():
        last_day -= timedelta(days=1)
    selected: list[float] = []
    while day <= last_day:
        _check(deadline)
        midnight = datetime.combine(day, datetime.min.time())
        bounds = []
        for hour in (night_start_hour, night_end_hour):
            wall = midnight + timedelta(hours=hour)
            first, second = wall.replace(tzinfo=zone, fold=0), wall.replace(tzinfo=zone, fold=1)
            if (
                first.utcoffset() != second.utcoffset()
                or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall
            ):
                raise ValueError("night window has ambiguous or nonexistent local boundary")
            bounds.append(first.timestamp())
        selected.extend(t for t in intervals if bounds[0] <= t and t + 3600 <= bounds[1])
        day += timedelta(days=1)
    if not selected:
        result.limitations = ["whole_evidenced_nighttime_energy_intervals_required"]
        return result
    # Each documented hour contributes the same real duration, including DST repeats.
    powers = sorted(intervals[t] for t in selected)
    middle = len(powers) // 2
    median = powers[middle] if len(powers) % 2 else powers[middle - 1] / 2 + powers[middle] / 2
    result.status, result.method, result.unit = (
        "partial",
        "time_weighted_median_of_hourly_mean_power",
        "W",
    )
    result.metrics = {
        "nighttime_median_power": median,
        "usable_night_seconds": len(selected) * 3600,
        "estimated_24_hour_energy_Wh": median * 24,
        "night_start_hour": night_start_hour,
        "night_end_hour": night_end_hour,
    }
    result.metric_units = {
        "nighttime_median_power": "W",
        "usable_night_seconds": "s",
        "estimated_24_hour_energy_Wh": "Wh",
        "night_start_hour": "h",
        "night_end_hour": "h",
    }
    _coverage(result, sorted(selected))
    result.limitations = [
        "power_is_derived_hourly_mean_energy_Wh_per_hour_not_instantaneous_power",
        "24_hour_extrapolation_is_an_estimate",
        "only_selected_channel_boundary_not_whole_installation",
        "partial_hours_and_unknown_gaps_excluded",
    ]
    return _finite(result)
