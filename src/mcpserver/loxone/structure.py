"""Normalize the user-filtered LoxAPP3 response into a minimal model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, NamedGroup

_REFERENCED_ONLY_INTERNAL = 1 << 0


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
        controls.append(
            Control(
                uuid=uuid,
                name=_text(item.get("name"), field="controls.name"),
                control_type=_text(item.get("type"), field="controls.type"),
                room_uuid=_optional_uuid(item.get("room")),
                category_uuid=_optional_uuid(item.get("cat")),
                action_uuid=_optional_uuid(item.get("action")),
                state_uuids=states,
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
