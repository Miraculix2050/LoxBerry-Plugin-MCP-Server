"""Thin MCP history-analysis adapter with one fresh caller context per request."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.comparable_days_models import ClassComparableDayOptions, ClassComparableDaysResult
from mcpserver.comparable_days_tools import (
    WeatherAnalysisSource,
    WeatherAnalysisSummary,
    class_day_analysis,
)
from mcpserver.history_analysis import (
    AnalysisOperation,
    HistoryAnalysisDeadline,
    SourceAnalysis,
    StateSegment,
    duration_summary,
    reconstruct_segments,
    statistic_summary,
)
from mcpserver.history_comparison import (
    ComparisonInput,
    ComparisonOperation,
    ComparisonResult,
    compare_history,
)
from mcpserver.installation_profile import (
    ProfileError,
    ProfileSources,
    ProfileStore,
    installation_identity,
    project_profile,
    visible_controls,
)
from mcpserver.load_flexibility import LoadFlexibility
from mcpserver.loxone.event_history import (
    EventHistoryQueryTimeout,
    EventHistoryStore,
    EventHistoryUnavailable,
)
from mcpserver.loxone.history_evidence import timezone, utc_timestamp
from mcpserver.loxone.models import Control, LoxoneStructure
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeAuthorizationError,
    RuntimeUnavailable,
    history_trace,
)
from mcpserver.loxone.state_semantics import SeriesSemantics, StateSemanticsResolver
from mcpserver.loxone.statistics import StatisticPoint
from mcpserver.tools import (
    ErrorData,
    EventHistoryRuntime,
    ToolEnvelope,
    _access,
    _CursorCodec,
    _error,
    _operation_error,
    _result,
    _rfc3339,
)

_LOGGER = logging.getLogger("mcpserver.history_analysis")


def _timing(trace_id: str, phase: str, started: float) -> None:
    _LOGGER.debug(
        "component=history_analysis trace_id=%s phase=%s duration_ms=%.1f",
        trace_id,
        phase,
        (time.perf_counter() - started) * 1000,
    )


class AnalysisSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_uuid: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    series_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    state_uuid: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    binding_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = None
    granularity: Literal["raw", "hour", "day", "month", "year"] = "raw"

    @model_validator(mode="after")
    def exact_source(self) -> AnalysisSource:
        if self.binding_id:
            if self.control_uuid or self.series_id or self.state_uuid:
                raise ValueError("binding_id cannot be combined with exact source identifiers")
        elif not self.control_uuid or bool(self.series_id) == bool(self.state_uuid):
            raise ValueError("exact control and one series or state identifier required")
        if self.state_uuid and self.granularity != "raw":
            raise ValueError("event history has no statistic granularity")
        return self


class AnalysisData(BaseModel):
    operation: AnalysisOperation
    start: str
    end: str
    timezone: str
    interval_convention: Literal["half_open"] = "half_open"
    method_version: Literal["history_analysis.v1"] = "history_analysis.v1"
    sources: list[SourceAnalysis] = Field(max_length=16)
    input_points: int = Field(ge=0, le=100_000)
    raw: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    next_cursor: str | None = None
    comparison: ComparisonResult | None = None
    comparable_days: ClassComparableDaysResult | None = None
    weather_sources: list[WeatherAnalysisSummary] = Field(default_factory=list, max_length=16)


class ComparisonOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    comparable_boundaries_confirmed: bool = False
    night_start_hour: int = Field(default=0, ge=0, le=23)
    night_end_hour: int = Field(default=5, ge=1, le=24)


class AnalysisEnvelope(ToolEnvelope):
    data: AnalysisData | ErrorData


def _statistic_calculation(
    operation: AnalysisOperation,
    semantics: SeriesSemantics,
    points: tuple[StatisticPoint, ...],
    begin: float,
    finish: float,
    control_id: str,
    source_id: str,
    deadline: float,
    include_raw: bool,
    native_granularity: str,
) -> tuple[SourceAnalysis, list[dict[str, Any]]]:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()
    result = statistic_summary(
        operation,
        semantics,
        points,
        start=begin,
        end=finish,
        control_uuid=control_id,
        source_id=source_id,
    )
    if (
        operation == "energy"
        and semantics.value_meaning == "interval_difference_sum"
        and native_granularity != "hour"
    ):
        result = SourceAnalysis(
            source_kind="statistic",
            control_uuid=control_id,
            source_id=source_id,
            status="insufficient_evidence",
            unit=semantics.unit,
            method="unavailable",
            limitations=["non_hourly_interval_energy_not_supported"],
        )
    raw = []
    if include_raw and semantics.timestamp_basis == "unix_utc":
        for point in points:
            if time.monotonic() >= deadline:
                raise HistoryAnalysisDeadline()
            raw.append(
                {
                    "source_kind": "statistic",
                    "control_uuid": control_id,
                    "source_id": source_id,
                    "timestamp": utc_timestamp(point.timestamp),
                    "value": point.value,
                }
            )
    return result, raw


def _raw_scope(
    cursors: _CursorCodec,
    family: str,
    operation: str,
    start: str,
    end: str,
    zone: str,
    sources: list[AnalysisSource | WeatherAnalysisSource],
    raw: list[dict[str, Any]],
    outputs: list[SourceAnalysis],
    deadline: float,
    comparison_options: ComparisonOptions | None = None,
    comparison: ComparisonResult | None = None,
) -> str:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()
    proof = json.dumps(
        [
            family,
            operation,
            start,
            end,
            zone,
            [s.model_dump() for s in sources],
            raw,
            [s.model_dump() for s in outputs],
            comparison_options.model_dump() if comparison_options else None,
            comparison.model_dump() if comparison else None,
        ],
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    digest = cursors.digest(proof)
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()
    return digest


def _state_calculation(
    structure: LoxoneStructure,
    control: Control,
    state_name: str,
    phases: tuple[tuple[float, float, object, tuple[tuple[float, object], ...]], ...],
    begin: float,
    finish: float,
    state_id: str,
    deadline: float,
    include_raw: bool,
) -> tuple[SourceAnalysis, list[dict[str, Any]], tuple[StateSegment, ...]]:
    resolver = StateSemanticsResolver()

    def decode(value: object) -> object:
        if time.monotonic() >= deadline:
            raise HistoryAnalysisDeadline()
        _meta, semantic = resolver.resolve(structure, control, state_name, value, {})
        return (
            semantic.get("active")
            if isinstance(semantic, dict) and semantic.get("kind") == "binary_state"
            else None
        )

    decoded = tuple(
        (a, b, decode(v), tuple((t, decode(x)) for t, x in changes)) for a, b, v, changes in phases
    )
    segments = reconstruct_segments(decoded, start=begin, end=finish)
    result = duration_summary(
        segments, start=begin, end=finish, control_uuid=control.uuid, source_id=state_id
    )
    raw = (
        [
            {
                "source_kind": "event_history",
                "control_uuid": control.uuid,
                "source_id": state_id,
                "start": utc_timestamp(s.start),
                "end": utc_timestamp(s.end),
                "active": s.active,
            }
            for s in segments
        ]
        if include_raw
        else []
    )
    return result, raw, segments


def register_history_analysis_tool(
    server: FastMCP,
    runtime: LoxoneRuntime | None,
    event_runtime: EventHistoryRuntime | None,
    profile_path: Path | None,
) -> None:
    cursors = _CursorCodec()
    pending: set[asyncio.Task[AnalysisEnvelope]] = set()

    async def calculate(
        operation: AnalysisOperation,
        sources: list[AnalysisSource | WeatherAnalysisSource],
        start: str,
        end: str,
        timezone_name: str,
        include_raw: bool,
        cursor: str | None,
        comparison_options: ComparisonOptions | None,
        comparable_day_options: ClassComparableDayOptions | None,
    ) -> AnalysisEnvelope:
        trace_id = str(uuid4())
        try:
            if runtime is None:
                raise RuntimeUnavailable("History analysis is not configured")
            access = _access()
            is_comparison = operation in {
                "consumer_ranking",
                "pv_load_overlap",
                "operating_phases",
                "baseload",
                "retrospective_shift",
            }
            if comparison_options is not None and not is_comparison:
                raise ValueError("comparison options require a comparison operation")
            if operation == "retrospective_shift" and (
                not sources or any(not source.binding_id for source in sources)
            ):
                raise ValueError("retrospective_shift requires confirmed profile bindings")
            is_day_comparison = operation == "comparable_days"
            if comparable_day_options is not None and not is_day_comparison:
                raise ValueError("comparable day options require comparable_days")
            if is_day_comparison and (comparable_day_options is None or include_raw or cursor):
                raise ValueError("comparable_days requires reference options and compact output")
            if not is_day_comparison and any(isinstance(s, WeatherAnalysisSource) for s in sources):
                raise ValueError("structured weather sources require comparable_days")
            first, last = _rfc3339(start), _rfc3339(end)
            zone = timezone(timezone_name)
            if first >= last or last > datetime.now(UTC):
                raise ValueError("history interval must be nonempty and end in the past")
            local_first, local_last = first.astimezone(zone), last.astimezone(zone)
            # Count the touched local calendar days, excluding an exact end midnight.
            touched = (local_last.date() - local_first.date()).days + (
                local_last.time().replace(tzinfo=None) != datetime.min.time()
            )
            if touched > 31:
                raise ValueError("analysis is limited to 31 local calendar days")
            if is_day_comparison:
                assert comparable_day_options is not None
                reference = datetime.fromisoformat(comparable_day_options.reference_day).date()
                last_day = local_last.date()
                if local_last.time().replace(tzinfo=None) == datetime.min.time():
                    last_day -= timedelta(days=1)
                if not local_first.date() <= reference <= last_day:
                    raise ValueError("reference must lie inside the selected range")
                if any(isinstance(s, AnalysisSource) and not s.binding_id for s in sources):
                    raise ValueError("class comparisons require structured weather selectors")
            if cursor is not None and not include_raw:
                raise ValueError("cursor requires explicitly requested raw data")
            begin, finish = first.timestamp(), last.timestamp()
            deadline = time.monotonic() + 30
            async with AsyncExitStack() as stack:
                stack.enter_context(history_trace(trace_id))
                await stack.enter_async_context(asyncio.timeout(30))
                structure, session = await stack.enter_async_context(
                    runtime.history_context(access)
                )
                controls = visible_controls(structure)
                resolved = []
                bindings: dict[str, dict[str, Any]] = {}
                profile_revision: int | None = None
                if any(source.binding_id for source in sources):
                    if profile_path is None:
                        raise ControlOperationError(
                            "not_found", "confirmed profile binding is not available"
                        )
                    identity = installation_identity(runtime.endpoint.origin, structure)
                    document = await run_admitted_worker(ProfileStore(profile_path).read, identity)
                    profile_revision = document.revision
                    profile_sources = (
                        ProfileSources.from_structure(identity, structure)
                        if is_day_comparison
                        or operation in {"operating_phases", "retrospective_shift"}
                        else controls
                    )
                    projection = project_profile(document, identity, profile_sources, limit=256)
                    bindings = {
                        b["binding_id"]: b
                        for b in projection["bindings"]
                        if b["status"] == "confirmed"
                    }
                if is_day_comparison:
                    assert comparable_day_options is not None
                    days, weather = await class_day_analysis(
                        runtime,
                        event_runtime,
                        access,
                        structure,
                        [source.model_dump() for source in sources],
                        bindings,
                        begin=begin,
                        finish=finish,
                        zone_name=timezone_name,
                        options=comparable_day_options,
                        deadline=deadline,
                    )
                    envelope = _result(
                        AnalysisEnvelope,
                        {
                            "operation": operation,
                            "start": utc_timestamp(begin),
                            "end": utc_timestamp(finish),
                            "timezone": timezone_name,
                            "sources": [],
                            "input_points": weather.input_versions,
                            "comparable_days": days,
                            "weather_sources": [weather],
                        },
                        trace_id=trace_id,
                        warnings=[
                            "Some recorded radiation values do not fit the class mapping. "
                            "Inform the user and review the mapping/source; "
                            "diagnostics are retained."
                        ]
                        if days.invalid_source_point_count
                        else [],
                    )
                    if len(envelope.model_dump_json().encode()) > 64 * 1024:
                        raise ValueError("analysis output byte limit exceeded")
                    if days.invalid_source_point_count:
                        _LOGGER.warning(
                            "component=history_analysis trace_id=%s operation=comparable_days "
                            "outcome=unexpected_class_values mapping=%s issues=%s count=%d "
                            "diagnostic_truncated=%s",
                            trace_id,
                            days.classification_origin,
                            ",".join(sorted({point.issue for point in days.invalid_points})),
                            days.invalid_source_point_count,
                            days.invalid_points_truncated,
                        )
                    return envelope
                seen = set()
                for source in sources:
                    if not isinstance(source, AnalysisSource):
                        raise ValueError("scalar operations require scalar sources")
                    binding = bindings.get(source.binding_id) if source.binding_id else None
                    if source.binding_id and binding is None:
                        raise ControlOperationError(
                            "not_found", "confirmed visible binding is not available"
                        )
                    if binding and binding.get("source_kind") == "weather":
                        raise ValueError("weather bindings require comparable_days")
                    control_id = binding["control_uuid"] if binding else source.control_uuid
                    series_id = binding["series_id"] if binding else source.series_id
                    state_id = binding["state_uuid"] if binding else source.state_uuid
                    control = controls.get(control_id or "")
                    if control is None:
                        raise ControlOperationError("not_found", "source is not visible")
                    key = (
                        (control.uuid, series_id, state_id)
                        if operation == "retrospective_shift"
                        else (control.uuid, series_id, state_id, source.granularity)
                    )
                    if key in seen:
                        if operation == "retrospective_shift":
                            raise ValueError(
                                "retrospective_shift requires distinct physical sources"
                            )
                        continue
                    seen.add(key)
                    resolved.append((source, binding, control, series_id, state_id))
                outputs = []
                comparison_inputs = []
                raw: list[dict[str, Any]] = []
                count = 0
                resolver = StateSemanticsResolver()
                for source, binding, control, series_id, state_id in resolved:
                    await runtime._require_access(access)
                    semantics = None
                    points: tuple[StatisticPoint, ...] = ()
                    segments: tuple[StateSegment, ...] = ()
                    if series_id is not None:
                        if source.granularity == "raw" and finish - begin > 7 * 86400:
                            raise ValueError("raw statistics are limited to seven days")
                        if ceil(begin) > ceil(finish) - 1:
                            raise ValueError("statistic interval must include a whole second")
                        _, series, points = await runtime.authorized_statistics(
                            access,
                            control,
                            session,
                            series_id,
                            ceil(begin),
                            ceil(finish) - 1,
                            source.granularity,
                            maximum_points=100_000 - count,
                        )
                        count += len(points)
                        if count > 100_000:
                            raise ValueError("analysis input point limit exceeded")
                        semantics = resolver.resolve_series(
                            control, series, granularity=source.granularity
                        )
                        phase_started = time.perf_counter()
                        source_operation: AnalysisOperation = operation
                        if is_comparison:
                            source_operation = (
                                "temperature_summary"
                                if operation == "operating_phases"
                                and semantics.measurement_quantity == "temperature"
                                else "energy"
                            )
                        result, source_raw = await run_admitted_worker(
                            _statistic_calculation,
                            source_operation,
                            semantics,
                            points,
                            begin,
                            finish,
                            control.uuid,
                            series_id,
                            deadline,
                            include_raw,
                            source.granularity,
                        )
                        raw.extend(source_raw)
                        _timing(trace_id, "statistics_calculation", phase_started)
                        result.native_source = (
                            "statistic_v2" if series.source == "statistic_v2" else "legacy"
                        )
                        result.semantic_reference = resolver.source_reference(
                            control, series=series
                        )
                    else:
                        assert state_id is not None
                        if source.granularity != "raw":
                            raise ValueError("event binding does not have statistic granularity")
                        state_name = next(
                            (n for n, u in control.state_uuids if u == state_id), None
                        )
                        if state_name is None:
                            raise ControlOperationError("not_found", "state is not visible")
                        metadata, _ = resolver.resolve(structure, control, state_name, None, {})
                        if (
                            operation
                            not in {
                                "state_duration",
                                "operating_phases",
                                "pv_load_overlap",
                                "retrospective_shift",
                            }
                            or metadata.measurement_quantity != "binary_state"
                        ):
                            result = SourceAnalysis(
                                source_kind="event_history",
                                control_uuid=control.uuid,
                                source_id=state_id,
                                status="insufficient_evidence",
                                method="unavailable",
                                limitations=["operation_not_supported_by_source_semantics"],
                            )
                        elif event_runtime is None:
                            result = SourceAnalysis(
                                source_kind="event_history",
                                control_uuid=control.uuid,
                                source_id=state_id,
                                status="insufficient_evidence",
                                method="unavailable",
                                limitations=["event_history_not_configured"],
                            )
                        else:
                            config = event_runtime._config_store.load()
                            if not config.event_history_enabled:
                                raise ControlOperationError(
                                    "feature_disabled", "Local event history is disabled"
                                )
                            store = EventHistoryStore(
                                event_runtime._store_path,
                                retention_days=config.event_history_retention_days,
                                maximum_mib=config.event_history_maximum_mib,
                            )
                            phase_started = time.perf_counter()
                            phases, consumed = await run_admitted_worker(
                                store.analysis_phases,
                                control.uuid,
                                state_id,
                                start=begin,
                                end=finish,
                                maximum_points=100_000 - count,
                                deadline=deadline,
                            )
                            count += consumed
                            _timing(trace_id, "sqlite", phase_started)

                            phase_started = time.perf_counter()
                            result, source_raw, segments = await run_admitted_worker(
                                _state_calculation,
                                structure,
                                control,
                                state_name,
                                phases,
                                begin,
                                finish,
                                state_id,
                                deadline,
                                include_raw,
                            )
                            raw.extend(source_raw)
                            _timing(trace_id, "state_calculation", phase_started)
                        result.native_source = "event_history"
                        result.semantic_reference = resolver.source_reference(
                            control, state_name=state_name
                        )
                    result.binding_id = source.binding_id
                    outputs.append(result)
                    if is_comparison:
                        comparison_inputs.append(
                            ComparisonInput(
                                result,
                                semantics,
                                points,
                                segments,
                                binding["role"] if binding else None,
                                binding["measurement_boundary"] if binding else None,
                                LoadFlexibility.model_validate(binding["load_flexibility"])
                                if binding and binding.get("load_constraints_usable")
                                else None,
                                binding["declared_direction"] if binding else None,
                            )
                        )
                comparison = None
                if is_comparison:
                    options = comparison_options or ComparisonOptions()
                    comparison = await run_admitted_worker(
                        compare_history,
                        cast(ComparisonOperation, operation),
                        tuple(comparison_inputs),
                        start=begin,
                        end=finish,
                        timezone_name=timezone_name,
                        comparable_boundaries_confirmed=options.comparable_boundaries_confirmed,
                        night_start_hour=options.night_start_hour,
                        night_end_hour=options.night_end_hour,
                        deadline=deadline,
                    )
                    if comparison.load_cycles is not None or operation == "retrospective_shift":
                        assert profile_path is not None and profile_revision is not None
                        current_profile = await run_admitted_worker(
                            ProfileStore(profile_path).read, identity
                        )
                        if current_profile.revision != profile_revision:
                            raise ControlOperationError(
                                "temporarily_unavailable",
                                "Installation profile changed during cycle analysis",
                            )
                        if comparison.load_cycles is not None:
                            comparison.load_cycles.profile_revision = profile_revision
                        if comparison.retrospective_shift is not None:
                            comparison.retrospective_shift.profile_revision = profile_revision
                scope = await run_admitted_worker(
                    _raw_scope,
                    cursors,
                    access.family_id,
                    operation,
                    start,
                    end,
                    timezone_name,
                    sources,
                    raw,
                    outputs,
                    deadline,
                    comparison_options,
                    comparison,
                )
                offset = cursors.decode(scope, cursor)
                envelope = _result(
                    AnalysisEnvelope,
                    {
                        "operation": operation,
                        "start": utc_timestamp(begin),
                        "end": utc_timestamp(finish),
                        "timezone": timezone_name,
                        "sources": outputs,
                        "input_points": count,
                        "comparison": comparison,
                        "raw": raw[offset : offset + 100],
                        "next_cursor": cursors.encode(scope, offset + 100)
                        if offset + 100 < len(raw)
                        else None,
                    },
                    trace_id=trace_id,
                )
                if len(envelope.model_dump_json().encode()) > 64 * 1024:
                    raise ValueError("analysis output byte limit exceeded")
                await runtime._require_access(access)
                return envelope
        except ValueError as exc:
            return _error(AnalysisEnvelope, "invalid_input", str(exc), trace_id=trace_id)
        except RuntimeAuthorizationError:
            return _error(
                AnalysisEnvelope,
                "permission_denied",
                "History access is not authorized",
                trace_id=trace_id,
            )
        except PermissionError:
            return _error(
                AnalysisEnvelope, "unauthenticated", "Authentication is required", trace_id=trace_id
            )
        except ControlOperationError as exc:
            return _operation_error(AnalysisEnvelope, exc, trace_id=trace_id)
        except (TimeoutError, HistoryAnalysisDeadline, EventHistoryQueryTimeout):
            return _error(
                AnalysisEnvelope,
                "deadline_exceeded",
                "Analysis exceeded its 30 second deadline",
                trace_id=trace_id,
            )
        except (RuntimeUnavailable, EventHistoryUnavailable, ProfileError, OSError):
            return _error(
                AnalysisEnvelope,
                "temporarily_unavailable",
                "History analysis is unavailable or exceeded a source limit",
                trace_id=trace_id,
            )

    @server.tool(
        name="loxone_analyze_history",
        description=(
            "Compute compact temperature, energy, state duration, consumer ranking, PV/load "
            "windows, operating phases, nighttime estimates or qualitative radiation-class "
            "comparable days. Classes do not establish radiation energy or normalized yield. "
            "Operating phases can describe confirmed load activity cycles. "
            "Retrospective shift analysis provides conditional shared-export absorption "
            "examples with unproven admissibility and unknown native locks; no scheduling "
            "or saving claim. "
            "Interval energy analysis requires hour granularity; "
            "non-hourly aggregates remain unqualified. "
            "Exact sources or confirmed "
            "visible profile bindings; UTC half-open "
            "period and explicit IANA timezone. Requires loxone:read and loxone:history. "
            "No raw data unless requested."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def analyze_history(
        operation: AnalysisOperation,
        sources: Annotated[
            list[AnalysisSource | WeatherAnalysisSource], Field(min_length=1, max_length=16)
        ],
        start: Annotated[str, Field(max_length=64, json_schema_extra={"format": "date-time"})],
        end: Annotated[str, Field(max_length=64, json_schema_extra={"format": "date-time"})],
        timezone: Annotated[str, Field(min_length=1, max_length=128)],
        include_raw: bool = False,
        cursor: Annotated[str | None, Field(max_length=512)] = None,
        comparison_options: ComparisonOptions | None = None,
        comparable_day_options: ClassComparableDayOptions | None = None,
    ) -> AnalysisEnvelope:
        if len(pending) >= 2:
            return _error(
                AnalysisEnvelope, "temporarily_unavailable", "Two analyses are already running"
            )
        task = asyncio.create_task(
            calculate(
                operation,
                sources,
                start,
                end,
                timezone,
                include_raw,
                cursor,
                comparison_options,
                comparable_day_options,
            )
        )
        pending.add(task)
        task.add_done_callback(pending.discard)
        # A cancelled request cannot release admission while a bounded worker still runs.
        return await asyncio.shield(task)
