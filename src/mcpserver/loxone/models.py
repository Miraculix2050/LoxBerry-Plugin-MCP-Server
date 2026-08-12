"""Small normalized models that never expose a raw LoxAPP3 document."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Freshness(StrEnum):
    """Freshness of a user-scoped state value."""

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LoxoneIdentity:
    """Identity returned by the user-filtered Miniserver session."""

    username: str
    miniserver_serial: str


@dataclass(frozen=True, slots=True)
class NamedGroup:
    uuid: str
    name: str


@dataclass(frozen=True, slots=True)
class StatisticSeries:
    """One user-visible statistic datapoint advertised by the structure file."""

    series_id: str
    source: str
    group_id: str
    output: str
    title: str
    format: str
    accumulated: bool = False
    legacy_output_index: int | None = None
    legacy_output_count: int | None = None


@dataclass(frozen=True, slots=True)
class Control:
    uuid: str
    name: str
    control_type: str
    room_uuid: str | None
    category_uuid: str | None
    action_uuid: str | None
    state_uuids: tuple[tuple[str, str], ...]
    restrictions: int = 0
    read_only: bool = False
    rating: int | None = None
    secured: bool = False
    has_notes: bool = False
    is_automatic: bool = False
    shading_animation: int | None = None
    has_history: bool = False
    picker_type: str | None = None
    min_kelvin: int = 2700
    max_kelvin: int = 6500
    scene_ids: tuple[str, ...] = ()
    radio_output_ids: tuple[str, ...] = ()
    radio_outputs: tuple[tuple[str, str], ...] = ()
    radio_reset_allowed: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    statistic_series: tuple[StatisticSeries, ...] = ()
    subcontrols: tuple[Control, ...] = ()
    linked_control_uuids: tuple[str, ...] = ()
    is_user_linked: bool = False
    is_hidden: bool = False


@dataclass(frozen=True, slots=True)
class LoxoneStructure:
    identity: LoxoneIdentity
    last_modified: str
    rooms: tuple[NamedGroup, ...]
    categories: tuple[NamedGroup, ...]
    controls: tuple[Control, ...]
    hidden_rooms: tuple[NamedGroup, ...] = ()
    hidden_categories: tuple[NamedGroup, ...] = ()
    hidden_controls: tuple[Control, ...] = ()


type StateValue = float | str | tuple[object, ...]


@dataclass(frozen=True, slots=True)
class StateRecord:
    uuid: str
    value: StateValue | None
    freshness: Freshness
    observed_at: float | None
