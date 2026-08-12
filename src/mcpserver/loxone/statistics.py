"""Bounded statistic parsing and disposable plugin-owned caching."""

from __future__ import annotations

import gzip
import hashlib
import math
import os
import re
import secrets
import stat
import struct
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final

from mcpserver.loxone.events import LoxoneProtocolError

_POINT: Final = struct.Struct("<Id")
_MAX_SOURCE_BYTES: Final = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StatisticPoint:
    timestamp: int
    value: float


@dataclass(frozen=True, slots=True)
class CacheClearResult:
    memory_entries_removed: int
    persistent_entries_removed: int
    bytes_freed: int


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
    """Small RAM result cache plus an optional private compressed source cache."""

    def __init__(
        self,
        directory: Path | None,
        *,
        maximum_bytes: int = 128 * 1024 * 1024,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if directory is not None and not directory.is_absolute():
            raise ValueError("statistics cache path must be absolute")
        if not 16 * 1024 * 1024 <= maximum_bytes <= 512 * 1024 * 1024:
            raise ValueError("statistics cache size is outside the supported range")
        self.directory = directory
        self.maximum_bytes = maximum_bytes
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._memory: OrderedDict[str, tuple[float, tuple[StatisticPoint, ...]]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> tuple[StatisticPoint, ...] | None:
        with self._lock:
            item = self._memory.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= self._clock():
                self._memory.pop(key, None)
                return None
            self._memory.move_to_end(key)
            return value

    def put(self, key: str, value: tuple[StatisticPoint, ...]) -> None:
        with self._lock:
            self._memory[key] = (self._clock() + self.ttl_seconds, value)
            self._memory.move_to_end(key)
            while len(self._memory) > 128:
                self._memory.popitem(last=False)

    @staticmethod
    def source_key(*parts: str) -> str:
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def put_legacy_source(self, key: str, payload: bytes) -> None:
        """Persist only an already validated legacy source blob."""
        if (
            self.directory is None
            or len(payload) > _MAX_SOURCE_BYTES
            or re.fullmatch(r"[0-9a-f]{64}", key) is None
        ):
            return
        with self._lock:
            if self.directory.exists() and (
                self.directory.is_symlink() or not self.directory.is_dir()
            ):
                return
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.directory.is_symlink() or not self.directory.is_dir():
                return
            os.chmod(self.directory, 0o700)
            target = self.directory / f"{key}.gz"
            temporary = self.directory / f".{key}.{secrets.token_hex(8)}.tmp"
            try:
                with gzip.open(temporary, "wb", compresslevel=6) as handle:
                    handle.write(payload)
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
                self._trim()
            finally:
                temporary.unlink(missing_ok=True)

    def _entries(self) -> list[tuple[Path, os.stat_result]]:
        if self.directory is None or not self.directory.exists() or self.directory.is_symlink():
            return []
        result: list[tuple[Path, os.stat_result]] = []
        for path in self.directory.iterdir():
            try:
                metadata = path.lstat()
            except OSError:
                continue
            if path.suffix == ".gz" and stat.S_ISREG(metadata.st_mode) and not path.is_symlink():
                result.append((path, metadata))
        return result

    def _trim(self) -> None:
        entries = self._entries()
        total = sum(metadata.st_size for _path, metadata in entries)
        for path, metadata in sorted(entries, key=lambda item: item[1].st_atime):
            if total <= self.maximum_bytes:
                break
            path.unlink(missing_ok=True)
            total -= metadata.st_size

    def clear(self) -> CacheClearResult:
        with self._lock:
            memory = len(self._memory)
            self._memory.clear()
            entries = self._entries()
            removed = 0
            freed = 0
            for path, metadata in entries:
                try:
                    path.unlink()
                except OSError:
                    continue
                removed += 1
                freed += metadata.st_size
            return CacheClearResult(memory, removed, freed)
