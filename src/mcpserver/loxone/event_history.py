"""Bounded, plugin-owned event history for selected live Loxone states."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from mcpserver.config import PluginConfig
    from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
    from mcpserver.loxone.client import LoxoneClient, LoxoneToken, LoxoneWebSocketSession
    from mcpserver.loxone.models import Control, LoxoneStructure


_LOGGER = logging.getLogger("mcpserver.event_history")


_SCHEMA_VERSION: Final = 4
_MAX_TEXT_BYTES: Final = 4096
_UNSUPPORTED_SOURCE_CONTROL_TYPES: Final = frozenset({"Daytimer"})


class EventHistoryUnavailable(RuntimeError):
    """The optional local history store cannot safely answer a request."""


class _UnsupportedEventValue(EventHistoryUnavailable):
    """A configured state emitted a value the local history cannot store."""


def _storage_failure_reason(exc: EventHistoryUnavailable) -> str:
    return "size_enforcement_failed" if "size limit" in str(exc) else "store_unavailable"


class _LoxBerryCredentials(Protocol):
    async def _credentials(self) -> tuple[str, str]: ...


async def _acquire_token(client: LoxoneClient, username: str, password: str) -> LoxoneToken:
    return await client.acquire_token(username, password)


async def _open_session(client: LoxoneClient, token: LoxoneToken) -> LoxoneWebSocketSession:
    return await client.open_session(token)


@dataclass(frozen=True, slots=True)
class EventHistoryEntry:
    event_id: int
    observed_at: float
    old_value: bool | float | int | str
    new_value: bool | float | int | str


@dataclass(frozen=True, slots=True)
class EventHistoryPage:
    entries: tuple[EventHistoryEntry, ...]
    capture_started_at: float | None
    retained_from: float | None
    coverage: str
    next_event_id: int | None
    next_event_at: float | None
    has_evidence: bool
    recording_ended_at: float | None


@dataclass(frozen=True, slots=True)
class EventHistoryCoverage:
    """Bounded coverage metadata without exposing stored event values."""

    capture_started_at: float | None
    retained_from: float | None
    coverage: str
    has_events: bool


@dataclass(frozen=True, slots=True)
class EventHistorySourceSummary:
    control_uuid: str
    state_uuid: str
    event_count: int
    oldest_event_at: float | None
    newest_event_at: float | None
    capture_started_at: float | None
    coverage_ended_at: float | None
    recording_ended_at: float | None
    recent_coverage: tuple[tuple[float, float | None, str], ...]


@dataclass(frozen=True, slots=True)
class EventHistoryStoreSummary:
    measured_at: float
    database_bytes: int
    wal_bytes: int
    sources: tuple[EventHistorySourceSummary, ...]
    truncated: bool = False
    clear_generation: int = 0


def source_revision_for_snapshot(
    active_sources: tuple[tuple[str, str], ...],
    snapshot: EventHistoryStoreSummary,
    *,
    retention_days: int,
    maximum_mib: int,
) -> str:
    """Track source membership, policy, and clears without changing on each event."""
    active = set(active_sources)
    source_keys = [
        (source.control_uuid, source.state_uuid, (source.control_uuid, source.state_uuid) in active)
        for source in snapshot.sources
    ]
    document = (
        sorted(active_sources),
        source_keys,
        snapshot.truncated,
        snapshot.clear_generation,
        retention_days,
        maximum_mib,
    )
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _value(value: object) -> bool | float | int | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("event value is not finite")
        return value
    if isinstance(value, str) and len(value.encode("utf-8")) <= _MAX_TEXT_BYTES:
        return value
    raise ValueError("event value is unsupported")


class EventHistoryStore:
    """A small SQLite store with explicit retention and coverage evidence."""

    def __init__(self, path: Path, *, retention_days: int, maximum_mib: int) -> None:
        if not path.is_absolute() or path.suffix != ".sqlite3":
            raise ValueError("event history store path must be an absolute SQLite file")
        self.path = path
        self.retention_seconds = retention_days * 24 * 60 * 60
        self.maximum_bytes = maximum_mib * 1024 * 1024
        self._lock = threading.RLock()

    def _connection(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise EventHistoryUnavailable("local event history is unavailable") from exc

    @contextmanager
    def _opened(self) -> Iterator[sqlite3.Connection]:
        connection = self._connection()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in {0, 1, 2, 3, _SCHEMA_VERSION}:
                    raise EventHistoryUnavailable("local event history needs migration")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                      id INTEGER PRIMARY KEY,
                      control_uuid TEXT NOT NULL,
                      state_uuid TEXT NOT NULL,
                      observed_at REAL NOT NULL,
                      old_value TEXT NOT NULL,
                      new_value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS events_source_time
                    ON events(control_uuid, state_uuid, observed_at DESC, id DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS coverage (
                      id INTEGER PRIMARY KEY,
                      control_uuid TEXT NOT NULL,
                      state_uuid TEXT NOT NULL,
                      started_at REAL NOT NULL,
                      ended_at REAL,
                      outcome TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS removed_sources ("
                    "control_uuid TEXT NOT NULL, state_uuid TEXT NOT NULL, "
                    "removed_at REAL, PRIMARY KEY(control_uuid, state_uuid))"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS coverage_source_time "
                    "ON coverage(control_uuid, state_uuid, started_at)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS source_totals ("
                    "control_uuid TEXT NOT NULL, state_uuid TEXT NOT NULL, "
                    "event_count INTEGER NOT NULL, oldest_event_at REAL NOT NULL, "
                    "newest_event_at REAL NOT NULL, "
                    "PRIMARY KEY(control_uuid, state_uuid))"
                )
                self._ensure_history_metadata(connection)
                if version < 3:
                    self._refresh_summaries(connection)
                # A process that did not reach ``end_coverage`` must not make a
                # later request look continuously recorded across its downtime.
                connection.execute(
                    "UPDATE coverage SET ended_at = started_at, outcome = 'interrupted' "
                    "WHERE ended_at IS NULL",
                )
                connection.execute("PRAGMA user_version = 4")
                connection.execute("COMMIT")
                connection.execute("BEGIN IMMEDIATE")
                pruned = self._prune(connection, now=time.time())
                connection.execute("COMMIT")
                self._compact(connection, vacuum=pruned)
            except EventHistoryUnavailable:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc
        try:
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise EventHistoryUnavailable(
                "local event history permissions are unavailable"
            ) from exc

    @staticmethod
    def _ensure_history_metadata(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS history_metadata ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "clear_generation INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO history_metadata(id, clear_generation) VALUES (1, 0)"
        )

    def _migrate_v3_snapshot(self) -> None:
        """Upgrade the clear marker without starting recorder maintenance."""
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 3:
                    self._ensure_history_metadata(connection)
                    connection.execute("PRAGMA user_version = 4")
                elif version != _SCHEMA_VERSION:
                    raise EventHistoryUnavailable("local event history needs migration")
                connection.execute("COMMIT")
            except (EventHistoryUnavailable, sqlite3.Error) as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(exc, EventHistoryUnavailable):
                    raise
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def begin_coverage(self, sources: tuple[tuple[str, str], ...], *, started_at: float) -> None:
        if not sources:
            return
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "DELETE FROM removed_sources WHERE control_uuid = ? AND state_uuid = ?",
                    sources,
                )
                connection.executemany(
                    "INSERT INTO coverage(control_uuid, state_uuid, started_at, ended_at, outcome) "
                    "VALUES (?, ?, ?, NULL, 'active')",
                    [
                        (control_uuid, state_uuid, started_at)
                        for control_uuid, state_uuid in sources
                    ],
                )
                connection.execute("COMMIT")
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def end_coverage(
        self, sources: tuple[tuple[str, str], ...], *, ended_at: float, outcome: str
    ) -> None:
        if not sources:
            return
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "UPDATE coverage SET ended_at = ?, outcome = ? WHERE id = ("
                    "SELECT id FROM coverage WHERE control_uuid = ? AND state_uuid = ? "
                    "AND ended_at IS NULL ORDER BY id DESC LIMIT 1)",
                    [
                        (ended_at, outcome, control_uuid, state_uuid)
                        for control_uuid, state_uuid in sources
                    ],
                )
                connection.execute("COMMIT")
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def record_transition(
        self,
        control_uuid: str,
        state_uuid: str,
        *,
        observed_at: float,
        old_value: object,
        new_value: object,
    ) -> None:
        old = _value(old_value)
        new = _value(new_value)
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, "
                    "new_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        control_uuid,
                        state_uuid,
                        observed_at,
                        json.dumps(old, ensure_ascii=False, separators=(",", ":")),
                        json.dumps(new, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                connection.execute(
                    "INSERT INTO source_totals VALUES (?, ?, 1, ?, ?) "
                    "ON CONFLICT(control_uuid, state_uuid) DO UPDATE SET "
                    "event_count = event_count + 1, "
                    "oldest_event_at = MIN(oldest_event_at, excluded.oldest_event_at), "
                    "newest_event_at = MAX(newest_event_at, excluded.newest_event_at)",
                    (control_uuid, state_uuid, observed_at, observed_at),
                )
                pruned = self._prune(connection, now=observed_at)
                connection.execute("COMMIT")
                self._compact(connection, vacuum=pruned)
            except ValueError:
                raise
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def _size(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (self.path, self.path.with_suffix(".sqlite3-wal"))
            if candidate.exists()
        )

    @staticmethod
    def _refresh_summaries(connection: sqlite3.Connection) -> None:
        """Rebuild counters only during migration or actual pruning."""
        connection.execute("DELETE FROM source_totals")
        connection.execute(
            "INSERT INTO source_totals "
            "SELECT control_uuid, state_uuid, COUNT(*), MIN(observed_at), MAX(observed_at) "
            "FROM events GROUP BY control_uuid, state_uuid"
        )

    def snapshot(self, active_sources: tuple[tuple[str, str], ...]) -> EventHistoryStoreSummary:
        """Read a consistent overview without starting maintenance or creating files."""
        measured_at = time.time()
        if not self.path.exists():
            return EventHistoryStoreSummary(
                measured_at,
                0,
                0,
                tuple(
                    EventHistorySourceSummary(control, state, 0, None, None, None, None, None, ())
                    for control, state in active_sources
                ),
            )
        try:
            with closing(
                sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
            ) as db:
                db.execute("BEGIN")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 3:
                    db.execute("ROLLBACK")
                    self._migrate_v3_snapshot()
                    db.execute("BEGIN")
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                if version != _SCHEMA_VERSION:
                    raise EventHistoryUnavailable("local event history needs migration")
                totals = {
                    (row[0], row[1]): row[2:]
                    for row in db.execute(
                        "SELECT control_uuid, state_uuid, event_count, oldest_event_at, "
                        "newest_event_at FROM source_totals"
                    )
                }
                coverage = {
                    (row[0], row[1]): row[2:]
                    for row in db.execute(
                        "SELECT control_uuid, state_uuid, MIN(started_at), "
                        "MAX(ended_at) FROM coverage GROUP BY control_uuid, state_uuid"
                    )
                }
                removed = {
                    (row[0], row[1]): row[2]
                    for row in db.execute(
                        "SELECT control_uuid, state_uuid, removed_at FROM removed_sources"
                    )
                }
                clear_generation = int(
                    db.execute(
                        "SELECT clear_generation FROM history_metadata WHERE id = 1"
                    ).fetchone()[0]
                )
                keys = set(active_sources) | set(totals) | set(coverage) | set(removed)
                active_set = set(active_sources)
                selected_keys = sorted(
                    keys,
                    key=lambda key: (key not in active_set, -(removed.get(key) or 0), key),
                )[:128]
                sources = tuple(
                    EventHistorySourceSummary(
                        key[0],
                        key[1],
                        int(totals.get(key, (0, None, None))[0]),
                        totals.get(key, (0, None, None))[1],
                        totals.get(key, (0, None, None))[2],
                        coverage.get(key, (None, None))[0],
                        coverage.get(key, (None, None))[1],
                        removed.get(key),
                        tuple(
                            (float(item[0]), item[1], str(item[2]))
                            for item in db.execute(
                                "SELECT started_at, ended_at, outcome FROM coverage "
                                "WHERE control_uuid = ? AND state_uuid = ? "
                                "ORDER BY started_at DESC LIMIT 3",
                                key,
                            )
                        ),
                    )
                    for key in selected_keys
                )
            database_bytes = self.path.stat().st_size
            wal = self.path.with_suffix(".sqlite3-wal")
            wal_bytes = wal.stat().st_size if wal.exists() else 0
            return EventHistoryStoreSummary(
                time.time(),
                database_bytes,
                wal_bytes,
                sources,
                len(keys) > len(selected_keys),
                clear_generation,
            )
        except (OSError, sqlite3.Error) as exc:
            raise EventHistoryUnavailable("local event history is unavailable") from exc

    @staticmethod
    def _used_database_bytes(connection: sqlite3.Connection) -> int:
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        return (int(page_count) - int(free_pages)) * int(page_size)

    def _prune(self, connection: sqlite3.Connection, *, now: float) -> bool:
        cutoff = now - self.retention_seconds
        event_deletions = connection.execute(
            "DELETE FROM events WHERE observed_at < ?", (cutoff,)
        ).rowcount
        deleted = event_deletions
        connection.execute(
            "UPDATE coverage SET started_at = ? WHERE started_at < ? "
            "AND (ended_at IS NULL OR ended_at > ?)",
            (cutoff, cutoff, cutoff),
        )
        deleted += connection.execute(
            "DELETE FROM coverage WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,)
        ).rowcount
        while self._used_database_bytes(connection) > self.maximum_bytes:
            evicted = connection.execute(
                "SELECT control_uuid, state_uuid, MAX(observed_at) FROM events WHERE id IN "
                "(SELECT id FROM events ORDER BY observed_at, id LIMIT 256) "
                "GROUP BY control_uuid, state_uuid"
            ).fetchall()
            removed = connection.execute(
                "DELETE FROM events WHERE id IN "
                "(SELECT id FROM events ORDER BY observed_at, id LIMIT 256)"
            ).rowcount
            if removed <= 0:
                removed = connection.execute(
                    "DELETE FROM coverage WHERE id IN "
                    "(SELECT id FROM coverage WHERE ended_at IS NOT NULL "
                    "ORDER BY ended_at, id LIMIT 256)"
                ).rowcount
                if removed <= 0:
                    break
            elif removed:
                event_deletions += removed
            deleted += removed
            for control_uuid, state_uuid, observed_at in evicted:
                boundary = math.nextafter(float(observed_at), math.inf)
                connection.execute(
                    "UPDATE coverage SET started_at = ? WHERE control_uuid = ? "
                    "AND state_uuid = ? AND started_at < ? "
                    "AND (ended_at IS NULL OR ended_at > ?)",
                    (boundary, control_uuid, state_uuid, boundary, boundary),
                )
        deleted += connection.execute(
            "DELETE FROM removed_sources WHERE NOT EXISTS ("
            "SELECT 1 FROM events WHERE events.control_uuid = removed_sources.control_uuid "
            "AND events.state_uuid = removed_sources.state_uuid) AND NOT EXISTS ("
            "SELECT 1 FROM coverage WHERE coverage.control_uuid = removed_sources.control_uuid "
            "AND coverage.state_uuid = removed_sources.state_uuid)"
        ).rowcount
        if event_deletions:
            self._refresh_summaries(connection)
        return deleted > 0

    def mark_removed(self, control_uuid: str, state_uuid: str, *, removed_at: float | None) -> None:
        with self._lock, self._opened() as connection:
            try:
                connection.execute(
                    "INSERT INTO removed_sources (control_uuid, state_uuid, removed_at) "
                    "SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM events WHERE control_uuid = ? "
                    "AND state_uuid = ?) OR EXISTS (SELECT 1 FROM coverage WHERE control_uuid = ? "
                    "AND state_uuid = ?) ON CONFLICT(control_uuid, state_uuid) "
                    "DO UPDATE SET removed_at = "
                    "COALESCE(removed_sources.removed_at, excluded.removed_at)",
                    (
                        control_uuid,
                        state_uuid,
                        removed_at,
                        control_uuid,
                        state_uuid,
                        control_uuid,
                        state_uuid,
                    ),
                )
            except sqlite3.Error as exc:
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def purge_source(self, control_uuid: str, state_uuid: str) -> tuple[int, int]:
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                events = connection.execute(
                    "DELETE FROM events WHERE control_uuid = ? AND state_uuid = ?",
                    (control_uuid, state_uuid),
                ).rowcount
                coverage = connection.execute(
                    "DELETE FROM coverage WHERE control_uuid = ? AND state_uuid = ?",
                    (control_uuid, state_uuid),
                ).rowcount
                connection.execute(
                    "DELETE FROM removed_sources WHERE control_uuid = ? AND state_uuid = ?",
                    (control_uuid, state_uuid),
                )
                connection.execute(
                    "DELETE FROM source_totals WHERE control_uuid = ? AND state_uuid = ?",
                    (control_uuid, state_uuid),
                )
                connection.execute("COMMIT")
                self._compact(connection, vacuum=bool(events or coverage))
                return events, coverage
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def _compact(self, connection: sqlite3.Connection, *, vacuum: bool) -> None:
        """Reclaim SQLite and WAL pages after bounded logical pruning."""
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if vacuum or self._size() > self.maximum_bytes:
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if self._size() > self.maximum_bytes:
                raise EventHistoryUnavailable("local event history size limit cannot be enforced")
        except (sqlite3.Error, OSError) as exc:
            raise EventHistoryUnavailable("local event history maintenance is unavailable") from exc

    def page(
        self,
        control_uuid: str,
        state_uuid: str,
        *,
        start: float,
        end: float,
        limit: int,
        before: tuple[float, int] | None = None,
    ) -> EventHistoryPage:
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                pruned = self._prune(connection, now=time.time())
                connection.execute("COMMIT")
                self._compact(connection, vacuum=pruned)
                coverage_rows = connection.execute(
                    "SELECT started_at, ended_at FROM coverage WHERE control_uuid = ? "
                    "AND state_uuid = ? "
                    "AND started_at <= ? AND COALESCE(ended_at, ?) >= ? ORDER BY started_at",
                    (control_uuid, state_uuid, end, time.time(), start),
                ).fetchall()
                capture = connection.execute(
                    "SELECT MIN(started_at) FROM coverage WHERE control_uuid = ? "
                    "AND state_uuid = ?",
                    (control_uuid, state_uuid),
                ).fetchone()[0]
                retained = connection.execute(
                    "SELECT MIN(observed_at) FROM events WHERE control_uuid = ? AND state_uuid = ?",
                    (control_uuid, state_uuid),
                ).fetchone()[0]
                removed = connection.execute(
                    "SELECT removed_at FROM removed_sources WHERE control_uuid = ? "
                    "AND state_uuid = ?",
                    (control_uuid, state_uuid),
                ).fetchone()
                has_evidence = retained is not None or capture is not None
                query = (
                    "SELECT id, observed_at, old_value, new_value FROM events "
                    "WHERE control_uuid = ? AND state_uuid = ? AND observed_at >= ? "
                    "AND observed_at <= ?"
                )
                parameters: list[object] = [control_uuid, state_uuid, start, end]
                if before is not None:
                    query += " AND (observed_at < ? OR (observed_at = ? AND id < ?))"
                    parameters.extend((before[0], before[0], before[1]))
                query += " ORDER BY observed_at DESC, id DESC LIMIT ?"
                parameters.append(limit + 1)
                rows = connection.execute(query, parameters).fetchall()
            except sqlite3.Error as exc:
                raise EventHistoryUnavailable("local event history is unavailable") from exc
        selected = rows[:limit]
        entries = tuple(
            EventHistoryEntry(row[0], row[1], json.loads(row[2]), json.loads(row[3]))
            for row in selected
        )
        coverage = self._coverage_status(coverage_rows, start=start, end=end, now=time.time())
        return EventHistoryPage(
            entries=entries,
            capture_started_at=capture,
            retained_from=retained,
            coverage=coverage,
            next_event_id=selected[-1][0] if len(rows) > limit else None,
            next_event_at=selected[-1][1] if len(rows) > limit else None,
            has_evidence=has_evidence,
            recording_ended_at=removed[0] if removed is not None else None,
        )

    @staticmethod
    def _coverage_status(
        coverage_rows: list[tuple[float, float | None]], *, start: float, end: float, now: float
    ) -> str:
        if not coverage_rows:
            return "not_recorded"
        covered_until = start
        for started_at, ended_at in coverage_rows:
            if started_at > covered_until:
                break
            covered_until = max(covered_until, min(end, now) if ended_at is None else ended_at)
            if covered_until >= end:
                break
        return "complete" if covered_until >= end else "partial_coverage"

    def coverage_many(
        self, sources: tuple[tuple[str, str], ...], *, start: float, end: float
    ) -> dict[tuple[str, str], EventHistoryCoverage]:
        """Return coverage evidence for configured sources in one bounded SQLite operation."""

        if not sources:
            return {}
        now = time.time()
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                pruned = self._prune(connection, now=now)
                connection.execute("COMMIT")
                self._compact(connection, vacuum=pruned)
                result = {}
                for control_uuid, state_uuid in sources:
                    coverage_rows = connection.execute(
                        "SELECT started_at, ended_at FROM coverage WHERE control_uuid = ? "
                        "AND state_uuid = ? "
                        "AND started_at <= ? AND COALESCE(ended_at, ?) >= ? ORDER BY started_at",
                        (control_uuid, state_uuid, end, now, start),
                    ).fetchall()
                    capture = connection.execute(
                        "SELECT MIN(started_at) FROM coverage WHERE control_uuid = ? "
                        "AND state_uuid = ?",
                        (control_uuid, state_uuid),
                    ).fetchone()[0]
                    retained = connection.execute(
                        "SELECT MIN(observed_at) FROM events WHERE control_uuid = ? "
                        "AND state_uuid = ?",
                        (control_uuid, state_uuid),
                    ).fetchone()[0]
                    has_events = connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM events WHERE control_uuid = ? "
                        "AND state_uuid = ? AND observed_at >= ? AND observed_at <= ?)",
                        (control_uuid, state_uuid, start, end),
                    ).fetchone()[0]
                    result[control_uuid, state_uuid] = EventHistoryCoverage(
                        capture_started_at=capture,
                        retained_from=retained,
                        coverage=self._coverage_status(
                            coverage_rows, start=start, end=end, now=now
                        ),
                        has_events=bool(has_events),
                    )
                return result
            except sqlite3.Error as exc:
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def clear(self) -> int:
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                connection.execute("DELETE FROM events")
                connection.execute("DELETE FROM coverage")
                connection.execute("DELETE FROM removed_sources")
                connection.execute("DELETE FROM source_totals")
                connection.execute(
                    "UPDATE history_metadata SET clear_generation = clear_generation + 1 "
                    "WHERE id = 1"
                )
                connection.execute("COMMIT")
                return int(count)
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc


def _controls(items: tuple[Control, ...]) -> tuple[Control, ...]:
    result: list[Control] = []
    pending = list(items)
    while pending:
        control = pending.pop()
        result.append(control)
        pending.extend(control.subcontrols)
    return tuple(result)


class EventHistoryMonitor:
    """Use the LoxBerry-owned identity to record only explicitly selected states."""

    def __init__(
        self,
        config: PluginConfig,
        store: EventHistoryStore,
        credentials: _LoxBerryCredentials,
        auth_coordinator: MiniserverAuthCoordinator | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.credentials = credentials
        self.auth_coordinator = auth_coordinator
        self._task: asyncio.Task[None] | None = None
        self.status = "disabled" if not config.event_history_enabled else "unknown"
        self.status_reason: str | None = None
        self.status_observed_at = time.time()
        self.capture_started_at: float | None = None

    def _set_status(self, status: str, reason: str | None = None) -> None:
        self.status = status
        self.status_reason = reason
        self.status_observed_at = time.time()

    def runtime_status(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.status_reason,
            "observed_at": time.time(),
            "state_changed_at": self.status_observed_at,
            "capture_started_at": self.capture_started_at,
        }

    @property
    def sources(self) -> tuple[tuple[str, str], ...]:
        return self.config.event_history_sources

    async def start(self) -> None:
        if not self.config.event_history_enabled:
            return
        try:
            await asyncio.to_thread(self.store.initialize)
        except EventHistoryUnavailable as exc:
            self._set_status(
                "unavailable",
                _storage_failure_reason(exc),
            )
            _LOGGER.warning("component=event_history outcome=store_unavailable")
            return
        if not self.sources:
            self._set_status("unavailable", "no_sources")
            return
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        while True:
            token = None
            session = None
            active: tuple[tuple[str, str], ...] = ()
            coverage_active = False
            try:
                await asyncio.to_thread(self.store.initialize)
                username, password = await self.credentials._credentials()
                from mcpserver.loxone.client import LoxoneClient

                client = LoxoneClient(
                    MiniserverEndpoint.parse(self.config.loxone_endpoint),
                    client_uuid=uuid5(
                        NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/event-history"
                    ),
                    timeout_seconds=self.config.connection_timeout,
                )
                if self.auth_coordinator is None:
                    token = await client.acquire_token(username, password)
                    session = await client.open_session(token)
                else:
                    acquired_token = await self.auth_coordinator.attempt(
                        partial(_acquire_token, client, username, password),
                        owner="runtime_event_stream",
                        phase="token_acquisition",
                    )
                    token = acquired_token
                    opened_session = await self.auth_coordinator.attempt(
                        partial(_open_session, client, acquired_token),
                        owner="runtime_event_stream",
                        phase="session_establishment",
                    )
                    session = opened_session
                structure = await session.load_structure()
                visible = {
                    (control.uuid, state_uuid)
                    for control in _controls(structure.controls)
                    for _state_name, state_uuid in control.state_uuids
                }
                active = tuple(source for source in self.sources if source in visible)
                if not active:
                    self._set_status("unavailable", "no_visible_sources")
                    _LOGGER.warning("component=event_history outcome=no_configured_sources_visible")
                    await asyncio.sleep(60)
                    continue
                state_sources = {
                    state_uuid: (control_uuid, state_uuid) for control_uuid, state_uuid in active
                }
                baselines: dict[str, object] = {}
                async for batch in session.state_events():
                    observed_at = time.time()
                    for event in batch:
                        source = state_sources.get(event.uuid)
                        if source is None:
                            continue
                        try:
                            value = _value(event.value)
                        except ValueError as exc:
                            raise _UnsupportedEventValue(
                                "configured state does not produce a supported scalar value"
                            ) from exc
                        if not coverage_active:
                            baselines[event.uuid] = value
                            if len(baselines) == len(active):
                                started_at = observed_at
                                await asyncio.to_thread(
                                    self.store.begin_coverage, active, started_at=started_at
                                )
                                self.capture_started_at = started_at
                                self._set_status("recording")
                                coverage_active = True
                            continue
                        previous = baselines[event.uuid]
                        if previous == value:
                            continue
                        try:
                            await asyncio.to_thread(
                                self.store.record_transition,
                                source[0],
                                source[1],
                                observed_at=observed_at,
                                old_value=previous,
                                new_value=value,
                            )
                        except ValueError as exc:
                            raise _UnsupportedEventValue(
                                "configured state does not produce a supported scalar value"
                            ) from exc
                        baselines[event.uuid] = value
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if isinstance(exc, _UnsupportedEventValue):
                    reason = "unsupported_value"
                elif isinstance(exc, EventHistoryUnavailable):
                    reason = _storage_failure_reason(exc)
                else:
                    reason = "subscription_unavailable"
                self._set_status("unavailable", reason)
                _LOGGER.warning(
                    "component=event_history outcome=%s error_type=%s",
                    reason,
                    type(exc).__name__,
                )
                if coverage_active:
                    with suppress(EventHistoryUnavailable):
                        await asyncio.to_thread(
                            self.store.end_coverage,
                            active,
                            ended_at=time.time(),
                            outcome="disconnected",
                        )
                    coverage_active = False
                await asyncio.sleep(5)
            finally:
                if coverage_active:
                    with suppress(EventHistoryUnavailable):
                        await asyncio.to_thread(
                            self.store.end_coverage,
                            active,
                            ended_at=time.time(),
                            outcome="disconnected",
                        )
                if session is not None:
                    await session.close()
                if token is not None:
                    token.destroy()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def visible_structure(self) -> LoxoneStructure:
        """Load one current service-owned structure for selection and validation."""
        from mcpserver.loxone.client import MiniserverEndpoint

        token = None
        session = None
        try:
            username, password = await self.credentials._credentials()
            from mcpserver.loxone.client import LoxoneClient

            client = LoxoneClient(
                MiniserverEndpoint.parse(self.config.loxone_endpoint),
                client_uuid=uuid5(
                    NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/event-history"
                ),
                timeout_seconds=self.config.connection_timeout,
            )
            if self.auth_coordinator is None:
                token = await client.acquire_token(username, password)
                session = await client.open_session(token)
            else:
                acquired_token = await self.auth_coordinator.attempt(
                    partial(_acquire_token, client, username, password),
                    owner="local_admin",
                    phase="token_acquisition",
                    allow_cooldown_probe=False,
                )
                token = acquired_token
                opened_session = await self.auth_coordinator.attempt(
                    partial(_open_session, client, acquired_token),
                    owner="local_admin",
                    phase="session_establishment",
                    allow_cooldown_probe=False,
                )
                session = opened_session
            return await session.load_structure()
        finally:
            if session is not None:
                await session.close()
            if token is not None:
                token.destroy()

    async def visible_controls(self) -> tuple[Control, ...]:
        """Return only visible controls from a current authorized structure."""
        return _controls((await self.visible_structure()).controls)

    async def validate_source(self, control_uuid: str, state_uuid: str) -> tuple[str, str, str]:
        """Resolve one exact source through current service-owned visibility."""
        controls = await self.visible_controls()
        control = next((item for item in controls if item.uuid == control_uuid), None)
        if control is None:
            raise ValueError("configured control is not visible to the service identity")
        if control.control_type in _UNSUPPORTED_SOURCE_CONTROL_TYPES:
            raise ValueError("configured control has no supported scalar event states")
        state_name = next((name for name, uuid in control.state_uuids if uuid == state_uuid), None)
        if state_name is None:
            raise ValueError("configured state does not belong to the visible control")
        return control.name, control.control_type, state_name

    async def update_config(self, config: PluginConfig) -> None:
        """Apply a persisted source update by recreating only this optional subscription."""
        await self.close()
        self.config = config
        self._set_status("unknown" if config.event_history_enabled else "disabled")
        self.capture_started_at = None
        await self.start()
