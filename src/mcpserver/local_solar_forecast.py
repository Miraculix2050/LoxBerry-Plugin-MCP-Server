"""Fixed local source adapter with independent live LoxBerry read authorization."""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.runtime import ControlOperationError
from mcpserver.solar_forecast import (
    MAX_FORECAST_BYTES,
    SOURCE_ID,
    ForecastEvidenceError,
    ForecastPointDiagnostic,
    ParsedForecast,
    SolarWindowOptions,
    SolarWindowsResult,
    parse_local_forecast,
    sampled_solar_windows,
)

if TYPE_CHECKING:
    from mcpserver.auth.provider import StoredAccessToken
    from mcpserver.config import PluginConfig
    from mcpserver.loxone.runtime import LoxoneRuntime
    from mcpserver.tools import LoxBerryReadRuntime

FORECAST_PATH = Path("/opt/loxberry/data/plugins/weather4lox/hourlyforecast.json")
_LOGGER = logging.getLogger("mcpserver.solar_forecast")


class ForecastSourcesResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["forecast_sources"] = "forecast_sources"
    source: Literal["weather4lox_visualcrossing_hourly_v1"] = SOURCE_ID
    status: Literal[
        "local_read_not_authorized",
        "disabled_not_probed",
        "unconfirmed",
        "missing",
        "unsupported",
        "changed",
        "stale",
        "available",
    ]
    unit: Literal["W/m²"] | None = None
    quantity: Literal["global_horizontal_irradiance"] | None = None
    first_source_point_at: str | None = None
    last_source_point_at: str | None = None
    publication_age_seconds: float | None = None
    invalid_point_count: int | None = Field(default=None, ge=0, le=768)
    forecast_version: str | None = None
    diagnostics: list[ForecastPointDiagnostic] = Field(default_factory=list, max_length=16)
    diagnostics_truncated: bool = False
    provider_issued_at: None = None
    forecast_confidence: None = None
    limitations: list[str] = Field(
        default_factory=lambda: [
            "only_registered_local_source_checked_not_exhaustive_project_discovery",
            "no_pv_yield_baseload_surplus_or_admissible_load_schedule",
        ],
        max_length=16,
    )
    configuration_guidance: list[str] = Field(
        default_factory=lambda: [
            "configure_weather4lox_visualcrossing_hourly_point_irradiance_on_this_loxberry",
            "local_administrator_must_review_location_timezone_and_confirm_installation_association",
            "enable_local_forecast_and_independently_approve_loxberry_read_for_this_client",
            "qualified_point_predictions_help_compare_sampled_solar_windows_without_pv_yield_claims",
            "future_config_mcp_import_requires_separate_explicit_user_instruction",
        ],
        max_length=8,
    )


