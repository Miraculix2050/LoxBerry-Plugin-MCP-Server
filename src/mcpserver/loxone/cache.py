"""Bounded in-memory state caches separated by Loxone identity."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Container, Iterable
from dataclasses import replace

from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Freshness, StateRecord


class UserStateCache:
    """Keep state values isolated by immutable Miniserver/user subject."""

    def __init__(
        self, *, max_states_per_user: int = 10_000, clock: Callable[[], float] = time.time
    ):
        if max_states_per_user < 1:
            raise ValueError("max_states_per_user must be positive")
        self._max_states = max_states_per_user
        self._clock = clock
        self._values: dict[str, OrderedDict[str, StateRecord]] = {}
        self._available: dict[str, bool] = {}

    def begin_connection(self, subject: str) -> None:
        values = self._values.setdefault(subject, OrderedDict())
        for uuid, record in tuple(values.items()):
            values[uuid] = replace(record, freshness=Freshness.STALE)
        self._available[subject] = True

    def apply(
        self, subject: str, events: Iterable[StateEvent], *, allowed_uuids: Container[str]
    ) -> None:
        values = self._values.setdefault(subject, OrderedDict())
        for uuid in tuple(values):
            if uuid not in allowed_uuids:
                del values[uuid]
        observed_at = self._clock()
        for event in events:
            if event.uuid not in allowed_uuids:
                continue
            values[event.uuid] = StateRecord(
                uuid=event.uuid,
                value=event.value,
                freshness=Freshness.CURRENT,
                observed_at=observed_at,
            )
            values.move_to_end(event.uuid)
            while len(values) > self._max_states:
                values.popitem(last=False)
        self._available[subject] = True

    def disconnect(self, subject: str) -> None:
        values = self._values.setdefault(subject, OrderedDict())
        for uuid, record in tuple(values.items()):
            values[uuid] = replace(record, freshness=Freshness.STALE)
        self._available[subject] = False

    def get(self, subject: str, uuid: str) -> StateRecord:
        values = self._values.get(subject)
        record = values.get(uuid) if values is not None else None
        if record is not None:
            return record
        freshness = (
            Freshness.UNKNOWN if self._available.get(subject, False) else Freshness.UNAVAILABLE
        )
        return StateRecord(uuid=uuid, value=None, freshness=freshness, observed_at=None)

    def clear(self, subject: str) -> None:
        self._values.pop(subject, None)
        self._available.pop(subject, None)
