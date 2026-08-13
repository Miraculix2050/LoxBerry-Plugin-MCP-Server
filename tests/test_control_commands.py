from __future__ import annotations

import pytest

from mcpserver.loxone.control import allowed_actions, prepare_control_command, visible_mood_ids
from mcpserver.loxone.models import Control, NamedOption


def _control(
    control_type: str,
    *,
    automatic: bool = False,
    read_only: bool = False,
    **kwargs: object,
) -> Control:
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
        **kwargs,  # type: ignore[arg-type]
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
        ("TimedSwitch", "pulse", {}, "pulse"),
        ("Pushbutton", "pulse", {}, "pulse"),
        ("UpDownAnalog", "set_value", {"value": 2}, "2"),
        ("Slider", "set_value", {"value": 2}, "2"),
        ("LeftRightAnalog", "set_value", {"value": 2}, "2"),
        ("CentralJalousie", "open", {}, "FullUp"),
        ("CentralJalousie", "disable_auto", {}, "NoAuto"),
        ("Daytimer", "pulse", {}, "pulse"),
        (
            "Daytimer",
            "start_override",
            {"value": 1, "duration_seconds": 300},
            "startOverride/1/300",
        ),
        ("Daytimer", "stop_override", {}, "stopOverride"),
        (
            "Radio",
            "select_output",
            {"output_id": "2"},
            "2",
        ),
        (
            "LightsceneRGB",
            "set_scene",
            {"scene_id": "3"},
            "3",
        ),
        (
            "ColorPickerV2",
            "set_color_hsv",
            {"hue": 360, "saturation": 50, "brightness": 25},
            "hsv(360,50,25)",
        ),
        (
            "ColorPickerV2",
            "set_color_temperature",
            {"brightness": 75, "kelvin": 4000},
            "temp(75,4000)",
        ),
    ],
)
def test_official_commands_are_mapped_without_raw_command_input(
    control_type: str, action: str, kwargs: dict[str, object], command: str
) -> None:
    options: dict[str, object] = {}
    if control_type == "Radio":
        options["radio_output_ids"] = ("2",)
    elif control_type == "Jalousie":
        options["shading_animation"] = 0
    elif control_type == "LightsceneRGB":
        options["scene_ids"] = ("3",)
    elif control_type == "ColorPickerV2":
        options["picker_type"] = "Rgb/Lumitech"
    elif control_type in {"UpDownAnalog", "Slider", "LeftRightAnalog"}:
        options.update({"minimum": 0.0, "maximum": 3.0, "step": 1.0})
    elif control_type == "Daytimer":
        options["is_analog"] = False
    prepared = prepare_control_command(_control(control_type, **options), action, **kwargs)  # type: ignore[arg-type]

    assert prepared.command == command


def test_automatic_actions_are_advertised_only_for_automatic_jalousie() -> None:
    assert "enable_auto" not in allowed_actions(_control("Jalousie"))
    assert "enable_auto" in allowed_actions(_control("Jalousie", automatic=True))
    assert allowed_actions(_control("Jalousie", automatic=True, read_only=True)) == []


def test_daytimer_actions_are_only_advertised_for_digital_controls() -> None:
    assert allowed_actions(_control("Daytimer", is_analog=False)) == [
        "pulse",
        "start_override",
        "stop_override",
    ]


def test_documented_temporary_hvac_overrides_are_bounded() -> None:
    irc = _control("IRoomControllerV2", timer_modes=())
    assert allowed_actions(irc) == []

    irc = _control("IRoomControllerV2", timer_modes=(NamedOption(1, "Comfort"),))
    assert (
        prepare_control_command(
            irc, "start_override", value=1, duration_seconds=60, now_seconds_since_2009=100
        ).command
        == "override/1/160"
    )
    assert prepare_control_command(irc, "stop_override").command == "stopOverride"

    ventilation = _control("Ventilation", ventilation_modes=(NamedOption(2, "Boost"),))
    assert (
        prepare_control_command(ventilation, "start_override", value=2, duration_seconds=60).command
        == "setTimer/60/100/2/-1"
    )
    assert prepare_control_command(ventilation, "stop_override").command == "setTimer/0"

    hvac = _control("ClimateControllerUS", connected_inputs=0)
    assert (
        prepare_control_command(
            hvac, "start_fan_override", duration_seconds=60, now_seconds_since_2009=100
        ).command
        == "startVentilationTimer/160"
    )
    assert prepare_control_command(hvac, "stop_mode_override").command == "startmodetimer/0/0/0"
    assert allowed_actions(_control("Daytimer", is_analog=True)) == []


