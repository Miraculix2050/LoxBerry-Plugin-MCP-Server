"""Pure bounded future planning against one shared hourly PV budget."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.loxone.history_evidence import timezone as get_timezone
from mcpserver.loxone.pv_forecast_hours import PvForecastHour, PvForecastResult
from mcpserver.retrospective_shift import _boundary


class ScenarioHour(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: int = Field(gt=0)
    power_w: float = Field(ge=0, le=1e9)


class PowerScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    origin: Literal["user_confirmed", "user_estimate"]
    constant_w: float | None = Field(default=None, ge=0, le=1e9)
    hours: list[ScenarioHour] | None = Field(default=None, min_length=1, max_length=78)

    @model_validator(mode="after")
    def one_model(self) -> PowerScenario:
        if (self.constant_w is None) == (self.hours is None):
            raise ValueError("choose one constant or hourly power scenario")
        if self.hours and len({h.start for h in self.hours}) != len(self.hours):
            raise ValueError("scenario hours must be unique")
        return self

    def at(self, start: int) -> float | None:
        if self.constant_w is not None:
            return self.constant_w
        return next((h.power_w for h in self.hours or [] if h.start == start), None)


class LoadPlanningOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    forecast_control_uuid: str = Field(min_length=1, max_length=128)
    start: str = Field(max_length=64)
    end: str = Field(max_length=64)
    timezone: str = Field(min_length=1, max_length=128)
    consumer_binding_ids: list[str] = Field(min_length=1, max_length=16)
    baseload: PowerScenario
    storage_reserve: PowerScenario
    history_days: int = Field(default=7, ge=1, le=31)

    @model_validator(mode="after")
    def selection(self) -> LoadPlanningOptions:
        import re

        if len(set(self.consumer_binding_ids)) != len(self.consumer_binding_ids) or any(
            re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item) is None for item in self.consumer_binding_ids
        ):
            raise ValueError("consumer bindings must be unique valid identifiers")
        get_timezone(self.timezone)
        self.interval()
        return self

    def interval(self) -> tuple[int, int]:
        first, last = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
        if first.utcoffset() is None or last.utcoffset() is None:
            raise ValueError("planning timestamps require UTC offsets")
        a, b = first.timestamp(), last.timestamp()
        if a != int(a) or b != int(b) or not 0 < b - a <= 72 * 3600:
            raise ValueError("planning interval must contain whole seconds and at most 72 hours")
        return int(a), int(b)


@dataclass(frozen=True)
class PlanningLoad:
    binding_id: str
    flexibility: LoadFlexibility
    # Consecutive duration/energy pieces covering a complete cycle.
    profile: tuple[tuple[int, float], ...]
    energy_origin: Literal["observed_intervals", "user_declared_uniform"]
    native_locked: bool | None = None


class PlanningAllocation(BaseModel):
    binding_id: str
    start: int
    end: int
    cycle_energy_wh: float
    conditional_pv_wh: float
    additional_grid_wh: float
    energy_origin: Literal["observed_intervals", "user_declared_uniform"]
    conditions: list[str] = Field(
        default_factory=lambda: [
            "native_future_locks_and_operational_permission_unverified",
            "minimum_off_time_and_other_activity_require_confirmation",
        ]
    )


class LoadPlanningResult(BaseModel):
    method_version: Literal["conditional_load_planning.v1"] = "conditional_load_planning.v1"
    status: Literal["conditional", "unavailable", "no_matching_windows", "budget_limited"]
    forecast: PvForecastResult
    profile_revision: int | None = None
    assumptions: dict[str, PowerScenario]
    allocations: list[PlanningAllocation] = Field(default_factory=list, max_length=16)
    unplanned: dict[str, str] = Field(default_factory=dict, max_length=16)
    evaluated_candidates: int = 0
    limitations: list[str] = Field(
        default_factory=lambda: [
            "conditional_scenarios_not_device_schedules_or_operation_permission",
            "forecast_not_measured_self_consumption_or_savings",
            "greedy_allocation_not_global_optimum",
            "storage_discharge_and_subhour_pv_dynamics_not_modeled",
            "whole_cycles_remain_contiguous_even_if_interruptible",
        ]
    )


def _window_deadline(load: PlanningLoad, at: int, end: int, zone_name: str) -> float | None:
    flex = load.flexibility
    if flex.timezone != zone_name:
        return None
    day = datetime.fromtimestamp(at, UTC).astimezone(get_timezone(zone_name)).date()
    for anchor in (day - timedelta(days=1), day):
        latest = _boundary(anchor, flex.latest_completion, flex.completion_day_offset, zone_name)
        for window in flex.windows:
            if anchor.weekday() not in window.weekdays:
                continue
            a = _boundary(anchor, window.start, 0, zone_name)
            b = _boundary(anchor, window.end, window.end_day_offset, zone_name)
            if (
                a is not None
                and b is not None
                and latest is not None
                and a <= at < end <= min(b, latest)
            ):
                return latest
    return None


def _demand(load: PlanningLoad, start: int, hours: list[PvForecastHour]) -> dict[int, float] | None:
    """Distribute a confirmed profile over forecast intervals; no PV interpolation."""
    demand: dict[int, float] = {}
    position = start
    for duration, energy in load.profile:
        end = position + duration
        covered = 0
        for hour in hours:
            overlap = max(0, min(end, hour.end) - max(position, hour.start))
            if overlap:
                demand[hour.start] = demand.get(hour.start, 0) + energy * overlap / duration
                covered += overlap
        if covered != duration:
            return None
        position = end
    return demand


def plan_loads(
    forecast: PvForecastResult,
    loads: tuple[PlanningLoad, ...],
    options: LoadPlanningOptions,
    *,
    now: float,
    deadline: float,
) -> LoadPlanningResult:
    begin, finish = options.interval()
    if begin < now:
        raise ValueError("planning interval must begin in the future")
    result = LoadPlanningResult(
        status="unavailable",
        forecast=forecast,
        assumptions={"baseload": options.baseload, "storage_reserve": options.storage_reserve},
    )
    if forecast.status != "available":
        return result
    hours = [h for h in forecast.hours if begin <= h.start and h.end <= finish]
    if not hours:
        result.limitations.append("requested_future_forecast_hours_unavailable")
        return result
    budget: dict[int, float] = {}
    for hour in hours:
        base, reserve = options.baseload.at(hour.start), options.storage_reserve.at(hour.start)
        if base is not None and reserve is not None:
            budget[hour.start] = max(0, hour.energy_wh - base - reserve)
    hours = [h for h in hours if h.start in budget]
    if not hours:
        result.limitations.append("requested_scenario_hour_coverage_unavailable")
        return result
    candidates: dict[str, list[tuple[int, float, dict[int, float]]]] = {}
    by_id = {load.binding_id: load for load in loads}
    for load in loads:
        flex = load.flexibility
        if load.native_locked:
            result.unplanned[load.binding_id] = "known_native_lock"
            continue
        if (
            not load.profile
            or sum(d for d, _ in load.profile) != flex.duration_seconds
            or any(d <= 0 or e < 0 for d, e in load.profile)
        ):
            result.unplanned[load.binding_id] = "complete_cycle_model_missing"
            continue
        candidates[load.binding_id] = []
        for hour in hours:
            if time.monotonic() >= deadline:
                raise HistoryAnalysisDeadline()
            result.evaluated_candidates += 1
            if result.evaluated_candidates > 100_000:
                result.status = "budget_limited"
                return result
            end = hour.start + flex.duration_seconds
            completion = _window_deadline(load, hour.start, end, options.timezone)
            if end > finish or completion is None:
                continue
            demand = _demand(load, hour.start, hours)
            if demand is not None:
                candidates[load.binding_id].append((hour.start, completion, demand))
    while candidates:
        if time.monotonic() >= deadline:
            raise HistoryAnalysisDeadline()
        choices = []
        for binding, rows in candidates.items():
            for start, completion, demand in rows:
                pv = sum(min(value, budget[at]) for at, value in demand.items())
                choices.append((-pv, completion, start, binding, demand))
        if not choices:
            break
        neg_pv, _, start, binding, demand = min(choices, key=lambda row: row[:4])
        if neg_pv >= 0:
            break
        load = by_id[binding]
        energy = sum(demand.values())
        result.allocations.append(
            PlanningAllocation(
                binding_id=binding,
                start=start,
                end=start + load.flexibility.duration_seconds,
                cycle_energy_wh=energy,
                conditional_pv_wh=-neg_pv,
                additional_grid_wh=energy + neg_pv,
                energy_origin=load.energy_origin,
            )
        )
        if load.native_locked is None:
            result.allocations[-1].conditions.append("native_current_lock_unresolved")
        for at, value in demand.items():
            budget[at] -= min(value, budget[at])
        del candidates[binding]
    for load in loads:
        if load.binding_id not in {a.binding_id for a in result.allocations}:
            result.unplanned.setdefault(load.binding_id, "no_window_with_usable_pv_budget")
    result.status = "conditional" if result.allocations else "no_matching_windows"
    return result
