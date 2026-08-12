"""Normalize the user-filtered LoxAPP3 response into a minimal model."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from mcpserver.loxone.models import (
    Control,
    LoxoneIdentity,
    LoxoneStructure,
    NamedGroup,
    StatisticSeries,
)

_REFERENCED_ONLY_INTERNAL = 1 << 0
_READ_ONLY_INTERNAL = 1 << 1
_READ_ONLY_EXTERNAL = 1 << 5
_READ_ONLY = _READ_ONLY_INTERNAL | _READ_ONLY_EXTERNAL


class LoxoneStructureError(ValueError):
    """Raised when the user-filtered structure is malformed."""


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise LoxoneStructureError(f"Structure field {field} must be text")
    return value


def _groups(value: object, *, field: str, allowed_uuids: set[str]) -> tuple[NamedGroup, ...]:
    if not isinstance(value, Mapping):
        raise LoxoneStructureError(f"Structure field {field} must be an object")
    groups: list[NamedGroup] = []
    for uuid, item in value.items():
        if not isinstance(uuid, str) or not isinstance(item, Mapping):
            raise LoxoneStructureError(f"Structure field {field} contains an invalid entry")
        if uuid not in allowed_uuids:
            continue
        groups.append(NamedGroup(uuid=uuid, name=_text(item.get("name"), field=f"{field}.name")))
    return tuple(groups)


def _optional_uuid(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _history_capability(value: object) -> bool:
    """Normalize documented booleans and numeric values emitted by real Miniservers."""
    return _capability_flag(value, field="details.hasHistory")


def _capability_flag(value: object, *, field: str) -> bool:
    """Normalize a documented boolean capability flag and real numeric variants."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value >= 0:
        return value > 0
    raise LoxoneStructureError(f"Control {field} must be boolean or non-negative integer")


def _bounded_integer(value: object, *, default: int, minimum: int, maximum: int) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
        else default
    )


def _scene_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        return ()
    return tuple(str(index) for index, name in enumerate(value) if isinstance(name, str))


def _radio_output_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping) or len(value) > 16:
        return ()
    ids = [
        key
        for key, name in value.items()
        if isinstance(key, str)
        and key.isdecimal()
        and 1 <= int(key) <= 16
        and isinstance(name, str)
    ]
    return tuple(sorted(ids, key=int))


