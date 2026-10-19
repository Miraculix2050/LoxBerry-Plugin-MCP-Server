import time
from dataclasses import replace

import pytest

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.solar_history import Observation, ObservationContract, normalize_hours


def contract(quantity="irradiance", unit="W/m²", cadence=900):
    return ObservationContract(quantity, unit, "plant", "generation", "fixture", cadence)


def normalize(points, source=None, starts=(0,)):
    return normalize_hours(points, source or contract(), starts, deadline=time.monotonic() + 5)


def test_trapezoidal_energy_and_provenance():
    hours = normalize([Observation(t, t / 9) for t in range(0, 7201, 900)], starts=(0, 3600))
    assert [hour.value for hour in hours] == [200, 600]
    assert all(hour.origin == "estimated" and hour.unit == "Wh/m²" for hour in hours)


def test_boundary_interpolation_without_extrapolation():
    points = [Observation(-450, 100), Observation(450, 300)]
    points += [Observation(t, 300) for t in range(1350, 4051, 900)]
    assert normalize(points)[0].value == 293.75
    assert normalize(points[1:]) == ()
    assert normalize(points[:-1]) == ()


def test_gap_limit_is_inclusive_and_never_over_one_hour():
    assert normalize([Observation(0, 100), Observation(1800, 100), Observation(3600, 100)])
    assert normalize([Observation(0, 100), Observation(1801, 100), Observation(3600, 100)]) == ()
    assert normalize([Observation(0, 100), Observation(7200, 100)], contract(cadence=3600)) == ()


@pytest.mark.parametrize("unit,value,expected", [("Wh/m²", 100, 100), ("MJ/m²", 3.6, 1000)])
def test_interval_radiation_unit_conversion(unit, value, expected):
    hour = normalize([Observation(0, value, 3600)], contract("radiation_energy", unit))[0]
    assert hour.value == pytest.approx(expected, abs=1e-10, rel=0)
    assert hour.origin == "observed"
    assert normalize([Observation(0, value, 1800)], contract("radiation_energy", unit)) == ()


def test_temperature_requires_exact_hour_start_and_energy_retains_boundary():
    assert normalize([Observation(0, -3)], contract("temperature", "°C"))[0].value == -3
    assert normalize([Observation(1, 20)], contract("temperature", "°C", cadence=None)) == ()
    assert normalize([Observation(0, 2, 3600)], contract("energy", "kWh"))[0].value == 2000


def test_temperature_bounded_sample_offset_is_explicit():
    hour = normalize([Observation(60, 20)], contract("temperature", "°C", cadence=60))[0]
    assert hour.method == "within_60s_of_hour_start" and hour.sample_at == 60
    assert normalize([Observation(61, 20)], contract("temperature", "°C", cadence=60)) == ()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -1])
def test_invalid_irradiance_is_rejected(bad):
    with pytest.raises(ValueError):
        normalize([Observation(0, bad)])


def test_duplicate_and_overlapping_data_are_not_summed():
    with pytest.raises(ValueError, match="duplicate"):
        normalize([Observation(0, 1), Observation(0, 2)])
    with pytest.raises(ValueError, match="overlapping"):
        normalize(
            [Observation(0, 1, 3600), Observation(1800, 1, 5400)],
            contract("radiation_energy", "Wh/m²"),
        )


def test_contract_cannot_turn_forecasts_or_unknown_units_into_observations():
    for source in (
        replace(contract(), origin="forecast"),
        replace(contract(), unit="lux"),
        replace(contract(), generation=""),
        replace(contract(), reference=""),
        replace(contract(), sample_period_seconds=None),
    ):
        with pytest.raises(ValueError):
            normalize([], source)


def test_deadline_and_input_budget():
    with pytest.raises(HistoryAnalysisDeadline):
        normalize_hours([], contract(), [0], deadline=0)
    with pytest.raises(ValueError, match="budget"):
        normalize([Observation(0, 1)] * 100_001)


def test_each_hour_is_normalized_once_from_shared_input():
    points = [Observation(t, 100) for t in range(0, 31 * 24 * 3600 + 1, 900)]
    hours = normalize(points, starts=tuple(range(0, 31 * 24 * 3600, 3600)))
    assert len(hours) == 744
    assert all(hour.value == 100 for hour in hours)
