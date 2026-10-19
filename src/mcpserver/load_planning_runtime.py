"""Assemble authorized planning inputs once; never perform I/O in the search."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.history_analysis import SourceAnalysis, StateSegment, reconstruct_segments
from mcpserver.history_comparison import ComparisonInput, qualified_hourly_energy
from mcpserver.installation_profile import (
    ProfileSources,
    ProfileStore,
    installation_identity,
    project_profile,
    visible_controls,
)
from mcpserver.load_cycles import describe_load_cycles
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.load_planning import (
    LoadPlanningOptions,
    LoadPlanningResult,
    PlanningLoad,
    plan_loads,
)
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.history_evidence import timezone
from mcpserver.loxone.models import Control, Freshness, LoxoneStructure
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.pv_forecast_runtime import read_pv_forecast, visible_pvpf

if TYPE_CHECKING:
    from mcpserver.tools import EventHistoryRuntime


async def calculate_load_plan(
    runtime: LoxoneRuntime,
    event_runtime: EventHistoryRuntime | None,
    profile_path: Path,
    access: StoredAccessToken,
    options: LoadPlanningOptions,
    *,
    deadline: float,
) -> LoadPlanningResult:
    assert options.forecast_control_uuid is not None
    assert options.consumer_binding_ids is not None
    begin, _ = options.interval()
    if begin < time.time():
        raise ValueError("planning interval must begin in the future")
    forecast_control, forecast_structure, forecast = await read_pv_forecast(
        runtime, access, options.forecast_control_uuid
    )
    if forecast.status != "available":
        return plan_loads(forecast, (), options, now=time.time(), deadline=deadline)
    async with runtime.snapshot_context(access) as snapshot:
        identity = installation_identity(runtime.endpoint.origin, snapshot.structure)
        store = ProfileStore(profile_path)
        document = await run_admitted_worker(store.read, identity)
        projection = project_profile(
            document,
            identity,
            ProfileSources.from_structure(identity, snapshot.structure),
            limit=256,
        )
        bindings = {b["binding_id"]: b for b in projection["bindings"]}
        selected: list[dict[str, Any]] = []
        visible = {
            key: control
            for key, control in visible_controls(snapshot.structure).items()
            if not control.is_hidden
        }
        for binding_id in options.consumer_binding_ids:
            binding = bindings.get(binding_id)
            if (
                binding is None
                or binding["control_uuid"] not in visible
                or binding["role"] != "consumer"
                or not binding.get("load_constraints_usable")
            ):
                raise ControlOperationError(
                    "not_found", "Confirmed usable consumer binding required"
                )
            selected.append(binding)
        if len({b["control_uuid"] for b in selected}) != len(selected):
            raise ValueError("consumer controls must be distinct")
        operating_sources = _operating_sources(selected, bindings, visible)
    loads = []
    missing: dict[str, str] = {}
    observed = [
        b
        for b in selected
        if b["load_flexibility"]["energy_profile_origin"] == "observed_intervals"
    ]
    profiles = (
        await _observed_profiles(
            runtime, event_runtime, access, observed, bindings, options, deadline
        )
        if observed
        else {}
    )
    for binding in selected:
        flex = LoadFlexibility.model_validate(binding["load_flexibility"])
        if flex.cycle_identity != "user_confirmed_cycle":
            missing[binding["binding_id"]] = "confirmed_complete_cycle_identity_required"
            continue
        profile = profiles.get(binding["binding_id"])
        origin: Literal["observed_intervals", "user_declared_uniform"] = "observed_intervals"
        if flex.energy_profile_origin == "user_declared":
            assert flex.declared_cycle_energy_wh is not None
            profile = ((flex.duration_seconds, flex.declared_cycle_energy_wh),)
            origin = "user_declared_uniform"
        if not profile:
            missing[binding["binding_id"]] = "complete_observed_cycle_unavailable"
            continue
        lock_controls = (
            visible[binding["control_uuid"]],
            operating_sources[binding["binding_id"]],
        )
        loads.append(
            PlanningLoad(
                binding["binding_id"],
                flex,
                profile,
                origin,
                native_locked=_known_lock(runtime, snapshot.subject, lock_controls),
            )
        )
    result = await run_admitted_worker(
        plan_loads,
        forecast,
        tuple(loads),
        options,
        now=time.time(),
        deadline=deadline,
    )
    result.unplanned.update(missing)
    result.profile_revision = document.revision
    # Release source admission before history; reacquire only for publication checks.
    async with runtime.snapshot_context(access) as refreshed:
        current_forecast = visible_pvpf(refreshed.structure, options.forecast_control_uuid)
        if (
            current_forecast.action_uuid != forecast_control.action_uuid
            or current_forecast.state_uuids != forecast_control.state_uuids
            or refreshed.structure.identity != forecast_structure.identity
        ):
            raise ControlOperationError("temporarily_unavailable", "PV forecast source changed")
        after_identity = installation_identity(runtime.endpoint.origin, refreshed.structure)
        after = await run_admitted_worker(store.read, after_identity)
        after_projection = project_profile(
            after,
            after_identity,
            ProfileSources.from_structure(after_identity, refreshed.structure),
            limit=256,
        )
        current = {b["binding_id"]: b for b in after_projection["bindings"]}
        current_visible = {
            key: c for key, c in visible_controls(refreshed.structure).items() if not c.is_hidden
        }
        current_operating = _operating_sources(selected, current, current_visible)
        if (
            after_identity != identity
            or after.revision != document.revision
            or any(
                current.get(b["binding_id"]) != b or b["control_uuid"] not in current_visible
                for b in selected
            )
        ):
            raise ControlOperationError(
                "temporarily_unavailable", "Planning profile or visibility changed"
            )
        for allocation in result.allocations:
            current_lock = _known_lock(
                runtime,
                refreshed.subject,
                (
                    current_operating[allocation.binding_id],
                    current_visible[bindings[allocation.binding_id]["control_uuid"]],
                ),
            )
            if current_lock is True:
                raise ControlOperationError(
                    "temporarily_unavailable", "Native operating lock changed"
                )
            if (
                current_lock is None
                and "native_current_lock_unresolved" not in allocation.conditions
            ):
                allocation.conditions.append("native_current_lock_unresolved")
        if forecast.prediction_at is None or time.time() - forecast.prediction_at > 10800:
            raise ControlOperationError("temporarily_unavailable", "PV forecast became stale")
    return result


def _operating_sources(
    selected: list[dict[str, Any]],
    bindings: dict[str, Any],
    visible: dict[str, Control],
) -> dict[str, Control]:
    result = {}
    seen: set[tuple[str, str]] = set()
    for binding in selected:
        operating = bindings.get(binding["load_flexibility"]["operating_binding_id"])
        if (
            operating is None
            or operating["control_uuid"] not in visible
            or operating.get("role") != "operating_state"
        ):
            raise ControlOperationError("not_found", "Confirmed visible operating binding required")
        key = (operating["control_uuid"], operating["state_uuid"])
        if key in seen:
            raise ValueError("consumer operating associations must be distinct")
        seen.add(key)
        result[binding["binding_id"]] = visible[key[0]]
    return result


def _known_lock(runtime: LoxoneRuntime, subject: str, controls: tuple[Control, ...]) -> bool | None:
    unresolved = not controls
    for control in controls:
        state_uuid = (
            dict(control.state_uuids).get("lockedOn") if control.control_type == "Switch" else None
        )
        if state_uuid:
            record = runtime.cache.get(subject, state_uuid)
            if (
                record.freshness is Freshness.CURRENT
                and type(record.value) in {int, float}
                and record.value == 1
            ):
                return True
            if not (
                record.freshness is Freshness.CURRENT
                and type(record.value) in {int, float}
                and record.value == 0
            ):
                unresolved = True
        else:
            unresolved = True
    return None if unresolved else False


async def _observed_profiles(
    runtime: LoxoneRuntime,
    event_runtime: EventHistoryRuntime | None,
    access: StoredAccessToken,
    selected: list[dict[str, Any]],
    bindings: dict[str, Any],
    options: LoadPlanningOptions,
    deadline: float,
) -> dict[str, tuple[tuple[int, float], ...]]:
    if event_runtime is None:
        return {}
    config = event_runtime._config_store.load()
    if not config.event_history_enabled:
        return {}
    event_store = EventHistoryStore(
        event_runtime._store_path,
        retention_days=config.event_history_retention_days,
        maximum_mib=config.event_history_maximum_mib,
    )
    zone = timezone(options.timezone)
    end = datetime.now(UTC).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=options.history_days)
    begin, finish = start.timestamp(), end.timestamp()
    resolver = StateSemanticsResolver()
    output: dict[str, tuple[tuple[int, float], ...]] = {}
    count = 0
    phase_cache: dict[tuple[str, str], Any] = {}
    async with runtime.history_context(access) as (structure, session):
        controls = {key: c for key, c in visible_controls(structure).items() if not c.is_hidden}
        for binding in selected:
            control = controls.get(binding["control_uuid"])
            flex = LoadFlexibility.model_validate(binding["load_flexibility"])
            operating = bindings.get(flex.operating_binding_id)
            if control is None or binding["source_kind"] != "statistic" or not operating:
                continue
            op_control = controls.get(operating["control_uuid"])
            if op_control is None:
                continue
            _, series, points = await runtime.authorized_statistics(
                access,
                control,
                session,
                binding["series_id"],
                int(begin),
                int(finish) - 1,
                "hour",
                maximum_points=100_000 - count,
            )
            count += len(points)
            semantic = resolver.resolve_series(control, series, granularity="hour")
            summary = SourceAnalysis(
                source_kind="statistic",
                control_uuid=control.uuid,
                source_id=binding["series_id"],
                status="supported",
                method="native_hourly",
            )
            hours = qualified_hourly_energy(
                ComparisonInput(summary, semantic, points), begin, finish, deadline
            )
            key = (op_control.uuid, operating["state_uuid"])
            if key not in phase_cache:
                phases, consumed = await run_admitted_worker(
                    event_store.analysis_phases,
                    *key,
                    start=begin,
                    end=finish,
                    maximum_points=100_000 - count,
                    deadline=deadline,
                )
                count += consumed
                phase_cache[key] = phases
            name = next((n for n, u in op_control.state_uuids if u == key[1]), None)
            if name is None:
                continue

            segments = await run_admitted_worker(
                _operating_segments,
                structure,
                op_control,
                name,
                phase_cache[key],
                begin,
                finish,
            )
            cycles = await run_admitted_worker(
                describe_load_cycles,
                segments,
                hours,
                flex,
                binding["binding_id"],
                start=begin,
                end=finish,
                deadline=deadline,
                newest_complete_only=True,
            )
            usable = [
                c
                for c in cycles.episodes
                if c.boundaries_complete
                and c.energy_profile_complete
                and not c.constraint_discrepancies
                and c.cycle_identity == "user_confirmed_cycle"
            ]
            if usable:
                cycle = max(usable, key=lambda c: datetime.fromisoformat(c.start).timestamp())
                output[binding["binding_id"]] = tuple(
                    (h.duration_seconds, h.energy_wh) for h in cycle.energy_intervals
                )
        await runtime._require_access(access)
    if config != event_runtime._config_store.load():
        raise ControlOperationError("temporarily_unavailable", "History configuration changed")
    return output


def _operating_segments(
    structure: LoxoneStructure,
    control: Control,
    name: str,
    phases: tuple[tuple[float, float, object, tuple[tuple[float, object], ...]], ...],
    begin: float,
    finish: float,
) -> tuple[StateSegment, ...]:
    resolver = StateSemanticsResolver()

    def decode(value: object) -> object:
        _, decoded = resolver.resolve(structure, control, name, value, {})
        return (
            decoded.get("active")
            if isinstance(decoded, dict) and decoded.get("kind") == "binary_state"
            else None
        )

    decoded = tuple(
        (a, b, decode(v), tuple((t, decode(x)) for t, x in changes)) for a, b, v, changes in phases
    )
    return reconstruct_segments(decoded, start=begin, end=finish)
