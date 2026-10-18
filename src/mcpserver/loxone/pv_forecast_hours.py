"""Native PVPF hourly energy contract (Structure File 17.1, pp.115-116)."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from mcpserver.loxone.source_time import loxone_time

MAX_BYTES = 32_768


class PvForecastError(ValueError):
    """Fixed, value-free source diagnostics."""


class PvForecastHour(BaseModel):
    start: int
    end: int
    energy_wh: float = Field(ge=0)


class PvForecastResult(BaseModel):
    source_kind: Literal["native_pv_forecast"] = "native_pv_forecast"
    schema_version: Literal["pv_forecast.v1"] = "pv_forecast.v1"
    status: Literal["available", "not_ready", "stale", "incomplete"]
    control_uuid: str
    retrieved_at: str
    prediction_at: int | None = None
    ready: bool | None = None
    error_info: int | None = None
    aggregates_kwh: dict[str, float | None] = Field(default_factory=dict)
    hours: list[PvForecastHour] = Field(default_factory=list, max_length=78)
    field_delivery_complete: bool = False
    limitations: list[str] = Field(
        default_factory=lambda: [
            "native_model_forecast_not_measured_energy",
            "provider_issuance_and_confidence_unknown",
            "inverter_limits_not_modeled",
        ]
    )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise PvForecastError("pv_forecast_duplicate_key")
        result[key] = value
    return result


def number(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and abs(result) <= 1e12 else None


def decode_forecast(
    raw: object, states: dict[str, object], *, control_uuid: str, retrieved_at: str, now: float
) -> PvForecastResult:
    """Convert documented hourly kWh; never manufacture missing hourly values."""
    ready = states.get("ready")
    error = number(states.get("errorInfo"))
    prediction = None
    try:
        issued = states.get("timestamp")
        if number(issued) is not None and number(issued) != 0:
            prediction = int(datetime.fromisoformat(loxone_time(issued)).timestamp())
    except ValueError:
        pass
    result = PvForecastResult(
        status="incomplete",
        control_uuid=control_uuid,
        retrieved_at=retrieved_at,
        ready=bool(ready) if type(ready) in {int, float} and ready in (0, 1) else None,
        prediction_at=prediction,
        error_info=int(error) if error is not None and error in (0, 1, 2, 3) else None,
        aggregates_kwh={
            key: number(states.get(key)) for key in ("period", "today", "tomorrow", "after")
        },
    )
    result.aggregates_kwh = {
        key: value if value is not None and value >= 0 else None
        for key, value in result.aggregates_kwh.items()
    }
    if result.ready is False:
        result.status = "not_ready"
        return result
    try:
        payload_size = len(raw.encode("utf-8")) if isinstance(raw, str) else MAX_BYTES + 1
    except UnicodeEncodeError:
        raise PvForecastError("pv_forecast_invalid_payload") from None
    if payload_size > MAX_BYTES:
        raise PvForecastError("pv_forecast_invalid_payload")
    try:
        document = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, RecursionError):
        raise PvForecastError("pv_forecast_invalid_payload") from None
    if not isinstance(document, dict) or set(document) - {"today", "tomorrow", "after"}:
        raise PvForecastError("pv_forecast_invalid_shape")
    seen: set[int] = set()
    for key in ("today", "tomorrow", "after"):
        rows = document.get(key, [])
        if not isinstance(rows, list) or len(rows) > 26:
            raise PvForecastError("pv_forecast_invalid_shape")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"t", "v"}:
                raise PvForecastError("pv_forecast_invalid_hour")
            at, energy = row["t"], number(row["v"])
            if type(at) is not int or not 0 < at < 4_102_444_800 or energy is None or energy < 0:
                raise PvForecastError("pv_forecast_invalid_hour")
            if (
                prediction is not None
                and not prediction - 26 * 3600 <= at <= prediction + 74 * 3600
            ):
                raise PvForecastError("pv_forecast_hour_outside_horizon")
            if at in seen:
                raise PvForecastError("pv_forecast_duplicate_hour")
            seen.add(at)
            result.hours.append(PvForecastHour(start=at, end=at + 3600, energy_wh=energy * 1000))
    result.hours.sort(key=lambda hour: hour.start)
    if any(a.end > b.start for a, b in zip(result.hours, result.hours[1:], strict=False)):
        raise PvForecastError("pv_forecast_overlapping_hours")
    result.field_delivery_complete = (
        bool(result.hours)
        and result.ready is not None
        and prediction is not None
        and result.error_info is not None
    )
    if prediction is not None and (now - prediction > 3 * 3600 or prediction > now + 300):
        result.status = "stale"
    elif result.field_delivery_complete and result.ready and result.error_info == 0:
        result.status = "available"
    return result
