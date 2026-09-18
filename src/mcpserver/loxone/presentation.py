"""Pure presentation helpers for the read-only Loxone discovery tools."""

from __future__ import annotations

from collections import Counter
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


def visible_controls(structure: LoxoneStructure) -> list[Control]:
    """Return the normalized control corpus used by ordinary discovery."""
    return flatten_controls(structure.controls)


def controls_for_diagnosis(structure: LoxoneStructure, *, include_hidden: bool) -> list[Control]:
    """Return public controls and explicitly requested hidden diagnostics."""
    controls = visible_controls(structure)
    if include_hidden:
        controls.extend(flatten_controls(structure.hidden_controls))
    return controls


def structure_overview(structure: LoxoneStructure, *, max_items: int) -> dict[str, Any]:
    """Aggregate one bounded overview from the authorized visible structure."""
    if max_items < 1:
        raise ValueError("max_items must be positive")

    controls = visible_controls(structure)
    rooms = {item.uuid: item.name for item in structure.rooms}
    categories = {item.uuid: item.name for item in structure.categories}
    room_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    unassigned_rooms = 0
    unassigned_categories = 0

    for control in controls:
        type_counts[control.control_type] += 1
        if control.room_uuid in rooms:
            room_counts[control.room_uuid] += 1
        else:
            unassigned_rooms += 1
        if control.category_uuid in categories:
            category_counts[control.category_uuid] += 1
        else:
            unassigned_categories += 1

    room_items: list[dict[str, object]] = [
        {
            "assignment": "assigned",
            "uuid": uuid,
            "name": name,
            "control_count": room_counts[uuid],
        }
        for uuid, name in rooms.items()
    ]
    if unassigned_rooms:
        room_items.append(
            {
                "assignment": "unassigned",
                "uuid": None,
                "name": None,
                "control_count": unassigned_rooms,
            }
        )

    category_items: list[dict[str, object]] = [
        {
            "assignment": "assigned",
            "uuid": uuid,
            "name": name,
            "control_count": category_counts[uuid],
        }
        for uuid, name in categories.items()
    ]
    if unassigned_categories:
        category_items.append(
            {
                "assignment": "unassigned",
                "uuid": None,
                "name": None,
                "control_count": unassigned_categories,
            }
        )

    type_items = [
        {"type": control_type, "control_count": count}
        for control_type, count in type_counts.items()
    ]

    def group_key(item: dict[str, object]) -> tuple[int, str, str]:
        name = item["name"]
        uuid = item["uuid"]
        count = item["control_count"]
        if not isinstance(count, int):  # pragma: no cover - constructed above
            raise TypeError("control_count must be an integer")
        return (
            -count,
            name.casefold() if isinstance(name, str) else "",
            uuid if isinstance(uuid, str) else "",
        )

    def type_key(item: dict[str, object]) -> tuple[int, str, str]:
        control_type = item["type"]
        count = item["control_count"]
        if not isinstance(control_type, str) or not isinstance(count, int):  # pragma: no cover
            raise TypeError("type breakdown is invalid")
        return (-count, control_type.casefold(), control_type)

    room_items.sort(key=group_key)
    category_items.sort(key=group_key)
    type_items.sort(key=type_key)

    def breakdown(items: list[dict[str, object]]) -> dict[str, object]:
        total = len(items)
        selected = items[:max_items]
        return {
            "items": selected,
            "returned": len(selected),
            "total": total,
            "truncated": len(selected) < total,
            "complete": len(selected) == total,
        }

    return {
        "counts": {
            "controls": len(controls),
            "rooms": len(rooms),
            "categories": len(categories),
            "control_types": len(type_counts),
        },
        "rooms": breakdown(room_items),
        "categories": breakdown(category_items),
        "control_types": breakdown(type_items),
    }


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
            "hidden"
            if control.is_hidden
            else "linked"
            if control.is_user_linked or control.is_monitor_referenced
            else "direct"
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
