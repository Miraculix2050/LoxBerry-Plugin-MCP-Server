from __future__ import annotations

import pytest

from mcpserver.loxone.control import allowed_actions, prepare_control_command, visible_mood_ids
from mcpserver.loxone.models import Control


def _control(control_type: str, *, automatic: bool = False, read_only: bool = False) -> Control:
    return Control(
        uuid="control",
        name="Control",
        control_type=control_type,
        room_uuid=None,
        category_uuid=None,
        action_uuid="action",
        state_uuids=(),
        read_only=read_only,
        is_automatic=automatic,
    )


@pytest.mark.parametrize(
    ("control_type", "action", "kwargs", "command"),
    [
        ("Switch", "on", {}, "on"),
        ("Dimmer", "set_level", {"level": 42.5}, "42.5"),
        ("LightController", "set_mood", {"mood_id": "7"}, "7"),
        ("LightControllerV2", "off", {}, "changeTo/0"),
        ("LightControllerV2", "set_mood", {"mood_id": "314"}, "changeTo/314"),
        ("Jalousie", "open", {}, "FullUp"),
        ("Jalousie", "close", {}, "FullDown"),
        ("Jalousie", "set_position", {"position": 25}, "manualPosition/25"),
        ("Jalousie", "set_slat_position", {"slat_position": 60}, "manualLamelle/60"),
        (
            "Jalousie",
            "set_position_and_slats",
            {"position": 20, "slat_position": 70},
            "manualPosBlind/20/70",
        ),
    ],
)
def test_official_commands_are_mapped_without_raw_command_input(
    control_type: str, action: str, kwargs: dict[str, object], command: str
) -> None:
    prepared = prepare_control_command(_control(control_type), action, **kwargs)  # type: ignore[arg-type]

    assert prepared.command == command


def test_automatic_actions_are_advertised_only_for_automatic_jalousie() -> None:
    assert "enable_auto" not in allowed_actions(_control("Jalousie"))
    assert "enable_auto" in allowed_actions(_control("Jalousie", automatic=True))
    assert allowed_actions(_control("Jalousie", automatic=True, read_only=True)) == []


@pytest.mark.parametrize(
    ("control", "action", "kwargs"),
    [
        (_control("Dimmer"), "set_level", {"level": 101}),
        (_control("Dimmer"), "set_level", {"level": -1}),
        (_control("LightController"), "set_mood", {"mood_id": "ID1"}),
        (_control("LightControllerV2"), "set_mood", {"mood_id": "ID1"}),
        (_control("LightControllerV2"), "set_mood", {"mood_id": "../../on"}),
        (_control("Jalousie"), "set_position", {}),
        (_control("Jalousie"), "open", {"position": 10}),
        (_control("Jalousie"), "enable_auto", {}),
    ],
)
def test_invalid_or_mismatched_parameters_are_rejected(
    control: Control, action: str, kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        prepare_control_command(control, action, **kwargs)  # type: ignore[arg-type]


def test_visible_mood_ids_accepts_numeric_target_data() -> None:
    value = '[{"name":"Synthetic A","id":314},{"name":"Synthetic B","id":999}]'

    assert visible_mood_ids(value) == frozenset({"314", "999"})
    assert visible_mood_ids('[{"name":"Unsafe","id":"../../on"}]') is None