def read_forecast(
    config: PluginConfig, *, deadline: float, path: Path = FORECAST_PATH
) -> ParsedForecast:
    """The test-only path argument is never part of an MCP or configuration input."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ForecastEvidenceError("unsupported_forecast_file")
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ForecastEvidenceError("forecast_file_changed")
            payload = stream.read(MAX_FORECAST_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = path.lstat()

        def signature(item: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns if os.name != "nt" else 0,
            )

        if signature(opened) != signature(after) or signature(after) != signature(current):
            raise ForecastEvidenceError("forecast_file_changed")
    except FileNotFoundError:
        raise ForecastEvidenceError("forecast_file_missing") from None
    except OSError:
        raise ForecastEvidenceError("forecast_file_unavailable") from None
    return parse_local_forecast(
        payload,
        publication_time=after.st_mtime,
        target_origin=MiniserverEndpoint.parse(config.loxone_endpoint).origin,
        now=time.time(),
        deadline=deadline,
    )


class LocalSolarForecastRuntime:
    def __init__(
        self, runtime: LoxoneRuntime, local_read: LoxBerryReadRuntime, *, path: Path = FORECAST_PATH
    ):
        self.runtime, self.local_read, self.path = runtime, local_read, path
        self._pending = 0

    @staticmethod
    def _policy(config: PluginConfig) -> tuple[bool, int, str, str]:
        return (
            config.solar_forecast_enabled,
            config.solar_forecast_maximum_age_minutes,
            config.solar_forecast_fingerprint,
            config.loxone_endpoint,
        )

    async def read(
        self,
        access: StoredAccessToken,
        options: SolarWindowOptions | None,
        *,
        limit: int,
        trace_id: str,
    ) -> ForecastSourcesResult | SolarWindowsResult:
        await self.runtime._require_access(access)
        try:
            config = self.local_read._allowed(access)
        except PermissionError:
            if options is None:
                return ForecastSourcesResult(status="local_read_not_authorized")
            raise ControlOperationError(
                "permission_denied", "Local forecasts require independent loxberry:read approval"
            ) from None
        if MiniserverEndpoint.parse(config.loxone_endpoint).origin != self.runtime.endpoint.origin:
            raise ControlOperationError("temporarily_unavailable", "Local forecast target changed")
        if not config.solar_forecast_enabled:
            unavailable = ForecastSourcesResult(status="disabled_not_probed")
        elif not config.solar_forecast_fingerprint:
            unavailable = ForecastSourcesResult(status="unconfirmed")
        else:
            unavailable = None
        if unavailable is not None:
            if options is None:
                return unavailable
            raise ControlOperationError(
                "not_found",
                "Local forecast requires administrator activation and source confirmation",
            )
        if self._pending >= 2:
            raise ControlOperationError(
                "temporarily_unavailable", "Local forecast worker budget is busy"
            )
        self._pending += 1
        deadline = time.monotonic() + 30
        try:
            async with asyncio.timeout(30), self.runtime.call_slot(access):
                result: ForecastSourcesResult | SolarWindowsResult
                try:
                    forecast = await run_admitted_worker(
                        read_forecast, config, deadline=deadline, path=self.path
                    )
                except ForecastEvidenceError as exc:
                    _LOGGER.warning(
                        "component=solar_forecast trace_id=%s source_issue=%s", trace_id, str(exc)
                    )
                    status: Literal["missing", "changed", "unsupported"] = (
                        "missing"
                        if str(exc) == "forecast_file_missing"
                        else "changed"
                        if str(exc) == "forecast_file_changed"
                        else "unsupported"
                    )
                    result = ForecastSourcesResult(status=status)
                else:
                    if forecast.fingerprint != config.solar_forecast_fingerprint:
                        result = ForecastSourcesResult(status="changed")
                    elif (
                        forecast.publication_age_seconds
                        > config.solar_forecast_maximum_age_minutes * 60
                    ):
                        result = ForecastSourcesResult(status="stale")
                    elif options is None:
                        from mcpserver.loxone.history_evidence import utc_timestamp

                        result = ForecastSourcesResult(
                            status="available",
                            unit="W/m²",
                            quantity="global_horizontal_irradiance",
                            first_source_point_at=utc_timestamp(forecast.points[0][0])
                            if forecast.points
                            else None,
                            last_source_point_at=utc_timestamp(forecast.points[-1][0])
                            if forecast.points
                            else None,
                            publication_age_seconds=forecast.publication_age_seconds,
                            invalid_point_count=forecast.invalid_points,
                            forecast_version=forecast.version,
                            diagnostics=list(forecast.diagnostics),
                            diagnostics_truncated=forecast.diagnostics_truncated,
                        )
                    else:
                        result = await run_admitted_worker(
                            sampled_solar_windows,
                            forecast,
                            options,
                            now=time.time(),
                            deadline=deadline,
                            limit=min(limit, 16),
                        )
                    if forecast.invalid_points:
                        _LOGGER.warning(
                            "component=solar_forecast trace_id=%s invalid_points=%d "
                            "diagnostics_truncated=%s issues=%s",
                            trace_id,
                            forecast.invalid_points,
                            forecast.diagnostics_truncated,
                            ",".join(sorted({item.issue for item in forecast.diagnostics})),
                        )
                    try:
                        checked = await run_admitted_worker(
                            read_forecast, config, deadline=deadline, path=self.path
                        )
                    except ForecastEvidenceError as exc:
                        _LOGGER.warning(
                            "component=solar_forecast trace_id=%s phase=verification source_issue=%s",
                            trace_id,
                            str(exc),
                        )
                        raise ControlOperationError(
                            "temporarily_unavailable",
                            "Local forecast verification failed; retry with current evidence",
                        ) from None
                    if (
                        checked.document_digest != forecast.document_digest
                        or checked.publication_at != forecast.publication_at
                    ):
                        raise ControlOperationError(
                            "temporarily_unavailable",
                            "Local forecast changed; retry with current evidence",
                        )
                await self.runtime._require_access(access)
                current = self.local_read._allowed(access, record_request=False)
                if self._policy(config) != self._policy(current):
                    raise ControlOperationError(
                        "temporarily_unavailable",
                        "Local forecast configuration changed; retry with current evidence",
                    )
                if isinstance(result, SolarWindowsResult) or result.status == "available":
                    age = time.time() - datetime.fromisoformat(forecast.publication_at).timestamp()
                    if age < 0:
                        raise ControlOperationError(
                            "temporarily_unavailable", "Local publication clock changed"
                        )
                    if age > current.solar_forecast_maximum_age_minutes * 60:
                        result = ForecastSourcesResult(status="stale")
                    else:
                        result.publication_age_seconds = age
                if options is not None and isinstance(result, ForecastSourcesResult):
                    raise ControlOperationError(
                        "not_found",
                        "Qualified local forecast is unavailable; "
                        "use forecast_sources for configuration guidance",
                    )
                return result
        except (HistoryAnalysisDeadline, TimeoutError):
            raise ControlOperationError(
                "temporarily_unavailable", "Local forecast read timed out"
            ) from None
        finally:
            self._pending -= 1
