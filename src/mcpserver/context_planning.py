"""Authorized request-local assembly; pure scheduling shares the legacy energy solver."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from mcpserver.analysis_context import (
    ContextContract,
    EnergyAnalysisContext,
    EnergyScope,
    ForecastCoverage,
    ProductionAsset,
    ResolvedAssociation,
    SourceSnapshot,
    read_profile_bindings,
    resolve_membership,
    resolve_source_association,
)
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.installation_profile import (
    installation_identity,
    visible_controls,
)
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.load_planning import (
    LoadPlanningOptions,
    PlanningAllocation,
    PlanningLoad,
    PowerScenario,
    plan_loads,
)
from mcpserver.load_planning_runtime import _known_lock, _observed_profiles, _operating_sources
from mcpserver.loxone.models import Control, LoxoneStructure
from mcpserver.loxone.pv_forecast_hours import PvForecastHour, PvForecastResult
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.pv_forecast_runtime import read_pv_forecasts

if TYPE_CHECKING:
    from mcpserver.tools import EventHistoryRuntime


class ContextAllocation(PlanningAllocation):
    load_id: str
    load_kind: Literal["profile", "real", "hypothetical"]


class ContextLoadModel(ContextContract):
    load_id: str
    kind: Literal["profile", "real", "hypothetical"]
    control_uuid: str | None
    cycle_origin: Literal["user_confirmed", "scenario_assumption"]
    energy_origin: Literal["observed_intervals", "user_declared_uniform"]


class ContextPlanningResult(ContextContract):
    method_version: Literal["conditional_context_planning.v1"] = "conditional_context_planning.v1"
    status: Literal["conditional", "unavailable", "no_matching_windows", "budget_limited"]
    scope: EnergyScope
    assets: list[ProductionAsset] = Field(max_length=16)
    forecasts: list[PvForecastResult] = Field(max_length=4)
    coverage: list[ForecastCoverage] = Field(max_length=4)
    associations: list[ResolvedAssociation] = Field(max_length=32)
    load_models: list[ContextLoadModel] = Field(max_length=16)
    assumptions: dict[str, PowerScenario]
    allocations: list[ContextAllocation] = Field(default_factory=list, max_length=16)
    unplanned: dict[str, str] = Field(default_factory=dict, max_length=16)
    evaluated_candidates: int = 0
    profile_revision: int | None = None
    unresolved_associations: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


def combine_forecasts(forecasts: list[PvForecastResult]) -> PvForecastResult:
    """Internal solver input only; output always retains all individual sources."""
    assert forecasts
    combined = forecasts[0].model_copy(deep=True)
    combined.aggregates_kwh = {}
    combined.hours = []
    if any(f.status != "available" for f in forecasts):
        combined.status = "incomplete"
        return combined
    maps = [{(h.start, h.end): h.energy_wh for h in f.hours} for f in forecasts]
    common = set(maps[0]).intersection(*(set(m) for m in maps[1:]))
    for start, end in sorted(common):
        energy = sum(m[(start, end)] for m in maps)
        if not math.isfinite(energy):
            raise ValueError("combined forecast energy overflow")
        combined.hours.append(PvForecastHour(start=start, end=end, energy_wh=energy))
    combined.status = "available" if combined.hours else "incomplete"
    return combined


async def _bindings(
    path: Path | None, identity: str, structure: LoxoneStructure, context: EnergyAnalysisContext
) -> tuple[dict[str, Any], int | None]:
    return await read_profile_bindings(
        path, identity, structure, required=any(load.kind == "profile" for load in context.loads)
    )


async def calculate_context_plan(
    runtime: LoxoneRuntime,
    event_runtime: EventHistoryRuntime | None,
    profile_path: Path | None,
    access: StoredAccessToken,
    options: LoadPlanningOptions,
    *,
    deadline: float,
) -> ContextPlanningResult:
    context = options.analysis_context
    assert context is not None
    if options.interval()[0] < time.time():
        raise ValueError("planning interval must begin in the future")
    async with runtime.snapshot_context(access) as snapshot:
        initial = snapshot.structure
        identity = installation_identity(runtime.endpoint.origin, initial)
        visible = {k: c for k, c in visible_controls(initial).items() if not c.is_hidden}
        bindings, revision = await _bindings(profile_path, identity, initial, context)
        selected = []
        load_controls = {}
        lock_controls: dict[str, tuple[Control, ...]] = {}
        models = []
        loads = []
        missing = {}
        referenced_bindings: set[str] = set()
        for load in context.loads:
            resolved = resolve_source_association(
                load.load_id,
                visible,
                bindings=bindings,
                binding_id=load.binding_id,
                control_uuid=load.control_uuid,
                origin=load.cycle.origin if load.cycle else "user_confirmed",
                expected_role="consumer",
            )
            if load.kind == "profile":
                binding = resolved.binding
                if (
                    not binding
                    or binding.get("role") != "consumer"
                    or not binding.get("load_constraints_usable")
                    or binding["control_uuid"] not in visible
                ):
                    raise ControlOperationError(
                        "not_found", "Confirmed usable load binding required"
                    )
                selected.append({**binding, "binding_id": load.load_id})
                load_controls[load.load_id] = binding["control_uuid"]
                assert load.binding_id is not None
                referenced_bindings.add(load.binding_id)
                companion_id = binding["load_flexibility"]["operating_binding_id"]
                companion = resolve_source_association(
                    load.load_id,
                    visible,
                    bindings=bindings,
                    binding_id=companion_id,
                    expected_role="operating_state",
                )
                assert companion.binding is not None
                referenced_bindings.add(companion_id)
            elif load.kind == "real":
                assert load.control_uuid is not None
                if load.control_uuid not in visible or (
                    load.operating_control_uuid is not None
                    and load.operating_control_uuid not in visible
                ):
                    raise ControlOperationError("not_found", "Load source is not accessible")
                load_controls[load.load_id] = load.control_uuid
                lock_controls[load.load_id] = tuple(
                    visible[uuid]
                    for uuid in (load.control_uuid, load.operating_control_uuid)
                    if uuid is not None
                )
            else:
                lock_controls[load.load_id] = ()
        operating_sources = _operating_sources(selected, bindings, visible)
        for binding in selected:
            lock_controls[binding["binding_id"]] = (
                visible[binding["control_uuid"]],
                operating_sources[binding["binding_id"]],
            )
        associations = resolve_membership(context, visible, load_controls)
        source_ids = (
            {f.control_uuid for f in context.forecasts}
            | {a.production_control_uuid for a in context.assets if a.production_control_uuid}
            | set(load_controls.values())
            | {c.uuid for controls in lock_controls.values() for c in controls}
            | ({context.scope.monitor_uuid} if context.scope.monitor_uuid else set())
        )
        guard = SourceSnapshot.capture(
            runtime.endpoint.origin, initial, source_ids, bindings, revision, referenced_bindings
        )
    # No nested admission: forecast transport and historical reads own their slots.
    forecasts = []
    try:
        batch = await read_pv_forecasts(
            runtime, access, [s.control_uuid for s in context.forecasts]
        )
    except ControlOperationError as exc:
        if exc.code == "not_found":
            raise ControlOperationError(
                "temporarily_unavailable", "Planning context changed"
            ) from None
        raise
    for _, structure, forecast in batch:
        if structure.identity != initial.identity:
            raise ControlOperationError("temporarily_unavailable", "Planning installation changed")
        forecasts.append(forecast)
    combined = combine_forecasts(forecasts)
    observed = [
        b
        for b in selected
        if b["load_flexibility"]["energy_profile_origin"] == "observed_intervals"
    ]
    profiles = (
        await _observed_profiles(
            runtime, event_runtime, access, observed, bindings, options, deadline
        )
        if observed and combined.status == "available"
        else {}
    )
    selected_by_id = {b["binding_id"]: b for b in selected}
    for load in context.loads:
        if load.kind == "profile":
            binding = selected_by_id[load.load_id]
            flex = LoadFlexibility.model_validate(binding["load_flexibility"])
            profile = profiles.get(load.load_id)
            origin: Literal["observed_intervals", "user_declared_uniform"] = "observed_intervals"
            if flex.energy_profile_origin == "user_declared":
                assert flex.declared_cycle_energy_wh is not None
                profile = ((flex.duration_seconds, flex.declared_cycle_energy_wh),)
                origin = "user_declared_uniform"
            cycle_origin: Literal["user_confirmed", "scenario_assumption"] = "user_confirmed"
            if flex.cycle_identity != "user_confirmed_cycle" or not profile:
                missing[load.load_id] = "complete_confirmed_cycle_unavailable"
                continue
        else:
            assert load.cycle is not None
            flex = load.cycle.flexibility(load.load_id)
            profile = ((flex.duration_seconds, load.cycle.cycle_energy_wh),)
            origin = "user_declared_uniform"
            cycle_origin = load.cycle.origin
        models.append(
            ContextLoadModel(
                load_id=load.load_id,
                kind=load.kind,
                control_uuid=load_controls.get(load.load_id),
                cycle_origin=cycle_origin,
                energy_origin=origin,
            )
        )
        loads.append(
            PlanningLoad(
                load.load_id,
                flex,
                profile,
                origin,
                native_locked=_known_lock(runtime, snapshot.subject, lock_controls[load.load_id]),
            )
        )
    solved = await run_admitted_worker(
        plan_loads, combined, tuple(loads), options, now=time.time(), deadline=deadline
    )
    async with runtime.snapshot_context(access) as refreshed:
        after_bindings, after_revision = await _bindings(
            profile_path, identity, refreshed.structure, context
        )
        guard.validate(runtime.endpoint.origin, refreshed.structure, after_bindings, after_revision)
        for allocation in solved.allocations:
            locked = _known_lock(runtime, refreshed.subject, lock_controls[allocation.binding_id])
            if locked:
                raise ControlOperationError("temporarily_unavailable", "Native load lock changed")
            if locked is None and "native_current_lock_unresolved" not in allocation.conditions:
                allocation.conditions.append("native_current_lock_unresolved")
        if any(
            f.status == "available"
            and (f.prediction_at is None or time.time() - f.prediction_at > 10800)
            for f in forecasts
        ):
            raise ControlOperationError("temporarily_unavailable", "PV forecast became stale")
    kinds = {load.load_id: load.kind for load in context.loads}
    unresolved = [
        "forecast_coverage_is_declared_not_native_meter_linkage",
        "native_future_locks_and_operation_permission_unverified",
    ]
    if any(load.kind == "real" and not load.operating_control_uuid for load in context.loads):
        unresolved.append("running_feedback_missing_confirm_program_description")
    if any(load.kind == "real" and load.operating_control_uuid for load in context.loads):
        unresolved.append("declared_running_feedback_semantics_not_measured")
    return ContextPlanningResult(
        status=solved.status,
        scope=context.scope,
        assets=context.assets,
        forecasts=forecasts,
        coverage=context.forecasts,
        associations=associations,
        load_models=models,
        assumptions=solved.assumptions,
        allocations=[
            ContextAllocation(**a.model_dump(), load_id=a.binding_id, load_kind=kinds[a.binding_id])
            for a in solved.allocations
        ],
        unplanned={**solved.unplanned, **missing},
        evaluated_candidates=solved.evaluated_candidates,
        profile_revision=revision,
        unresolved_associations=unresolved,
        limitations=[
            *solved.limitations,
            "one_request_one_budget_not_coordinated_with_other_requests",
            "coverage_confirmations_do_not_independently_prove_physical_disjointness",
            "hypothetical_loads_do_not_satisfy_real_consumer_acceptance",
        ],
    )
