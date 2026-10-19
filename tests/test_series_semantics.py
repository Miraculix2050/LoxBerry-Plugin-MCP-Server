from dataclasses import replace

import pytest

from mcpserver.loxone.models import Control, StatisticSeries
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure


def series(**changes):
    return replace(
        StatisticSeries("v2:2:total", "statistic_v2", "2", "total", "Synthetic", "%.3f kWh", True),
        **changes,
    )


def control(kind="Meter"):
    return Control("c", "PV import battery", kind, None, None, None, (("total", "s"),))


def resolve(item=None, kind="Meter", granularity="raw"):
    return StateSemanticsResolver().resolve_series(
        control(kind), item or series(), granularity=granularity
    )


@pytest.mark.parametrize("fmt,unit", [("0,000kWh", "kWh"), ("%.3f Wh", "Wh")])
def test_efm_self_consumption_counter_has_narrow_hourly_contract(fmt, unit):
    item = series(output="totalSelfConsumption", format=fmt)
    result = resolve(item, kind="EFM", granularity="hour")
    assert result.measurement_quantity == "energy" and result.unit == unit
    assert result.measurement_role == "native_self_consumption_channel"
    assert result.value_meaning == "interval_difference_sum"
    assert result.timestamp_basis == "unix_utc" and result.timestamp_position == "interval_start"
    assert result.reset_semantics is None
    assert "native_efm_calculation_not_independent_meter" in result.limitations
    assert "measurement_boundary_unverified" in result.limitations
    assert StateSemanticsResolver().source_reference(control("EFM"), series=item) == (
        "StatisticV2.series.v1+EFM.series.totalSelfConsumption.v1"
    )


@pytest.mark.parametrize(
    "changes,kind",
    [
        ({"format": "0,000kW"}, "EFM"),
        ({"format": "0,00€"}, "EFM"),
        ({"format": "0%"}, "EFM"),
        ({"format": "1,000kWh"}, "EFM"),
        ({"accumulated": False}, "EFM"),
        ({"source": "legacy"}, "EFM"),
        ({"output": "selfConsumption"}, "EFM"),
        ({}, "InfoOnlyAnalog"),
        ({}, "Meter"),
    ],
)
def test_other_channels_cannot_borrow_efm_self_consumption_contract(changes, kind):
    item = series(output="totalSelfConsumption", format="0,000kWh")
    result = resolve(replace(item, **changes), kind=kind, granularity="hour")
    assert result.unit is None and result.measurement_quantity is None
    assert all(source.rule_id != "EFM.series.totalSelfConsumption.v1" for source in result.sources)


@pytest.mark.parametrize("granularity", ["raw", "hour", "day", "month", "year"])
def test_counter_and_adapter_difference_meaning(granularity):
    result = resolve(granularity=granularity)
    assert result.value_meaning == (
        "cumulative_counter" if granularity == "raw" else "interval_difference_sum"
    )
    assert result.timestamp_basis == "unix_utc"
    assert result.timestamp_position == (
        "observation"
        if granularity == "raw"
        else "interval_start"
        if granularity == "hour"
        else None
    )
    assert result.measurement_quantity == "energy" and result.unit == "kWh"
    assert result.unit_origin == "structure_declared"
    assert (
        result.measurement_method is None
        and result.measurement_boundary is None
        and result.direction is None
    )
    assert result.rollover_semantics is None
    assert "decreases_require_reset_evidence" in result.limitations
    assert result.reset_semantics == "control_reset_to_zero_supported"


@pytest.mark.parametrize("fmt", ["kWh-ish", "%.3f W", "%.3f kWh extra", "%.3f m³", "x" * 100])
def test_names_and_conflicting_or_unsupported_units_remain_unknown(fmt):
    result = resolve(series(format=fmt))
    assert result.unit is None and result.measurement_quantity is None
    assert result.direction is None and result.measurement_method is None


@pytest.mark.parametrize("kind", ["EFM", "InfoOnlyAnalog", "UnknownMeter", "MeterStorage"])
def test_unknown_families_get_only_explicit_statistic_meaning(kind):
    result = resolve(kind=kind)
    assert result.value_meaning == "cumulative_counter"
    assert result.unit is None and result.measurement_quantity is None


