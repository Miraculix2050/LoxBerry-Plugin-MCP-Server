"""Bounded, plugin-owned event history for selected live Loxone states."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from mcpserver.config import PluginConfig
    from mcpserver.loxone.models import Control


_LOGGER = logging.getLogger("mcpserver.event_history")


_SCHEMA_VERSION: Final = 1
_MAX_TEXT_BYTES: Final = 4096
_UNSUPPORTED_SOURCE_CONTROL_TYPES: Final = frozenset({"Daytimer"})


class EventHistoryUnavailable(RuntimeError):
    """The optional local history store cannot safely answer a request."""


class _LoxBerryCredentials(Protocol):
    async def _credentials(self) -> tuple[str, str]: ...


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
        except sqlite3.Error as exc:
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
                if version not in {0, _SCHEMA_VERSION}:
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
                # A process that did not reach ``end_coverage`` must not make a
                # later request look continuously recorded across its downtime.
                connection.execute(
                    "UPDATE coverage SET ended_at = started_at, outcome = 'interrupted' "
                    "WHERE ended_at IS NULL",
                )
                connection.execute("PRAGMA user_version = 1")
                connection.execute("COMMIT")
                self._compact(connection, vacuum=self._prune(connection, now=time.time()))
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

    def begin_coverage(self, sources: tuple[tuple[str, str], ...], *, started_at: float) -> None:
        if not sources:
            return
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
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
                pruned = self._prune(connection, now=observed_at)
                connection.execute("COMMIT")
                self._compact(connection, vacuum=pruned)
            except ValueError:
                raise
            except sqlite3.Error as exc:
                connection.execute("ROLLBACK")
                raise EventHistoryUnavailable("local event history is unavailable") from exc

    def _size(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (self.path, self.path.with_suffix(".sqlite3-wal"))
            if candidate.exists()
        )

    @staticmethod
    def _used_database_bytes(connection: sqlite3.Connection) -> int:
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        return (int(page_count) - int(free_pages)) * int(page_size)

    def _prune(self, connection: sqlite3.Connection, *, now: float) -> bool:
        cutoff = now - self.retention_seconds
        deleted = connection.execute("DELETE FROM events WHERE observed_at < ?", (cutoff,)).rowcount
        if deleted:
            connection.execute(
                "UPDATE coverage SET started_at = ? WHERE started_at < ?", (cutoff, cutoff)
            )
        deleted += connection.execute(
            "DELETE FROM coverage WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,)
        ).rowcount
        while self._used_database_bytes(connection) > self.maximum_bytes:
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
            deleted += removed
            connection.execute(
                "UPDATE coverage SET started_at = ? WHERE started_at < ?", (now, now)
            )
        return deleted > 0

    def _compact(self, connection: sqlite3.Connection, *, vacuum: bool) -> None:
        """Reclaim SQLite and WAL pages after bounded logical pruning."""
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if vacuum or self._size() > self.maximum_bytes:
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise EventHistoryUnavailable("local event history maintenance is unavailable") from exc
        if self._size() > self.maximum_bytes:
            raise EventHistoryUnavailable("local event history size limit cannot be enforced")

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
                self._compact(connection, vacuum=self._prune(connection, now=time.time()))
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
        if not coverage_rows:
            coverage = "not_recorded"
        else:
            covered_until = start
            for started_at, ended_at in coverage_rows:
                if started_at > covered_until:
                    break
                covered_until = max(
                    covered_until, min(end, time.time()) if ended_at is None else ended_at
                )
                if covered_until >= end:
                    break
            coverage = "complete" if covered_until >= end else "partial_coverage"
        return EventHistoryPage(
            entries=entries,
            capture_started_at=capture,
            retained_from=retained,
            coverage=coverage,
            next_event_id=selected[-1][0] if len(rows) > limit else None,
            next_event_at=selected[-1][1] if len(rows) > limit else None,
        )

    def clear(self) -> int:
        with self._lock, self._opened() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                connection.execute("DELETE FROM events")
                connection.execute("DELETE FROM coverage")
                connection.execute("COMMIT")
                return int(count)
            except sqlite3.Error as exc:
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
        self, config: PluginConfig, store: EventHistoryStore, credentials: _LoxBerryCredentials
    ) -> None:
        self.config = config
        self.store = store
        self.credentials = credentials
        self._task: asyncio.Task[None] | None = None
        self.status = "disabled" if not config.event_history_enabled else "unknown"
        self.capture_started_at: float | None = None

    @property
    def sources(self) -> tuple[tuple[str, str], ...]:
        return self.config.event_history_sources

    async def start(self) -> None:
        if not self.config.event_history_enabled:
            return
        try:
            await asyncio.to_thread(self.store.initialize)
        except EventHistoryUnavailable:
            self.status = "unavailable"
            _LOGGER.warning("component=event_history outcome=store_unavailable")
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
                username, password = await self.credentials._credentials()
                from mcpserver.loxone.client import LoxoneClient

                client = LoxoneClient(
                    MiniserverEndpoint.parse(self.config.loxone_endpoint),
                    client_uuid=uuid5(
                        NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/event-history"
                    ),
                    timeout_seconds=self.config.connection_timeout,
                )
                token = await client.acquire_token(username, password)
                session = await client.open_session(token)
                structure = await session.load_structure()
                visible = {
                    (control.uuid, state_uuid)
                    for control in _controls(structure.controls)
                    for _state_name, state_uuid in control.state_uuids
                }
                active = tuple(source for source in self.sources if source in visible)
                if not active:
                    self.status = "unavailable"
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
                            self.status = "unavailable"
                            raise EventHistoryUnavailable(
                                "configured state does not produce a supported scalar value"
                            ) from exc
                        previous = baselines.get(event.uuid)
                        if event.uuid not in baselines:
                            baselines[event.uuid] = value
                            continue
                        if not coverage_active:
                            continue
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
                            raise EventHistoryUnavailable(
                                "configured state does not produce a supported scalar value"
                            ) from exc
                        baselines[event.uuid] = value
                    if not coverage_active and len(baselines) == len(active):
                        started_at = observed_at
                        await asyncio.to_thread(
                            self.store.begin_coverage, active, started_at=started_at
                        )
                        self.capture_started_at = started_at
                        self.status = "recording"
                        coverage_active = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = "unavailable"
                _LOGGER.warning(
                    "component=event_history outcome=subscription_unavailable error_type=%s",
                    type(exc).__name__,
                )
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

    async def validate_source(self, control_uuid: str, state_uuid: str) -> tuple[str, str, str]:
        """Resolve one source through the service-owned identity before enabling capture."""
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
            token = await client.acquire_token(username, password)
            session = await client.open_session(token)
            structure = await session.load_structure()
            control = next(
                (item for item in _controls(structure.controls) if item.uuid == control_uuid), None
            )
            if control is None:
                raise ValueError("configured control is not visible to the service identity")
            if control.control_type in _UNSUPPORTED_SOURCE_CONTROL_TYPES:
                raise ValueError("configured control has no supported scalar event states")
            state_name = next(
                (name for name, uuid in control.state_uuids if uuid == state_uuid), None
            )
            if state_name is None:
                raise ValueError("configured state does not belong to the visible control")
            return control.name, control.control_type, state_name
        finally:
            if session is not None:
                await session.close()
            if token is not None:
                token.destroy()

    async def update_config(self, config: PluginConfig) -> None:
        """Apply a persisted source update by recreating only this optional subscription."""
        await self.close()
        self.config = config
        self.status = "unknown" if config.event_history_enabled else "disabled"
        self.capture_started_at = None
        await self.start()
