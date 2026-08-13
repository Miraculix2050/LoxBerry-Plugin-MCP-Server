"""Pure presentation helpers for the read-only Loxone discovery tools."""

from __future__ import annotations

from typing import Any

from mcpserver.loxone.models import Control, LoxoneStructure, NamedGroup
from mcpserver.loxone.runtime import RuntimeSnapshot


def groups(items: tuple[NamedGroup, ...]) -> list[dict[str, str]]:
    """Serialize visible Loxone groups for the stable MCP contract."""
    return [{"uuid": item.uuid, "name": item.name} for item in items]


def flatten_controls(controls: tuple[Control, ...]) -> list[Control]:
    """Return controls and their nested subcontrols in structure order."""
    result: list[Control] = []
    for control in controls:
        result.append(control)
        result.extend(flatten_controls(control.subcontrols))
    return result


def controls_for_diagnosis(structure: LoxoneStructure, *, include_hidden: bool) -> list[Control]:
    """Return public controls and explicitly requested hidden diagnostics."""
    controls = flatten_controls(structure.controls)
    if include_hidden:
        controls.extend(flatten_controls(structure.hidden_controls))
    return controls


def control_summary(control: Control, snapshot: RuntimeSnapshot) -> dict[str, Any]:
    """Serialize the shared bounded control summary."""
    rooms = {
        item.uuid: item.name
        for item in snapshot.structure.rooms
        + (snapshot.structure.hidden_rooms if control.is_hidden else ())
    }
    categories = {
        item.uuid: item.name
        for item in snapshot.structure.categories
        + (snapshot.structure.hidden_categories if control.is_hidden else ())
    }
    return {
        "uuid": control.uuid,
        "name": control.name,
        "type": control.control_type,
        "visibility": (
            "hidden" if control.is_hidden else "linked" if control.is_user_linked else "direct"
        ),
        "room": (
            {"uuid": control.room_uuid, "name": rooms.get(control.room_uuid, "")}
            if control.room_uuid
            else None
        ),
        "category": (
            {"uuid": control.category_uuid, "name": categories.get(control.category_uuid, "")}
            if control.category_uuid
            else None
        ),
    }


def control_matches_query(control: Control, query: str | None) -> bool:
    """Match a normalized discovery query against bounded visible labels."""
    if query is None:
        return True
    return query in control.name.casefold() or any(
        query in output_name.casefold() for _output_id, output_name in control.radio_outputs
    )


def linked_control(control: Control) -> dict[str, str]:
    return {"uuid": control.uuid, "name": control.name, "type": control.control_type}


def parent_control(controls: tuple[Control, ...], control_uuid: str) -> Control | None:
    for candidate in controls:
        if any(subcontrol.uuid == control_uuid for subcontrol in candidate.subcontrols):
            return candidate
        parent = parent_control(candidate.subcontrols, control_uuid)
        if parent is not None:
            return parent
    return None


def linked_controls(control: Control, controls: list[Control]) -> list[Control]:
    by_uuid = {item.uuid: item for item in controls}
    return [by_uuid[uuid] for uuid in control.linked_control_uuids if uuid in by_uuid]
