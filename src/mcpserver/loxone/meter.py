"""Documented normalized meter outputs, independent of physical input polarity."""

from __future__ import annotations

from .models import Control

DOCUMENTS = {
    "unidirectional": "https://www.loxone.com/dede/kb/zaehler/",
    "bidirectional": "https://www.loxone.com/dede/kb/zaehler-bidirektional/",
    "storage": "https://www.loxone.com/dede/kb/zaehler-speicher/",
}
CONVENTIONS = {
    "unidirectional": "non_negative",
    "bidirectional": "positive_consumption_negative_delivery",
    "storage": "positive_discharge_negative_charge",
}
READINGS = frozenset({"total", "totalDay", "totalWeek", "totalMonth", "totalYear"})
NEGATIVE_READINGS = frozenset(
    {"totalNeg", "totalNegDay", "totalNegWeek", "totalNegMonth", "totalNegYear"}
)


def output_convention(control: Control, channel: str) -> str | None:
    """No name, powerName/PwrN, unit, value-sign or EFM-role inference."""
    if (
        control.control_type != "Meter"
        or control.meter_type is None
        or control.meter_type not in DOCUMENTS
        or "meter_type" in control.semantics_invalid_fields
    ):
        return None
    if channel == "actual":
        return CONVENTIONS[control.meter_type]
    if channel in READINGS or (
        control.meter_type != "unidirectional" and channel in NEGATIVE_READINGS
    ):
        return "non_negative"
    return None


def output_direction(meter_type: str, value: int | float) -> str:
    if value == 0:
        return "zero"
    if meter_type == "storage":
        return "discharge" if value > 0 else "charge"
    if meter_type == "bidirectional":
        return "consumption" if value > 0 else "delivery"
    return "single_direction"
