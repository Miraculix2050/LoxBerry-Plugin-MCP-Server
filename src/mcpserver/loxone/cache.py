"""Bounded in-memory state caches separated by Loxone identity."""

from __future__ import annotations

import sys
import time
from collections import OrderedDict
from collections.abc import Callable, Container, Iterable, Iterator
from dataclasses import replace
from itertools import chain

from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Freshness, StateRecord

_MAX_VALUE_NODES = 65_536
_MAX_VALUE_DEPTH = 32
_ENTRY_OVERHEAD_BYTES = 768


def _state_size(uuid: str, value: object, limit: int) -> int | None:
    """Conservative ingress estimate; not a process RSS measurement.

    Exact decoder-built containers only. Bound traversal and iterator storage;
    strings have O(1) sizing, and no payload-sized serialization is allocated.
    """
    size = _ENTRY_OVERHEAD_BYTES + sys.getsizeof(uuid)
    frames: list[Iterator[object]] = [iter((value,))]
    containers: set[int] = set()
    nodes = 0
    while frames:
        try:
            item = next(frames[-1])
        except StopIteration:
            frames.pop()
            continue
        nodes += 1
        if nodes > _MAX_VALUE_NODES:
            return None
        kind = type(item)
        if kind not in (str, float, int, bool, type(None), dict, list, tuple):
            return None
        size += sys.getsizeof(item)
        if size > limit:
            return None
        if kind in (dict, list, tuple):
            # The wire decoders produce trees. Reject cycles/aliases rather than
            # retaining an unaccounted or non-serializable mutable graph.
            if id(item) in containers or len(frames) >= _MAX_VALUE_DEPTH:
                return None
            containers.add(id(item))
            if isinstance(item, dict):
                frames.append(chain(item.keys(), item.values()))
            elif isinstance(item, list | tuple):
                frames.append(iter(item))
    return size


