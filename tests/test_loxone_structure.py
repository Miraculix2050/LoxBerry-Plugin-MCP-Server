from __future__ import annotations

import pytest

from mcpserver.loxone.structure import LoxoneStructureError, normalize_structure


def test_structure_is_reduced_to_user_visible_domain_fields() -> None:
    raw = {
        "lastModified": "2026-08-01 12:00:00",
        "msInfo": {"serialNr": "000000000000", "projectName": "must not leak"},
        "rooms": {
            "room-1": {"name": "Kitchen", "image": "ignored"},
            "denied-room": {"name": "Secret room"},
        },
        "cats": {
            "cat-1": {"name": "Lights"},
            "denied-category": {"name": "Secret category"},
        },
        "controls": {
            "control-1": {
                "name": "Ceiling",
                "type": "Switch",
                "room": "room-1",
                "cat": "cat-1",
                "uuidAction": "action-1",
                "action": "must-not-be-used",
                "restrictions": 0,
                "states": {"active": "state-1"},
                "details": {"password": "must not leak"},
                "links": ["denied-control"],
                "subControls": {
                    "sub-1": {
                        "name": "Sub",
                        "type": "InfoOnlyDigital",
                        "restrictions": 17,
                        "states": {"active": "state-2"},
                    }
                },
            },
            "denied-control": {
                "name": "Denied",
                "type": "InfoOnlyAnalog",
                "restrictions": 17,
                "room": "denied-room",
                "cat": "denied-category",
                "states": {"value": "denied-state"},
            },
            "unlinked-control": {
                "name": "Unlinked",
                "type": "InfoOnlyAnalog",
                "restrictions": 17,
                "states": {"value": "unlinked-state"},
            },
        },
    }

    structure = normalize_structure(raw, username="restricted-reader")

    assert structure.identity.username == "restricted-reader"
    assert structure.identity.miniserver_serial == "000000000000"
    assert structure.rooms[0].name == "Kitchen"
    assert structure.controls[0].state_uuids == (("active", "state-1"),)
    assert structure.controls[0].action_uuid == "action-1"
    assert structure.controls[0].subcontrols[0].uuid == "sub-1"
    assert {control.uuid for control in structure.controls} == {"control-1", "denied-control"}
    assert {control.uuid for control in structure.hidden_controls} == {"unlinked-control"}
    assert structure.hidden_controls[0].is_hidden is True
    assert structure.controls[0].linked_control_uuids == ("denied-control",)
    assert structure.controls[1].is_user_linked is True
    assert {room.uuid for room in structure.rooms} == {"room-1", "denied-room"}
    assert {category.uuid for category in structure.categories} == {"cat-1", "denied-category"}
    assert "must not leak" not in repr(structure)


