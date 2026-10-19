from dataclasses import replace

import pytest

from mcpserver.loxone.models import StatisticSeries
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure

MISSING = object()


def fixture(kind=MISSING, *, states=None, **details):
    if kind is not MISSING:
        details["type"] = kind
    raw = {
        "msInfo": {"serialNr": "synthetic"},
        "controls": {
            "meter": {
                "name": "Storage consumption delivery kWh",
                "type": "Meter",
                "details": details,
                "states": states or {"actual": "power", "total": "counter"},
            }
        },
    }
    structure = normalize_structure(raw, username="reader")
    return structure, structure.controls[0]


def resolve(kind, value, channel="actual", **details):
    structure, control = fixture(kind, **details)
    return StateSemanticsResolver().resolve(structure, control, channel, value, {})


@pytest.mark.parametrize("kind", ["unidirectional", "bidirectional", "storage", "legacy"])
def test_explicit_documented_subtype_is_retained(kind):
    _, control = fixture(kind)
    assert control.meter_type == kind and not control.meter_type_defaulted


def test_missing_subtype_has_documented_default_not_a_label_guess():
    structure, control = fixture(powerName="Battery discharge", displayType=9)
    assert control.meter_type == "unidirectional" and control.meter_type_defaulted
    descriptor, decoded = StateSemanticsResolver().resolve(structure, control, "actual", 2, {})
    assert descriptor.sign_convention == "non_negative"
    assert decoded["output_direction"] == "single_direction"
    assert descriptor.sources[0].rule_id == "Meter.type.default.v1"


@pytest.mark.parametrize("kind", [None, True, 1, {}, [], "Storage", "future", "x" * 10000])
def test_invalid_or_unknown_subtype_does_not_use_missing_default(kind):
    structure, control = fixture(kind)
    assert control.meter_type is None and "meter_type" in control.semantics_invalid_fields
    descriptor, decoded = StateSemanticsResolver().resolve(structure, control, "actual", -3, {})
    assert descriptor.sign_convention is None and decoded is None


@pytest.mark.parametrize("kind", [MISSING, "unidirectional"])
@pytest.mark.parametrize("state", ["totalNeg", "totalNegDay", "storage"])
def test_conflicting_unidirectional_channels_drop_enrichment(kind, state):
    _, control = fixture(kind, states={"actual": "power", state: "extra"})
    assert control.meter_type is None and "meter_type" in control.semantics_invalid_fields


@pytest.mark.parametrize(
    "kind,convention,negative,positive",
    [
        ("storage", "positive_discharge_negative_charge", "charge", "discharge"),
        ("bidirectional", "positive_consumption_negative_delivery", "delivery", "consumption"),
    ],
)
@pytest.mark.parametrize("value", [-2.5, 0, 2.5])
def test_normalized_output_sign_is_independent_of_labels_and_units(
    kind, convention, negative, positive, value
):
    descriptor, decoded = resolve(kind, value, powerName="unrelated text", format="m³/h")
    assert descriptor.sign_convention == convention
    assert decoded["value"] == value
    assert decoded["output_direction"] == (
        negative if value < 0 else positive if value > 0 else "zero"
    )
    assert descriptor.unit is None and descriptor.measurement_quantity is None
    assert descriptor.interpretation_status == "partial"
    assert all("sign_convention" in s.fields for s in descriptor.sources[1:])


@pytest.mark.parametrize("value", [0, 1.5])
def test_unidirectional_includes_zero_without_consumer_or_producer_inference(value):
    descriptor, decoded = resolve("unidirectional", value)
    assert descriptor.sign_convention == "non_negative"
    assert decoded["output_direction"] == ("zero" if value == 0 else "single_direction")


@pytest.mark.parametrize("kind", ["unidirectional", "bidirectional", "storage"])
@pytest.mark.parametrize("value", [True, False, "2", float("nan"), float("inf"), 10**1000])
def test_invalid_numbers_get_no_semantic_value(kind, value):
    descriptor, decoded = resolve(kind, value)
    assert descriptor.reason == "invalid_documented_value" and decoded is None


def test_negative_uni_is_invalid_without_clamping_raw_value():
    descriptor, decoded = resolve("unidirectional", -1)
    assert descriptor.interpretation_status == "invalid" and decoded is None
    assert descriptor.sign_convention == "non_negative"


@pytest.mark.parametrize("kind", ["bidirectional", "storage"])
def test_directional_readings_are_nonnegative_not_signed_net_readings(kind):
    structure, control = fixture(kind, states={"total": "a", "totalNeg": "b"})
    for channel in ["total", "totalNeg"]:
        descriptor, decoded = StateSemanticsResolver().resolve(structure, control, channel, 10, {})
        assert descriptor.sign_convention == "non_negative"
        assert "output_direction" not in decoded  # No undocumented native total/KB alias.
        bad, value = StateSemanticsResolver().resolve(structure, control, channel, -10, {})
        assert bad.interpretation_status == "invalid" and value is None


def test_legacy_and_unrelated_channels_do_not_gain_new_rules():
    assert resolve("legacy", -2)[0].sign_convention is None
    assert resolve("storage", 10, "storage")[0].sign_convention is None
    structure, control = fixture("storage")
    result, decoded = StateSemanticsResolver().resolve(
        structure, replace(control, control_type="EFM"), "actual", 2, {}
    )
    assert result.sign_convention is None and decoded is None


@pytest.mark.parametrize("kind", ["unidirectional", "bidirectional", "storage"])
def test_advertised_statistics_share_sign_rule_and_profile_source_changes(kind):
    _, control = fixture(kind)
    resolver = StateSemanticsResolver()
    series = StatisticSeries("v2:1:actual", "statistic_v2", "1", "actual", "Synthetic", "%.3f kW")
    result = resolver.resolve_series(control, series)
    descriptor = resolve(kind, None)[0]
    assert result.sign_convention == descriptor.sign_convention
    assert result.measurement_boundary is None and result.direction is None
    assert f"Meter.output.{kind}.actual.v1" in resolver.source_reference(control, series=series)
    assert (
        resolver.resolve_series(control, replace(series, accumulated=True)).sign_convention is None
    )
    assert resolver.resolve_series(control, replace(series, output="Spwr")).sign_convention is None


def test_difference_sums_do_not_inherit_nonnegative_counter_output_rule():
    _, control = fixture("storage")
    series = StatisticSeries(
        "v2:1:total", "statistic_v2", "1", "total", "Synthetic", "%.3f kWh", accumulated=True
    )
    resolver = StateSemanticsResolver()
    assert resolver.resolve_series(control, series).sign_convention == "non_negative"
    result = resolver.resolve_series(control, series, granularity="hour")
    assert result.value_meaning == "interval_difference_sum"
    assert result.sign_convention is None
    assert "decreases_require_reset_evidence" in result.limitations
