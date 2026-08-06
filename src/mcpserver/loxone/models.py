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
    is_automatic: bool = False
    subcontrols: tuple[Control, ...] = ()


@dataclass(frozen=True, slots=True)
class LoxoneStructure:
    identity: LoxoneIdentity
    last_modified: str
    rooms: tuple[NamedGroup, ...]
    categories: tuple[NamedGroup, ...]
    controls: tuple[Control, ...]


type StateValue = float | str | tuple[object, ...]


@dataclass(frozen=True, slots=True)
class StateRecord:
    uuid: str
    value: StateValue | None
    freshness: Freshness
    observed_at: float | None
