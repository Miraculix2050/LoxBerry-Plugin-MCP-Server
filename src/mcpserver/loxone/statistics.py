"""Bounded statistic parsing and disposable in-memory caching."""

from __future__ import annotations

import hashlib
import math
import struct
import sys
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Final

from mcpserver.loxone.events import LoxoneProtocolError

_POINT: Final = struct.Struct("<Id")
_MAX_SOURCE_BYTES: Final = 64 * 1024 * 1024
_MAX_MEMORY_POINTS: Final = 100_000


@dataclass(frozen=True, slots=True)
class StatisticPoint:
    timestamp: int
    value: float


def parse_statistic_points(
    payload: bytes, *, maximum_points: int = 100_000
) -> tuple[StatisticPoint, ...]:
    """Decode a single-output Loxone statistic binary response."""
    if len(payload) > _MAX_SOURCE_BYTES:
        raise LoxoneProtocolError("Statistic response exceeds the configured limit")
    if len(payload) % _POINT.size:
        raise LoxoneProtocolError("Statistic response has a truncated entry")
    count = len(payload) // _POINT.size
    if count > maximum_points:
        raise LoxoneProtocolError("Statistic response contains too many points")
    result: list[StatisticPoint] = []
    previous = -1
    for timestamp, value in _POINT.iter_unpack(payload):
        if timestamp < previous:
            raise LoxoneProtocolError("Statistic response is not ordered")
        if timestamp > 4_102_444_800 or not math.isfinite(value):
            raise LoxoneProtocolError("Statistic response contains an invalid point")
        previous = timestamp
        result.append(StatisticPoint(timestamp=timestamp, value=value))
    return tuple(result)


class StatisticsCache:
    """Small bounded RAM cache for parsed statistic results."""

    def __init__(
        self,
        *,
        maximum_bytes: int = 128 * 1024 * 1024,
        ttl_seconds: float = 60.0,
        maximum_memory_points: int = _MAX_MEMORY_POINTS,
        maximum_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 16 * 1024 * 1024 <= maximum_bytes <= 512 * 1024 * 1024:
            raise ValueError("statistics cache size is outside the supported range")
        if maximum_memory_points < 1:
            raise ValueError("statistics memory cache point limit must be positive")
        if maximum_entries < 1:
            raise ValueError("statistics memory cache entry limit must be positive")
        self.maximum_bytes = maximum_bytes
        self.ttl_seconds = ttl_seconds
        self.maximum_memory_points = maximum_memory_points
        self.maximum_entries = maximum_entries
        self._clock = clock
        self._memory: OrderedDict[str, tuple[float, tuple[StatisticPoint, ...], int]] = (
            OrderedDict()
        )
        # Insertion/refresh expiry order is independent of access-based LRU.
        # The supplied clock, like the default, must be monotonic.
        self._expiry: OrderedDict[str, float] = OrderedDict()
        self._point_count = 0
        self._accounted_bytes = 0
        self._lock = RLock()

    def _discard(self, key: str) -> None:
        item = self._memory.pop(key, None)
        self._expiry.pop(key, None)
        if item is not None:
            self._point_count -= len(item[1])
            self._accounted_bytes -= item[2]

    def get(self, key: str) -> tuple[StatisticPoint, ...] | None:
        with self._lock:
            item = self._memory.get(key)
            if item is None:
                return None
            expires_at, value, _size = item
            if expires_at <= self._clock():
                self._discard(key)
                return None
            self._memory.move_to_end(key)
            return value

    def put(self, key: str, value: tuple[StatisticPoint, ...]) -> None:
        with self._lock:
            now = self._clock()
            while self._expiry:
                expired_key = next(iter(self._expiry))
                if self._expiry[expired_key] > now:
                    break
                self._discard(expired_key)
            if len(value) > self.maximum_memory_points:
                return
            # Charge tuple/key storage plus conservative per-entry container and
            # per-point Python-object overhead, not just 12-byte wire records.
            size = sys.getsizeof(key) + sys.getsizeof(value) + 512 + len(value) * 128
            if size > self.maximum_bytes:
                return
            self._discard(key)
            expires_at = now + self.ttl_seconds
            self._memory[key] = (expires_at, value, size)
            self._expiry[key] = expires_at
            self._point_count += len(value)
            self._accounted_bytes += size
            while (
                self._point_count > self.maximum_memory_points
                or self._accounted_bytes > self.maximum_bytes
                or len(self._memory) > self.maximum_entries
            ):
                self._discard(next(iter(self._memory)))

    @staticmethod
    def source_key(*parts: str) -> str:
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def clear(self) -> int:
        """Clear cached in-memory data."""
        with self._lock:
            memory = len(self._memory)
            self._memory.clear()
            self._expiry.clear()
            self._point_count = 0
            self._accounted_bytes = 0
        return memory
