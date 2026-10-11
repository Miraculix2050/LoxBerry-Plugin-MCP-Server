"""Thin MCP history-analysis adapter with one fresh caller context per request."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.history_analysis import (
    AnalysisOperation,
    HistoryAnalysisDeadline,
    SourceAnalysis,
    duration_summary,
    reconstruct_segments,
    statistic_summary,
)
from mcpserver.installation_profile import (
    ProfileError,
    ProfileStore,
    installation_identity,
    project_profile,
    visible_controls,
)
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
    sources: list[AnalysisSource],
    raw: list[dict[str, Any]],
    outputs: list[SourceAnalysis],
    deadline: float,
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
) -> tuple[SourceAnalysis, list[dict[str, Any]]]:
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
    return result, raw


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
        sources: list[AnalysisSource],
        start: str,
        end: str,
        timezone_name: str,
        include_raw: bool,
        cursor: str | None,
    ) -> AnalysisEnvelope:
        trace_id = str(uuid4())
        try:
            if runtime is None:
                raise RuntimeUnavailable("History analysis is not configured")
            access = _access()
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
            if cursor is not None and not include_raw:
                raise ValueError("cursor requires explicitly requested raw data")
            begin, finish = first.timestamp(), last.timestamp()
            deadline = time.monotonic() + 30
            async with asyncio.timeout(30), runtime.history_context(access) as (structure, session):
                controls = visible_controls(structure)
                resolved = []
                bindings: dict[str, dict[str, Any]] = {}
                if any(source.binding_id for source in sources):
                    if profile_path is None:
                        raise ControlOperationError(
                            "not_found", "confirmed profile binding is not available"
                        )
                    identity = installation_identity(runtime.endpoint.origin, structure)
                    document = await asyncio.to_thread(ProfileStore(profile_path).read, identity)
                    projection = project_profile(document, identity, controls, limit=256)
                    bindings = {
                        b["binding_id"]: b
                        for b in projection["bindings"]
                        if b["status"] == "confirmed"
                    }
                seen = set()
                for source in sources:
                    binding = bindings.get(source.binding_id) if source.binding_id else None
                    if source.binding_id and binding is None:
                        raise ControlOperationError(
                            "not_found", "confirmed visible binding is not available"
                        )
                    control_id = binding["control_uuid"] if binding else source.control_uuid
                    series_id = binding["series_id"] if binding else source.series_id
                    state_id = binding["state_uuid"] if binding else source.state_uuid
                    control = controls.get(control_id or "")
                    if control is None:
                        raise ControlOperationError("not_found", "source is not visible")
                    key = (control.uuid, series_id, state_id, source.granularity)
                    if key in seen:
                        continue
                    seen.add(key)
                    resolved.append((source, binding, control, series_id, state_id))
                outputs = []
                raw: list[dict[str, Any]] = []
                count = 0
                resolver = StateSemanticsResolver()
                for source, _binding, control, series_id, state_id in resolved:
                    await runtime._require_access(access)
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
                        result, source_raw = await run_admitted_worker(
                            _statistic_calculation,
                            operation,
                            semantics,
                            points,
                            begin,
                            finish,
                            control.uuid,
                            series_id,
                            deadline,
                            include_raw,
                        )
                        raw.extend(source_raw)
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
                            operation != "state_duration"
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

                            result, source_raw = await run_admitted_worker(
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
                        result.native_source = "event_history"
                        result.semantic_reference = resolver.source_reference(
                            control, state_name=state_name
                        )
                    result.binding_id = source.binding_id
                    outputs.append(result)
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
            "Compute compact temperature sample summaries, verified energy or observed state "
            "duration. Exact sources or confirmed visible profile bindings; UTC half-open "
            "period and explicit IANA timezone. Requires loxone:read and loxone:history. "
            "No raw data unless requested."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def analyze_history(
        operation: AnalysisOperation,
        sources: Annotated[list[AnalysisSource], Field(min_length=1, max_length=16)],
        start: Annotated[str, Field(max_length=64, json_schema_extra={"format": "date-time"})],
        end: Annotated[str, Field(max_length=64, json_schema_extra={"format": "date-time"})],
        timezone: Annotated[str, Field(min_length=1, max_length=128)],
        include_raw: bool = False,
        cursor: Annotated[str | None, Field(max_length=512)] = None,
    ) -> AnalysisEnvelope:
        if len(pending) >= 2:
            return _error(
                AnalysisEnvelope, "temporarily_unavailable", "Two analyses are already running"
            )
        task = asyncio.create_task(
            calculate(operation, sources, start, end, timezone, include_raw, cursor)
        )
        pending.add(task)
        task.add_done_callback(pending.discard)
        # A cancelled request cannot release admission while a bounded worker still runs.
        return await asyncio.shield(task)
