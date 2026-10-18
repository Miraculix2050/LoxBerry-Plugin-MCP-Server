"""Numerical day adapter: one authorized range read per qualified local source."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from math import ceil, fsum, isfinite
from statistics import median
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.comparable_days import (
    DayEvidence,
    HourEvidence,
    Options,
    PVRule,
    RadiationRule,
    TemperatureRule,
    _boundary,
    _check,
    compare_days,
)
from mcpserver.comparable_days_models import (
    DayMetricComparison,
    NumericalComparableDayOptions,
    NumericalComparableDaysResult,
    SolarSourceSummary,
)
from mcpserver.history_analysis import statistic_summary
from mcpserver.history_comparison import (
    ComparisonInput,
    hourly_energy_semantics_qualified,
    qualified_hourly_energy,
)
from mcpserver.installation_profile import installation_identity, visible_controls
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.history_evidence import timezone
from mcpserver.loxone.pv_forecast import decode
from mcpserver.loxone.runtime import ControlOperationError
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.uuid import normalize_loxone_uuid
from mcpserver.solar_history import ObservationContract, normalize_hours
from mcpserver.solar_recording import SolarHistory, SolarRecordingSource, observations

if TYPE_CHECKING:
    from mcpserver.auth.provider import StoredAccessToken
    from mcpserver.loxone.models import LoxoneStructure
    from mcpserver.loxone.runtime import LoxoneRuntime
    from mcpserver.tools import EventHistoryRuntime


class SolarAnalysisSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_kind: Literal["solar_observation"]
    control_uuid: str = Field(min_length=1, max_length=128)
    state_uuid: str | None = Field(default=None, min_length=1, max_length=128)
    binding_id: None = None

    @field_validator("control_uuid", "state_uuid")
    @classmethod
    def uuid(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None


def _metric(
    selected: list[str],
    reference: str,
    day_starts: dict[str, list[float]],
    hours: dict[float, float],
    method: Literal["unavailable", "direct_observed", "pv_minus_export"],
) -> DayMetricComparison:
    if method == "unavailable":
        return DayMetricComparison(
            limitations=["confirmed_self_consumption_or_matching_pv_export_boundary_required"]
        )
    totals = {}
    exclusions = []
    for day in [reference, *selected]:
        starts = day_starts[day]
        if starts and all(t in hours for t in starts):
            try:
                total = fsum(hours[t] for t in starts)
            except OverflowError:
                total = float("inf")
            if isfinite(total):
                totals[day] = total
            else:
                exclusions.append({"day": day, "reason": "derived_numeric_overflow"})
        else:
            exclusions.append({"day": day, "reason": "self_consumption_common_window_incomplete"})
    ref = totals.get(reference)
    pairs: list[dict[str, Any]] = [
        {
            "day": day,
            "energy_wh": totals[day],
            "absolute_difference_wh": ref - totals[day] if ref is not None else None,
            "relative_difference": (ref - totals[day]) / totals[day]
            if ref is not None and totals[day] > 0
            else None,
        }
        for day in selected
        if day in totals
    ]
    for pair in pairs:
        if any(
            v is not None and not isfinite(v)
            for k, v in pair.items()
            if k.endswith("difference") or k.endswith("difference_wh")
        ):
            pair["absolute_difference_wh"] = pair["relative_difference"] = None
    group = None
    if ref is not None and len(pairs) >= 3:
        values = [totals[p["day"]] for p in pairs]
        middle = median(values)
        group = dict(
            count=len(values),
            median_wh=middle,
            minimum_wh=min(values),
            maximum_wh=max(values),
            absolute_difference_wh=ref - middle,
            relative_difference=(ref - middle) / middle if middle > 0 else None,
        )
        if any(not isfinite(v) for v in group.values() if isinstance(v, float)):
            group = None
    return DayMetricComparison.model_validate(
        dict(
            status="partial" if group else "insufficient_evidence",
            method=method,
            reference_wh=ref,
            pairs=pairs,
            group=group,
            exclusions=exclusions,
            limitations=[
                "same_weather_selected_days_and_fixed_hour_window",
                "no_storage_balance_or_causal_diagnosis",
            ],
        )
    )


def _forecast_context(rows: list[tuple[float, dict[str, object]]]) -> list[dict[str, Any]]:
    """Bounded latest revisions; native cycle times do not establish period bounds."""
    result = []
    for captured, payload in rows[-8:]:
        states = payload.get("states")
        if not isinstance(states, dict):
            continue
        try:
            decoded = {
                name: decode(name, states.get(name), states)
                for name in ("period", "today", "tomorrow", "after")
            }
        except ValueError:
            continue
        period = decoded["period"]
        times = period.get("times")
        times = times if isinstance(times, dict) else {}
        result.append(
            dict(
                captured_at=datetime.fromtimestamp(captured, UTC).isoformat(),
                predicted_at=times.get("predicted_at"),
                cycle_from=times.get("cycle_from"),
                cycle_until=times.get("cycle_until"),
                status=period["status"],
                period_kwh=period["energy_kwh"],
                today_kwh=decoded["today"]["energy_kwh"],
                tomorrow_kwh=decoded["tomorrow"]["energy_kwh"],
                after_kwh=decoded["after"]["energy_kwh"],
                inputperiod_hours=period["period_hours"],
            )
        )
    return result


def _calculate(
    local: list[tuple[SolarRecordingSource, str, list[tuple[float, dict[str, object]]]]],
    energies: dict[str, dict[float, float]],
    *,
    begin: float,
    finish: float,
    zone_name: str,
    options: NumericalComparableDayOptions,
    installation: str,
    balance_matches: bool,
    deadline: float,
    now: datetime,
) -> NumericalComparableDaysResult:
    now = datetime.fromtimestamp(min(now.timestamp(), finish), UTC)
    zone = timezone(zone_name)
    first = datetime.fromtimestamp(begin, zone).date()
    last_local = datetime.fromtimestamp(finish, zone)
    last = last_local.date() - (
        timedelta(days=1) if last_local.time() == datetime.min.time() else timedelta()
    )
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    starts_by_day: dict[str, list[float]] = {}
    invalid_days: set[date] = set()
    starts = []
    for day in days:
        _check(deadline)
        day_starts = []
        try:
            for hour in range(options.start_hour, options.end_hour):
                t, end = _boundary(day, hour, zone), _boundary(day, hour + 1, zone)
                if end - t != 3600:
                    raise ValueError("non_hourly_local_window")
                if begin <= t and end <= finish and end <= now.timestamp():
                    starts.append(t)
                    day_starts.append(t)
        except ValueError:
            invalid_days.add(day)
        starts_by_day[day.isoformat()] = day_starts
    normalized: dict[str, dict[float, float]] = {}
    summaries = []
    generations = []
    forecasts = []
    for source, fingerprint, rows in local:
        _check(deadline)
        generations.append(fingerprint)
        if source.kind == "pv_forecast":
            forecasts.extend(rows)
            summaries.append(
                SolarSourceSummary(
                    control_uuid=source.control_uuid,
                    kind=source.kind,
                    unit=source.unit,
                    input_points=len(rows),
                    normalized_hours=0,
                    value_origin="forecast",
                )
            )
            continue
        contract = ObservationContract(
            source.kind,
            source.unit,
            installation,
            fingerprint,
            "administrator_confirmed_local_source.v1",
            source.sampling_period_seconds,
        )
        hours = normalize_hours(
            observations(rows), contract, sorted(set(starts)), deadline=deadline
        )
        normalized[source.kind] = {h.start: h.value for h in hours}
        offsets = [abs(h.sample_at - h.start) for h in hours if h.sample_at is not None]
        summaries.append(
            SolarSourceSummary(
                control_uuid=source.control_uuid,
                state_uuid=source.state_uuid,
                kind=source.kind,
                unit=source.unit,
                input_points=len(rows),
                normalized_hours=len(hours),
                value_origin="estimated_from_observed_source_states"
                if source.kind == "irradiance"
                else "observed_source_states",
                maximum_sample_offset_seconds=max(offsets) if offsets else None,
            )
        )
    generation = hashlib.sha256("/".join(sorted(generations)).encode()).hexdigest()
    radiation, temperatures, pv = (
        normalized.get("irradiance", {}),
        normalized.get("temperature", {}),
        energies.get("production", {}),
    )
    evidence = tuple(
        DayEvidence(
            day,
            tuple(
                HourEvidence(t, t + 3600, radiation.get(t), temperatures.get(t), pv.get(t))
                for t in starts_by_day[day.isoformat()]
            ),
            RadiationRule.ESTIMATED_SAMPLE_ENERGY,
            TemperatureRule.CELSIUS_NEAR_HOUR_START,
            PVRule.HOURLY_ENERGY_WH if "production" in energies else None,
            installation,
            generation,
            ("ambiguous_or_nonexistent_local_window",) if day in invalid_days else (),
            "within_60s_of_hour_start",
        )
        for day in days
    )
    result = compare_days(
        evidence,
        reference=date.fromisoformat(options.reference_day),
        timezone_name=zone_name,
        now=now,
        options=Options(
            **options.model_dump(exclude={"method", "reference_day", "pv_export_balance_confirmed"})
        ),
        deadline=deadline,
    )
    # Self consumption uses the fixed reference window, never a coverage-dependent subset.
    positions = result["common_hour_positions"]
    metric_starts: dict[str, list[float]] = {}
    for day in days:
        try:
            metric_starts[day.isoformat()] = [_boundary(day, h, zone) for h in positions]
        except ValueError:
            metric_starts[day.isoformat()] = []
    self_hours = energies.get("self_consumption", {})
    method: Literal["unavailable", "direct_observed", "pv_minus_export"] = (
        "direct_observed" if "self_consumption" in energies else "unavailable"
    )
    if (
        method == "unavailable"
        and options.pv_export_balance_confirmed
        and balance_matches
        and {"production", "grid_export"} <= energies.keys()
    ):
        exported = energies.get("grid_export", {})
        self_hours = {
            t: value - exported[t]
            for t, value in pv.items()
            if t in exported and value >= exported[t]
        }
        method = "pv_minus_export"
    metric = _metric(
        [c["day"] for c in result["candidates"]],
        options.reference_day,
        metric_starts,
        self_hours,
        method,
    )
    deviations = [
        dict(
            day=c["day"],
            metric="pv_yield",
            absolute_difference_wh=c["pv_absolute_difference_wh"],
            relative_difference=c["pv_relative_difference"],
        )
        for c in result["candidates"]
        if c["pv_absolute_difference_wh"] is not None
    ]
    deviations.extend(
        dict(
            day=p.day,
            metric="self_consumption",
            absolute_difference_wh=p.absolute_difference_wh,
            relative_difference=p.relative_difference,
        )
        for p in metric.pairs
        if p.absolute_difference_wh is not None
    )
    deviations.sort(key=lambda x: (x["absolute_difference_wh"], x["day"], x["metric"]))
    guidance = []
    if not radiation:
        guidance.append(
            "selected_irradiance_has_no_complete_hours_no_backfill_enable_or_continue_recording"
            if "irradiance" in normalized
            else (
                "admin_register_independent_irradiance_with_documented_unit_cadence_and_enable_recording"
            )
        )
    if not temperatures:
        guidance.append(
            "selected_temperature_has_no_complete_hours_no_backfill_enable_or_continue_recording"
            if "temperature" in normalized
            else "admin_register_outside_temperature_celsius_and_enable_recording"
        )
    if not pv:
        guidance.append(
            "confirm_visible_production_profile_binding_to_documented_hourly_energy_statistic"
        )
    return NumericalComparableDaysResult.model_validate(
        {
            **result,
            "radiation_origin": "estimated_from_source_samples",
            "temperature_position": "within_60s_of_hour_start",
            "self_consumption": metric,
            "ranked_deviations": deviations,
            "forecast_context": _forecast_context(forecasts),
            "forecast_context_truncated": len(forecasts) > 8,
            "forecast_limitations": [
                "native_period_bounds_unverified_cycle_times_describe_current_prediction_hour",
                "no_subdaily_forecast_distribution",
            ],
            "solar_sources": summaries,
            "configuration_guidance": guidance,
        }
    )


async def numerical_day_analysis(
    runtime: LoxoneRuntime,
    event_runtime: EventHistoryRuntime | None,
    access: StoredAccessToken,
    structure: LoxoneStructure,
    session: Any,
    selectors: list[dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
    *,
    begin: float,
    finish: float,
    zone_name: str,
    options: NumericalComparableDayOptions,
    deadline: float,
) -> tuple[NumericalComparableDaysResult, int]:
    if event_runtime is None:
        raise ControlOperationError(
            "temporarily_unavailable", "Local solar history is not configured"
        )
    config = await run_admitted_worker(event_runtime._config_store.load)
    if not config.loxone_history_enabled:
        raise ControlOperationError(
            "permission_denied", "History requires administrator activation"
        )
    if MiniserverEndpoint.parse(config.loxone_endpoint).origin != runtime.endpoint.origin:
        raise ControlOperationError(
            "temporarily_unavailable", "Solar endpoint configuration changed"
        )
    installation = installation_identity(runtime.endpoint.origin, structure)
    controls = visible_controls(structure)
    store = SolarHistory(
        EventHistoryStore(
            event_runtime._store_path,
            retention_days=config.event_history_retention_days,
            maximum_mib=config.event_history_maximum_mib,
        )
    )
    local = []
    count = 0
    seen: set[tuple[str, ...]] = set()
    roles: dict[str, tuple[Any, dict[str, Any]]] = {}
    local_kinds: set[str] = set()
    resolver = StateSemanticsResolver()
    energies = {}
    now = datetime.now(UTC)
    for selector in selectors:
        _check(deadline)
        if selector.get("source_kind") == "solar_observation":
            source = next(
                (
                    s
                    for s in config.solar_history_sources
                    if (s.control_uuid, s.state_uuid)
                    == (selector["control_uuid"], selector.get("state_uuid"))
                ),
                None,
            )
            if source is None or source.control_uuid not in controls:
                raise ControlOperationError(
                    "not_found", "Registered visible solar source is not available"
                )
            key: tuple[str, ...] = (source.key,)
            if key in seen:
                continue
            if source.kind in local_kinds:
                raise ValueError("one distinct local source per solar quantity required")
            seen.add(key)
            local_kinds.add(source.kind)
            try:
                fingerprint = source.fingerprint(controls[source.control_uuid], installation)
            except ValueError as exc:
                raise ControlOperationError(
                    "not_found", "Registered visible solar source is not available"
                ) from exc
            margin = min(3600, 2 * source.sampling_period_seconds)
            await runtime._require_access(access)
            rows, consumed = await run_admitted_worker(
                store.read,
                source,
                fingerprint,
                begin - margin,
                min(now.timestamp(), finish + margin),
                maximum_points=100_000 - count,
                deadline=deadline,
            )
            count += consumed
            local.append((source, fingerprint, rows))
            continue
        binding = bindings.get(selector.get("binding_id", ""))
        if binding is None:
            raise ControlOperationError("not_found", "Confirmed energy binding is not available")
        if binding.get("source_kind") != "statistic" or selector.get("granularity") != "hour":
            raise ValueError("numerical energy sources require confirmed hourly statistic bindings")
        role = binding["role"]
        if role not in {"production", "self_consumption", "grid_export"}:
            raise ValueError("numerical energy role is not supported")
        control = controls.get(binding["control_uuid"])
        if control is None:
            raise ControlOperationError("not_found", "Statistic source is not visible")
        key = (control.uuid, binding["series_id"])
        if key in seen:
            if role not in roles or roles[role][1]["series_id"] != binding["series_id"]:
                raise ValueError("one physical source cannot establish multiple energy roles")
            continue
        if role in roles:
            raise ValueError("one distinct statistic per numerical energy role required")
        seen.add(key)
        _, series, points = await runtime.authorized_statistics(
            access,
            control,
            session,
            binding["series_id"],
            ceil(begin),
            ceil(finish) - 1,
            "hour",
            maximum_points=100_000 - count,
        )
        count += len(points)
        semantics = resolver.resolve_series(control, series, granularity="hour")
        summary = await run_admitted_worker(
            statistic_summary,
            "energy",
            semantics,
            points,
            start=begin,
            end=finish,
            control_uuid=control.uuid,
            source_id=series.series_id,
        )
        if hourly_energy_semantics_qualified(semantics):
            energies[role] = await run_admitted_worker(
                qualified_hourly_energy,
                ComparisonInput(summary, semantics, points),
                begin,
                finish,
                deadline,
            )
        roles[role] = (control, binding)
    production = roles.get("production", (None, {}))[1]
    exported = roles.get("grid_export", (None, {}))[1]
    balance_matches = bool(
        production.get("measurement_boundary")
        and production.get("measurement_boundary") == exported.get("measurement_boundary")
        and exported.get("declared_direction") == "export"
    )
    result = await run_admitted_worker(
        _calculate,
        local,
        energies,
        begin=begin,
        finish=finish,
        zone_name=zone_name,
        options=options,
        installation=installation,
        balance_matches=balance_matches,
        deadline=deadline,
        now=now,
    )
    await runtime._require_access(access)
    current = await run_admitted_worker(event_runtime._config_store.load)
    if (
        not current.loxone_history_enabled
        or current.solar_history_sources != config.solar_history_sources
        or current.event_history_retention_days != config.event_history_retention_days
        or current.event_history_maximum_mib != config.event_history_maximum_mib
        or MiniserverEndpoint.parse(current.loxone_endpoint).origin != runtime.endpoint.origin
    ):
        raise ControlOperationError("permission_denied", "Solar history configuration changed")
    for solar_summary in result.solar_sources:
        solar_summary.recording_enabled = current.solar_history_enabled
    return result, count
