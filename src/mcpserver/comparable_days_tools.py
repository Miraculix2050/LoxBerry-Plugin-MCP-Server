"""Class-day adapter inside the existing fresh history context and worker admission."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.comparable_class_days import ClassDay, ClassPoint, ClassRule, compare_class_days
from mcpserver.comparable_days import Options, _check
from mcpserver.comparable_days_models import ClassComparableDayOptions, ClassComparableDaysResult
from mcpserver.installation_profile import installation_identity
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.history_evidence import timezone
from mcpserver.loxone.runtime import ControlOperationError
from mcpserver.loxone.uuid import normalize_loxone_uuid
from mcpserver.loxone.weather_history import RULE, WeatherHistory, source_fingerprint

if TYPE_CHECKING:
    from mcpserver.auth.provider import StoredAccessToken
    from mcpserver.loxone.models import LoxoneStructure
    from mcpserver.loxone.runtime import LoxoneRuntime
    from mcpserver.tools import EventHistoryRuntime


# Owner decision on 2026-10-13 permits this explicitly labelled qualitative
# assumption only. It is neither verified native encoding nor numerical units.
NATIVE_CLASS_RULE: ClassRule | None = ClassRule.OWNER_ASSUMED_RISK_CLASS


class WeatherAnalysisSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_kind: Literal["structured_weather"]
    state_uuid: str = Field(min_length=1, max_length=128)
    stored_mode: Literal["actual"] = "actual"
    binding_id: None = None

    @field_validator("state_uuid")
    @classmethod
    def uuid(cls, value: str) -> str:
        return normalize_loxone_uuid(value)


class WeatherAnalysisSummary(BaseModel):
    source_kind: Literal["structured_weather"] = "structured_weather"
    state_uuid: str
    stored_mode: Literal["actual"] = "actual"
    field: Literal["solar_radiation"] = "solar_radiation"
    source_rule: str = RULE
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    recording_enabled: bool
    retained_source_points: int = Field(ge=0, le=100_000)
    input_versions: int = Field(ge=0, le=100_000)
    axis: Literal["received_at_with_source_point_positions"] = (
        "received_at_with_source_point_positions"
    )
    limitations: list[str] = Field(max_length=16)


def _calculate(
    points: list[dict[str, Any]],
    *,
    begin: float,
    finish: float,
    zone_name: str,
    options: ClassComparableDayOptions,
    installation: str,
    fingerprint: str,
    rule: ClassRule | None,
    deadline: float,
) -> ClassComparableDaysResult:
    zone = timezone(zone_name)
    first = datetime.fromtimestamp(begin, zone).date()
    end_local = datetime.fromtimestamp(finish, zone)
    last = end_local.date() - (
        timedelta(days=1) if end_local.time() == datetime.min.time() else timedelta()
    )
    selected: dict[date, list[ClassPoint]] = {}
    for item in points:
        _check(deadline)
        local = datetime.fromtimestamp(item["point_at"], zone).date()
        selected.setdefault(local, []).append(
            ClassPoint(item["point_at"], item["fields"].get("solar_radiation"))
        )
    days = tuple(
        ClassDay(day, tuple(selected.get(day, ())), rule, installation, fingerprint)
        for offset in range((last - first).days + 1)
        for day in (first + timedelta(days=offset),)
    )
    result = compare_class_days(
        days,
        reference=date.fromisoformat(options.reference_day),
        timezone_name=zone_name,
        now=datetime.now(UTC),
        options=Options(
            start_hour=options.start_hour,
            end_hour=options.end_hour,
            maximum_seasonal_days=options.maximum_seasonal_days,
        ),
        deadline=deadline,
    )
    result["limitations"].extend(
        [
            "receptions_outside_analysis_interval_are_not_backfilled",
            "provider_or_station_changes_are_not_fully_identified",
        ]
    )
    return ClassComparableDaysResult.model_validate(result)


async def class_day_analysis(
    runtime: LoxoneRuntime,
    event_runtime: EventHistoryRuntime | None,
    access: StoredAccessToken,
    structure: LoxoneStructure,
    selectors: list[dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
    *,
    begin: float,
    finish: float,
    zone_name: str,
    options: ClassComparableDayOptions,
    deadline: float,
) -> tuple[ClassComparableDaysResult, WeatherAnalysisSummary]:
    if event_runtime is None:
        raise ControlOperationError(
            "temporarily_unavailable", "Local weather history is not configured"
        )
    config = event_runtime._config_store.load()
    origin = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    if origin != runtime.endpoint.origin:
        raise ControlOperationError(
            "temporarily_unavailable", "Weather endpoint configuration changed"
        )
    if not config.loxone_history_enabled:
        raise ControlOperationError(
            "permission_denied", "Loxone history requires administrator activation"
        )
    targets: set[str] = set()
    for selector in selectors:
        binding_id = selector.get("binding_id")
        if binding_id:
            binding = bindings.get(binding_id)
            if binding is None:
                raise ControlOperationError(
                    "not_found", "Confirmed visible weather binding is not available"
                )
            if (binding.get("source_kind"), binding.get("mode"), binding.get("field")) != (
                "weather",
                "actual",
                "solar_radiation",
            ) or selector.get("granularity") != "raw":
                raise ValueError(
                    "class comparisons require an actual solar-radiation weather binding"
                )
            target = binding["weather_state_uuid"]
        elif (
            selector.get("source_kind") == "structured_weather"
            and selector.get("stored_mode") == "actual"
        ):
            target = selector["state_uuid"]
        else:
            raise ValueError("class comparisons require a structured weather source")
        targets.add(target)
    if len(targets) != 1:
        raise ValueError("class comparisons require exactly one deduplicated weather source")
    target = targets.pop()
    source = next(
        (
            s
            for s in config.weather_history_sources
            if s.state_uuid == target and s.mode == "actual"
        ),
        None,
    )
    if source is None or "solar_radiation" not in source.fields:
        raise ControlOperationError(
            "not_found", "Actual solar-radiation recording source is not configured"
        )
    installation = installation_identity(runtime.endpoint.origin, structure)
    try:
        fingerprint = source_fingerprint(source, structure, installation)
    except ValueError as exc:
        raise ControlOperationError("not_found", "Weather history source is not visible") from exc
    store = WeatherHistory(
        EventHistoryStore(
            event_runtime._store_path,
            retention_days=config.event_history_retention_days,
            maximum_mib=config.event_history_maximum_mib,
        )
    )
    await runtime._require_access(access)
    points, count = await run_admitted_worker(
        store.analysis_points,
        source,
        fingerprint,
        begin,
        finish,
        maximum_points=100_000,
        deadline=deadline,
    )
    result = await run_admitted_worker(
        _calculate,
        points,
        begin=begin,
        finish=finish,
        zone_name=zone_name,
        options=options,
        installation=installation,
        fingerprint=fingerprint,
        rule=NATIVE_CLASS_RULE,
        deadline=deadline,
    )
    await runtime._require_access(access)
    current = event_runtime._config_store.load()
    if (
        not current.loxone_history_enabled
        or source not in current.weather_history_sources
        or MiniserverEndpoint.parse(current.loxone_endpoint).origin != origin
        or current.event_history_retention_days != config.event_history_retention_days
        or current.event_history_maximum_mib != config.event_history_maximum_mib
    ):
        raise ControlOperationError("permission_denied", "Weather history configuration changed")
    return result, WeatherAnalysisSummary(
        state_uuid=source.state_uuid,
        fingerprint=fingerprint,
        recording_enabled=current.weather_history_enabled,
        retained_source_points=len(points),
        input_versions=count,
        limitations=[
            "raw_delivery_rule_is_provenance_not_numeric_units",
            "forecasts_and_predating_source_points_are_not_used",
        ],
    )
