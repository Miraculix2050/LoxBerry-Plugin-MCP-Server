"""Officially documented, narrowly allowlisted Loxone control commands."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from mcpserver.loxone.models import Control

SUPPORTED_CONTROL_TYPES = frozenset(
    {
        "Switch",
        "Dimmer",
        "LightController",
        "LightControllerV2",
        "Jalousie",
        "TimedSwitch",
        "Radio",
        "LightsceneRGB",
        "ColorPicker",
        "ColorPickerV2",
        "Pushbutton",
        "UpDownAnalog",
        "Slider",
        "LeftRightAnalog",
        "CentralJalousie",
        "Daytimer",
    }
)
_MOOD_ID = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")


@dataclass(frozen=True, slots=True)
class PreparedControlCommand:
    command: str
    expected_states: tuple[tuple[str, float | str], ...] = ()


def visible_mood_ids(value: object) -> frozenset[str] | None:
    """Return bounded decimal IDs from one visible LightControllerV2 moodList state."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, list) or len(value) > 1000:
        return None
    result: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            return None
        mood_id = item.get("id")
        if isinstance(mood_id, bool):
            return None
        normalized = str(mood_id) if isinstance(mood_id, int | str) else ""
        if not _MOOD_ID.fullmatch(normalized):
            return None
        result.add(normalized)
    return frozenset(result)


def allowed_actions(control: Control) -> list[str]:
    """Return actions whose command contracts are documented for this control."""
    if control.action_uuid is None or not 1 <= len(control.action_uuid) <= 128 or control.read_only:
        return []
    match control.control_type:
        case "Switch":
            return ["on", "off"]
        case "Dimmer":
            return ["on", "off", "set_level"]
        case "LightController":
            return ["on", "off", "set_mood"]
        case "LightControllerV2":
            return ["off", "set_mood"]
        case "Jalousie":
            actions = [
                "open",
                "close",
                "shade",
                "stop",
                "set_position",
            ]
            if control.shading_animation == 0:
                actions.extend(["set_slat_position", "set_position_and_slats"])
            if control.is_automatic:
                actions.extend(["enable_auto", "disable_auto"])
            return actions
        case "CentralJalousie":
            return ["open", "close", "shade", "stop", "enable_auto", "disable_auto"]
        case "Daytimer":
            return (
                ["pulse", "start_override", "stop_override"] if control.is_analog is False else []
            )
        case "TimedSwitch":
            return ["on", "off", "pulse"]
        case "Radio":
            actions = ["select_output"] if control.radio_output_ids else []
            if control.radio_reset_allowed:
                actions.append("reset")
            return actions
        case "LightsceneRGB":
            return ["on", "off", "set_scene"] if control.scene_ids else ["on", "off"]
        case "ColorPicker":
            actions = ["on", "off"]
            if control.picker_type in {"Rgb", "Lumitech", "Rgb/Lumitech"}:
                actions.append("set_color_hsv")
            if control.picker_type in {"Lumitech", "Rgb/Lumitech"}:
                actions.append("set_color_temperature")
            return actions
        case "ColorPickerV2":
            actions = []
            if control.picker_type in {"Rgb", "Lumitech", "Rgb/Lumitech"}:
                actions.append("set_color_hsv")
            if control.picker_type in {"Lumitech", "Rgb/Lumitech", "TunableWhite"}:
                actions.append("set_color_temperature")
            return actions
        case "Pushbutton":
            return ["pulse"]
        case "UpDownAnalog" | "Slider" | "LeftRightAnalog":
            return (
                ["set_value"]
                if control.minimum is not None
                and control.maximum is not None
                and control.step is not None
                else []
            )
        case _:
            return []


def _percentage(value: float | None, name: str) -> float:
    if value is None or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be a number from 0 to 100")
    return float(value)


