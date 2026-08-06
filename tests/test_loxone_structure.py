from __future__ import annotations

from mcpserver.loxone.structure import normalize_structure


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
        },
    }

    structure = normalize_structure(raw, username="restricted-reader")

    assert structure.identity.username == "restricted-reader"
    assert structure.identity.miniserver_serial == "000000000000"
    assert structure.rooms[0].name == "Kitchen"
    assert structure.controls[0].state_uuids == (("active", "state-1"),)
    assert structure.controls[0].action_uuid == "action-1"
    assert structure.controls[0].subcontrols[0].uuid == "sub-1"
    assert {control.uuid for control in structure.controls} == {"control-1"}
    assert {room.uuid for room in structure.rooms} == {"room-1"}
    assert {category.uuid for category in structure.categories} == {"cat-1"}
    assert "must not leak" not in repr(structure)


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
                "details": {"isAutomatic": True, "private": "ignored"},
                "states": {},
            }
        },
    }

    control = normalize_structure(raw, username="reader").controls[0]

    assert control.action_uuid == "blind-action"
    assert control.read_only is True
    assert control.is_automatic is True
    assert "private" not in repr(control)


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
