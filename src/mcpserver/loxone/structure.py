"""Normalize the user-filtered LoxAPP3 response into a minimal model."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mcpserver.loxone.models import (
    Control,
    GlobalMetadata,
    LoxoneIdentity,
    LoxoneStructure,
    NamedGroup,
    NamedOption,
    Room,
    StatisticSeries,
    StatusMonitorInput,
    StatusMonitorStatus,
    VentilationTimerProfile,
    WindowMonitorItem,
)

_REFERENCED_ONLY_INTERNAL = 1 << 0
_READ_ONLY_INTERNAL = 1 << 1
_READ_ONLY_EXTERNAL = 1 << 5
_READ_ONLY = _READ_ONLY_INTERNAL | _READ_ONLY_EXTERNAL


class LoxoneStructureError(ValueError):
    """Raised when the user-filtered structure is malformed."""


@dataclass(slots=True)
class StructureBudget:
    """Reject oversized or excessively nested untrusted structure documents."""

    max_controls: int
    max_state_references: int
    max_depth: int
    controls: int = 0
    state_references: int = 0

    def visit(self, *, depth: int, state_references: int) -> None:
        if depth > self.max_depth:
            raise LoxoneStructureError("Structure nesting depth exceeds the configured limit")
        self.controls += 1
        if self.controls > self.max_controls:
            raise LoxoneStructureError("Structure control count exceeds the configured limit")
        self.state_references += state_references
        if self.state_references > self.max_state_references:
            raise LoxoneStructureError("Structure state count exceeds the configured limit")


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise LoxoneStructureError(f"Structure field {field} must be text")
    return value


def _groups(
    value: object,
    *,
    field: str,
    allowed_uuids: set[str],
) -> tuple[NamedGroup, ...]:
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


def _rooms(
    value: object,
    *,
    allowed_uuids: set[str],
    room_group_uuids: Mapping[str, str | None],
) -> tuple[Room, ...]:
    if not isinstance(value, Mapping):
        raise LoxoneStructureError("Structure field rooms must be an object")
    rooms: list[Room] = []
    for uuid, item in value.items():
        if not isinstance(uuid, str) or not isinstance(item, Mapping):
            raise LoxoneStructureError("Structure field rooms contains an invalid entry")
        if uuid not in allowed_uuids:
            continue
        rooms.append(
            Room(
                uuid=uuid,
                name=_text(item.get("name"), field="rooms.name"),
                room_group_uuid=room_group_uuids.get(uuid),
            )
        )
    return tuple(rooms)


def _optional_uuid(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _bounded_text(value: object, *, maximum: int = 200) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= maximum else None


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


def _up_down_range(
    details: Mapping[str, object],
) -> tuple[float | None, float | None, float | None]:
    minimum, maximum, step = details.get("min"), details.get("max"), details.get("step")
    if (
        not isinstance(minimum, int | float)
        or isinstance(minimum, bool)
        or not isinstance(maximum, int | float)
        or isinstance(maximum, bool)
        or not isinstance(step, int | float)
        or isinstance(step, bool)
    ):
        return None, None, None
    normalized_minimum, normalized_maximum, normalized_step = (
        float(minimum),
        float(maximum),
        float(step),
    )
    if not all(
        math.isfinite(value) for value in (normalized_minimum, normalized_maximum, normalized_step)
    ):
        return None, None, None
    if normalized_minimum > normalized_maximum or normalized_step <= 0:
        return None, None, None
    return normalized_minimum, normalized_maximum, normalized_step


def _scene_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        return ()
    return tuple(str(index) for index, name in enumerate(value) if isinstance(name, str))


def _radio_outputs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping) or len(value) > 16:
        return ()
    outputs = [
        (key, name)
        for key, name in value.items()
        if isinstance(key, str)
        and key.isdecimal()
        and 1 <= int(key) <= 16
        and isinstance(name, str)
    ]
    return tuple(sorted(outputs, key=lambda item: int(item[0])))


def _rating(value: object) -> int | None:
    # LoxAPP3 ratings are not limited to the five-star presentation convention.
    # Keep a generous finite bound so a malformed structure cannot create unbounded data.
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
        return value
    return None


def _named_options(value: object, *, maximum: int = 32) -> tuple[NamedOption, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        return ()
    result: list[NamedOption] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        option_id, name = item.get("id"), item.get("name")
        if (
            isinstance(option_id, int)
            and not isinstance(option_id, bool)
            and -1000 <= option_id <= 1000
            and isinstance(name, str)
            and 1 <= len(name) <= 200
        ):
            result.append(NamedOption(option_id, name))
    return tuple(result)


def _ventilation_profiles(value: object) -> tuple[VentilationTimerProfile, ...]:
    if not isinstance(value, list) or len(value) > 32:
        return ()
    result: list[VentilationTimerProfile] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        name, interval, modes, default_mode, speed = (
            item.get("name"),
            item.get("interval"),
            item.get("modes"),
            item.get("defaultMode"),
            item.get("speed"),
        )
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            continue
        if (
            not isinstance(interval, int)
            or isinstance(interval, bool)
            or not 1 <= interval <= 86_400
        ):
            continue
        if not isinstance(modes, list) or len(modes) > 32:
            continue
        mode_ids = tuple(
            item
            for item in modes
            if isinstance(item, int) and not isinstance(item, bool) and -1000 <= item <= 1000
        )
        if len(mode_ids) != len(modes):
            continue
        if (
            not isinstance(default_mode, int)
            or isinstance(default_mode, bool)
            or default_mode not in mode_ids
        ):
            default_mode = None
        speed_enabled = isinstance(speed, Mapping) and speed.get("enabled") is True
        result.append(
            VentilationTimerProfile(index, name, interval, mode_ids, default_mode, speed_enabled)
        )
    return tuple(result)


def _window_monitor_items(value: object) -> tuple[WindowMonitorItem, ...]:
    entries: list[tuple[str | None, object]]
    if isinstance(value, list) and len(value) <= 100:
        entries = [(None, item) for item in value]
    elif isinstance(value, Mapping) and len(value) <= 100:
        entries = [(key if isinstance(key, str) else None, item) for key, item in value.items()]
    else:
        return ()
    result: list[WindowMonitorItem] = []
    for index, (mapped_uuid, item) in enumerate(entries):
        if not isinstance(item, Mapping):
            result.append(WindowMonitorItem(index, None, None, None, None))
            continue
        window: Mapping[str, object] = item

        def text(key: str, source: Mapping[str, object] = window) -> str | None:
            candidate = source.get(key)
            return candidate if isinstance(candidate, str) and len(candidate) <= 200 else None

        result.append(
            WindowMonitorItem(
                index,
                text("name"),
                text("room"),
                text("uuid") or mapped_uuid,
                text("installPlace"),
            )
        )
    return tuple(result)


def _room_groups(
    document: Mapping[str, object],
) -> tuple[tuple[NamedGroup, ...], dict[str, str | None]]:
    """Return bounded explicit room-group metadata and unambiguous room memberships."""
    raw_groups = document.get("roomGroups")
    if not isinstance(raw_groups, list):
        return (), {}
    groups: list[NamedGroup] = []
    memberships: dict[str, set[str]] = {}
    for item in raw_groups[:100]:
        if not isinstance(item, Mapping):
            continue
        identifier, name = _bounded_text(item.get("uuid")), _bounded_text(item.get("name"))
        if identifier is None or name is None:
            continue
        groups.append(NamedGroup(identifier, name))
        room_ids = item.get("rooms", item.get("roomUuids"))
        if isinstance(room_ids, list) and len(room_ids) <= 100:
            for room_uuid in room_ids:
                normalized_room_uuid = _bounded_text(room_uuid, maximum=128)
                if normalized_room_uuid is not None:
                    memberships.setdefault(normalized_room_uuid, set()).add(identifier)
    known_groups = {item.uuid for item in groups}
    rooms = document.get("rooms")
    if isinstance(rooms, Mapping):
        for room_uuid, room in rooms.items():
            if not isinstance(room_uuid, str) or not isinstance(room, Mapping):
                continue
            group_uuid = _bounded_text(room.get("roomGroup"))
            if group_uuid in known_groups:
                memberships.setdefault(room_uuid, set()).add(group_uuid)
    return tuple(groups), {
        room_uuid: next(iter(group_uuids)) if len(group_uuids) == 1 else None
        for room_uuid, group_uuids in memberships.items()
    }


def _global_metadata(
    document: Mapping[str, object], *, room_groups: tuple[NamedGroup, ...]
) -> tuple[GlobalMetadata, ...]:
    """Keep only bounded, user-visible global metadata; never expose raw LoxAPP3."""
    result: list[GlobalMetadata] = []
    operating_modes = document.get("operatingModes")
    if isinstance(operating_modes, Mapping):
        for identifier, name in list(operating_modes.items())[:100]:
            if _bounded_text(identifier) is not None and _bounded_text(name) is not None:
                result.append(GlobalMetadata("operating_mode", identifier, name))
    modes = document.get("modes")
    if isinstance(modes, Mapping):
        for identifier, item in list(modes.items())[:100]:
            if isinstance(identifier, str) and isinstance(item, Mapping):
                mode_id, name = item.get("id"), item.get("name")
                normalized_name = _bounded_text(name)
                if (
                    isinstance(mode_id, int)
                    and not isinstance(mode_id, bool)
                    and normalized_name is not None
                ):
                    result.append(
                        GlobalMetadata(
                            "mode", str(mode_id), normalized_name, locked=item.get("locked") is True
                        )
                    )
    times = document.get("times")
    if isinstance(times, Mapping):
        for identifier, item in list(times.items())[:100]:
            if isinstance(identifier, str) and isinstance(item, Mapping):
                name, analog = item.get("name"), item.get("analog")
                normalized_identifier, normalized_name = (
                    _bounded_text(identifier),
                    _bounded_text(name),
                )
                if normalized_identifier and normalized_name and isinstance(analog, bool):
                    result.append(
                        GlobalMetadata(
                            "time", normalized_identifier, normalized_name, analog=analog
                        )
                    )
    result.extend(GlobalMetadata("room_group", item.uuid, item.name) for item in room_groups)
    global_states = document.get("globalStates")
    if isinstance(global_states, Mapping):
        for name, state_uuid in list(global_states.items())[:100]:
            if (
                _bounded_text(name) is not None
                and isinstance(state_uuid, str)
                and 1 <= len(state_uuid) <= 128
            ):
                result.append(GlobalMetadata("global_state", name, name, state_uuid=state_uuid))
    weather = document.get("weatherServer")
    if isinstance(weather, Mapping):
        states = weather.get("states")
        if isinstance(states, Mapping):
            for name, state_uuid in list(states.items())[:16]:
                if (
                    _bounded_text(name) is not None
                    and isinstance(state_uuid, str)
                    and 1 <= len(state_uuid) <= 128
                ):
                    result.append(
                        GlobalMetadata("weather_state", name, name, state_uuid=state_uuid)
                    )
    return tuple(result)


def _status_monitor_details(
    details: Mapping[str, object],
) -> tuple[tuple[StatusMonitorInput, ...], tuple[StatusMonitorStatus, ...]]:
    """Return bounded, position-stable input and status metadata."""
    inputs_value = details.get("inputs")
    inputs: list[StatusMonitorInput] = []
    if isinstance(inputs_value, list):
        for index, item in enumerate(inputs_value[:100]):
            if not isinstance(item, Mapping):
                inputs.append(StatusMonitorInput(index, None, None, None, None))
                continue
            name = item.get("name")
            if not isinstance(name, str) or len(name) > 200:
                name = None
            install_place = item.get("installPlace")
            if not isinstance(install_place, str) or len(install_place) > 200:
                install_place = None
            inputs.append(
                StatusMonitorInput(
                    index=index,
                    name=name,
                    install_place=install_place,
                    uuid=_optional_uuid(item.get("uuid")),
                    room_uuid=_optional_uuid(item.get("room")),
                )
            )
    statuses_value = details.get("status")
    statuses: list[StatusMonitorStatus] = []
    if isinstance(statuses_value, Mapping):
        for item in statuses_value.values():
            if not isinstance(item, Mapping):
                continue
            status_id, name, priority = item.get("id"), item.get("name"), item.get("prio")
            if (
                not isinstance(status_id, int)
                or isinstance(status_id, bool)
                or not 0 <= status_id <= 255
                or not isinstance(name, str)
                or len(name) > 200
                or not isinstance(priority, int)
                or isinstance(priority, bool)
                or not 0 <= priority <= 255
            ):
                continue
            color = item.get("color")
            if not isinstance(color, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", color) is None:
                color = None
            statuses.append(
                StatusMonitorStatus(
                    status_id=status_id,
                    name=name,
                    priority=priority,
                    color=color,
                )
            )
    return tuple(inputs), tuple(sorted(statuses, key=lambda status: status.status_id))


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


def _links(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 64:
        return ()
    return tuple(item for item in value if isinstance(item, str) and 1 <= len(item) <= 128)


def _linked_control_uuids(value: object, *, maximum_controls: int) -> frozenset[str]:
    if not isinstance(value, Mapping):
        raise LoxoneStructureError("Structure field controls must be an object")
    result: set[str] = set()
    for index, item in enumerate(value.values(), start=1):
        if index > maximum_controls:
            raise LoxoneStructureError("Structure control count exceeds the configured limit")
        if not isinstance(item, Mapping):
            continue
        restrictions = item.get("restrictions", 0)
        if (
            isinstance(restrictions, int)
            and not isinstance(restrictions, bool)
            and not (restrictions & _REFERENCED_ONLY_INTERNAL)
        ):
            result.update(_links(item.get("links")))
    return frozenset(result)


def _controls(
    value: object,
    *,
    referenced: bool = False,
    linked_control_uuids: frozenset[str] = frozenset(),
    hidden_only: bool = False,
    budget: StructureBudget,
    depth: int = 1,
) -> tuple[Control, ...]:
    if not isinstance(value, Mapping):
        raise LoxoneStructureError("Structure field controls must be an object")
    controls: list[Control] = []
    for uuid, item in value.items():
        if not isinstance(uuid, str) or not isinstance(item, Mapping):
            raise LoxoneStructureError("Structure contains an invalid control")
        restrictions = item.get("restrictions", 0)
        if not isinstance(restrictions, int) or isinstance(restrictions, bool) or restrictions < 0:
            raise LoxoneStructureError("Control restrictions must be a non-negative integer")
        is_hidden = (
            not referenced
            and bool(restrictions & _REFERENCED_ONLY_INTERNAL)
            and uuid not in linked_control_uuids
        )
        if is_hidden != hidden_only:
            continue
        states_value = item.get("states", {})
        if not isinstance(states_value, Mapping):
            raise LoxoneStructureError("Control states must be an object")
        states = tuple(
            (name, state_uuid)
            for name, state_uuid in states_value.items()
            if isinstance(name, str) and isinstance(state_uuid, str)
        )
        budget.visit(depth=depth, state_references=len(states))
        subcontrols_value = item.get("subControls", {})
        details = item.get("details", {})
        if not isinstance(details, Mapping):
            raise LoxoneStructureError("Control details must be an object")
        is_automatic = details.get("isAutomatic", False)
        if not isinstance(is_automatic, bool):
            raise LoxoneStructureError("Control details.isAutomatic must be boolean")
        shading_animation = details.get("animation")
        if (
            not isinstance(shading_animation, int)
            or isinstance(shading_animation, bool)
            or shading_animation not in {0, 1, 2, 3, 4, 5}
        ):
            shading_animation = None
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
        radio_outputs = _radio_outputs(details.get("outputs"))
        minimum, maximum, step = _up_down_range(details)
        format_value = details.get("format")
        if not isinstance(format_value, str) or len(format_value) > 64:
            format_value = None
        connected_inputs = details.get("connectedInputs")
        if (
            not isinstance(connected_inputs, int)
            or isinstance(connected_inputs, bool)
            or connected_inputs < 0
        ):
            connected_inputs = None
        analog = details.get("analog")
        if not isinstance(analog, bool):
            analog = None
        status_monitor_inputs, status_monitor_statuses = (
            _status_monitor_details(details) if item.get("type") == "StatusMonitor" else ((), ())
        )
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
                is_favorite=item.get("isFavorite", False) is True,
                secured=item.get("isSecured", False) is True,
                has_notes=_capability_flag(
                    item.get("hasControlNotes", False), field="hasControlNotes"
                ),
                is_automatic=is_automatic,
                shading_animation=shading_animation,
                has_history=has_history,
                picker_type=picker_type,
                min_kelvin=min_kelvin,
                max_kelvin=max_kelvin,
                scene_ids=_scene_ids(details.get("sceneList")),
                radio_output_ids=tuple(output_id for output_id, _name in radio_outputs),
                radio_outputs=radio_outputs,
                radio_reset_allowed=isinstance(details.get("allOff"), str)
                and bool(details.get("allOff")),
                minimum=minimum,
                maximum=maximum,
                step=step,
                is_analog=analog,
                statistic_series=_statistic_series(item),
                status_monitor_inputs=status_monitor_inputs,
                status_monitor_statuses=status_monitor_statuses,
                format=format_value,
                timer_modes=_named_options(details.get("timerModes")),
                ventilation_modes=_named_options(details.get("modes")),
                ventilation_timer_profiles=_ventilation_profiles(details.get("timerProfiles")),
                window_monitor_items=_window_monitor_items(details.get("windows")),
                connected_inputs=connected_inputs,
                subcontrols=(
                    _controls(
                        subcontrols_value,
                        referenced=True,
                        budget=budget,
                        depth=depth + 1,
                    )
                    if subcontrols_value
                    else ()
                ),
                linked_control_uuids=_links(item.get("links")),
                is_user_linked=(
                    not referenced
                    and bool(restrictions & _REFERENCED_ONLY_INTERNAL)
                    and uuid in linked_control_uuids
                ),
                is_hidden=is_hidden,
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


def normalize_structure(
    document: Mapping[str, Any],
    *,
    username: str,
    max_controls: int = 20_000,
    max_state_references: int = 100_000,
    max_depth: int = 32,
) -> LoxoneStructure:
    """Return only fields required for read-only discovery and state association."""
    ms_info = document.get("msInfo")
    if not isinstance(ms_info, Mapping):
        raise LoxoneStructureError("Structure field msInfo must be an object")
    serial = ms_info.get("serialNr", ms_info.get("serial"))
    last_modified = document.get("lastModified", "")
    controls_value = document.get("controls", {})
    linked_control_uuids = _linked_control_uuids(controls_value, maximum_controls=max_controls)
    budget = StructureBudget(max_controls, max_state_references, max_depth)
    controls = _controls(controls_value, linked_control_uuids=linked_control_uuids, budget=budget)
    hidden_controls = _controls(
        controls_value,
        linked_control_uuids=linked_control_uuids,
        hidden_only=True,
        budget=budget,
    )
    room_groups, room_group_uuids = _room_groups(document)
    return LoxoneStructure(
        identity=LoxoneIdentity(
            username=username,
            miniserver_serial=_text(serial, field="msInfo.serialNr"),
        ),
        last_modified=_text(last_modified, field="lastModified"),
        rooms=_rooms(
            document.get("rooms", {}),
            allowed_uuids=_group_references(controls, field="room"),
            room_group_uuids=room_group_uuids,
        ),
        categories=_groups(
            document.get("cats", {}),
            field="cats",
            allowed_uuids=_group_references(controls, field="category"),
        ),
        controls=controls,
        hidden_rooms=_groups(
            document.get("rooms", {}),
            field="rooms",
            allowed_uuids=_group_references(hidden_controls, field="room"),
        ),
        hidden_categories=_groups(
            document.get("cats", {}),
            field="cats",
            allowed_uuids=_group_references(hidden_controls, field="category"),
        ),
        hidden_controls=hidden_controls,
        global_metadata=_global_metadata(document, room_groups=room_groups),
        room_groups=room_groups,
    )
