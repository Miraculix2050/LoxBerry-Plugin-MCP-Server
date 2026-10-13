"""Typed, freshly authorized weather history branch of loxone_get_weather."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.installation_profile import installation_identity
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.event_history import EventHistoryStore, EventHistoryUnavailable
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.loxone.uuid import normalize_loxone_uuid
from mcpserver.loxone.weather_history import WeatherHistory, source_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from mcpserver.auth.provider import StoredAccessToken
    from mcpserver.config import AtomicConfigStore
    from mcpserver.tools import _CursorCodec


class WeatherHistoryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_uuid: str = Field(max_length=128)
    stored_mode: Literal["actual", "forecast"]
    start: str = Field(max_length=40, description="Inclusive received-at UTC/offset timestamp.")
    end: str = Field(
        max_length=40,
        description="Exclusive received-at timestamp, at most 31 days after start; not future.",
    )
    include_raw: bool = False

    @field_validator("state_uuid")
    @classmethod
    def uuid(cls, value: str) -> str:
        return normalize_loxone_uuid(value)

    def period(self) -> tuple[float, float]:
        try:
            a, b = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
            if a.tzinfo is None or b.tzinfo is None:
                raise ValueError
            begin, finish = a.timestamp(), b.timestamp()
            if not 0 < finish - begin <= 31 * 86400 or finish > datetime.now(UTC).timestamp():
                raise ValueError
            return begin, finish
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError(
                "weather history requires an explicit past received-time range of at most 31 days"
            ) from exc


class WeatherHistoryPoint(BaseModel):
    point_predates_capture: bool = Field(
        description=(
            "Source point time predates this capture; no earlier capture coverage is established."
        )
    )
    point_at: float = Field(
        description="Source point time, Unix UTC seconds; forecast points may be future."
    )
    received_at: float = Field(description="Local delivery reception, Unix UTC seconds.")
    reported_update_at: float = Field(
        description="Reported source update time; not proven forecast issuance."
    )
    fields: dict[str, float] | None = None


class WeatherCaptureInterval(BaseModel):
    started_at: float
    ended_at: float | None
    outcome: str


class WeatherHistoryData(BaseModel):
    mode: Literal["history"] = "history"
    source_kind: Literal["structured_weather"] = "structured_weather"
    state_uuid: str
    stored_mode: Literal["actual", "forecast"]
    fingerprint: str
    configured_fields: list[str]
    unit: None = None
    recording_enabled: bool
    axis: Literal["received_at"]
    rule: str
    start: str
    end: str
    items: list[WeatherHistoryPoint]
    next_cursor: str | None
    capture_intervals: list[WeatherCaptureInterval]
    capture_intervals_truncated: bool
    coverage: Literal["deliveries_only", "no_deliveries"]
    limitations: list[str]


class WeatherHistoryReader:
    def __init__(self, runtime: LoxoneRuntime, config_store: AtomicConfigStore, path: Path) -> None:
        self.runtime, self.config_store, self.path = runtime, config_store, path

    async def read(
        self,
        access: StoredAccessToken,
        options: WeatherHistoryOptions,
        cursor: str | None,
        limit: int,
        codec: _CursorCodec,
    ) -> WeatherHistoryData:
        if type(limit) is not int or not 1 <= limit <= 96:
            raise ValueError("weather history limit must be between 1 and 96")
        start, end = options.period()
        config = self.config_store.load()
        configured_origin = MiniserverEndpoint.parse(config.loxone_endpoint).origin
        if configured_origin != self.runtime.endpoint.origin:
            raise ControlOperationError(
                "temporarily_unavailable", "Weather history endpoint configuration changed"
            )
        if not config.loxone_history_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone history requires administrator activation"
            )
        source = next(
            (
                s
                for s in config.weather_history_sources
                if (s.state_uuid, s.mode) == (options.state_uuid, options.stored_mode)
            ),
            None,
        )
        if source is None:
            raise ControlOperationError("not_found", "Weather history source is not configured")
        if not self.path.is_file():
            raise ControlOperationError(
                "temporarily_unavailable", "No weather history has been recorded"
            )
        async with asyncio.timeout(30), self.runtime.history_call_slot(access):
            snapshot = await self.runtime.snapshot(access, fresh_visibility=True)
            installation = installation_identity(self.runtime.endpoint.origin, snapshot.structure)
            try:
                fingerprint = source_fingerprint(source, snapshot.structure, installation)
            except ValueError as exc:
                raise ControlOperationError(
                    "not_found", "Weather history source is not visible"
                ) from exc
            scope = codec.digest(
                json.dumps(
                    [
                        "weather_history",
                        access.family_id,
                        access.identity_id,
                        access.miniserver_id,
                        installation,
                        fingerprint,
                        start,
                        end,
                        options.include_raw,
                    ],
                    separators=(",", ":"),
                ).encode()
            )
            anchor = None
            generation = None
            if cursor is not None:
                decoded = codec.decode_anchor(scope, cursor)
                if decoded[0] != "weather_history":
                    raise ValueError("weather history cursor is invalid")
                anchor = (float(decoded[2]), decoded[1])
                generation = decoded[3]
            store = WeatherHistory(
                EventHistoryStore(
                    self.path,
                    retention_days=config.event_history_retention_days,
                    maximum_mib=config.event_history_maximum_mib,
                )
            )
            try:
                # The existing history slot admits and remains held through this
                # worker. Re-entering its semaphore would deadlock at limit one.
                page = await run_admitted_worker(
                    store.page,
                    source,
                    fingerprint,
                    start,
                    end,
                    limit=limit,
                    anchor=anchor,
                    generation=generation,
                )
            except EventHistoryUnavailable as exc:
                raise ControlOperationError(
                    "temporarily_unavailable", "Weather history is unavailable"
                ) from exc
            await self.runtime._require_access(access)
            current = self.config_store.load()
            if (
                not current.loxone_history_enabled
                or source not in current.weather_history_sources
                or MiniserverEndpoint.parse(current.loxone_endpoint).origin != configured_origin
                or current.event_history_retention_days != config.event_history_retention_days
            ):
                raise ControlOperationError(
                    "permission_denied", "Weather history configuration changed"
                )
            next_anchor = page.pop("anchor")
            current_generation = page.pop("generation")
            next_cursor = (
                codec.encode_anchor(
                    scope,
                    ("weather_history", next_anchor[1], str(next_anchor[0]), current_generation),
                )
                if next_anchor is not None
                else None
            )
            if not options.include_raw:
                for point in page["items"]:
                    point["fields"] = None
            result = WeatherHistoryData(
                **page,
                state_uuid=source.state_uuid,
                stored_mode=source.mode,
                fingerprint=fingerprint,
                configured_fields=list(source.fields),
                recording_enabled=current.weather_history_enabled,
                start=options.start,
                end=options.end,
                next_cursor=next_cursor,
            )
            return result
