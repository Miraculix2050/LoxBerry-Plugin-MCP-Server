from __future__ import annotations

from mcpserver.loxone.structure import normalize_structure


def test_structure_is_reduced_to_user_visible_domain_fields() -> None:
    raw = {
        "lastModified": "2026-08-01 12:00:00",
        "msInfo": {"serialNr": "000000000000", "projectName": "must not leak"},
        "rooms": {"room-1": {"name": "Kitchen", "image": "ignored"}},
        "cats": {"cat-1": {"name": "Lights"}},
        "controls": {
            "control-1": {
                "name": "Ceiling",
                "type": "Switch",
                "room": "room-1",
                "cat": "cat-1",
                "action": "action-1",
                "states": {"active": "state-1"},
                "details": {"password": "must not leak"},
                "subControls": {
                    "sub-1": {
                        "name": "Sub",
                        "type": "InfoOnlyDigital",
                        "states": {"active": "state-2"},
                    }
                },
            }
        },
    }

    structure = normalize_structure(raw, username="restricted-reader")

    assert structure.identity.username == "restricted-reader"
    assert structure.identity.miniserver_serial == "000000000000"
    assert structure.rooms[0].name == "Kitchen"
    assert structure.controls[0].state_uuids == (("active", "state-1"),)
    assert structure.controls[0].subcontrols[0].uuid == "sub-1"
    assert "must not leak" not in repr(structure)


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
