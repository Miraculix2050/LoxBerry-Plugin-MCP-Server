"""Bounded observed activity episodes, distinct from native program identity."""

from __future__ import annotations

import time
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.loxone.history_evidence import utc_timestamp


class CycleEnergyInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset_seconds: int = Field(ge=0, le=86400)
    duration_seconds: Literal[3600] = 3600
    energy_wh: FiniteFloat = Field(ge=0)


class ActivityEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: str
    end: str
    observed_duration_seconds: FiniteFloat = Field(gt=0)
    boundaries_complete: bool
    energy_profile_complete: bool
    observed_energy_wh: FiniteFloat | None
    energy_intervals: list[CycleEnergyInterval] = Field(max_length=24)
    declared_cycle_energy_wh: FiniteFloat | None
    cycle_identity: Literal["active_episode_only", "user_confirmed_cycle"]
    identity_origin: Literal["user_declared"] = "user_declared"
    constraint_discrepancies: list[str] = Field(max_length=8)
    limitations: list[str] = Field(max_length=8)


class LoadCyclesResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    method_version: Literal["load_cycles.observed_activity.v1"] = "load_cycles.observed_activity.v1"
    status: Literal["partial", "insufficient_evidence"]
    consumer_binding_id: str
    operating_binding_id: str
    profile_revision: int | None = Field(default=None, ge=0, le=2**31 - 1)
    energy_profile_origin: Literal["observed_intervals", "user_declared"]
    episode_count: int = Field(ge=0, le=100_000)
    episodes: list[ActivityEpisode] = Field(max_length=16)
    truncated: bool
    energy_intervals_truncated: bool = False
    native_lock_status: Literal["not_checked"] = "not_checked"
    planning_status: Literal["not_evaluated"] = "not_evaluated"
    limitations: list[str] = Field(max_length=8)


def describe_load_cycles(
    segments: tuple[StateSegment, ...],
    energy_hours: dict[float, float],
    flexibility: LoadFlexibility,
    consumer_binding_id: str,
    *,
    start: float,
    end: float,
    deadline: float,
) -> LoadCyclesResult:
    """Energy hours are already qualified by the existing native interval adapter."""

    def check() -> None:
        if time.monotonic() >= deadline:
            raise HistoryAnalysisDeadline()

    check()
    merged: list[StateSegment] = []
    for segment in segments:
        check()
        if not start <= segment.start < segment.end <= end:
            raise ValueError("activity episode lies outside analysis interval")
        if merged and segment.start < merged[-1].end:
            raise ValueError("overlapping activity segments")
        if (
            merged
            and segment.start == merged[-1].end
            and segment.active == merged[-1].active
            and segment.capture_index is not None
            and segment.capture_index == merged[-1].capture_index
        ):
            previous = merged[-1]
            merged[-1] = StateSegment(
                previous.start, segment.end, previous.active, previous.capture_index
            )
        else:
            merged.append(segment)
    count = sum(segment.active for segment in merged)
    if count > 100_000:
        raise ValueError("activity input point limit exceeded")
    result = LoadCyclesResult(
        status="insufficient_evidence",
        consumer_binding_id=consumer_binding_id,
        operating_binding_id=flexibility.operating_binding_id,
        energy_profile_origin=flexibility.energy_profile_origin,
        episode_count=count,
        episodes=[],
        truncated=count > 16,
        limitations=[
            "local_observation_edges_are_not_native_program_identity",
            "constraints_and_cycle_identity_are_user_declarations",
            "native_locks_are_not_checked_and_must_never_be_overridden",
            "no_scheduling_or_operation_authorization",
        ],
    )
    remaining = 128
    for index, active in enumerate(merged):
        check()
        if not active.active or len(result.episodes) == 16:
            continue
        before = merged[index - 1] if index else None
        after = merged[index + 1] if index + 1 < len(merged) else None
        complete = (
            active.capture_index is not None
            and before is not None
            and after is not None
            and not before.active
            and not after.active
            and before.end == active.start
            and after.start == active.end
            and before.capture_index == active.capture_index == after.capture_index
            and start < active.start < active.end < end
        )
        limits = [] if complete else ["both_edges_in_one_continuous_capture_not_proven"]
        duration = active.end - active.start
        discrepancies = []
        if duration != flexibility.duration_seconds:
            discrepancies.append("observed_duration_differs_from_declared_duration")
        if duration < flexibility.minimum_run_seconds:
            discrepancies.append("minimum_run_not_observed")
        if (
            before is None
            or before.capture_index != active.capture_index
            or before.end != active.start
            or before.end - before.start < flexibility.minimum_off_seconds
        ):
            discrepancies.append("minimum_off_not_proven")
        hours = int(duration / 3600)
        positions = [active.start + offset * 3600 for offset in range(min(hours, 24))]
        energy_available = (
            complete
            and duration == hours * 3600
            and 0 < hours <= 24
            and all(at in energy_hours for at in positions)
        )
        energy_complete = energy_available and remaining >= hours
        if energy_available and not energy_complete:
            result.energy_intervals_truncated = True
            limits.append("energy_profile_output_budget_exceeded")
        intervals = []
        if energy_complete:
            intervals = [
                CycleEnergyInterval(offset_seconds=i * 3600, energy_wh=energy_hours[at])
                for i, at in enumerate(positions)
            ]
            remaining -= hours
        else:
            limits.append("complete_whole_cycle_energy_intervals_not_available")
        total = sum(i.energy_wh for i in intervals) if energy_complete else None
        if total is not None and not isfinite(total):
            total = None
            energy_complete = False
            intervals = []
            remaining += hours
            limits.append("derived_numeric_overflow")
        if flexibility.cycle_identity == "active_episode_only":
            limits.append("complete_program_cycle_identity_not_confirmed")
        result.episodes.append(
            ActivityEpisode(
                start=utc_timestamp(active.start),
                end=utc_timestamp(active.end),
                observed_duration_seconds=duration,
                boundaries_complete=complete,
                energy_profile_complete=energy_complete,
                observed_energy_wh=total,
                energy_intervals=intervals,
                declared_cycle_energy_wh=flexibility.declared_cycle_energy_wh,
                cycle_identity=flexibility.cycle_identity,
                constraint_discrepancies=discrepancies,
                limitations=limits,
            )
        )
    if result.episodes:
        result.status = "partial"
    return result