def test_structure_preserves_status_monitor_input_mapping() -> None:
    raw = {
        "msInfo": {"serialNr": "000000000000"},
        "lastModified": "1",
        "rooms": {},
        "cats": {},
        "controls": {
            "monitor": {
                "name": "Network status",
                "type": "StatusMonitor",
                "states": {"inputStates": "monitor-input-states"},
                "details": {
                    "inputs": [
                        {"name": "Printer", "installPlace": "Office", "uuid": "printer"},
                        {"name": "NAS", "room": "server-room"},
                        {"name": 3},
                    ],
                    "status": {
                        "status1": {"id": 1, "name": "Offline", "prio": 0, "color": "#E4354A"},
                        "invalid": {"id": "0", "name": "Online", "prio": 1},
                    },
                },
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.status_monitor_inputs[0].name == "Printer"
    assert control.status_monitor_inputs[0].install_place == "Office"
    assert control.status_monitor_inputs[1].room_uuid == "server-room"
    assert len(control.status_monitor_inputs) == 3
    assert control.status_monitor_inputs[2].index == 2
    assert control.status_monitor_inputs[2].name is None
    assert control.status_monitor_statuses[0].status_id == 1
    assert control.status_monitor_statuses[0].color == "#E4354A"


def test_structure_preserves_operability_flags_without_exposing_details() -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "blind": {
                "name": "Blind",
                "type": "Jalousie",
                "uuidAction": "blind-action",
                "restrictions": 32,
                "details": {"isAutomatic": True, "animation": 1, "private": "ignored"},
                "states": {},
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.action_uuid == "blind-action"
    assert control.read_only is True
    assert control.is_automatic is True
    assert control.shading_animation == 1
    assert "private" not in repr(control)


@pytest.mark.parametrize("animation", (True, False, -1, 6, "0", 0.0))
def test_structure_ignores_invalid_jalousie_animation_values(animation: object) -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "blind": {
                "name": "Blind",
                "type": "Jalousie",
                "uuidAction": "blind-action",
                "details": {"animation": animation},
                "states": {},
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.shading_animation is None


def test_absent_controls_remain_absent() -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {},
    }

    structure = normalize_structure(raw, username="restricted-reader")

    assert structure.controls == ()


def test_structure_extracts_only_bounded_phase_four_capabilities() -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "picker": {
                "name": "Picker",
                "type": "ColorPickerV2",
                "uuidAction": "picker-action",
                "defaultRating": 4,
                "isSecured": True,
                "hasControlNotes": True,
                "states": {},
                "details": {
                    "hasHistory": True,
                    "pickerType": "Rgb/Lumitech",
                    "minKelvin": 2200,
                    "maxKelvin": 9000,
                },
                "statisticV2": {
                    "groups": [
                        {
                            "id": 1,
                            "accumulated": True,
                            "dataPoints": [
                                {"output": "value", "title": "Energy", "format": "%.1f kWh"},
                                {"output": "../unsafe", "title": "Unsafe"},
                            ],
                        }
                    ]
                },
            },
            "radio": {
                "name": "Radio",
                "type": "Radio",
                "uuidAction": "radio-action",
                "states": {},
                "details": {"outputs": {"1": "One", "2": "Two"}, "allOff": "Off"},
            },
            "up-down": {
                "name": "Linked value",
                "type": "UpDownAnalog",
                "uuidAction": "up-down-action",
                "states": {"value": "up-down-value"},
                "details": {"min": 0.0, "max": 3.0, "step": 1.0},
            },
        },
    }

    picker, radio, up_down = normalize_structure(raw, username="reader").controls

    assert picker.has_history is True
    assert (picker.rating, picker.secured, picker.has_notes) == (4, True, True)
    assert (picker.picker_type, picker.min_kelvin, picker.max_kelvin) == (
        "Rgb/Lumitech",
        2200,
        9000,
    )
    assert [series.series_id for series in picker.statistic_series] == ["v2:1:value"]
    assert radio.radio_output_ids == ("1", "2")
    assert radio.radio_outputs == (("1", "One"), ("2", "Two"))
    assert radio.radio_reset_allowed is True
    assert (up_down.minimum, up_down.maximum, up_down.step) == (0.0, 3.0, 1.0)


def test_structure_preserves_documented_favorite_and_high_rating() -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "control": {
                "name": "Favorite",
                "type": "Switch",
                "defaultRating": 9,
                "isFavorite": True,
                "states": {},
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.rating == 9
    assert control.is_favorite is True


def test_structure_exposes_documented_legacy_statistic_outputs() -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "temperature": {
                "name": "Temperature",
                "type": "InfoOnlyAnalog",
                "uuidAction": "temperature-action",
                "states": {},
                "statistic": {
                    "frequency": 10,
                    "outputs": [
                        {"id": 0, "name": "Temperature", "format": "%.1f °C"},
                        {"id": 1, "name": "Average", "format": "%.1f °C"},
                    ],
                },
            }
        },
    }

    series = normalize_structure(raw, username="reader").controls[0].statistic_series

    assert [
        (item.series_id, item.source, item.legacy_output_index, item.legacy_output_count)
        for item in series
    ] == [
        ("legacy:0", "legacy", 0, 2),
        ("legacy:1", "legacy", 1, 2),
    ]


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [(False, False), (True, True), (0, False), (20, True)],
)
def test_structure_accepts_documented_and_numeric_history_capabilities(
    raw_value: object, expected: bool
) -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "control": {
                "name": "Control",
                "type": "Switch",
                "uuidAction": "control-action",
                "states": {},
                "details": {"hasHistory": raw_value},
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.has_history is expected


@pytest.mark.parametrize("raw_value", [-1, "true", 1.0, None])
def test_structure_rejects_invalid_history_capabilities(raw_value: object) -> None:
    raw = {
        "lastModified": "now",
        "msInfo": {"serialNr": "000000000000"},
        "rooms": {},
        "cats": {},
        "controls": {
            "control": {
                "name": "Control",
                "type": "Switch",
                "uuidAction": "control-action",
                "states": {},
                "details": {"hasHistory": raw_value},
            }
        },
    }

    with pytest.raises(
        LoxoneStructureError,
        match="Control details.hasHistory must be boolean or non-negative integer",
    ):
        normalize_structure(raw, username="reader")
