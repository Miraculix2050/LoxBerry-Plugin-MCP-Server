"""Bounded shared results and private cursor leases; never authorization."""

import asyncio
import secrets
from collections import OrderedDict


class ProjectResultCache[T]:
    """Owners must independently authorize before reading or publishing results."""

    def __init__(
        self, *, max_entries: int, max_bytes: int, max_leases: int, ttl: int = 300
    ) -> None:
        if min(max_entries, max_bytes, max_leases, ttl) <= 0:
            raise ValueError("project result cache bounds must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_leases = max_leases
        self.ttl = ttl
        self.entries: OrderedDict[str, tuple[float, T, int]] = OrderedDict()
        self.leases: OrderedDict[str, tuple[float, str, str]] = OrderedDict()
        self.locks = tuple(asyncio.Lock() for _ in range(16))
        self.cache_bytes = 0

    def prune(self, now: float) -> None:
        for key, (expires, _value, size) in tuple(self.entries.items()):
            if expires <= now:
                self.entries.pop(key)
                self.cache_bytes -= size
        for key, (expires, result_key, _scope) in tuple(self.leases.items()):
            if expires <= now or result_key not in self.entries:
                self.leases.pop(key)

    def cursor_scope(self, lease_key: str, result_key: str, *, continuation: bool) -> str:
        lease = self.leases.get(lease_key)
        if lease is not None and lease[1] == result_key:
            return lease[2]
        if continuation:
            raise ValueError("cursor has expired; start a new query")
        return lease_key + ":" + secrets.token_hex(16)

    def get(self, result_key: str) -> tuple[float, T, int] | None:
        return self.entries.get(result_key)

    def touch(self, result_key: str) -> None:
        # Another key can evict this entry during the owner's authorization await.
        if result_key in self.entries:
            self.entries.move_to_end(result_key)

    def put(self, result_key: str, result: T, *, expires: float, size: int) -> None:
        if size < 0 or size > self.max_bytes:
            raise ValueError("project result exceeds the cache bound")
        previous = self.entries.pop(result_key, None)
        if previous is not None:
            self.cache_bytes -= previous[2]
        self.entries[result_key] = (expires, result, size)
        self.cache_bytes += size
        while len(self.entries) > self.max_entries or self.cache_bytes > self.max_bytes:
            _key, (_expires, _value, removed) = self.entries.popitem(last=False)
            self.cache_bytes -= removed
        self._drop_missing_leases()

    def bind(self, lease_key: str, result_key: str, scope: str, *, expires: float) -> None:
        entry = self.entries.get(result_key)
        if entry is None:
            self.leases.pop(lease_key, None)
            return
        self.leases[lease_key] = (min(expires, entry[0]), result_key, scope)
        self.leases.move_to_end(lease_key)
        while len(self.leases) > self.max_leases:
            self.leases.popitem(last=False)
        self._drop_missing_leases()

    def _drop_missing_leases(self) -> None:
        for key, (_expires, result_key, _scope) in tuple(self.leases.items()):
            if result_key not in self.entries:
                self.leases.pop(key)
