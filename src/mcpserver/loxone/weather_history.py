"""Structured weather deliveries in the shared, bounded history database.

Reception is evidence of a delivery, never evidence of continuous measurements.
Source point time, reported update time and local reception are independent axes.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from mcpserver.loxone.uuid import normalize_loxone_uuid

if TYPE_CHECKING:
    from pathlib import Path

    from mcpserver.loxone.event_history import EventHistoryStore
    from mcpserver.loxone.models import LoxoneStructure

FIELDS = (
    "weather_type",
    "wind_direction",
    "solar_radiation",
    "relative_humidity",
    "temperature",
    "perceived_temperature",
    "dew_point",
    "precipitation",
    "wind_speed",
    "barometric_pressure",
)
MAX_DELIVERY_BYTES = 32 * 1024
MAX_POINTS = 96
MAX_SOURCES = 16
RULE = "weather_history.raw_delivery.v1"
LOXONE_EPOCH = 1230768000


@contextmanager
def _read_connection(path: Path) -> Iterator[sqlite3.Connection]:
    from mcpserver.loxone.event_history import EventHistoryUnavailable

    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            yield db
    except (sqlite3.Error, OSError) as exc:
        raise EventHistoryUnavailable("local weather history is unavailable") from exc


@dataclass(frozen=True, slots=True)
class WeatherHistorySource:
    state_uuid: str
    mode: Literal["actual", "forecast"]
    fields: tuple[str, ...]

    @classmethod
    def parse(cls, value: object) -> WeatherHistorySource:
        if not isinstance(value, dict) or set(value) != {"state_uuid", "mode", "fields"}:
            raise ValueError("weather history source is invalid")
        uuid = normalize_loxone_uuid(value["state_uuid"])
        mode, fields = value["mode"], value["fields"]
        if mode not in {"actual", "forecast"} or not isinstance(fields, list):
            raise ValueError("weather history source is invalid")
        if not 1 <= len(fields) <= len(FIELDS) or any(f not in FIELDS for f in fields):
            raise ValueError("weather history fields are invalid")
        if len(set(fields)) != len(fields):
            raise ValueError("weather history fields must be unique")
        return cls(uuid, mode, tuple(f for f in FIELDS if f in fields))

    def document(self) -> dict[str, object]:
        return {"state_uuid": self.state_uuid, "mode": self.mode, "fields": list(self.fields)}


def source_fingerprint(
    source: WeatherHistorySource, structure: LoxoneStructure, installation: str
) -> str:
    """Bind data to one installation, exact visible mode and presentation generation."""
    if not any(
        item.kind == "weather_state"
        and item.identifier == source.mode
        and item.state_uuid == source.state_uuid
        for item in structure.global_metadata
    ):
        raise ValueError("weather history source is not currently visible")
    if not installation:
        raise ValueError("weather history installation is unavailable")
    keys = {
        "relative_humidity": "relativeHumidity",
        "temperature": "temperature",
        "precipitation": "precipitation",
        "wind_speed": "windSpeed",
        "barometric_pressure": "barometricPressure",
    }
    formats = dict(structure.weather.formats)
    selected_formats = {keys[f]: formats.get(keys[f]) for f in source.fields if f in keys}
    document = [
        RULE,
        installation,
        structure.identity.miniserver_serial,
        source.document(),
        selected_formats,
        structure.weather.type_texts if "weather_type" in source.fields else (),
    ]
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("weather delivery contains an invalid number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("weather delivery contains a nonfinite number")
    return number


def selected_delivery(
    source: WeatherHistorySource, value: object, *, started_at: float, received_at: float
) -> tuple[float, list[tuple[float, str]], str]:
    if received_at < started_at:
        raise ValueError("weather reception precedes the capture start")
    if not isinstance(value, dict):
        raise ValueError("weather delivery is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_POINTS:
        raise ValueError("weather delivery point limit exceeded")
    updated = LOXONE_EPOCH + _number(value.get("last_update"))
    points: list[tuple[float, str]] = []
    seen: set[float] = set()
    for entry in entries[:1] if source.mode == "actual" else entries:
        if not isinstance(entry, dict):
            raise ValueError("weather delivery point is invalid")
        at = LOXONE_EPOCH + _number(entry.get("timestamp"))
        if at in seen:
            raise ValueError("weather delivery has duplicate point times")
        seen.add(at)
        selected = {field: _number(entry.get(field)) for field in source.fields}
        encoded = json.dumps(selected, separators=(",", ":"), allow_nan=False)
        # Archive newly received deliveries on their reception axis. An old
        # source point is labelled separately and never backfills prior coverage.
        if source.mode == "actual" and at > received_at:
            raise ValueError("actual weather source point is in the future")
        points.append((at, encoded))
    payload = json.dumps([updated, points], separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > MAX_DELIVERY_BYTES:
        raise ValueError("weather delivery byte limit exceeded")
    return updated, points, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def initialize_weather(connection: sqlite3.Connection) -> None:
    for statement in (
        "CREATE TABLE IF NOT EXISTS weather_captures (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "state_uuid TEXT NOT NULL, mode TEXT NOT NULL, fingerprint TEXT NOT NULL, "
        "started_at REAL NOT NULL, ended_at REAL, outcome TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS weather_capture_source_time ON "
        "weather_captures(state_uuid, mode, fingerprint, started_at, id)",
        "CREATE TABLE IF NOT EXISTS weather_deliveries (id INTEGER PRIMARY KEY, "
        "capture_id INTEGER NOT NULL REFERENCES weather_captures(id) ON DELETE CASCADE, "
        "received_at REAL NOT NULL, reported_update_at REAL NOT NULL, "
        "payload_hash TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS weather_delivery_capture_time ON "
        "weather_deliveries(capture_id, received_at, id)",
        "CREATE INDEX IF NOT EXISTS weather_delivery_retention ON "
        "weather_deliveries(received_at,id)",
        "CREATE TABLE IF NOT EXISTS weather_points (id INTEGER PRIMARY KEY, "
        "delivery_id INTEGER NOT NULL REFERENCES weather_deliveries(id) ON DELETE CASCADE, "
        "state_uuid TEXT NOT NULL, mode TEXT NOT NULL, fingerprint TEXT NOT NULL, "
        "received_at REAL NOT NULL, "
        "point_at REAL NOT NULL, point_predates_capture INTEGER NOT NULL, "
        "fields_json TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS weather_point_delivery_time ON "
        "weather_points(delivery_id,point_at,id)",
        "CREATE INDEX IF NOT EXISTS weather_point_source_received ON "
        "weather_points(state_uuid,mode,fingerprint,received_at DESC,id DESC)",
        "CREATE INDEX IF NOT EXISTS weather_point_retention ON weather_points(received_at,id)",
        "CREATE INDEX IF NOT EXISTS events_retention_time ON events(observed_at,id)",
    ):
        connection.execute(statement)
    connection.execute(
        "UPDATE weather_captures SET ended_at=MAX(started_at,COALESCE(("
        "SELECT MAX(received_at) FROM weather_deliveries "
        "WHERE capture_id=weather_captures.id),started_at)), outcome='interrupted' "
        "WHERE ended_at IS NULL"
    )


def prune_weather(connection: sqlite3.Connection, cutoff: float) -> int:
    deleted = connection.execute(
        "DELETE FROM weather_deliveries WHERE received_at < ?", (cutoff,)
    ).rowcount
    deleted += connection.execute(
        "DELETE FROM weather_captures WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,)
    ).rowcount
    connection.execute(
        "UPDATE weather_captures SET started_at=? WHERE started_at < ? "
        "AND (ended_at IS NULL OR ended_at >= ?)",
        (cutoff, cutoff, cutoff),
    )
    return deleted


def evict_weather(connection: sqlite3.Connection) -> int:
    """Evict a bounded oldest prefix without crossing an older scalar event."""
    weather = connection.execute(
        "SELECT id,received_at FROM weather_deliveries ORDER BY received_at,id LIMIT 1"
    ).fetchone()
    scalar = connection.execute(
        "SELECT observed_at FROM events ORDER BY observed_at,id LIMIT 1"
    ).fetchone()
    if weather is not None and (scalar is None or weather[1] <= scalar[0]):
        boundary = scalar[0] if scalar is not None else math.inf
        return connection.execute(
            "DELETE FROM weather_deliveries WHERE id IN (SELECT id FROM weather_deliveries "
            "WHERE received_at <= ? ORDER BY received_at,id LIMIT 256)",
            (boundary,),
        ).rowcount
    return 0


class WeatherHistory:
    """One transaction per delivery; no independent storage or authorization."""

    def __init__(self, store: EventHistoryStore) -> None:
        self.store = store

    def analysis_points(
        self,
        source: WeatherHistorySource,
        fingerprint: str,
        start: float,
        end: float,
        *,
        maximum_points: int,
        deadline: float,
    ) -> tuple[list[dict[str, Any]], int]:
        """One bounded reception-index read; retain the latest version of each point.

        Both reception and source position must be inside the requested interval.
        Later receptions are deliberately excluded, not silently backfilled.
        Duplicate versions consume the input budget even when not returned.
        """
        from mcpserver.loxone.event_history import EventHistoryQueryTimeout, EventHistoryUnavailable

        if (
            source.mode != "actual"
            or type(maximum_points) is not int
            or not 0 <= maximum_points <= 100_000
            or not math.isfinite(start + end)
            or not 0 < end - start <= 32 * 86400
        ):
            raise ValueError("weather analysis range or budget is invalid")
        if time.monotonic() >= deadline:
            raise EventHistoryQueryTimeout("weather analysis deadline exceeded")
        effective_start = max(start, time.time() - self.store.retention_seconds)
        with _read_connection(self.store.path) as db:
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            try:
                db.execute("BEGIN")
                if db.execute("PRAGMA user_version").fetchone()[0] != 8:
                    raise EventHistoryUnavailable("local weather history needs migration")
                rows = db.execute(
                    "SELECT p.point_at,p.fields_json,p.received_at,p.point_predates_capture "
                    "FROM weather_points p INDEXED BY weather_point_source_received "
                    "WHERE p.state_uuid=? AND p.mode=? AND p.fingerprint=? "
                    "AND p.received_at>=? AND p.received_at<? "
                    "ORDER BY p.received_at DESC,p.id DESC LIMIT ?",
                    (
                        source.state_uuid,
                        source.mode,
                        fingerprint,
                        effective_start,
                        end,
                        maximum_points + 1,
                    ),
                ).fetchall()
                if len(rows) > maximum_points:
                    raise ValueError("analysis input point limit exceeded")
                db.execute("COMMIT")
            except sqlite3.Error as exc:
                if time.monotonic() >= deadline:
                    raise EventHistoryQueryTimeout("weather analysis deadline exceeded") from exc
                raise EventHistoryUnavailable("local weather analysis is unavailable") from exc
        points = []
        seen: set[float] = set()
        for at, fields, received, predates in rows:
            if time.monotonic() >= deadline:
                raise EventHistoryQueryTimeout("weather analysis deadline exceeded")
            if at in seen:
                continue
            seen.add(at)
            if predates or not start <= at < end or at > received:
                continue
            points.append({"point_at": at, "received_at": received, "fields": json.loads(fields)})
        return points, len(rows)

    def summary(self) -> dict[str, int]:
        if not self.store.path.is_file():
            return {"deliveries": 0, "points": 0}
        self.store.prepare_chart_read()
        cutoff = time.time() - self.store.retention_seconds
        with _read_connection(self.store.path) as db:
            deadline = time.monotonic() + 10
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
            db.execute("BEGIN")
            return {
                "deliveries": int(
                    db.execute(
                        "SELECT count(*) FROM weather_deliveries WHERE received_at>=?", (cutoff,)
                    ).fetchone()[0]
                ),
                "points": int(
                    db.execute(
                        "SELECT count(*) FROM weather_points WHERE received_at>=?", (cutoff,)
                    ).fetchone()[0]
                ),
            }

    def begin(self, source: WeatherHistorySource, fingerprint: str, at: float) -> int:
        with self._phase_write(at) as db:
            row = db.execute(
                "INSERT INTO weather_captures(state_uuid,mode,fingerprint,started_at,outcome) "
                "VALUES (?,?,?,?,'receiving')",
                (source.state_uuid, source.mode, fingerprint, at),
            )
            assert row.lastrowid is not None
            return row.lastrowid

    def end(self, capture_id: int, at: float, outcome: str) -> None:
        if outcome not in {
            "disconnected",
            "source_changed",
            "disabled",
            "storage_error",
            "cleared",
            "unsupported_value",
        }:
            raise ValueError("weather capture outcome is invalid")
        with self._phase_write(at) as db:
            db.execute(
                "UPDATE weather_captures SET ended_at=?,outcome=? WHERE id=? AND ended_at IS NULL",
                (at, outcome, capture_id),
            )

    @contextmanager
    def _phase_write(self, at: float) -> Iterator[sqlite3.Connection]:
        from mcpserver.loxone.event_history import EventHistoryUnavailable

        with self.store._lock, self.store._opened() as db:
            try:
                deadline = time.monotonic() + 10
                db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
                db.execute("BEGIN IMMEDIATE")
                yield db
                pruned = self.store._prune(db, now=at)
                db.execute("COMMIT")
                self.store._compact(db, vacuum=pruned)
            except sqlite3.Error as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise EventHistoryUnavailable("local weather history is unavailable") from exc

    def record(
        self, capture_id: int, source: WeatherHistorySource, value: object, received_at: float
    ) -> bool:
        from mcpserver.loxone.event_history import EventHistoryUnavailable

        with self.store._lock, self.store._opened() as db:
            try:
                deadline = time.monotonic() + 10
                db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
                db.execute("BEGIN IMMEDIATE")
                capture = db.execute(
                    "SELECT started_at,fingerprint FROM weather_captures "
                    "WHERE id=? AND ended_at IS NULL",
                    (capture_id,),
                ).fetchone()
                if capture is None:
                    # A live clear invalidates the old phase; never resurrect it.
                    raise EventHistoryUnavailable("weather capture was cleared or closed")
                updated, points, digest = selected_delivery(
                    source, value, started_at=capture[0], received_at=received_at
                )
                if not points:
                    db.execute("ROLLBACK")
                    return False
                last = db.execute(
                    "SELECT payload_hash FROM weather_deliveries WHERE capture_id=? "
                    "ORDER BY id DESC LIMIT 1",
                    (capture_id,),
                ).fetchone()
                if last is not None and last[0] == digest:
                    db.execute("ROLLBACK")
                    return False
                inserted = db.execute(
                    "INSERT INTO weather_deliveries"
                    "(capture_id,received_at,reported_update_at,payload_hash) "
                    "VALUES (?,?,?,?)",
                    (capture_id, received_at, updated, digest),
                )
                db.executemany(
                    "INSERT INTO weather_points"
                    "(delivery_id,state_uuid,mode,fingerprint,received_at,point_at,"
                    "point_predates_capture,fields_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (
                            inserted.lastrowid,
                            source.state_uuid,
                            source.mode,
                            capture[1],
                            received_at,
                            at,
                            int(at < capture[0]),
                            fields,
                        )
                        for at, fields in points
                    ],
                )
                pruned = self.store._prune(db, now=received_at)
                db.execute("COMMIT")
                self.store._compact(db, vacuum=pruned)
                return True
            except (sqlite3.Error, ValueError, EventHistoryUnavailable) as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                if isinstance(exc, ValueError | EventHistoryUnavailable):
                    raise
                raise EventHistoryUnavailable("local weather history is unavailable") from exc

    def page(
        self,
        source: WeatherHistorySource,
        fingerprint: str,
        start: float,
        end: float,
        *,
        limit: int,
        anchor: tuple[float, int] | None = None,
        generation: int | None = None,
    ) -> dict[str, Any]:
        from mcpserver.loxone.event_history import EventHistoryUnavailable

        if not 1 <= limit <= MAX_POINTS or not math.isfinite(start + end) or start >= end:
            raise ValueError("weather history page is invalid")
        cutoff = time.time() - self.store.retention_seconds
        effective_start = max(start, cutoff)
        with _read_connection(self.store.path) as db:
            try:
                deadline = time.monotonic() + 10
                db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
                db.execute("BEGIN")
                if db.execute("PRAGMA user_version").fetchone()[0] != 8:
                    raise EventHistoryUnavailable("local weather history needs migration")
                current = int(
                    db.execute(
                        "SELECT mutation_generation FROM history_metadata WHERE id=1"
                    ).fetchone()[0]
                )
                if generation is not None and current != generation:
                    raise ValueError("weather history changed; restart at page one")
                args: list[object] = [
                    source.state_uuid,
                    source.mode,
                    fingerprint,
                    effective_start,
                    end,
                ]
                clause = ""
                if anchor is not None:
                    clause = " AND (p.received_at,p.id) < (?,?)"
                    args.extend((anchor[0], anchor[1]))
                rows = db.execute(
                    "SELECT p.id,p.point_at,p.fields_json,d.received_at,d.reported_update_at, "
                    "p.point_predates_capture "
                    "FROM weather_points p INDEXED BY weather_point_source_received "
                    "JOIN weather_deliveries d ON d.id=p.delivery_id "
                    "WHERE p.state_uuid=? AND p.mode=? AND p.fingerprint=? "
                    "AND p.received_at>=? AND p.received_at<?"
                    + clause
                    + " ORDER BY p.received_at DESC,p.id DESC LIMIT ?",
                    (*args, limit + 1),
                ).fetchall()
                phases = db.execute(
                    "SELECT started_at,ended_at,outcome FROM weather_captures "
                    "WHERE state_uuid=? AND mode=? AND fingerprint=? AND started_at<? "
                    "AND (ended_at IS NULL OR ended_at>=?) "
                    "ORDER BY started_at DESC,id DESC LIMIT 129",
                    (source.state_uuid, source.mode, fingerprint, end, effective_start),
                ).fetchall()
                if effective_start >= end:
                    phases = []
                db.execute("COMMIT")
            except (sqlite3.Error, ValueError) as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                if isinstance(exc, ValueError):
                    raise
                raise EventHistoryUnavailable("local weather history is unavailable") from exc
        selected = rows[:limit]
        return {
            "items": [
                {
                    "point_at": r[1],
                    "fields": json.loads(r[2]),
                    "received_at": r[3],
                    "reported_update_at": r[4],
                    "point_predates_capture": bool(r[5]),
                }
                for r in selected
            ],
            "anchor": (selected[-1][3], selected[-1][0]) if len(rows) > limit else None,
            "generation": current,
            "capture_intervals": [
                {"started_at": max(p[0], cutoff), "ended_at": p[1], "outcome": p[2]}
                for p in phases[:128]
            ],
            "capture_intervals_truncated": len(phases) > 128,
            "coverage": "deliveries_only" if selected else "no_deliveries",
            "axis": "received_at",
            "rule": RULE,
            "limitations": [
                "No continuous observation or delivery cadence is established.",
                "Reported update time is not proven forecast issuance time.",
                "Numeric units and radiation encoding remain unverified.",
                "No history before recording is backfilled.",
            ],
        }
