"""Generation-specific, bounded native metadata and TextEvent decoding.

No network access, control authorization, scheduling or energy balance logic.
Structure metadata and state payload identities are deliberately not joined.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

MAX_LOADS = 100
MAX_JSON_BYTES = 16_384
DOCUMENT = "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf"
GENERATION = {"EnergyManager": 1, "EnergyManager2": 2}
PowerRole = Literal[
    "grid_power", "storage_power", "production_power", "maximum_storage_power_parameter"
]
PercentageRole = Literal["storage_state_of_charge", "minimum_storage_soc_parameter"]
POWER_ROLES: dict[str, PowerRole] = {
    "Gpwr": "grid_power",
    "Spwr": "storage_power",
    "Ppwr": "production_power",
    "MaxSpwr": "maximum_storage_power_parameter",
}
PERCENT_ROLES: dict[str, PercentageRole] = {
    "Ssoc": "storage_state_of_charge",
    "MinSoc": "minimum_storage_soc_parameter",
}
Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class LoadMetadata:
    id: int
    name: str | None = None
    minimum_on_time_seconds: int | float | None = None
    trigger_status: Literal["unavailable_zero_min_on_time", "unverified"] = "unverified"


@dataclass(frozen=True, slots=True)
class ManagerMetadata:
    generation: Literal[1, 2]
    status: Literal["missing", "valid", "invalid"]
    declared_loads: Annotated[tuple[LoadMetadata, ...], Field(max_length=MAX_LOADS)] = ()
    minimum_soc_parameter_edit_locked: bool | None = None
    maximum_storage_power_parameter_edit_locked: bool | None = None
    storage_soc_input_connected_and_valid: bool | None = None
    storage_power_input_connected_and_valid: bool | None = None
    diagnostics: tuple[str, ...] = ()


def _text(value: object, maximum: int = 200) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("invalid_text")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError("invalid_text")
    return value


def _number(value: object, *, nonnegative: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("invalid_number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (nonnegative and value < 0):
        raise ValueError("invalid_number")
    return value


def _identifier(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_147_483_647:
        raise ValueError("invalid_identifier")
    return value


def normalize(kind: str, details: Mapping[str, object]) -> ManagerMetadata | None:
    """Retain only documented fields, independently of caller disclosure policy."""
    if kind not in GENERATION:
        return None
    if kind == "EnergyManager":
        if "loads" not in details:
            return ManagerMetadata(1, "missing")
        raw = details["loads"]
        if not isinstance(raw, list) or len(raw) > MAX_LOADS:
            return ManagerMetadata(1, "invalid", diagnostics=("invalid_load_metadata",))
        loads: list[LoadMetadata] = []
        ids: set[int] = set()
        try:
            for item in raw:
                if not isinstance(item, Mapping):
                    raise ValueError("invalid_load_metadata")
                load_id = _identifier(item.get("id"))
                if load_id in ids:
                    raise ValueError("duplicate_load_identity")
                ids.add(load_id)
                minimum = (
                    _number(item["minOnTime"], nonnegative=True) if "minOnTime" in item else None
                )
                loads.append(
                    LoadMetadata(
                        load_id,
                        _text(item["name"]) if "name" in item else None,
                        minimum,
                        "unavailable_zero_min_on_time" if minimum == 0 else "unverified",
                    )
                )
        except (ValueError, UnicodeError):
            return ManagerMetadata(1, "invalid", diagnostics=("invalid_load_metadata",))
        if (
            len(
                json.dumps(
                    [
                        {"id": row.id, "name": row.name, "minOnTime": row.minimum_on_time_seconds}
                        for row in loads
                    ],
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            > MAX_JSON_BYTES
        ):
            return ManagerMetadata(1, "invalid", diagnostics=("load_metadata_too_large",))
        return ManagerMetadata(1, "valid", tuple(loads))
    names = (
        "MinSocLocked",
        "MaxSpwrLocked",
        "HasSsoc",
        "HasSpwr",
    )
    flags: list[bool | None] = []
    invalid: list[str] = []
    for name in names:
        value = details.get(name)
        flags.append(value if isinstance(value, bool) else None)
        if name in details and not isinstance(value, bool):
            invalid.append(name)
    return ManagerMetadata(
        2,
        "invalid" if invalid else "valid" if any(name in details for name in names) else "missing",
        minimum_soc_parameter_edit_locked=flags[0],
        maximum_storage_power_parameter_edit_locked=flags[1],
        storage_soc_input_connected_and_valid=flags[2],
        storage_power_input_connected_and_valid=flags[3],
        diagnostics=tuple(f"invalid_{name}" for name in invalid),
    )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def decode_loads(generation: Literal[1, 2], value: object) -> dict[str, object]:
    """Decode one bounded last-delivered payload without metadata/state joins."""
    if not isinstance(value, str) or len(value) > MAX_JSON_BYTES:
        raise ValueError("invalid_load_payload")
    if len(value.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("invalid_load_payload")
    raw = json.loads(
        value,
        object_pairs_hook=_pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )
    if not isinstance(raw, list) or len(raw) > MAX_LOADS:
        raise ValueError("invalid_load_payload")
    booleans = (
        ("isActive", "isPreparing", "isWaitingforActivation", "isPermanentOn")
        if generation == 1
        else (
            "hasActual",
            "active",
            "activatedManually",
            "deactivatedManually",
            "activeDueToDailyRuntime",
        )
    )
    numbers = ("activeUntil",) if generation == 1 else ("pwr", "ppwr", "minimumActiveUntil")
    texts = () if generation == 1 else ("name", "uuid", "icon")
    identifiers = ("id",) if generation == 1 else ("id", "prio")
    documented = {*booleans, *numbers, *texts, *identifiers}
    loads: list[dict[str, Scalar]] = []
    ids: set[int] = set()
    references: set[str] = set()
    omitted = 0
    for item in raw:
        if not isinstance(item, dict) or len(item) > 16:
            raise ValueError("invalid_load_payload")
        if any(isinstance(v, dict | list) for v in item.values()):
            raise ValueError("nested_load_value")
        if any(isinstance(v, float) and not math.isfinite(v) for v in item.values()):
            raise ValueError("nonfinite_load_value")
        load_id = _identifier(item.get("id"))
        if load_id in ids:
            raise ValueError("duplicate_load_identity")
        ids.add(load_id)
        row: dict[str, Scalar] = {"id": load_id}
        for name in identifiers[1:]:
            row[name] = _identifier(item[name]) if name in item else None
        for name in booleans:
            if name in item and not isinstance(item[name], bool):
                raise ValueError("invalid_load_boolean")
            row[name] = item.get(name)
        for name in numbers:
            row[name] = (
                _number(item[name], nonnegative=name not in {"pwr", "ppwr"})
                if name in item
                else None
            )
        for name in texts:
            row[name] = _text(item[name], 512 if name == "icon" else 200) if name in item else None
        if generation == 2:
            reference = row["uuid"]
            if isinstance(reference, str):
                if not reference or reference in references:
                    raise ValueError("invalid_load_reference")
                references.add(reference)
            row["power_evidence"] = (
                "status_feedback_type_unverified"
                if row["hasActual"] is True
                else "manager_assumption"
                if row["hasActual"] is False
                else "unknown"
            )
        omitted += len(item.keys() - documented)
        loads.append(row)
    return {
        "generation": generation,
        "loads": loads,
        "structure_load_association": "unverified" if generation == 1 else "not_joined",
        "load_power_unit": None,
        "priority_direction": None,
        "native_activation_is_physical_cycle": False,
        "has_actual_proves_power_meter": False,
        "time_axis": "seconds_since_2009_timezone_unverified"
        if generation == 1
        else "utc_seconds_since_2009",
        "zero_active_until_meaning": "active_without_end_when_output_active"
        if generation == 1
        else "unverified",
        "omitted_undocumented_fields": omitted,
    }