def _number(value: float) -> str:
    if value == 0:
        return "0"
    formatted = format(Decimal(str(value)), "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def prepare_control_command(
    control: Control,
    action: str,
    *,
    level: float | None = None,
    mood_id: str | None = None,
    position: float | None = None,
    slat_position: float | None = None,
    scene_id: str | None = None,
    output_id: str | None = None,
    hue: float | None = None,
    saturation: float | None = None,
    brightness: float | None = None,
    kelvin: int | None = None,
    value: float | None = None,
    duration_seconds: int | None = None,
) -> PreparedControlCommand:
    """Validate one exact action/parameter combination and build its Loxone command."""
    provided = {
        "level": level,
        "mood_id": mood_id,
        "position": position,
        "slat_position": slat_position,
        "scene_id": scene_id,
        "output_id": output_id,
        "hue": hue,
        "saturation": saturation,
        "brightness": brightness,
        "kelvin": kelvin,
        "value": value,
        "duration_seconds": duration_seconds,
    }

    def require_only(*names: str) -> None:
        unexpected = [
            name for name, value in provided.items() if value is not None and name not in names
        ]
        missing = [name for name in names if provided[name] is None]
        if unexpected or missing:
            expected = ", ".join(names) if names else "no parameters"
            raise ValueError(f"action {action} requires {expected}")

    if action not in allowed_actions(control):
        raise ValueError(f"action {action} is not supported for {control.control_type}")

    if control.control_type == "Switch":
        require_only()
        return PreparedControlCommand(action, (("active", 1.0 if action == "on" else 0.0),))

    if control.control_type == "Dimmer":
        if action in {"on", "off"}:
            require_only()
            expected = (("position", "__positive__"),) if action == "on" else (("position", 0.0),)
            return PreparedControlCommand(action, expected)
        require_only("level")
        target = _percentage(level, "level")
        return PreparedControlCommand(_number(target), (("position", target),))

    if control.control_type == "LightController":
        if action in {"on", "off"}:
            require_only()
            target = 9.0 if action == "on" else 0.0
            return PreparedControlCommand(action, (("activeScene", target),))
        require_only("mood_id")
        if mood_id is None or not mood_id.isdecimal() or not 0 <= int(mood_id) <= 99:
            raise ValueError("mood_id must be a decimal scene number from 0 to 99")
        return PreparedControlCommand(mood_id, (("activeScene", float(mood_id)),))

    if control.control_type == "LightControllerV2":
        if action == "off":
            require_only()
            return PreparedControlCommand("changeTo/0", (("activeMoods", "0"),))
        require_only("mood_id")
        if mood_id is None or not _MOOD_ID.fullmatch(mood_id):
            raise ValueError("mood_id must be a decimal ID from the visible moodList")
        return PreparedControlCommand(f"changeTo/{mood_id}", (("activeMoods", mood_id),))

    if control.control_type == "TimedSwitch":
        require_only()
        targets = {"on": -1.0, "off": 0.0}
        timed_expected: tuple[tuple[str, float | str], ...] = (
            (("deactivationDelay", targets[action]),) if action in targets else ()
        )
        return PreparedControlCommand(action, timed_expected)

    if control.control_type == "Pushbutton":
        require_only()
        return PreparedControlCommand("pulse")

    if control.control_type in {"UpDownAnalog", "Slider", "LeftRightAnalog"}:
        require_only("value")
        if (
            value is None
            or isinstance(value, bool)
            or control.minimum is None
            or control.maximum is None
            or control.step is None
            or not control.minimum <= value <= control.maximum
        ):
            raise ValueError("value is outside the visible supported range")
        target = float(value)
        steps = (target - control.minimum) / control.step
        if not math.isclose(steps, round(steps), rel_tol=0, abs_tol=1e-9):
            raise ValueError("value is not aligned to the visible step")
        return PreparedControlCommand(_number(target), (("value", target),))

    if control.control_type == "Daytimer":
        if action == "pulse":
            require_only()
            return PreparedControlCommand("pulse")
        if action == "stop_override":
            require_only()
            return PreparedControlCommand("stopOverride", (("override", 0.0),))
        require_only("value", "duration_seconds")
        if value not in {0, 1} or duration_seconds is None or not 1 <= duration_seconds <= 86_400:
            raise ValueError(
                "digital daytimer override requires value 0 or 1 and duration_seconds "
                "from 1 to 86400"
            )
        return PreparedControlCommand(
            f"startOverride/{_number(float(value))}/{duration_seconds}",
            (("override", "__positive__"),),
        )

    if control.control_type == "CentralJalousie":
        require_only()
        commands = {
            "open": "FullUp",
            "close": "FullDown",
            "shade": "shade",
            "stop": "stop",
            "enable_auto": "auto",
            "disable_auto": "NoAuto",
        }
        return PreparedControlCommand(commands[action])

    if control.control_type == "Radio":
        if action == "reset":
            require_only()
            return PreparedControlCommand("reset", (("activeOutput", 0.0),))
        require_only("output_id")
        if output_id not in control.radio_output_ids:
            raise ValueError("output_id is not present in the visible outputs")
        return PreparedControlCommand(output_id, (("activeOutput", float(output_id)),))

    if control.control_type == "LightsceneRGB":
        if action in {"on", "off"}:
            require_only()
            return PreparedControlCommand(action)
        require_only("scene_id")
        if scene_id not in control.scene_ids:
            raise ValueError("scene_id is not present in the visible sceneList")
        return PreparedControlCommand(scene_id, (("activeScene", float(scene_id)),))

    if control.control_type in {"ColorPicker", "ColorPickerV2"}:
        if action in {"on", "off"}:
            require_only()
            return PreparedControlCommand(action)
        if action == "set_color_hsv":
            require_only("hue", "saturation", "brightness")
            if hue is None or isinstance(hue, bool) or not 0 <= hue <= 360:
                raise ValueError("hue must be a number from 0 to 360")
            selected_hue = float(hue)
            selected_saturation = _percentage(saturation, "saturation")
            selected_brightness = _percentage(brightness, "brightness")
            command = (
                f"hsv({_number(float(selected_hue))},{_number(selected_saturation)},"
                f"{_number(selected_brightness)})"
            )
            return PreparedControlCommand(command, (("color", command),))
        require_only("brightness", "kelvin")
        selected_brightness = _percentage(brightness, "brightness")
        if (
            kelvin is None
            or isinstance(kelvin, bool)
            or not control.min_kelvin <= kelvin <= control.max_kelvin
        ):
            raise ValueError("kelvin is outside the visible supported range")
        prefix = "lumitech" if control.control_type == "ColorPicker" else "temp"
        command = f"{prefix}({_number(selected_brightness)},{kelvin})"
        return PreparedControlCommand(command, (("color", command),))

    if action in {"open", "close", "shade", "stop", "enable_auto", "disable_auto"}:
        require_only()
        commands = {
            "open": "FullUp",
            "close": "FullDown",
            "shade": "shade",
            "stop": "stop",
            "enable_auto": "auto",
            "disable_auto": "NoAuto",
        }
        expected_by_action: dict[str, tuple[tuple[str, float | str], ...]] = {
            "open": (("targetPosition", 0.0),),
            "close": (("targetPosition", 1.0),),
            "enable_auto": (("autoActive", 1.0),),
            "disable_auto": (("autoActive", 0.0),),
        }
        return PreparedControlCommand(commands[action], expected_by_action.get(action, ()))
    if action == "set_position":
        require_only("position")
        target = _percentage(position, "position")
        return PreparedControlCommand(
            f"manualPosition/{_number(target)}", (("targetPosition", target / 100),)
        )
    if action == "set_slat_position":
        require_only("slat_position")
        target = _percentage(slat_position, "slat_position")
        return PreparedControlCommand(
            f"manualLamelle/{_number(target)}", (("targetPositionLamelle", target / 100),)
        )
    require_only("position", "slat_position")
    target = _percentage(position, "position")
    slats = _percentage(slat_position, "slat_position")
    return PreparedControlCommand(
        f"manualPosBlind/{_number(target)}/{_number(slats)}",
        (("targetPosition", target / 100), ("targetPositionLamelle", slats / 100)),
    )
