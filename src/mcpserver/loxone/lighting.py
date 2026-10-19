"""Bounded projection of existing source-proven LightControllerV2 mood data."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from mcpserver.loxone.models import Control

MOOD_ID_PATTERN = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")


def visible_mood_items(value: object) -> tuple[Mapping[str, object], ...] | None:
    """Return validated source rows from one bounded visible LightControllerV2 moodList."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, list) or len(value) > 1000:
        return None
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        mood_id = item.get("id")
        if isinstance(mood_id, bool):
            return None
        normalized = str(mood_id) if isinstance(mood_id, int | str) else ""
        if not MOOD_ID_PATTERN.fullmatch(normalized):
            return None
        result.append(item)
    return tuple(result)


def visible_mood_ids(value: object) -> frozenset[str] | None:
    """Retain the released operation ID contract through the shared validator."""
    rows = visible_mood_items(value)
    return frozenset(str(item["id"]) for item in rows) if rows is not None else None


MAX_MOODS = 100
MAX_MOOD_NAME = 200
MAX_MOOD_BYTES = 32_768
MAX_MOOD_INPUT_CHARACTERS = 1_048_576


@dataclass(frozen=True, slots=True)
class MoodEntry:
    id: str
    name: str | None
    name_truncated: bool


@dataclass(frozen=True, slots=True)
class MoodProjection:
    status: Literal["available", "invalid", "source_limit"]
    moods: tuple[MoodEntry, ...]
    total: int | None
    omitted: int | None
    truncated: bool
    names_complete: bool


def project_moods(value: object) -> MoodProjection:
    """Share operation ID validation; preserve source order and unknown names."""
    if isinstance(value, str) and len(value) > MAX_MOOD_INPUT_CHARACTERS:
        return MoodProjection("source_limit", (), None, None, False, False)
    try:
        rows = visible_mood_items(value)
    except (RecursionError, ValueError):
        return MoodProjection("invalid", (), None, None, False, False)
    if rows is None:
        return MoodProjection("invalid", (), None, None, False, False)
    moods: list[MoodEntry] = []
    names_complete = True
    used = 2
    for row in rows[:MAX_MOODS]:
        name = row.get("name")
        truncated = isinstance(name, str) and len(name) > MAX_MOOD_NAME
        bounded_name = name[:MAX_MOOD_NAME] if isinstance(name, str) else None
        try:
            size = len(
                json.dumps(
                    {"id": str(row["id"]), "name": bounded_name},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except UnicodeEncodeError:
            bounded_name = None
            size = len(str(row["id"])) + 24
        if used + size + bool(moods) > MAX_MOOD_BYTES:
            break
        used += size + bool(moods)
        names_complete &= bounded_name is not None and not truncated
        moods.append(MoodEntry(str(row["id"]), bounded_name, truncated))
    return MoodProjection(
        "available",
        tuple(moods),
        len(rows),
        len(rows) - len(moods),
        len(rows) > len(moods),
        names_complete,
    )


MAX_LIGHTING_OUTPUTS = 100
MAX_OUTPUT_STATES = 16
MAX_OUTPUT_BYTES = 16_384
LIGHTING_OUTPUT_TYPES = frozenset({"Switch", "Dimmer", "ColorPicker", "ColorPickerV2"})


@dataclass(frozen=True, slots=True)
class LightingOutput:
    uuid: str
    name: str | None
    type: str
    name_truncated: bool
    states: tuple[tuple[str, str], ...]
    states_omitted: int

    def wire_value(self) -> dict[str, object]:
        """Share the actual entry/state object shape with the MCP adapter budget."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "type": self.type,
            "name_truncated": self.name_truncated,
            "states": [{"name": name, "uuid": uuid} for name, uuid in self.states],
            "states_omitted": self.states_omitted,
        }


@dataclass(frozen=True, slots=True)
class LightingOutputProjection:
    status: Literal["available", "unsupported"]
    entries: tuple[LightingOutput, ...]
    total: int | None
    omitted: int | None
    unsupported_types: int | None


def project_lighting_outputs(control: Control) -> LightingOutputProjection:
    """Project explicit visible children; containment proves no physical connector."""
    if control.control_type != "LightControllerV2":
        return LightingOutputProjection("unsupported", (), None, None, None)
    entries: list[LightingOutput] = []
    total = unsupported = 0
    used = 2  # JSON list brackets.
    for child in control.subcontrols:
        if child.is_hidden:
            continue
        if child.control_type not in LIGHTING_OUTPUT_TYPES:
            unsupported += 1
            continue
        total += 1
        if len(entries) >= MAX_LIGHTING_OUTPUTS or not 1 <= len(child.uuid) <= 128:
            continue
        name = child.name[:200]
        states = tuple(
            (key[:100], uuid)
            for key, uuid in child.state_uuids[:MAX_OUTPUT_STATES]
            if 1 <= len(uuid) <= 128 and len(key) <= 100
        )
        entry = LightingOutput(
            child.uuid,
            name,
            child.control_type,
            len(child.name) > 200,
            states,
            len(child.state_uuids) - len(states),
        )
        try:
            size = len(
                json.dumps(entry.wire_value(), ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ) + bool(entries)
        except UnicodeEncodeError:
            continue
        if used + size > MAX_OUTPUT_BYTES:
            continue
        used += size
        entries.append(entry)
    return LightingOutputProjection(
        "available", tuple(entries), total, total - len(entries), unsupported
    )