def _rating(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 5:
        return value
    return None


def _statistic_series(item: Mapping[str, object]) -> tuple[StatisticSeries, ...]:
    value = item.get("statisticV2")
    if isinstance(value, Mapping):
        return _statistic_v2_series(value)
    return _legacy_statistic_series(item.get("statistic"))


def _statistic_v2_series(value: Mapping[str, object]) -> tuple[StatisticSeries, ...]:
    groups = value.get("groups")
    if not isinstance(groups, list) or len(groups) > 64:
        return ()
    result: list[StatisticSeries] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        group_id = group.get("id")
        normalized_group = (
            str(group_id)
            if isinstance(group_id, int | str) and not isinstance(group_id, bool)
            else ""
        )
        if not normalized_group.isdecimal() or len(normalized_group) > 10:
            continue
        data_points = group.get("dataPoints")
        if not isinstance(data_points, list) or len(data_points) > 32:
            continue
        accumulated = group.get("accumulated", False) is True
        for point in data_points:
            if not isinstance(point, Mapping):
                continue
            output = point.get("output")
            title = point.get("title")
            format_value = point.get("format", "")
            if (
                not isinstance(output, str)
                or not output
                or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", output) is None
                or not isinstance(title, str)
                or len(title) > 200
                or not isinstance(format_value, str)
                or len(format_value) > 64
            ):
                continue
            result.append(
                StatisticSeries(
                    series_id=f"v2:{normalized_group}:{output}",
                    source="statistic_v2",
                    group_id=normalized_group,
                    output=output,
                    title=title,
                    format=format_value,
                    accumulated=accumulated,
                )
            )
    return tuple(result[:128])


def _legacy_statistic_series(value: object) -> tuple[StatisticSeries, ...]:
    """Expose documented legacy statistic outputs when StatisticV2 is absent."""
    if not isinstance(value, Mapping):
        return ()
    outputs = value.get("outputs")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 16:
        return ()
    result: list[StatisticSeries] = []
    for index, output in enumerate(outputs):
        if not isinstance(output, Mapping):
            continue
        output_id = output.get("id")
        title = output.get("name")
        format_value = output.get("format", "")
        if (
            not isinstance(output_id, int)
            or isinstance(output_id, bool)
            or output_id < 0
            or not isinstance(title, str)
            or not title
            or len(title) > 200
            or not isinstance(format_value, str)
            or len(format_value) > 64
        ):
            continue
        result.append(
            StatisticSeries(
                series_id=f"legacy:{index}",
                source="legacy",
                group_id=str(output_id),
                output=str(output_id),
                title=title,
                format=format_value,
                legacy_output_index=index,
                legacy_output_count=len(outputs),
            )
        )
    return tuple(result)


def _controls(value: object, *, referenced: bool = False) -> tuple[Control, ...]:
    if not isinstance(value, Mapping):
        raise LoxoneStructureError("Structure field controls must be an object")
    controls: list[Control] = []
    for uuid, item in value.items():
        if not isinstance(uuid, str) or not isinstance(item, Mapping):
            raise LoxoneStructureError("Structure contains an invalid control")
        restrictions = item.get("restrictions", 0)
        if not isinstance(restrictions, int) or isinstance(restrictions, bool) or restrictions < 0:
            raise LoxoneStructureError("Control restrictions must be a non-negative integer")
        if not referenced and restrictions & _REFERENCED_ONLY_INTERNAL:
            continue
        states_value = item.get("states", {})
        if not isinstance(states_value, Mapping):
            raise LoxoneStructureError("Control states must be an object")
        states = tuple(
            (name, state_uuid)
            for name, state_uuid in states_value.items()
            if isinstance(name, str) and isinstance(state_uuid, str)
        )
        subcontrols_value = item.get("subControls", {})
        details = item.get("details", {})
        if not isinstance(details, Mapping):
            raise LoxoneStructureError("Control details must be an object")
        is_automatic = details.get("isAutomatic", False)
        if not isinstance(is_automatic, bool):
            raise LoxoneStructureError("Control details.isAutomatic must be boolean")
        has_history = _history_capability(details.get("hasHistory", False))
        picker_type = details.get("pickerType")
        if not isinstance(picker_type, str) or len(picker_type) > 32:
            picker_type = None
        min_kelvin = _bounded_integer(
            details.get("minKelvin"), default=2700, minimum=1000, maximum=20000
        )
        max_kelvin = _bounded_integer(
            details.get("maxKelvin"), default=6500, minimum=1000, maximum=20000
        )
        if min_kelvin > max_kelvin:
            min_kelvin, max_kelvin = 2700, 6500
        controls.append(
            Control(
                uuid=uuid,
                name=_text(item.get("name"), field="controls.name"),
                control_type=_text(item.get("type"), field="controls.type"),
                room_uuid=_optional_uuid(item.get("room")),
                category_uuid=_optional_uuid(item.get("cat")),
                action_uuid=_optional_uuid(item.get("uuidAction")),
                state_uuids=states,
                restrictions=restrictions,
                read_only=bool(restrictions & _READ_ONLY),
                rating=_rating(item.get("defaultRating")),
                secured=item.get("isSecured", False) is True,
                has_notes=_capability_flag(
                    item.get("hasControlNotes", False), field="hasControlNotes"
                ),
                is_automatic=is_automatic,
                has_history=has_history,
                picker_type=picker_type,
                min_kelvin=min_kelvin,
                max_kelvin=max_kelvin,
                scene_ids=_scene_ids(details.get("sceneList")),
                radio_output_ids=_radio_output_ids(details.get("outputs")),
                radio_reset_allowed=isinstance(details.get("allOff"), str)
                and bool(details.get("allOff")),
                statistic_series=_statistic_series(item),
                subcontrols=(
                    _controls(subcontrols_value, referenced=True) if subcontrols_value else ()
                ),
            )
        )
    return tuple(controls)


def _group_references(controls: tuple[Control, ...], *, field: str) -> set[str]:
    result: set[str] = set()
    for control in controls:
        uuid = control.room_uuid if field == "room" else control.category_uuid
        if uuid is not None:
            result.add(uuid)
        result.update(_group_references(control.subcontrols, field=field))
    return result


def normalize_structure(document: Mapping[str, Any], *, username: str) -> LoxoneStructure:
    """Return only fields required for read-only discovery and state association."""
    ms_info = document.get("msInfo")
    if not isinstance(ms_info, Mapping):
        raise LoxoneStructureError("Structure field msInfo must be an object")
    serial = ms_info.get("serialNr", ms_info.get("serial"))
    last_modified = document.get("lastModified", "")
    controls = _controls(document.get("controls", {}))
    return LoxoneStructure(
        identity=LoxoneIdentity(
            username=username,
            miniserver_serial=_text(serial, field="msInfo.serialNr"),
        ),
        last_modified=_text(last_modified, field="lastModified"),
        rooms=_groups(
            document.get("rooms", {}),
            field="rooms",
            allowed_uuids=_group_references(controls, field="room"),
        ),
        categories=_groups(
            document.get("cats", {}),
            field="cats",
            allowed_uuids=_group_references(controls, field="category"),
        ),
        controls=controls,
    )