class UserStateCache:
    """Keep state values isolated by immutable Miniserver/user subject."""

    def __init__(
        self,
        *,
        max_states_per_user: int = 10_000,
        max_bytes_per_user: int = 16 * 1024 * 1024,
        max_total_bytes: int = 64 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
    ):
        if max_states_per_user < 1:
            raise ValueError("max_states_per_user must be positive")
        if any(
            type(value) is not int or value < 1 for value in (max_bytes_per_user, max_total_bytes)
        ):
            raise ValueError("State cache byte budgets must be positive integers")
        self._max_states = max_states_per_user
        self._max_bytes_per_user = max_bytes_per_user
        self._max_total_bytes = max_total_bytes
        self._sizes: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._subject_bytes: dict[str, int] = {}
        self._total_bytes = 0
        self._subject_identity: dict[str, tuple[str, ...]] = {}
        self._identity_subjects: dict[tuple[str, ...], set[str]] = {}
        self._identity_entries: dict[tuple[str, ...], OrderedDict[tuple[str, str], None]] = {}
        self._identity_bytes: dict[tuple[str, ...], int] = {}
        self._byte_evictions = 0
        self._oversized_events = 0
        self._clock = clock
        self._values: dict[str, OrderedDict[str, StateRecord]] = {}
        self._available: dict[str, bool] = {}
        self._allowed_snapshots: dict[str, frozenset[str]] = {}

    def _identity_quota(self) -> int:
        return min(
            self._max_bytes_per_user,
            self._max_total_bytes // max(1, len(self._identity_subjects)),
        )

    def _register_identity(
        self, subject: str, identity_key: tuple[str, str] | None = None
    ) -> tuple[str, ...]:
        previous = self._subject_identity.get(subject)
        # Only explicit stable Miniserver/Loxone identity IDs may join families.
        # Missing identity evidence remains isolated by family, never by a label.
        key = ("identity", *identity_key) if identity_key else previous or ("family", subject)
        if key != previous:
            if previous is not None:
                self.clear(subject)
            self._subject_identity[subject] = key
            self._identity_subjects.setdefault(key, set()).add(subject)
            self._identity_entries.setdefault(key, OrderedDict())
            self._identity_bytes.setdefault(key, 0)
            # Actual new identities get an equal protected capacity share;
            # extra OAuth families of the same identity cannot multiply it.
            for identity in self._identity_subjects:
                self._trim_identity(identity)
        return key

    def _trim_identity(self, identity: tuple[str, ...]) -> None:
        while self._identity_bytes[identity] > self._identity_quota():
            family, uuid = next(iter(self._identity_entries[identity]))
            self._discard(family, uuid)
            self._byte_evictions += 1

    def begin_connection(
        self, subject: str, *, identity_key: tuple[str, str] | None = None
    ) -> None:
        self._register_identity(subject, identity_key)
        self._allowed_snapshots.pop(subject, None)
        values = self._values.setdefault(subject, OrderedDict())
        for uuid, record in tuple(values.items()):
            values[uuid] = replace(record, freshness=Freshness.STALE)
        self._available[subject] = True

    def apply(
        self, subject: str, events: Iterable[StateEvent], *, allowed_uuids: Container[str]
    ) -> None:
        identity = self._register_identity(subject)
        values = self._values.setdefault(subject, OrderedDict())
        # Only identity of an exact immutable snapshot can skip re-pruning.
        # Mutable/general containers retain their existing per-call behavior.
        immutable = type(allowed_uuids) is frozenset
        if not immutable or self._allowed_snapshots.get(subject) is not allowed_uuids:
            for uuid in tuple(values):
                if uuid not in allowed_uuids:
                    self._discard(subject, uuid)
            if type(allowed_uuids) is frozenset:
                self._allowed_snapshots[subject] = allowed_uuids
            else:
                self._allowed_snapshots.pop(subject, None)
        observed_at = self._clock()
        for event in events:
            if event.uuid not in allowed_uuids:
                continue
            size = _state_size(event.uuid, event.value, self._identity_quota())
            # An oversized replacement invalidates the old observation too.
            self._discard(subject, event.uuid)
            if size is None:
                self._oversized_events += 1
                continue
            values[event.uuid] = StateRecord(
                uuid=event.uuid,
                value=event.value,
                freshness=Freshness.CURRENT,
                observed_at=observed_at,
            )
            values.move_to_end(event.uuid)
            key = (subject, event.uuid)
            self._sizes[key] = size
            self._identity_entries[identity][key] = None
            self._identity_bytes[identity] += size
            self._subject_bytes[subject] = self._subject_bytes.get(subject, 0) + size
            self._total_bytes += size
            while len(values) > self._max_states:
                self._discard(subject, next(iter(values)))
            while self._subject_bytes.get(subject, 0) > self._max_bytes_per_user:
                self._discard(subject, next(iter(values)))
                self._byte_evictions += 1
            self._trim_identity(identity)
        self._available[subject] = True

    def _discard(self, subject: str, uuid: str) -> None:
        values = self._values.get(subject)
        if values is not None:
            values.pop(uuid, None)
        size = self._sizes.pop((subject, uuid), 0)
        identity = self._subject_identity.get(subject)
        if identity is not None:
            self._identity_entries[identity].pop((subject, uuid), None)
            self._identity_bytes[identity] -= size
        remaining = self._subject_bytes.get(subject, 0) - size
        if remaining:
            self._subject_bytes[subject] = remaining
        else:
            self._subject_bytes.pop(subject, None)
        self._total_bytes -= size

    def disconnect(self, subject: str) -> None:
        self._allowed_snapshots.pop(subject, None)
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
        for uuid in tuple(self._values.get(subject, ())):
            self._discard(subject, uuid)
        self._allowed_snapshots.pop(subject, None)
        self._values.pop(subject, None)
        self._available.pop(subject, None)
        identity = self._subject_identity.pop(subject, None)
        if identity is not None:
            self._identity_subjects[identity].discard(subject)
            if not self._identity_subjects[identity]:
                self._identity_subjects.pop(identity)
                self._identity_entries.pop(identity)
                self._identity_bytes.pop(identity)

    def clear_all(self) -> None:
        """Release every subject through the normal per-subject cleanup path."""
        for subject in self._values.keys() | self._available.keys() | self._subject_identity.keys():
            self.clear(subject)
