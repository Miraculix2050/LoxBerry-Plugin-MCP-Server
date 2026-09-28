"""Bounded, evidence-based KNX/EIB semantics for parsed project objects."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import ProjectElement

_ADDRESS = re.compile(r"^(\d{1,2})/(\d{1,4})(?:/(\d{1,3}))?$")
_EDGE_ADDRESS = re.compile(r"^(.+):(0|1)$")
_ENDPOINT_DIRECTIONS = {
    "EIBsensor": "bus_to_loxone",
    "EIBactor": "loxone_to_bus",
    "EIBextsensor": "bus_to_loxone",
}
_LOGIC_TYPES = {"EIBPush", "EibDimmer", "EIBJalousie"}


@dataclass(frozen=True, slots=True)
class KnxAddressVariant:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class KnxGroupAddress:
    """An endpoint group address without inventing an unsupported representation."""

    original: str
    canonical: str | None
    format: str | None
    segments: tuple[int, ...] | None
    source_field: str
    variant: KnxAddressVariant | None


@dataclass(frozen=True, slots=True)
class KnxDatatype:
    """A raw project datatype code; its EIS/DPT meaning is intentionally unresolved."""

    source_field: str
    source_value: str
    system: str = "unknown"
    normalized_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnxSemantics:
    """Allowlisted KNX/EIB facts derived from a confirmed project object type."""

    object_kind: str
    flow_direction: str | None
    source_type: str
    title: str | None
    description: str | None
    internal_name: str | None
    group_address: KnxGroupAddress | None
    datatype: KnxDatatype | None
    truncated_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignalUseRule:
    """One independently reviewed internal block-flow rule.

    The rule is deliberately keyed by the exact project block type and connector
    keys. Unknown blocks never receive inferred internal signal relationships.
    """

    rule_id: str
    input_key: str
    output_key: str
    interpretation: str
    effect: str | None = None


# These rules encode only compact, independently stated connector behaviour.
# They do not package Loxone documentation and must remain backed by fixtures.
_SIGNAL_USE_RULES: dict[str, tuple[SignalUseRule, ...]] = {
    "EIBPush": (
        SignalUseRule("eib_push_toggle", "Tg", "O", "rising_edge", "toggle"),
        SignalUseRule("eib_push_on", "On", "O", "rising_edge", "set_on"),
        SignalUseRule("eib_push_off", "Off", "O", "rising_edge", "set_off"),
        SignalUseRule("eib_push_status", "S", "O", "level"),
    ),
}


def signal_use_rules(block_type: str | None) -> tuple[SignalUseRule, ...]:
    """Return reviewed internal-flow rules for one exact project block type."""

    return _SIGNAL_USE_RULES.get(block_type or "", ())


def _bounded(value: str | None, field: str, limit: int, truncated: list[str]) -> str | None:
    if value is None:
        return None
    if len(value) > limit:
        truncated.append(field)
        return value[:limit]
    return value


def _group_address(
    value: str | None, source_field: str, truncated: list[str], *, allow_edge: bool = False
) -> KnxGroupAddress | None:
    original = _bounded(value, "group_address.original", 200, truncated)
    if original is None:
        return None
    if value is not None and len(value) > 200:
        return KnxGroupAddress(original, None, None, None, source_field, None)
    address = original.strip()
    variant = None
    if allow_edge and (edge := _EDGE_ADDRESS.fullmatch(address)) is not None:
        address = edge.group(1)
        variant = KnxAddressVariant("edge", edge.group(2))
    match = _ADDRESS.fullmatch(address)
    if match is None:
        return KnxGroupAddress(original, None, None, None, source_field, None)
    parts = tuple(int(item) for item in match.groups() if item is not None)
    if len(parts) == 2:
        valid = parts[0] <= 31 and parts[1] <= 2047
        format_name = "two_level"
    else:
        valid = parts[0] <= 31 and parts[1] <= 7 and parts[2] <= 255
        format_name = "three_level"
    if not valid:
        return KnxGroupAddress(original, None, None, None, source_field, None)
    return KnxGroupAddress(
        original, "/".join(str(item) for item in parts), format_name, parts, source_field, variant
    )


def is_valid_group_address_filter(value: str) -> bool:
    """Accept only modeled KNX address forms, including supported edge variants."""
    address = _group_address(value, "EibAddr", [], allow_edge=True)
    return address is not None and address.canonical is not None


def classify_knx(element: ProjectElement) -> KnxSemantics | None:
    """Return only semantics proven by the exact Loxone project type and attributes."""
    source_type = element.value("Type")
    if source_type is None:
        return None
    truncated: list[str] = []
    title = _bounded(element.value("Title"), "title", 200, truncated)
    description = _bounded(element.value("Desc"), "description", 500, truncated)
    internal_name = _bounded(element.value("IName"), "internal_name", 200, truncated)

    def result(
        object_kind: str,
        flow_direction: str | None,
        group_address: KnxGroupAddress | None,
        datatype: KnxDatatype | None,
    ) -> KnxSemantics:
        return KnxSemantics(
            object_kind,
            flow_direction,
            source_type,
            title,
            description,
            internal_name,
            group_address,
            datatype,
            tuple(truncated),
        )

    if source_type == "EIBline":
        return result("line", None, None, None)
    direction = _ENDPOINT_DIRECTIONS.get(source_type)
    if direction is not None:
        datatype_value = _bounded(element.value("EIBType"), "datatype.source_value", 200, truncated)
        datatype = KnxDatatype("EIBType", datatype_value) if datatype_value is not None else None
        address_field = "EibAddr"
        address_value = element.value(address_field)
        if source_type == "EIBextsensor" and address_value is None:
            address_field = "EibAddrPulse"
            address_value = element.value(address_field)
        address = _group_address(
            address_value, address_field, truncated, allow_edge=source_type == "EIBextsensor"
        )
        return result("endpoint", direction, address, datatype)
    if source_type in _LOGIC_TYPES:
        return result("logic_block", None, None, None)
    return None
