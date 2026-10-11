"""Bounded read-only metadata projection; callers retain project authorization."""

from __future__ import annotations

import copy
import json
import sqlite3
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from stat import S_ISREG
from sys import getsizeof
from threading import RLock
from typing import Any

from .model import KnxError, metadata
from .read_model import details, query_filters, query_sql
from .store import KnxStore

MAX_CACHE_BYTES = 16 * 1024 * 1024
_BATCH = 100


def _owned_size(value: object) -> int:
    size = getsizeof(value)
    if isinstance(value, dict):
        size += sum(_owned_size(k) + _owned_size(v) for k, v in value.items())
    elif isinstance(value, list | tuple):
        size += sum(_owned_size(v) for v in value)
    return size


class ProjectMetadata:
    """One service-owned LRU; misses are batched, including negative results."""

    def __init__(self, path: Path, *, max_bytes: int = MAX_CACHE_BYTES) -> None:
        self.store = KnxStore(path)
        self.cache: OrderedDict[tuple[str, int, int], tuple[dict[str, Any] | None, int]] = (
            OrderedDict()
        )
        self.cache_bytes = 0
        self._lock = RLock()
        self._observed_database = False
        self.max_bytes = max(
            0,
            min(max_bytes, MAX_CACHE_BYTES)
            - getsizeof(self)
            - getsizeof(self.cache)
            - getsizeof(self._lock),
        )

    def _exists(self) -> bool:
        try:
            mode = self.store.path.stat(follow_symlinks=False).st_mode
        except FileNotFoundError:
            if self._observed_database:
                raise KnxError("knx_storage_failed") from None
            return False
        except OSError:
            raise KnxError("knx_storage_failed") from None
        if not S_ISREG(mode):
            raise KnxError("knx_storage_invalid")
        self._observed_database = True
        return True

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Setup failures belong to storage, never to Loxone authentication."""
        try:
            with self.store.connection() as db:
                yield db
        except (OSError, sqlite3.Error):
            raise KnxError("knx_storage_failed") from None

    def revision(self, target: str) -> int:
        revision = 0
        if self._exists():
            with self._connection() as db:
                revision = self.store.revision(db, target)
        with self._lock:
            for key in tuple(self.cache):
                if key[0] == target and key[1] != revision:
                    self.cache_bytes -= self.cache.pop(key)[1]
        return revision

    def search(self, target: str, revision: int, query: str) -> frozenset[int]:
        if not self._exists():
            if revision:
                raise KnxError("knx_revision_conflict")
            return frozenset()
        # Public project search permits 200 characters; local UI permits 128.
        where, arguments = query_sql(query_filters({"query": query}, query_limit=200))
        with self._connection() as db:
            db.execute("BEGIN")
            self.store.check(db, target, revision)
            return frozenset(
                row[0]
                for row in db.execute(
                    "SELECT a.address FROM addresses AS a WHERE a.target=?" + where,
                    [target, *arguments],
                )
            )

    def lookup(self, target: str, revision: int, numbers: set[int]) -> dict[int, Any]:
        if len(numbers) > _BATCH or any(type(n) is not int or not 0 <= n <= 65535 for n in numbers):
            raise KnxError("knx_page_invalid")
        if not self._exists():
            if revision:
                raise KnxError("knx_revision_conflict")
            return {}
        with self._lock, self._connection() as db:
            db.execute("BEGIN")
            self.store.check(db, target, revision)
            result: dict[int, Any] = {}
            missing = []
            for number in numbers:
                key = (target, revision, number)
                cached = self.cache.get(key)
                if cached is None:
                    missing.append(number)
                else:
                    self.cache.move_to_end(key)
                    if cached[0] is not None:
                        result[number] = copy.deepcopy(cached[0])
            fetched: dict[int, Any] = {}
            if missing:
                rows = db.execute(
                    "SELECT a.address,a.imported,a.overrides,a.original,a.format,"
                    "json_extract(s.source,'$.file_format'),"
                    "json_extract(s.source,'$.imported_at'),"
                    "json_extract(s.source,'$.digest') FROM addresses AS a "
                    "LEFT JOIN ets_sources AS s ON s.target=a.target AND s.address=a.address "
                    "WHERE a.target=? AND a.address IN (" + ",".join("?" for _ in missing) + ")",
                    [target, *missing],
                )
                for (
                    number,
                    raw,
                    manual,
                    original,
                    address_format,
                    file_format,
                    imported_at,
                    digest,
                ) in rows:
                    try:
                        imported, overrides = (
                            metadata(json.loads(raw)),
                            metadata(json.loads(manual)),
                        )
                    except (KnxError, ValueError, TypeError):
                        raise KnxError("knx_storage_failed") from None
                    source = {
                        "file_format": file_format,
                        "imported_at": imported_at,
                        "digest": digest,
                    }
                    fetched[number] = {
                        "revision": revision,
                        "address": original,
                        "address_format": address_format,
                        "imported": imported,
                        "manual": overrides,
                        "import_info": {
                            key: source[key]
                            for key in ("file_format", "imported_at", "digest")
                            if source[key] is not None
                        },
                        **details(imported, overrides),
                    }
                for number in missing:
                    value = fetched.get(number)
                    key = (target, revision, number)
                    # Conservative per-entry dictionary/LRU overhead is included.
                    size = _owned_size(key) + _owned_size(value) + 256
                    if size <= self.max_bytes:
                        while self.cache and self.cache_bytes + size > self.max_bytes:
                            self.cache_bytes -= self.cache.popitem(last=False)[1][1]
                        self.cache[key] = (value, size)
                        self.cache_bytes += size
                result.update(copy.deepcopy(fetched))
            return result

    def selected_labels(self, target: str, revision: int) -> list[dict[str, str]]:
        if not self._exists():
            if revision:
                raise KnxError("knx_revision_conflict")
            return []
        with self._connection() as db:
            db.execute("BEGIN")
            self.store.check(db, target, revision)
            return [
                {"address_format": fmt, "prefix": prefix, "label": json.loads(fields)["name"]}
                for fmt, prefix, fields in db.execute(
                    "SELECT format,prefix,fields FROM import_groups "
                    "WHERE target=? AND selected=1 ORDER BY format,prefix LIMIT 129",
                    (target,),
                )
            ]
