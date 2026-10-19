"""Bounded conditional export absorption; no native lock or operation claim."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment
from mcpserver.load_cycles import ActivityEpisode, LoadCyclesResult
from mcpserver.load_flexibility import LoadFlexibility, clock_minutes
from mcpserver.loxone.history_evidence import timezone, utc_timestamp


@dataclass(frozen=True, slots=True)
class ShiftLoad:
    binding_id: str
    flexibility: LoadFlexibility
    cycles: LoadCyclesResult
    segments: tuple[StateSegment, ...]


class ConditionalHour(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: str
    energy_wh: FiniteFloat = Field(ge=0)


class ConditionalShift(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    binding_id: str
    original_start: str
    original_end: str
    alternative_start: str
    alternative_end: str
    conditional_export_absorption_upper_bound_wh: FiniteFloat = Field(gt=0)
    hourly_absorption: list[ConditionalHour] = Field(min_length=1, max_length=24)
    admissibility: Literal["not_proven"] = "not_proven"
    native_lock_status: Literal["not_checked"] = "not_checked"
    blocking_conditions: list[Literal["historical_native_lock_coverage_missing"]] = Field(
        default=["historical_native_lock_coverage_missing"]
    )


class RetrospectiveShiftResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    method_version: Literal["retrospective_shift.conditional_export.v1"] = (
        "retrospective_shift.conditional_export.v1"
    )
    status: Literal["partial", "insufficient_evidence"] = "insufficient_evidence"
    unit: Literal["Wh"] = "Wh"
    profile_revision: int | None = Field(default=None, ge=0, le=2**31 - 1)
    evaluated_alternatives: int = Field(default=0, ge=0, le=4096)
    examples: list[ConditionalShift] = Field(default_factory=list, max_length=16)
    examples_truncated: bool = False
    excluded_cycles: int = Field(default=0, ge=0, le=112)
    conditional_export_absorption_upper_bound_wh: FiniteFloat = Field(default=0, ge=0)
    qualification: Literal["conditional_only"] = "conditional_only"
    limitations: list[str] = Field(
        default_factory=lambda: [
            "historical_native_locks_not_checked_no_admissible_schedule_claim",
            "boundary_constraints_and_cycle_identity_are_user_declarations",
            "measured_export_is_not_proven_pv_generation",
            "conditional_absorption_is_not_measured_self_consumption_or_net_saving",
            "storage_other_load_responses_and_subhour_dynamics_unknown",
            "whole_contiguous_cycles_only_no_fragmentation_or_operation_authorization",
        ],
        max_length=16,
    )


@dataclass(frozen=True, slots=True)
class _Alternative:
    load: ShiftLoad
    episode: ActivityEpisode
    start: float
    end: float
    demand: tuple[tuple[float, Decimal], ...]


@dataclass(frozen=True, slots=True)
class BudgetCandidate:
    load_id: str
    cycle_id: str
    start: float
    end: float
    minimum_off_seconds: int
    demand: tuple[tuple[float, Decimal], ...]


@dataclass(frozen=True, slots=True)
class BudgetSelection:
    candidate: BudgetCandidate
    allocations: tuple[tuple[float, Decimal], ...]
    absorbed_wh: Decimal


def allocate_candidates(
    candidates: list[BudgetCandidate], budget: dict[float, Decimal], deadline: float
) -> tuple[list[BudgetSelection], bool]:
    """Allocate one measured budget; candidates carry no fabricated source provenance."""
    budget = dict(budget)
    selections: list[BudgetSelection] = []
    remaining = 128
    for candidate in candidates:
        _check(deadline)
        if (
            not isfinite(candidate.start)
            or not isfinite(candidate.end)
            or candidate.start >= candidate.end
            or len({at for at, _ in candidate.demand}) != len(candidate.demand)
            or any(
                at not in budget or not value.is_finite() or value < 0
                for at, value in candidate.demand
            )
        ):
            raise ValueError("invalid shared-budget candidate")
    while candidates:
        _check(deadline)
        score, chosen = min(
            (
                (sum((min(value, budget[at]) for at, value in c.demand), Decimal(0)), c)
                for c in candidates
            ),
            key=lambda pair: (-pair[0], pair[1].start, pair[1].load_id, pair[1].cycle_id),
        )
        if score == 0:
            break
        if len(selections) == 16 or len(chosen.demand) > remaining:
            return selections, True
        allocations = tuple((at, min(value, budget[at])) for at, value in chosen.demand)
        for at, value in allocations:
            budget[at] -= value
        remaining -= len(allocations)
        selections.append(BudgetSelection(chosen, allocations, score))
        candidates = [
            c
            for c in candidates
            if not (
                c.load_id == chosen.load_id
                and (
                    c.cycle_id == chosen.cycle_id
                    or (
                        c.start - chosen.minimum_off_seconds < chosen.end
                        and chosen.start < c.end + chosen.minimum_off_seconds
                    )
                )
            )
        ]
    return selections, False


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()


def _boundary(day: date, clock: str, offset: int, zone_name: str) -> float | None:
    """Reject nonexistent and ambiguous local clocks rather than selecting a fold."""
    minutes = clock_minutes(clock)
    local = datetime.combine(day + timedelta(days=offset), datetime.min.time()) + timedelta(
        minutes=minutes
    )
    zone = timezone(zone_name)
    values = {
        local.replace(tzinfo=zone, fold=fold).timestamp()
        for fold in (0, 1)
        if local.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == local
    }
    return next(iter(values)) if len(values) == 1 else None


def _inactive(
    segments: tuple[StateSegment, ...], start: float, end: float, deadline: float
) -> bool:
    position = start
    capture = None
    for segment in segments:
        _check(deadline)
        if segment.end <= position:
            continue
        if segment.start > position or segment.active or segment.capture_index is None:
            return False
        if capture is not None and segment.capture_index != capture:
            return False
        capture = segment.capture_index
        position = min(end, segment.end)
        if position == end:
            return True
    return False


def conditional_retrospective_shift(
    loads: tuple[ShiftLoad, ...],
    export_hours: dict[float, float],
    *,
    start: float,
    end: float,
    deadline: float,
) -> RetrospectiveShiftResult:
    """Inputs have passed source/semantic gates; unknown locks stay blocking."""
    # Cover the complete finite float exponent range without dropping small
    # allocations from a large shared budget during subtraction or ranking.
    with localcontext() as context:
        context.prec = 800
        return _conditional_retrospective_shift(loads, export_hours, start, end, deadline)


def observed_candidates(
    loads: tuple[ShiftLoad, ...],
    export_hours: dict[float, float],
    start: float,
    end: float,
    deadline: float,
) -> tuple[RetrospectiveShiftResult, list[_Alternative]]:
    _check(deadline)
    result = RetrospectiveShiftResult()
    alternatives: list[_Alternative] = []
    if (
        not loads
        or len(loads) > 7
        or len(export_hours) > 768
        or not isfinite(start)
        or not isfinite(end)
        or not start < end
    ):
        raise ValueError("retrospective input bounds invalid")
    if sum(len(load.segments) for load in loads) > 100_000:
        raise ValueError("retrospective input point limit exceeded")
    if len({load.binding_id for load in loads}) != len(loads) or len(
        {load.flexibility.operating_binding_id for load in loads}
    ) != len(loads):
        raise ValueError("duplicate retrospective load association")
    ordered_hours = sorted(export_hours)
    if any(
        not isfinite(at) or not isfinite(value) or value < 0 or not start <= at < at + 3600 <= end
        for at, value in export_hours.items()
    ) or any(b < a + 3600 for a, b in pairwise(ordered_hours)):
        raise ValueError("export interval energy invalid")
    budget = {at: Decimal(str(value)) for at, value in export_hours.items()}
    for load in loads:
        _check(deadline)
        flex = load.flexibility
        if load.cycles.consumer_binding_id != load.binding_id or (
            load.cycles.operating_binding_id != flex.operating_binding_id
        ):
            raise ValueError("cycle association mismatch")
        if load.cycles.truncated or load.cycles.energy_intervals_truncated:
            result.limitations.append("complete_cycle_inventory_output_budget_missing")
            return result, []
        for episode in load.cycles.episodes:
            _check(deadline)
            original = datetime.fromisoformat(episode.start)
            original_end = datetime.fromisoformat(episode.end)
            if original.tzinfo is None or original_end.tzinfo is None:
                raise ValueError("cycle timestamps require timezone")
            observed_start, observed_end = original.timestamp(), original_end.timestamp()
            energy = episode.energy_intervals
            eligible = (
                episode.boundaries_complete
                and episode.energy_profile_complete
                and episode.cycle_identity == flex.cycle_identity == "user_confirmed_cycle"
                and flex.energy_profile_origin
                == load.cycles.energy_profile_origin
                == "observed_intervals"
                and not episode.constraint_discrepancies
                and observed_end - observed_start
                == episode.observed_duration_seconds
                == flex.duration_seconds
                and start < observed_start < observed_end < end
                and len(energy) * 3600 == flex.duration_seconds
                and all(item.offset_seconds == i * 3600 for i, item in enumerate(energy))
                and episode.observed_energy_wh is not None
            )
            if not eligible:
                result.excluded_cycles += 1
                continue
            day = original.astimezone(timezone(flex.timezone)).date()
            completion = _boundary(
                day, flex.latest_completion, flex.completion_day_offset, flex.timezone
            )
            windows = [
                (
                    _boundary(day, w.start, 0, flex.timezone),
                    _boundary(day, w.end, w.end_day_offset, flex.timezone),
                )
                for w in flex.windows
                if day.weekday() in w.weekdays
            ]
            for at in ordered_hours:
                _check(deadline)
                finish = at + flex.duration_seconds
                if (
                    completion is None
                    or finish > completion
                    or not start <= at < finish <= end
                    or not any(
                        a is not None and b is not None and a <= at < finish <= b
                        for a, b in windows
                    )
                    or (at < observed_end and observed_start < finish)
                ):
                    continue
                if result.evaluated_alternatives == 4096:
                    result.limitations.append(
                        "alternative_search_budget_exceeded_no_partial_allocation"
                    )
                    return result, []
                result.evaluated_alternatives += 1
                if not _inactive(
                    load.segments,
                    at - flex.minimum_off_seconds,
                    finish + flex.minimum_off_seconds,
                    deadline,
                ) or any(at + item.offset_seconds not in budget for item in energy):
                    continue
                demand = tuple(
                    (at + item.offset_seconds, Decimal(str(item.energy_wh))) for item in energy
                )
                if any(min(value, budget[position]) > 0 for position, value in demand):
                    alternatives.append(_Alternative(load, episode, at, finish, demand))
    return result, alternatives


def _conditional_retrospective_shift(
    loads: tuple[ShiftLoad, ...],
    export_hours: dict[float, float],
    start: float,
    end: float,
    deadline: float,
) -> RetrospectiveShiftResult:
    result, alternatives = observed_candidates(loads, export_hours, start, end, deadline)
    if not alternatives:
        if not any("budget" in item for item in result.limitations):
            result.limitations.append("no_complete_positive_conditional_alternative")
        return result
    budget = {at: Decimal(str(value)) for at, value in export_hours.items()}
    candidates = {
        BudgetCandidate(
            alt.load.binding_id,
            alt.episode.start,
            alt.start,
            alt.end,
            alt.load.flexibility.minimum_off_seconds,
            alt.demand,
        ): alt
        for alt in alternatives
    }
    selections, result.examples_truncated = allocate_candidates(list(candidates), budget, deadline)
    total = sum((s.absorbed_wh for s in selections), Decimal(0))
    if not isfinite(float(total)):
        return RetrospectiveShiftResult(limitations=["derived_numeric_overflow"])
    for selection in selections:
        chosen = candidates[selection.candidate]
        result.examples.append(
            ConditionalShift(
                binding_id=chosen.load.binding_id,
                original_start=chosen.episode.start,
                original_end=chosen.episode.end,
                alternative_start=utc_timestamp(chosen.start),
                alternative_end=utc_timestamp(chosen.end),
                conditional_export_absorption_upper_bound_wh=float(selection.absorbed_wh),
                hourly_absorption=[
                    ConditionalHour(start=utc_timestamp(at), energy_wh=float(value))
                    for at, value in selection.allocations
                ],
            )
        )
    result.conditional_export_absorption_upper_bound_wh = float(total)
    if result.examples:
        result.status = "partial"
    else:
        result.limitations.append("no_complete_positive_conditional_alternative")
    return result
