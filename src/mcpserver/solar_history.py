"""Bounded normalization of observed solar data, independent of transport and storage.

Contracts are supplied by source adapters after source qualification, never by an
analysis caller. Forecasts are deliberately not an accepted observation origin.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from mcpserver.comparable_days import _check

Quantity = Literal["irradiance", "radiation_energy", "temperature", "energy"]
Unit = Literal["W/m²", "Wh/m²", "MJ/m²", "°C", "Wh", "kWh"]


@dataclass(frozen=True, slots=True)
class ObservationContract:
    """A source-specific, documented contract; not an assertion of calibration."""

    quantity: Quantity
    unit: Unit
    installation: str
    generation: str
    reference: str
    sample_period_seconds: int | None = None
    origin: Literal["observed"] = "observed"

    def validate(self) -> None:
        allowed: dict[str, set[str]] = {
            "irradiance": {"W/m²"},
            "radiation_energy": {"Wh/m²", "MJ/m²"},
            "temperature": {"°C"},
            "energy": {"Wh", "kWh"},
        }
        if self.origin != "observed" or self.unit not in allowed.get(self.quantity, set()):
            raise ValueError("observed_quantity_unit_contract_required")
        if not all((self.installation, self.generation, self.reference)):
            raise ValueError("source_identity_and_contract_reference_required")
        if self.quantity == "irradiance" and (
            type(self.sample_period_seconds) is not int
            or not 1 <= self.sample_period_seconds <= 3600
        ):
            raise ValueError("documented_sampling_period_required")


@dataclass(frozen=True, slots=True)
class Observation:
    start: float
    value: float
    end: float | None = None


@dataclass(frozen=True, slots=True)
class HourlyObservation:
    start: float
    end: float
    value: float
    unit: str
    origin: Literal["observed", "estimated"]
    method: str


def normalize_hours(
    observations: Sequence[Observation],
    contract: ObservationContract,
    starts: Sequence[float],
    *,
    deadline: float,
) -> tuple[HourlyObservation, ...]:
    """Normalize complete requested hours in one pass after sorting.

    Irradiance is linearly interpolated only between adjacent measured points;
    no extrapolation or bridging beyond min(2 * cadence, 3600 s) is allowed.
    Temperature uses an exact hour-start observation. Energy intervals must
    exactly match an hour; partial interval energy is never apportioned.
    """
    contract.validate()
    _check(deadline)
    if len(observations) > 100_000 or len(starts) > 31 * 24:
        raise ValueError("solar_normalization_budget_exceeded")
    if any(isinstance(t, bool) or not math.isfinite(t) for t in starts):
        raise ValueError("invalid_hour_position")
    hours = sorted(set(starts))
    if len(hours) != len(starts) or any(b < a + 3600 for a, b in pairwise(hours)):
        raise ValueError("duplicate_or_overlapping_hours")
    points = sorted(observations, key=lambda item: item.start)
    previous: float | None = None
    for point in points:
        _check(deadline)
        if (
            isinstance(point.start, bool)
            or not math.isfinite(point.start)
            or isinstance(point.value, bool)
            or not math.isfinite(point.value)
            or (contract.quantity != "temperature" and point.value < 0)
            or (previous is not None and point.start == previous)
            or (
                point.end is not None
                and (
                    isinstance(point.end, bool)
                    or not math.isfinite(point.end)
                    or point.end <= point.start
                )
            )
        ):
            raise ValueError("invalid_or_duplicate_solar_observation")
        previous = point.start
    if contract.quantity == "irradiance":
        if any(point.end is not None for point in points):
            raise ValueError("irradiance_point_observations_required")
        return _integrate(points, hours, contract, deadline)
    index = {point.start: point for point in points}
    result = []
    factor = {"MJ/m²": 1_000_000 / 3600, "kWh": 1000}.get(contract.unit, 1)
    for start in hours:
        _check(deadline)
        selected = index.get(start)
        if selected is None:
            continue
        temperature = contract.quantity == "temperature"
        if (temperature and selected.end is not None) or (
            not temperature and selected.end != start + 3600
        ):
            continue
        # An additional overlapping interval invalidates the source, not just
        # the duplicate's start position. Check once in the ordered input below.
        value = selected.value * factor
        if not math.isfinite(value):
            raise ValueError("solar_normalization_overflow")
        result.append(
            HourlyObservation(
                start,
                start + 3600,
                value,
                (
                    "°C"
                    if temperature
                    else "Wh/m²"
                    if contract.quantity == "radiation_energy"
                    else "Wh"
                ),
                "observed",
                "hour_start_sample" if temperature else "whole_interval_unit_conversion",
            )
        )
    last_end: float | None = None
    for point in points:
        _check(deadline)
        if point.end is not None:
            if last_end is not None and point.start < last_end:
                raise ValueError("overlapping_solar_observations")
            last_end = point.end
    return tuple(result)


def _integrate(
    points: list[Observation],
    hours: list[float],
    contract: ObservationContract,
    deadline: float,
) -> tuple[HourlyObservation, ...]:
    assert contract.sample_period_seconds is not None
    gap_limit = min(2 * contract.sample_period_seconds, 3600)
    result = []
    index = 0
    for start in hours:
        _check(deadline)
        end = start + 3600
        while index + 1 < len(points) and points[index + 1].start <= start:
            _check(deadline)
            index += 1
        position, cursor = start, index
        areas = []
        while cursor + 1 < len(points) and position < end:
            _check(deadline)
            left, right = points[cursor], points[cursor + 1]
            gap = right.start - left.start
            if not left.start <= position < right.start or gap > gap_limit:
                break
            stop = min(end, right.start)
            # Convex combinations avoid overflowing a subtraction between
            # opposite-sign finite values; irradiance is nonnegative.
            a = (position - left.start) / gap
            b = (stop - left.start) / gap
            first = left.value * (1 - a) + right.value * a
            last = left.value * (1 - b) + right.value * b
            areas.append((first / 2 + last / 2) * ((stop - position) / 3600))
            position = stop
            cursor += 1
        if position == end:
            try:
                value = math.fsum(areas)
            except OverflowError:
                raise ValueError("solar_normalization_overflow") from None
            if not math.isfinite(value):
                raise ValueError("solar_normalization_overflow")
            result.append(
                HourlyObservation(
                    start, end, value, "Wh/m²", "estimated", "bounded_trapezoidal_irradiance.v1"
                )
            )
    return tuple(result)
