"""Deterministic history calculations; no transport, authorization or persistence."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import isfinite
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, Field

from mcpserver.loxone.history_evidence import HistoryInterval, utc_timestamp
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint

AnalysisOperation = Literal[
    "temperature_summary",
    "energy",
    "state_duration",
    "consumer_ranking",
    "pv_load_overlap",
    "operating_phases",
    "baseload",
]


class HistoryAnalysisDeadline(RuntimeError):
    """Analysis work exceeded its deadline, independently of native transport."""


@dataclass(frozen=True, slots=True)
class StateSegment:
    start: float
    end: float
    active: bool


class SourceAnalysis(BaseModel):
    source_kind: Literal["statistic", "event_history"]
    control_uuid: str
    source_id: str
    binding_id: str | None = None
    native_source: Literal["statistic_v2", "legacy", "event_history"] | None = None
    semantic_reference: str | None = Field(default=None, max_length=1024)
    status: Literal["supported", "partial", "insufficient_evidence"]
    unit: str | None = None
    method: str
    method_version: Literal["history_analysis.v1"] = "history_analysis.v1"
    metrics: dict[str, float | int | None] = Field(default_factory=dict, max_length=16)
    usable_intervals: list[HistoryInterval] = Field(default_factory=list, max_length=128)
    usable_intervals_truncated: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=16)


def statistic_summary(
    operation: AnalysisOperation,
    semantics: SeriesSemantics,
    points: tuple[StatisticPoint, ...],
    *,
    start: float,
    end: float,
    control_uuid: str,
    source_id: str,
) -> SourceAnalysis:
    result = SourceAnalysis(
        source_kind="statistic",
        control_uuid=control_uuid,
        source_id=source_id,
        status="insufficient_evidence",
        unit=semantics.unit,
        method="unavailable",
    )
    if semantics.timestamp_basis != "unix_utc":
        result.limitations = ["timestamp_basis_not_verified"]
        return result
    if semantics.interpretation_status == "invalid" or semantics.unit is None:
        result.limitations = ["quantity_or_unit_not_verified"]
        return result
    selected = sorted((p for p in points if start <= p.timestamp < end), key=lambda p: p.timestamp)
    if not selected:
        result.limitations = ["no_points_in_requested_interval"]
        return result
    if any(not isfinite(p.value) for p in selected):
        result.limitations = ["nonfinite_values"]
        return result
    if len({p.timestamp for p in selected}) != len(selected):
        result.limitations = ["duplicate_timestamps_not_reconciled"]
        return result
    if (
        operation == "temperature_summary"
        and semantics.measurement_quantity == "temperature"
        and semantics.value_meaning == "sample"
    ):
        result.status, result.method = "partial", "sample_mean"
        values = [p.value for p in selected]
        try:
            mean = fmean(values)
        except OverflowError:
            result.status = "insufficient_evidence"
            result.limitations = ["derived_numeric_overflow"]
            return result
        result.metrics = {
            "sample_count": len(values),
            "mean": mean,
            "minimum": min(values),
            "maximum": max(values),
        }
        result.limitations = [
            "sample_mean_is_not_time_weighted",
            "points_do_not_prove_continuous_coverage",
        ]
        return result
    if operation != "energy" or semantics.measurement_quantity != "energy":
        result.limitations = ["operation_not_supported_by_source_semantics"]
        return result
    if semantics.value_meaning == "cumulative_counter":
        if len(selected) < 2:
            result.limitations = ["two_counter_observations_required"]
            return result
        if any(b.value < a.value for a, b in pairwise(selected)):
            result.limitations = ["counter_decrease_requires_reset_or_rollover_evidence"]
            return result
        result.status, result.method = "partial", "observed_counter_difference"
        energy = selected[-1].value - selected[0].value
        if not isfinite(energy):
            result.status = "insufficient_evidence"
            result.limitations = ["derived_numeric_overflow"]
            return result
        result.metrics = {
            "energy": energy,
            "sample_count": len(selected),
        }
        result.usable_intervals = [
            HistoryInterval(
                start=utc_timestamp(selected[0].timestamp),
                end=utc_timestamp(selected[-1].timestamp),
            )
        ]
        result.limitations = [
            "difference_applies_only_between_observed_endpoints",
            "unobserved_resets_cannot_be_excluded",
            "measurement_boundary_unverified",
            "direction_unverified",
        ]
        return result
    if (
        semantics.value_meaning == "interval_difference_sum"
        and semantics.timestamp_position == "interval_start"
    ):
        whole = [p for p in selected if p.timestamp + 3600 <= end]
        if any(b.timestamp < a.timestamp + 3600 for a, b in pairwise(whole)):
            result.limitations = ["overlapping_energy_intervals_not_reconciled"]
            return result
        if not whole or any(p.value < 0 for p in whole):
            result.limitations = ["no_complete_nonnegative_energy_intervals"]
            return result
        result.method, result.status = "whole_hourly_interval_sum", "partial"
        energy = sum(p.value for p in whole)
        if not isfinite(energy):
            result.status = "insufficient_evidence"
            result.limitations = ["derived_numeric_overflow"]
            return result
        result.metrics = {"energy": energy, "interval_count": len(whole)}
        intervals = [
            HistoryInterval(start=utc_timestamp(p.timestamp), end=utc_timestamp(p.timestamp + 3600))
            for p in whole
        ]
        result.usable_intervals, result.usable_intervals_truncated = (
            intervals[:128],
            len(intervals) > 128,
        )
        result.limitations = [
            "only_whole_documented_intervals",
            "no_missing_interval_interpolation",
            "measurement_boundary_unverified",
            "direction_unverified",
        ]
        return result
    result.limitations = ["energy_representation_not_verified"]
    return result


def reconstruct_segments(
    phases: tuple[tuple[float, float, object, tuple[tuple[float, object], ...]], ...],
    *,
    start: float,
    end: float,
) -> tuple[StateSegment, ...]:
    """Values are already decoded by the semantic adapter; None remains unknown."""
    segments: list[StateSegment] = []
    previous_end = float("-inf")
    for phase_start, phase_end, initial, changes in phases:
        if phase_start < previous_end:
            raise ValueError("overlapping capture phases")
        previous_end = phase_end
        position, value = max(start, phase_start), initial
        for observed, next_value in changes:
            if observed < position or observed >= min(end, phase_end):
                continue
            if isinstance(value, bool) and observed > position:
                segments.append(StateSegment(position, observed, value))
            position, value = observed, next_value
        if isinstance(value, bool) and position < min(end, phase_end):
            segments.append(StateSegment(position, min(end, phase_end), value))
    return tuple(segments)


def duration_summary(
    segments: tuple[StateSegment, ...],
    *,
    start: float,
    end: float,
    control_uuid: str,
    source_id: str,
) -> SourceAnalysis:
    covered = sum(s.end - s.start for s in segments)
    result = SourceAnalysis(
        source_kind="event_history",
        control_uuid=control_uuid,
        source_id=source_id,
        status="supported"
        if abs(covered - (end - start)) < 1e-6
        else "partial"
        if covered
        else "insufficient_evidence",
        unit="s",
        method="observed_state_segments",
        metrics={
            "active_seconds": sum(s.end - s.start for s in segments if s.active),
            "inactive_seconds": sum(s.end - s.start for s in segments if not s.active),
            "unknown_seconds": max(0, end - start - covered),
        },
        usable_intervals=[
            HistoryInterval(start=utc_timestamp(s.start), end=utc_timestamp(s.end))
            for s in segments[:128]
        ],
        usable_intervals_truncated=len(segments) > 128,
        limitations=[
            "state_duration_is_not_measured_energy",
            "reconnect_gaps_and_unknown_values_are_not_activity",
        ],
    )
    if not covered:
        result.metrics = {
            "active_seconds": None,
            "inactive_seconds": None,
            "unknown_seconds": end - start,
        }
    return result
