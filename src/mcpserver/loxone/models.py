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
class StatusMonitorInput:
    """One position-stable StatusMonitor input advertised by LoxAPP3."""

    index: int
    name: str | None
    install_place: str | None
    uuid: str | None
    room_uuid: str | None


@dataclass(frozen=True, slots=True)
class StatusMonitorStatus:
    """One configured StatusMonitor status value."""

    status_id: int
    name: str
    priority: int
    color: str | None


@dataclass(frozen=True, slots=True)
class NamedOption:
    """A bounded id/name option advertised by a control."""

    option_id: int
    name: str


@dataclass(frozen=True, slots=True)
class VentilationTimerProfile:
    """One bounded, visible Ventilation timer profile."""

    index: int
    name: str
    interval_seconds: int
    mode_ids: tuple[int, ...]
    default_mode_id: int | None
    speed_enabled: bool


@dataclass(frozen=True, slots=True)
class WindowMonitorItem:
    """One position-stable WindowMonitor entry."""

    index: int
    name: str | None
    room_uuid: str | None
    control_uuid: str | None
    install_place: str | None


@dataclass(frozen=True, slots=True)
class GlobalMetadata:
    """One normalized, read-only LoxAPP3 global metadata entry."""

    kind: str
    identifier: str
    name: str
    analog: bool | None = None
    locked: bool | None = None
    state_uuid: str | None = None


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
    is_favorite: bool = False
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
    is_analog: bool | None = None
    statistic_series: tuple[StatisticSeries, ...] = ()
    status_monitor_inputs: tuple[StatusMonitorInput, ...] = ()
    status_monitor_statuses: tuple[StatusMonitorStatus, ...] = ()
    format: str | None = None
    timer_modes: tuple[NamedOption, ...] = ()
    ventilation_modes: tuple[NamedOption, ...] = ()
    ventilation_timer_profiles: tuple[VentilationTimerProfile, ...] = ()
    window_monitor_items: tuple[WindowMonitorItem, ...] = ()
    connected_inputs: int | None = None
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
    global_metadata: tuple[GlobalMetadata, ...] = ()


type StateValue = float | str | tuple[object, ...] | dict[str, object]


@dataclass(frozen=True, slots=True)
class StateRecord:
    uuid: str
    value: StateValue | None
    freshness: Freshness
    observed_at: float | None