def test_nonaccumulated_is_not_interval_energy_or_a_time_average():
    item = series(accumulated=False, output="actual", format="%.3f kW", recording_mode=8)
    result = resolve(item)
    assert result.value_meaning == "sample" and result.measurement_quantity == "power"
    assert result.recording_mode == 8 and result.timestamp_position == "observation"
    assert resolve(item, granularity="hour").aggregation is None
    assert "aggregation_unverified" in resolve(item, granularity="hour").limitations
    assert resolve(replace(item, accumulated=True)).unit is None


def test_malformed_accumulated_flag_cannot_establish_counter_meaning():
    result = resolve(series(accumulated_metadata_valid=False))
    assert result.interpretation_status == "invalid" and result.value_meaning is None
    assert result.sources == ()


def test_legacy_retains_local_clock_uncertainty():
    result = resolve(series(source="legacy"))
    assert result.value_meaning is None and result.unit is None
    assert result.timestamp_basis == "local_miniserver_seconds_since_2009"
    assert "legacy_timezone_conversion_unverified" in result.limitations


def test_temperature_series_roles_units_conflicts_and_missing_current_value():
    c = replace(control("IRoomControllerV2"), state_uuids=(("tempActual", "s"),), format="%.1f°C")
    item = series(output="tempActual", accumulated=False, format="%.1f°C")
    result = StateSemanticsResolver().resolve_series(c, item)
    assert result.measurement_quantity == "temperature" and result.unit == "°C"
    assert result.measurement_role == "actual_temperature"
    assert StateSemanticsResolver().resolve_series(c, replace(item, format="%.1f°F")).unit is None
    assert (
        StateSemanticsResolver()
        .resolve_series(c, replace(item, output="value"))
        .measurement_quantity
        is None
    )
    assert StateSemanticsResolver().resolve_series(c, replace(item, accumulated=True)).unit is None


def test_rule_references_are_versioned_without_physical_role_inference():
    result = StateSemanticsResolver().source_reference(control(), series=series())
    assert result == "StatisticV2.series.v1+Meter.series.v1"
    assert (
        StateSemanticsResolver().source_reference(control("Unknown"), series=series())
        == "StatisticV2.series.v1"
    )


@pytest.mark.parametrize(
    "accumulated,valid", [(True, True), (False, True), (None, False), (1, False), ("true", False)]
)
def test_normalization_retains_semantic_validity(accumulated, valid):
    raw = {
        "msInfo": {"serialNr": "test"},
        "controls": {
            "00000001-0000-0000-0000000000000001": {
                "name": "Synthetic",
                "type": "Meter",
                "states": {},
                "statisticV2": {
                    "groups": [
                        {
                            "id": 2,
                            "mode": 8,
                            "accumulated": accumulated,
                            "dataPoints": [
                                {"title": "Synthetic", "format": "%.3f kWh", "output": "total"}
                            ],
                        }
                    ]
                },
            }
        },
    }
    item = normalize_structure(raw, username="synthetic").controls[0].statistic_series[0]
    assert item.recording_mode == 8 and item.accumulated_metadata_valid is valid


@pytest.mark.parametrize(
    "kind,name,rule",
    [
        ("SmokeAlarm", "level", "SmokeAlarm.level.active.v1"),
        ("Alarm", "level", "Alarm.level.v1"),
        ("StatusMonitor", "numState1", "StatusMonitor.numState1.v1"),
        ("WindowMonitor", "windowStates", "WindowMonitor.windowStates.v1"),
        ("Irrigation", "rainActive", "Irrigation.rainActive.v1"),
    ],
)
def test_profile_references_cover_existing_state_decoder_families(kind, name, rule):
    c = replace(control(kind), state_uuids=((name, "state"),))
    reference = StateSemanticsResolver().source_reference(c, state_name=name)
    assert reference is not None and rule in reference
    assert reference.endswith("StateSemanticsResolver.rules.v1")


def test_profile_reference_changes_with_companion_ruleset(monkeypatch):
    c = replace(control("SmokeAlarm"), state_uuids=(("level", "state"),))
    before = StateSemanticsResolver().source_reference(c, state_name="level")
    monkeypatch.setattr(
        "mcpserver.loxone.state_semantics._STATE_RULESET_REFERENCE",
        "StateSemanticsResolver.rules.v2",
    )
    assert StateSemanticsResolver().source_reference(c, state_name="level") != before
