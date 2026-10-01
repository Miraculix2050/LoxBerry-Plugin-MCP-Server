"""Pure, bounded interpretation of user-visible runtime states."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from .models import Control, LoxoneStructure


@dataclass(frozen=True, slots=True)
class SemanticsSource:
    kind: Literal["structure_file", "runtime_state", "decoder_rule"]
    reference: str
    fields: tuple[str, ...]
    rule_id: str | None = None
    document_version: str | None = None
    firmware_version: str | None = None
    state_uuid: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticsRange:
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True, slots=True)
class SemanticsEncoding:
    code: int
    label: str


@dataclass(frozen=True, slots=True)
class SemanticsPosition:
    index: int
    label: str | None


@dataclass(slots=True)
class StateSemantics:
    interpretation_status: Literal["known", "partial", "unknown", "invalid"] = "unknown"
    reason: Literal[
        "no_supported_evidence",
        "metadata_only",
        "invalid_structure_metadata",
        "position_bound_metadata",
        "incomplete_metadata",
        "value_unavailable",
        "invalid_documented_value",
        "documented_decoder",
        "companion_unavailable",
        "metadata_truncated",
    ] = "no_supported_evidence"
    value_type: str | None = None
    display_format: str | None = None
    display_format_total_length: int | None = None
    display_format_returned_length: int = 0
    display_format_truncated: bool = False
    display_format_complete: bool = False
    unit: str | None = None
    range: SemanticsRange | None = None
    precision: int | None = None
    sign_convention: str | None = None
    encoding: Annotated[list[SemanticsEncoding], Field(max_length=100)] = field(
        default_factory=list
    )
    encoding_total: int | None = None
    encoding_returned: int = 0
    encoding_truncated: bool = False
    encoding_complete: bool = False
    positions: Annotated[list[SemanticsPosition], Field(max_length=100)] = field(
        default_factory=list
    )
    positions_total: int | None = None
    positions_returned: int = 0
    positions_truncated: bool = False
    positions_complete: bool = False
    sources: Annotated[list[SemanticsSource], Field(max_length=8)] = field(default_factory=list)
    sources_returned: int = 0
    sources_total: int = 0
    sources_truncated: bool = False
    sources_complete: bool = True


_DOCUMENT = "https://www.loxone.com/enen/kb/api/"
_IRRIGATION_RULES = {"zones", "rainActive", "currentZone"}
_ALARM_RULES = {
    "isEnabled",
    "isAlarmActive",
    "confirmationNeeded",
    "entryList",
    "currentEntry",
    "nextEntry",
    "nextEntryMode",
    "ringingTime",
    "ringDuration",
    "prepareDuration",
    "snoozeTime",
    "snoozeDuration",
    "nextEntryTime",
    "deviceState",
    "deviceSettings",
    "wakeAlarmSoundSettings",
}
_FORMAT_TYPES = {"InfoOnlyAnalog", "UpDownAnalog", "Slider"}


class StateSemanticsResolver:
    """Resolve only exact, reviewed type/state rules, without I/O or role inference."""

    def resolve(
        self,
        structure: LoxoneStructure,
        control: Control,
        state_name: str,
        value: object,
        companion_values: Mapping[str, object],
    ) -> tuple[StateSemantics, object | None]:
        result = StateSemantics()
        semantic_value: object | None = None
        if control.control_type == "AalEmergency" and state_name == "status":
            result.value_type = "integer"
            labels = ("normal_operation", "alarm_triggered", "reset_active", "temporarily_disabled")
            result.encoding = [SemanticsEncoding(i, label) for i, label in enumerate(labels)]
            result.encoding_total = result.encoding_returned = 4
            result.encoding_complete = True
            result.sources.append(
                SemanticsSource(
                    "decoder_rule",
                    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=26",
                    ("semantic_value", "encoding", "value_type"),
                    rule_id="AalEmergency.status.v1",
                    document_version="17.1",
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                if (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value in (0, 1, 2, 3)
                ):
                    semantic_value = {"status": labels[int(value)], "alert_active": value == 1}
                    result.interpretation_status, result.reason = "known", "documented_decoder"
                else:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
        if control.control_type in _FORMAT_TYPES and state_name == "value":
            result.display_format_total_length = control.format_total_length
            result.display_format_returned_length = (
                len(control.format) if control.format is not None else 0
            )
            result.display_format_truncated = (
                control.format_total_length is not None and control.format_total_length > 64
            )
            result.display_format_complete = (
                control.format_total_length is not None and not result.display_format_truncated
            )
            if control.format is not None:
                result.display_format = control.format
                result.sources.append(
                    SemanticsSource("structure_file", "details.format", ("display_format",))
                )
            if control.control_type == "UpDownAnalog" and all(
                v is not None for v in (control.minimum, control.maximum, control.step)
            ):
                assert (
                    control.minimum is not None
                    and control.maximum is not None
                    and control.step is not None
                )
                result.range = SemanticsRange(control.minimum, control.maximum, control.step)
                result.sources.append(
                    SemanticsSource("structure_file", "details.min/max/step", ("range",))
                )
            if result.sources:
                result.interpretation_status, result.reason = "partial", "metadata_only"
            if result.display_format_truncated:
                result.interpretation_status, result.reason = "partial", "metadata_truncated"
                result.sources.append(
                    SemanticsSource("structure_file", "details.format", ("display_format",))
                )
            invalid_fields = set(control.semantics_invalid_fields) & (
                {"format", "range"} if control.control_type == "UpDownAnalog" else {"format"}
            )
            if invalid_fields:
                result.interpretation_status, result.reason = (
                    "invalid",
                    "invalid_structure_metadata",
                )
                result.sources.append(
                    SemanticsSource("structure_file", "details", ("interpretation_status",))
                )

        if control.control_type == "StatusMonitor" and state_name == "inputStates":
            result.encoding = [
                SemanticsEncoding(s.status_id, s.name)
                for s in control.status_monitor_statuses[:100]
            ]
            result.encoding_total = control.status_monitor_status_total
            result.encoding_complete = (
                control.status_monitor_status_complete
                and len(control.status_monitor_statuses) <= 100
            )
            result.encoding_returned = len(result.encoding)
            result.encoding_truncated = len(control.status_monitor_statuses) > 100 or (
                result.encoding_total is not None and result.encoding_total > len(result.encoding)
            )
            result.positions = [
                SemanticsPosition(s.index, s.name) for s in control.status_monitor_inputs[:100]
            ]
            result.positions_total = control.status_monitor_input_total
            result.positions_complete = (
                control.status_monitor_input_complete and len(control.status_monitor_inputs) <= 100
            )
            result.positions_returned = len(result.positions)
            result.positions_truncated = len(control.status_monitor_inputs) > 100 or (
                result.positions_total is not None
                and result.positions_total > len(result.positions)
            )
            if result.encoding_total is not None or result.encoding:
                result.sources.append(
                    SemanticsSource("structure_file", "details.status", ("encoding",))
                )
            if result.positions_total is not None or result.positions:
                result.sources.append(
                    SemanticsSource("structure_file", "details.inputs", ("positions",))
                )
            if result.encoding or result.positions:
                result.interpretation_status, result.reason = "partial", "position_bound_metadata"
            if "status_monitor" in control.semantics_invalid_fields:
                result.interpretation_status, result.reason = (
                    "invalid",
                    "invalid_structure_metadata",
                )
            elif not result.encoding_complete or not result.positions_complete:
                result.reason = "incomplete_metadata"

        supported = (control.control_type == "Irrigation" and state_name in _IRRIGATION_RULES) or (
            control.control_type == "AlarmClock" and state_name in _ALARM_RULES
        )
        if supported:
            result.sources.append(
                SemanticsSource(
                    "decoder_rule",
                    _DOCUMENT,
                    ("semantic_value",),
                    rule_id=f"{control.control_type}.{state_name}.v1",
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                semantic_value, invalid = decode_state_value(
                    structure, control, state_name, value, companion_values
                )
                result.interpretation_status = "invalid" if invalid else "known"
                result.reason = "invalid_documented_value" if invalid else "documented_decoder"
                if not invalid and isinstance(semantic_value, dict):
                    missing_companion = (
                        (
                            control.control_type == "Irrigation"
                            and state_name == "currentZone"
                            and semantic_value.get("status") == "zone"
                            and "zone_name" not in semantic_value
                        )
                        or (
                            control.control_type == "AlarmClock"
                            and state_name in {"currentEntry", "nextEntry"}
                            and semantic_value.get("status") == "entry"
                            and "entry" not in semantic_value
                        )
                        or (
                            control.control_type == "AlarmClock"
                            and state_name == "nextEntryMode"
                            and semantic_value.get("status") == "mode"
                            and "mode_name" not in semantic_value
                        )
                    )
                    if missing_companion:
                        result.interpretation_status, result.reason = (
                            "partial",
                            "companion_unavailable",
                        )
                    refs = dict(control.state_uuids)
                    if "zone_name" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "runtime_state",
                                "states.zones",
                                ("semantic_value.zone_name",),
                                state_uuid=refs.get("zones"),
                            )
                        )
                    if "entry" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "runtime_state",
                                "states.entryList",
                                ("semantic_value.entry",),
                                state_uuid=refs.get("entryList"),
                            )
                        )
                    if "mode_name" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "structure_file",
                                "global_metadata.operating_mode",
                                ("semantic_value.mode_name",),
                            )
                        )
            if state_name in {"rainActive", "isEnabled", "isAlarmActive", "confirmationNeeded"}:
                result.value_type = "boolean"
            elif state_name in {
                "ringingTime",
                "ringDuration",
                "prepareDuration",
                "snoozeTime",
                "snoozeDuration",
            }:
                result.unit = "s"
                result.value_type = "integer"
            if result.value_type or result.unit:
                result.sources.append(
                    SemanticsSource(
                        "decoder_rule",
                        _DOCUMENT,
                        ("value_type", "unit"),
                        rule_id=f"{control.control_type}.{state_name}.v1",
                    )
                )
        result.sources_returned = result.sources_total = len(result.sources)
        return result, semantic_value


_MAX_SEMANTIC_JSON_TEXT = 65_536
_MAX_SEMANTIC_ENTRIES = 100
_LOXONE_EPOCH_UNIX = 1_230_768_000


class _SemanticValueError(ValueError):
    pass


def _semantic_json(value: object) -> object:
    if not isinstance(value, str) or len(value) > _MAX_SEMANTIC_JSON_TEXT:
        raise _SemanticValueError
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _SemanticValueError from exc


def _semantic_integer(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _SemanticValueError
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise _SemanticValueError from exc
    if not math.isfinite(number) or not number.is_integer():
        raise _SemanticValueError
    result = int(number)
    if not minimum <= result <= maximum:
        raise _SemanticValueError
    return result


def _semantic_number(value: object, *, minimum: float, maximum: float) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _SemanticValueError
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise _SemanticValueError from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise _SemanticValueError
    return value


def _semantic_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return bool(_semantic_integer(value, minimum=0, maximum=1))


def _semantic_text(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise _SemanticValueError
    return value


def _irrigation_zones(value: object) -> list[dict[str, object]]:
    raw = _semantic_json(value)
    if not isinstance(raw, list) or len(raw) > _MAX_SEMANTIC_ENTRIES:
        raise _SemanticValueError
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise _SemanticValueError
        result.append(
            {
                "id": _semantic_integer(item.get("id"), minimum=0, maximum=99),
                "name": _semantic_text(item.get("name")),
                "duration_seconds": _semantic_integer(
                    item.get("duration"), minimum=0, maximum=31_536_000
                ),
                "set_by_logic": _semantic_boolean(item.get("setByLogic")),
            }
        )
    return result


def _alarm_entries(value: object) -> list[dict[str, object]]:
    raw = _semantic_json(value)
    if not isinstance(raw, Mapping) or len(raw) > _MAX_SEMANTIC_ENTRIES:
        raise _SemanticValueError
    result: list[dict[str, object]] = []
    for identifier, item in raw.items():
        if (
            not isinstance(identifier, str)
            or not identifier.isdecimal()
            or not isinstance(item, Mapping)
        ):
            raise _SemanticValueError
        entry_id = int(identifier)
        if not 0 <= entry_id <= 1_000_000:
            raise _SemanticValueError
        alarm_time = _semantic_integer(item.get("alarmTime"), minimum=0, maximum=86_399)
        modes = item.get("modes")
        if not isinstance(modes, list) or len(modes) > _MAX_SEMANTIC_ENTRIES:
            raise _SemanticValueError
        mode_ids = [_semantic_integer(mode, minimum=0, maximum=1000) for mode in modes]
        alarm_time_text = (
            f"{alarm_time // 3600:02d}:{alarm_time % 3600 // 60:02d}:{alarm_time % 60:02d}"
        )
        result.append(
            {
                "id": entry_id,
                "name": _semantic_text(item.get("name")),
                "active": _semantic_boolean(item.get("isActive")),
                "alarm_time_seconds": alarm_time,
                "alarm_time": alarm_time_text,
                "mode_ids": mode_ids,
                "night_light": _semantic_boolean(item.get("nightLight", False)),
                "daily": _semantic_boolean(item.get("daily", False)),
            }
        )
    return sorted(
        result,
        key=lambda item: _semantic_integer(item["id"], minimum=0, maximum=1_000_000),
    )


def _alarm_settings(value: object, *, sound: bool) -> dict[str, object]:
    raw = _semantic_json(value)
    if not isinstance(raw, Mapping) or len(raw) > 16:
        raise _SemanticValueError
    result: dict[str, object] = {}
    if sound:
        if "sound" in raw:
            result["sound_id"] = _semantic_integer(raw["sound"], minimum=0, maximum=1000)
        if "volume" in raw:
            result["volume"] = _semantic_number(raw["volume"], minimum=0, maximum=100)
        if "isSloping" in raw:
            result["sloping"] = _semantic_boolean(raw["isSloping"])
    else:
        if "beepUsed" in raw:
            result["beep_used"] = _semantic_boolean(raw["beepUsed"])
        if "brightInactive" in raw:
            result["brightness_inactive"] = _semantic_number(
                raw["brightInactive"], minimum=0, maximum=100
            )
        if "brightActive" in raw:
            result["brightness_active"] = _semantic_number(
                raw["brightActive"], minimum=0, maximum=100
            )
    return result


def _alarm_entry_reference(value: object, entries_value: object) -> dict[str, object]:
    entry_id = _semantic_integer(value, minimum=-1, maximum=1_000_000)
    if entry_id == -1:
        return {"status": "none"}
    result: dict[str, object] = {"status": "entry", "entry_id": entry_id}
    try:
        entry = next(
            (item for item in _alarm_entries(entries_value) if item["id"] == entry_id), None
        )
    except _SemanticValueError:
        entry = None
    if entry is not None:
        result["entry"] = entry
    return result


def decode_state_value(
    structure: LoxoneStructure,
    control: Control,
    state_name: str,
    value: object,
    companion_values: Mapping[str, object],
) -> tuple[object | None, bool]:
    try:
        if control.control_type == "Irrigation":
            if state_name == "zones":
                return _irrigation_zones(value), False
            if state_name == "rainActive":
                return _semantic_boolean(value), False
            if state_name == "currentZone":
                zone_id = _semantic_integer(value, minimum=-1, maximum=8)
                if zone_id == -1:
                    return {"status": "off"}, False
                if zone_id == 8:
                    return {"status": "all"}, False
                result: dict[str, object] = {"status": "zone", "zone_id": zone_id}
                try:
                    zone = next(
                        (
                            item
                            for item in _irrigation_zones(companion_values.get("zones"))
                            if item["id"] == zone_id
                        ),
                        None,
                    )
                except _SemanticValueError:
                    zone = None
                if zone is not None:
                    result["zone_name"] = zone["name"]
                return result, False

        if control.control_type == "AlarmClock":
            if state_name in {"isEnabled", "isAlarmActive", "confirmationNeeded"}:
                return _semantic_boolean(value), False
            if state_name == "entryList":
                return _alarm_entries(value), False
            if state_name in {"currentEntry", "nextEntry"}:
                return _alarm_entry_reference(value, companion_values.get("entryList")), False
            if state_name == "nextEntryMode":
                mode_id = _semantic_integer(value, minimum=-1, maximum=1000)
                if mode_id == -1:
                    return {"status": "none"}, False
                result = {"status": "mode", "mode_id": mode_id}
                mode_name = next(
                    (
                        item.name
                        for item in structure.global_metadata
                        if item.kind == "operating_mode" and item.identifier == str(mode_id)
                    ),
                    None,
                )
                if mode_name is not None:
                    result["mode_name"] = mode_name
                return result, False
            if state_name in {
                "ringingTime",
                "ringDuration",
                "prepareDuration",
                "snoozeTime",
                "snoozeDuration",
            }:
                return {"seconds": _semantic_integer(value, minimum=0, maximum=31_536_000)}, False
            if state_name == "nextEntryTime":
                seconds = _semantic_integer(value, minimum=-1, maximum=4_000_000_000)
                if seconds <= 0:
                    return {"status": "none"}, False
                return {"status": "scheduled", "at": _loxone_time(seconds)}, False
            if state_name == "deviceState":
                state = _semantic_integer(value, minimum=0, maximum=2)
                return {"status": {0: "not_connected", 1: "offline", 2: "online"}[state]}, False
            if state_name == "deviceSettings":
                return _alarm_settings(value, sound=False), False
            if state_name == "wakeAlarmSoundSettings":
                return _alarm_settings(value, sound=True), False
    except ValueError:
        return None, True
    return None, False


def _loxone_time(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("weather timestamp is invalid")
    number = float(value)
    if not number.is_integer() or not 0 <= number <= 4_000_000_000:
        raise ValueError("weather timestamp is invalid")
    try:
        return (
            datetime.fromtimestamp(_LOXONE_EPOCH_UNIX + int(number), UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("weather timestamp is invalid") from exc
