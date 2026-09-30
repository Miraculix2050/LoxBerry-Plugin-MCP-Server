from __future__ import annotations

from dataclasses import replace

import pytest

from mcpserver.loxone.models import Control, LoxoneStructure, Room
from mcpserver.loxone.presentation import window_monitor_description
from mcpserver.loxone.structure import normalize_structure


def _structure(windows: object, *, target_room: str | None = "room") -> LoxoneStructure:
    return normalize_structure(
        {
            "msInfo": {"serialNr": "serial"},
            "rooms": {"room": {"name": "Same name"}, "other-room": {"name": "Same name"}},
            "controls": {
                "monitor": {
                    "name": "Windows",
                    "type": "WindowMonitor",
                    "details": {"windows": windows},
                },
                "target": {"name": "Window", "type": "Switch", "room": target_room},
                "other": {"name": "Other", "type": "Switch", "room": "other-room"},
            },
        },
        username="reader",
    )


@pytest.mark.parametrize(
    "source,codes",
    [
        ("rejected-shape-marker", ("invalid_window_monitor_entry",)),
        (
            {"name": [], "room": {}, "uuid": 1, "installPlace": False},
            (
                "invalid_control_reference",
                "invalid_install_place",
                "invalid_name",
                "invalid_room_reference",
            ),
        ),
        (
            {"name": None, "room": None, "uuid": None, "installPlace": None},
            (
                "invalid_control_reference",
                "invalid_install_place",
                "invalid_name",
                "invalid_room_reference",
            ),
        ),
        ({}, ()),
        ({"name": "", "installPlace": ""}, ()),
    ],
)
def test_input_diagnostics_are_fixed_and_keep_neighbor_positions(
    source: object, codes: tuple[str, ...]
) -> None:
    structure = _structure(
        [{"uuid": "target", "room": "room"}, source, {"uuid": "target", "room": "room"}]
    )
    items = structure.controls[0].window_monitor_items
    assert [item.index for item in items] == [0, 1, 2]
    assert items[1].diagnostics == codes
    assert items[0].control_uuid == items[2].control_uuid == "target"
    assert "rejected-shape-marker" not in repr(items)


@pytest.mark.parametrize("field", ["name", "room", "uuid", "installPlace"])
def test_rejected_oversized_source_values_are_not_retained(field: str) -> None:
    rejected = "rejected-value-marker" * 20
    structure = _structure([{field: rejected}])
    item = structure.controls[0].window_monitor_items[0]
    assert len(item.diagnostics) == 1
    assert rejected not in repr(item)
    description = window_monitor_description(
        structure.controls[0],
        {control.uuid: control for control in structure.controls},
        {room.uuid: room.name for room in structure.rooms},
    )
    assert "rejected-value-marker" not in repr(description)


def test_mapping_fallback_retains_invalid_explicit_reference_diagnostic() -> None:
    monitor = _structure({"target": {"uuid": ["rejected"], "room": "room"}}).controls[0]
    item = monitor.window_monitor_items[0]
    assert item.control_uuid == "target"
    assert item.diagnostics == ("invalid_control_reference",)
    explicit = _structure({"x" * 201: {"uuid": "target"}}).controls[0].window_monitor_items[0]
    assert explicit.control_uuid == "target"
    assert explicit.diagnostics == ()


@pytest.mark.parametrize("key", [123, "rejected-key-marker" * 20])
def test_rejected_mapping_keys_are_diagnosed_without_echoing(key: object) -> None:
    monitor = _structure({key: {}}).controls[0]
    item = monitor.window_monitor_items[0]
    assert item.control_uuid is None
    assert item.diagnostics == ("invalid_control_reference",)
    assert "rejected-key-marker" not in repr(item)


@pytest.mark.parametrize("windows", [None, "invalid-collection-marker"])
def test_empty_or_invalid_collections_have_zero_resolution_counts(windows: object) -> None:
    structure = _structure(windows)
    items, summary = window_monitor_description(structure.controls[0], {}, {})
    assert items == []
    assert summary is not None
    assert summary["resolved"] == summary["partially_resolved"] == summary["unresolved"] == 0
    assert "invalid-collection-marker" not in repr(summary)


