"""Documented point irradiance forecasts; never interval or plant energy."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from math import isfinite
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.loxone.history_evidence import timezone, utc_timestamp

SOURCE_ID: Final = "weather4lox_visualcrossing_hourly_v1"
SOURCE_RULE: Final = "weather4lox.visualcrossing.point_irradiance.v1"
MAX_FORECAST_BYTES = 4 * 1024 * 1024


class ForecastEvidenceError(ValueError):
    """Messages are fixed technical codes, never contents of a foreign file."""


class SolarWindowOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    source: Literal["weather4lox_visualcrossing_hourly_v1"] = SOURCE_ID
    start: str = Field(max_length=64, json_schema_extra={"format": "date-time"})
    end: str = Field(max_length=64, json_schema_extra={"format": "date-time"})
    timezone: str = Field(min_length=1, max_length=128)
    duration_hours: int = Field(default=1, ge=1, le=24)
    minimum_sample_irradiance_w_m2: FiniteFloat = Field(default=0, ge=0)
    include_samples: bool = False

    @field_validator("minimum_sample_irradiance_w_m2", mode="before")
    @classmethod
    def supported_threshold(cls, value: object) -> object:
        if _finite_number(value) is None:
            raise ValueError("unsupported_irradiance_threshold")
        return value


class IrradianceSample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    at: str
    irradiance_w_m2: FiniteFloat = Field(ge=0)


ForecastIssue = Literal[
    "invalid_timestamp",
    "epoch_or_offset_mismatch",
    "missing_irradiance",
    "non_numeric_irradiance",
    "non_finite_irradiance",
    "negative_irradiance",
    "duplicate_timestamp",
    "numeric_precision_not_supported",
]


class ForecastPointDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=767)
    at: str | None
    issue: ForecastIssue
    raw_number: FiniteFloat | None
    raw_numeric_text: str | None = Field(
        default=None, max_length=256, pattern=r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$"
    )


@dataclass(frozen=True, slots=True)
class ParsedForecast:
    """Private fingerprint/document digest never enter MCP output."""

    points: tuple[tuple[float, float], ...]
    fingerprint: str
    document_digest: str
    version: str
    timezone: str
    publication_at: str
    publication_age_seconds: float
    source_reported_generated_at: str | None
    total_points: int
    invalid_points: int
    diagnostics: tuple[ForecastPointDiagnostic, ...]
    diagnostics_truncated: bool


class SampledSolarWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: str
    nominal_end: str
    sample_count: int = Field(ge=1, le=24)
    mean_sample_irradiance_w_m2: FiniteFloat = Field(gt=0)
    minimum_sample_irradiance_w_m2: FiniteFloat = Field(ge=0)
    samples: list[IrradianceSample] = Field(default_factory=list, max_length=24)


class SolarWindowsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["solar_windows"] = "solar_windows"
    method_version: Literal["solar_windows.point_predictions.v1"] = (
        "solar_windows.point_predictions.v1"
    )
    status: Literal["partial", "insufficient_evidence"] = "insufficient_evidence"
    source: Literal["weather4lox_visualcrossing_hourly_v1"] = SOURCE_ID
    semantic_reference: Literal["weather4lox.visualcrossing.point_irradiance.v1"] = SOURCE_RULE
    unit: Literal["W/m²"] = "W/m²"
    quantity: Literal["global_horizontal_irradiance"] = "global_horizontal_irradiance"
    timestamp_basis: Literal["unix_utc_prediction_sample"] = "unix_utc_prediction_sample"
    forecast_version: str
    source_timezone: str
    publication_at: str
    publication_age_seconds: FiniteFloat = Field(ge=0)
    source_reported_generated_at: str | None
    provider_issued_at: None = None
    forecast_confidence: None = None
    first_source_point_at: str | None
    last_source_point_at: str | None
    invalid_point_count: int = Field(ge=0, le=768)
    diagnostics: list[ForecastPointDiagnostic] = Field(max_length=16)
    diagnostics_truncated: bool
    installation_association_origin: Literal["local_admin_declaration"] = "local_admin_declaration"
    planning_status: Literal["weather_guidance_only"] = "weather_guidance_only"
    windows: list[SampledSolarWindow] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "point_predictions_do_not_establish_conditions_between_samples",
            "publication_freshness_is_not_provider_issue_or_model_freshness",
            "source_generation_time_is_not_verified_provider_issue_time",
            "forecast_confidence_is_not_supplied",
            "installation_association_is_declared_not_independently_verified",
            "no_irradiance_energy_or_pv_yield_conversion",
            "plant_model_baseload_surplus_and_native_load_constraints_unqualified",
            "no_admissible_load_schedule_operation_permission_or_saving_claim",
        ],
        max_length=16,
    )


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise HistoryAnalysisDeadline()


def _timestamp(value: object) -> float:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
        )
        is None
    ):
        raise ForecastEvidenceError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError) as exc:
        raise ForecastEvidenceError("invalid_timestamp") from exc


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ForecastEvidenceError("duplicate_json_key")
        result[key] = value
    return result


def _finite_number(value: object) -> float | None:
    if type(value) not in (int, float, Decimal):
        return None
    assert isinstance(value, int | float | Decimal)
    try:
        number = float(value)
        if not isfinite(number):
            return None
        if isinstance(value, int) and int(number) != value:
            return None
        if isinstance(value, Decimal) and Decimal(str(number)) != value:
            return None
        return number
    except OverflowError:
        return None


def _generation_time(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value
        )
        is None
    ):
        return None
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError:
        return None


def parse_local_forecast(
    payload: bytes,
    *,
    publication_time: float,
    target_origin: str,
    now: float,
    deadline: float,
) -> ParsedForecast:
    _check(deadline)
    if len(payload) > MAX_FORECAST_BYTES:
        raise ForecastEvidenceError("forecast_file_too_large")
    if not isfinite(publication_time) or not isfinite(now) or publication_time > now:
        raise ForecastEvidenceError("invalid_publication_clock")
    try:
        document = json.loads(payload, object_pairs_hook=_object, parse_float=Decimal)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ForecastEvidenceError):
            raise
        raise ForecastEvidenceError("invalid_forecast_json") from exc
    if not isinstance(document, dict) or set(document) - {
        "generatedAt",
        "hourlyforecast",
        "location",
        "refresh",
        "visualcrossing",
    }:
        raise ForecastEvidenceError("unsupported_forecast_shape")
    metadata, location, rows = (
        document.get(key) for key in ("visualcrossing", "location", "hourlyforecast")
    )
    if (
        not isinstance(metadata, dict)
        or metadata.get("schemaVersion") != "v1.0"
        or metadata.get("grabberScript") != "grabber_visualcrossing.pl"
        or not isinstance(location, dict)
        or not isinstance(rows, list)
        or len(rows) > 768
    ):
        raise ForecastEvidenceError("unsupported_forecast_source")
    zone_name = location.get("timezone")
    if not isinstance(zone_name, str) or len(zone_name) > 128:
        raise ForecastEvidenceError("invalid_source_timezone")
    try:
        zone = timezone(zone_name)
    except ValueError as exc:
        raise ForecastEvidenceError("invalid_source_timezone") from exc
    latitude, longitude = (_finite_number(location.get(key)) for key in ("latitude", "longitude"))
    if latitude is None or longitude is None:
        raise ForecastEvidenceError("invalid_source_location")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ForecastEvidenceError("invalid_source_location")
    identity = [
        SOURCE_RULE,
        target_origin,
        float(latitude) or 0.0,
        float(longitude) or 0.0,
        zone_name,
    ]
    fingerprint = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    generated = _generation_time(document.get("generatedAt"))
    found = []
    diagnostics = []
    timestamp_counts: Counter[float] = Counter()
    for index, row in enumerate(rows):
        _check(deadline)
        issue: ForecastIssue | None = None
        at = None
        value = row.get("solarRadiation") if isinstance(row, dict) else None
        raw_number = _finite_number(value)
        clock = row.get("time") if isinstance(row, dict) else None
        try:
            if not isinstance(clock, dict):
                raise ForecastEvidenceError("invalid_timestamp")
            at = _timestamp(clock.get("datetime"))
            timestamp_counts[at] += 1
            local = datetime.fromtimestamp(at, zone)
            claimed = datetime.fromisoformat(clock["datetime"])
            if (
                type(clock.get("epoch")) is not int
                or clock["epoch"] != at
                or local.utcoffset() != claimed.utcoffset()
            ):
                issue = "epoch_or_offset_mismatch"
        except (ForecastEvidenceError, ValueError, OverflowError):
            issue = "invalid_timestamp"
        if issue is None:
            if value is None:
                issue = "missing_irradiance"
            elif type(value) not in (int, float, Decimal):
                issue = "non_numeric_irradiance"
            elif raw_number is None:
                try:
                    finite = isfinite(float(value))
                except OverflowError:
                    finite = False
                issue = "numeric_precision_not_supported" if finite else "non_finite_irradiance"
            elif value < 0:
                issue = "negative_irradiance"
        if issue is not None:
            diagnostics.append(
                ForecastPointDiagnostic(
                    index=index,
                    at=utc_timestamp(at) if at is not None else None,
                    issue=issue,
                    raw_number=raw_number,
                    raw_numeric_text=(
                        str(value)
                        if issue == "numeric_precision_not_supported" and len(str(value)) <= 256
                        else None
                    ),
                )
            )
        else:
            assert at is not None and raw_number is not None
            found.append((index, at, raw_number))
    points = []
    for index, at, value in found:
        _check(deadline)
        if timestamp_counts[at] > 1:
            diagnostics.append(
                ForecastPointDiagnostic(
                    index=index, at=utc_timestamp(at), issue="duplicate_timestamp", raw_number=value
                )
            )
        else:
            points.append((at, value))
    points.sort()
    diagnostics.sort(key=lambda item: item.index)
    try:
        published = utc_timestamp(publication_time)
    except (ValueError, OverflowError, OSError) as exc:
        raise ForecastEvidenceError("invalid_publication_clock") from exc
    # The public version excludes location identity and unrelated foreign data.
    version = hashlib.sha256(
        json.dumps(
            [
                SOURCE_RULE,
                points,
                published,
                generated,
                zone_name,
                len(rows),
                len(diagnostics),
                [item.model_dump() for item in diagnostics[:16]],
                len(diagnostics) > 16,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ParsedForecast(
        tuple(points),
        fingerprint,
        hashlib.sha256(payload).hexdigest(),
        version,
        zone_name,
        published,
        now - publication_time,
        generated,
        len(rows),
        len(diagnostics),
        tuple(diagnostics[:16]),
        len(diagnostics) > 16,
    )


def sampled_solar_windows(
    forecast: ParsedForecast,
    options: SolarWindowOptions,
    *,
    now: float,
    deadline: float,
    limit: int = 16,
) -> SolarWindowsResult:
    _check(deadline)
    start, end = _timestamp(options.start), _timestamp(options.end)
    try:
        zone = timezone(options.timezone)
    except ValueError as exc:
        raise ForecastEvidenceError("invalid_future_timezone") from exc
    first, last = (datetime.fromtimestamp(at, UTC).astimezone(zone) for at in (start, end))
    touched = (last.date() - first.date()).days + (
        last.time().replace(tzinfo=None) != datetime.min.time()
    )
    if not now <= start < end or touched > 31 or not 1 <= limit <= 16:
        raise ForecastEvidenceError("invalid_future_window")
    result = SolarWindowsResult(
        forecast_version=forecast.version,
        source_timezone=forecast.timezone,
        publication_at=forecast.publication_at,
        publication_age_seconds=forecast.publication_age_seconds,
        source_reported_generated_at=forecast.source_reported_generated_at,
        first_source_point_at=utc_timestamp(forecast.points[0][0]) if forecast.points else None,
        last_source_point_at=utc_timestamp(forecast.points[-1][0]) if forecast.points else None,
        invalid_point_count=forecast.invalid_points,
        diagnostics=list(forecast.diagnostics),
        diagnostics_truncated=forecast.diagnostics_truncated,
    )
    candidates = []
    count = options.duration_hours
    with localcontext() as context:
        context.prec = 800
        for index in range(len(forecast.points)):
            _check(deadline)
            samples = forecast.points[index : index + count]
            if (
                len(samples) != count
                or not start <= samples[0][0]
                or samples[-1][0] + 3600 > end
                or any(at != samples[0][0] + i * 3600 for i, (at, _) in enumerate(samples))
                or any(value < options.minimum_sample_irradiance_w_m2 for _, value in samples)
            ):
                continue
            mean = sum((Decimal(str(value)) for _, value in samples), Decimal(0)) / count
            if mean > 0:
                candidates.append((mean, samples))
    selected: list[tuple[float, float]] = []
    for mean, samples in sorted(
        candidates, key=lambda item: (item[0].copy_negate(), item[1][0][0])
    ):
        _check(deadline)
        a, b = samples[0][0], samples[-1][0] + 3600
        if any(a < d and c < b for c, d in selected):
            continue
        public_mean = float(mean)
        if public_mean <= 0 or not isfinite(public_mean):
            if "sample_mean_not_representable" not in result.limitations:
                result.limitations.append("sample_mean_not_representable")
            continue
        selected.append((a, b))
        result.windows.append(
            SampledSolarWindow(
                start=utc_timestamp(a),
                nominal_end=utc_timestamp(b),
                sample_count=count,
                mean_sample_irradiance_w_m2=public_mean,
                minimum_sample_irradiance_w_m2=min(v for _, v in samples),
                samples=[
                    IrradianceSample(at=utc_timestamp(at), irradiance_w_m2=value)
                    for at, value in samples
                ]
                if options.include_samples
                else [],
            )
        )
        if len(result.windows) == limit:
            break
    if result.windows:
        result.status = "partial"
    else:
        result.limitations.append("no_complete_positive_sampled_window_in_requested_future_range")
    return result