@pytest.mark.parametrize("animation", (None, 1, 2, 3, 4, 5))
@pytest.mark.parametrize(
    ("action", "kwargs"),
    [
        ("set_slat_position", {"slat_position": 50}),
        ("set_position_and_slats", {"position": 50, "slat_position": 50}),
    ],
)
def test_jalousie_without_blind_animation_rejects_slat_actions(
    animation: int | None, action: str, kwargs: dict[str, int]
) -> None:
    control = _control("Jalousie", shading_animation=animation)

    assert "set_slat_position" not in allowed_actions(control)
    assert "set_position_and_slats" not in allowed_actions(control)
    with pytest.raises(ValueError, match="not supported"):
        prepare_control_command(control, action, **kwargs)


def test_blind_animation_advertises_slat_actions() -> None:
    control = _control("Jalousie", shading_animation=0)

    assert "set_slat_position" in allowed_actions(control)
    assert "set_position_and_slats" in allowed_actions(control)


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
        (_control("Radio", radio_output_ids=("2",)), "select_output", {"output_id": "3"}),
        (_control("Radio"), "reset", {}),
        (_control("Pushbutton"), "off", {}),
        (_control("CentralJalousie"), "set_position", {"position": 20}),
        (
            _control("Daytimer", is_analog=False),
            "start_override",
            {"value": 2, "duration_seconds": 1},
        ),
        (
            _control("Daytimer", is_analog=False),
            "start_override",
            {"value": 1, "duration_seconds": 0},
        ),
        (_control("Daytimer", is_analog=True), "pulse", {}),
        (
            _control("UpDownAnalog", minimum=0.0, maximum=3.0, step=1.0),
            "set_value",
            {"value": 4},
        ),
        (
            _control("UpDownAnalog", minimum=0.0, maximum=3.0, step=1.0),
            "set_value",
            {"value": 2.5},
        ),
        (_control("LightsceneRGB", scene_ids=("1",)), "set_scene", {"scene_id": "2"}),
        (
            _control("ColorPickerV2", picker_type="Rgb"),
            "set_color_hsv",
            {"hue": 361, "saturation": 50, "brightness": 50},
        ),
        (
            _control("ColorPickerV2", picker_type="TunableWhite"),
            "set_color_temperature",
            {"brightness": 50, "kelvin": 900},
        ),
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


def test_radio_reset_is_advertised_only_when_visible_details_allow_it() -> None:
    assert allowed_actions(_control("Radio")) == []
    assert allowed_actions(_control("Radio", radio_reset_allowed=True)) == ["reset"]


def test_combined_v1_color_picker_advertises_temperature_control() -> None:
    control = _control("ColorPicker", picker_type="Rgb/Lumitech")

    assert "set_color_temperature" in allowed_actions(control)
    prepared = prepare_control_command(
        control,
        "set_color_temperature",
        brightness=75,
        kelvin=4000,
    )
    assert prepared.command == "lumitech(75,4000)"


@pytest.mark.parametrize(
    ("action", "kwargs", "command"),
    [
        ("set_color_hsv", {"hue": -0.0, "saturation": -0.0, "brightness": -0.0}, "hsv(0,0,0)"),
        ("set_color_temperature", {"brightness": -0.0, "kelvin": 4000}, "temp(0,4000)"),
    ],
)
def test_color_commands_canonicalize_signed_zero(
    action: str, kwargs: dict[str, float | int], command: str
) -> None:
    control = _control("ColorPickerV2", picker_type="Rgb/Lumitech")

    assert prepare_control_command(control, action, **kwargs).command == command
