"""Read-only native PV-production forecasts; no yield or weather reconstruction."""

from __future__ import annotations

import math
from collections.abc import Mapping

from mcpserver.loxone.source_time import loxone_time

DOCUMENT = "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=115"
ENERGY_STATES = frozenset({"period", "today", "tomorrow", "after"})
TIME_STATES = frozenset({"timestamp", "cycleFrom", "cycleUntil"})
STATES = ENERGY_STATES | TIME_STATES | {"inputperiod", "ready", "errorInfo"}


def _number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("invalid_pv_forecast_number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("invalid_pv_forecast_number")
    return value


def decode(name: str, value: object, companions: Mapping[str, object]) -> dict[str, object]:
    """Decode one exact documented state with current companion observations."""
    number = _number(value)
    base: dict[str, object] = {
        "kind": "pv_production_forecast",
        "value_origin": "forecast",
        "source_reference": DOCUMENT,
    }
    if name in TIME_STATES:
        return {
            **base,
            "status": "unavailable" if number == 0 else "available",
            "at": None if number == 0 else loxone_time(value),
        }
    if name == "ready":
        if number not in (0, 1):
            raise ValueError("invalid_pv_forecast_ready")
        return {**base, "ready": bool(number)}
    if name == "errorInfo":
        if number not in (0, 1, 2, 3):
            raise ValueError("invalid_pv_forecast_error_mask")
        return {
            **base,
            "internet_error": bool(int(number) & 1),
            "weather_service_error": bool(int(number) & 2),
        }
    if name == "inputperiod":
        if not 0 <= number <= 72:
            raise ValueError("invalid_pv_forecast_period")
        return {**base, "hours": number}
    if name not in ENERGY_STATES or (number < 0 and number != -1):
        raise ValueError("invalid_pv_forecast_energy")
    ready, error = companions.get("ready"), companions.get("errorInfo")
    ready_valid = not isinstance(ready, bool) and isinstance(ready, int | float) and ready in (0, 1)
    error_valid = (
        not isinstance(error, bool) and isinstance(error, int | float) and error in (0, 1, 2, 3)
    )
    issued, begin, end = (companions.get(key) for key in ("timestamp", "cycleFrom", "cycleUntil"))
    times = None
    try:
        times = {
            "predicted_at": loxone_time(issued),
            "cycle_from": loxone_time(begin),
            "cycle_until": loxone_time(end),
        }
        if any(_number(v) <= 0 for v in (issued, begin, end)) or _number(begin) >= _number(end):
            times = None
    except ValueError:
        pass
    period = companions.get("inputperiod")
    period_valid = (
        not isinstance(period, bool) and isinstance(period, int | float) and 0 < period <= 72
    )
    unavailable = number == -1 or (ready_valid and ready == 0) or (error_valid and error != 0)
    usable = (
        not unavailable
        and ready_valid
        and error_valid
        and times is not None
        and (name != "period" or period_valid)
    )
    return {
        **base,
        "status": "unavailable" if unavailable else "available" if usable else "incomplete",
        "horizon": name,
        "energy_kwh": number if usable else None,
        "period_hours": period if name == "period" and period_valid else None,
        "times": times,
        "limitations": [
            "forecast_is_not_observed_yield_or_historical_irradiation",
            "no_subdaily_distribution_or_inverter_limit_validation",
        ],
    }