@pytest.mark.parametrize(
    "fields,target_room,codes,status,consistency",
    [
        ({"uuid": "target", "room": "room"}, "room", [], "resolved", "match"),
        (
            {"uuid": "target", "room": "other-room"},
            "room",
            ["room_reference_mismatch"],
            "resolved",
            "mismatch",
        ),
        (
            {"uuid": "unknown", "room": "room"},
            "room",
            ["control_reference_unavailable"],
            "partially_resolved",
            "unknown",
        ),
        (
            {"uuid": "target", "room": "unknown"},
            "room",
            ["room_reference_unavailable"],
            "partially_resolved",
            "unknown",
        ),
        ({"room": "room"}, "room", ["missing_control_reference"], "partially_resolved", "unknown"),
        ({"uuid": "target"}, "room", ["missing_room_reference"], "partially_resolved", "unknown"),
        (
            {},
            "room",
            ["missing_control_reference", "missing_room_reference"],
            "unresolved",
            "unknown",
        ),
        ({"uuid": "target", "room": "room"}, None, [], "resolved", "unknown"),
        ({"uuid": "target", "room": "room"}, "unknown", [], "resolved", "unknown"),
        ("malformed", "room", ["invalid_window_monitor_entry"], "unresolved", "unknown"),
    ],
)
def test_visible_resolution_and_room_consistency_are_independent(
    fields: object, target_room: str | None, codes: list[str], status: str, consistency: str
) -> None:
    structure = _structure([fields], target_room=target_room)
    items, summary = window_monitor_description(
        structure.controls[0],
        {control.uuid: control for control in structure.controls},
        {room.uuid: room.name for room in structure.rooms},
    )
    assert items[0]["diagnostics"] == codes
    assert items[0]["resolution_status"] == status
    assert items[0]["room_consistency"] == consistency
    assert summary is not None
    assert summary[status] == 1
    assert (
        summary["resolved"] + summary["partially_resolved"] + summary["unresolved"]
        == summary["returned"]
        == 1
    )


@pytest.mark.parametrize("hidden_exists", [False, True])
def test_hidden_and_absent_targets_have_identical_resolution(hidden_exists: bool) -> None:
    structure = _structure([{"uuid": "hidden-target", "room": "hidden-room"}])
    structure = replace(
        structure,
        hidden_controls=(
            Control(
                "hidden-target",
                "private-name-marker",
                "Switch",
                "hidden-room",
                None,
                None,
                (),
                is_hidden=True,
            ),
        )
        if hidden_exists
        else (),
        hidden_rooms=(Room("hidden-room", "private-room-marker"),) if hidden_exists else (),
    )
    items, _summary = window_monitor_description(
        structure.controls[0],
        {control.uuid: control for control in structure.controls},
        {room.uuid: room.name for room in structure.rooms},
    )
    assert items[0]["diagnostics"] == [
        "control_reference_unavailable",
        "room_reference_unavailable",
    ]
    assert items[0]["resolution_status"] == "unresolved"
    assert items[0]["room_consistency"] == "unknown"
    assert items[0]["room"] is items[0]["control"] is None
    assert "private-" not in repr(items)


def test_resolution_counts_exclude_omitted_and_include_malformed_positions() -> None:
    structure = _structure(
        [
            {"uuid": "target", "room": "room"},
            {"uuid": "target"},
            *(["malformed"] * 98),
            {"uuid": "target", "room": "room"},
        ]
    )
    items, summary = window_monitor_description(
        structure.controls[0],
        {control.uuid: control for control in structure.controls},
        {room.uuid: room.name for room in structure.rooms},
    )
    assert len(items) == 100
    assert summary == {
        "total": 101,
        "returned": 100,
        "omitted": 1,
        "truncated": True,
        "diagnostics": [],
        "resolved": 1,
        "partially_resolved": 1,
        "unresolved": 98,
    }
