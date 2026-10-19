"""Opt-in solar samples in the existing history store and event-stream lifecycle."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcpserver.loxone.pv_forecast import STATES as PVPF_STATES
from mcpserver.loxone.pv_forecast import decode as decode_pv_forecast
from mcpserver.loxone.uuid import normalize_loxone_uuid

if TYPE_CHECKING:
    from mcpserver.loxone.event_history import EventHistoryStore
    from mcpserver.loxone.models import Control
    from mcpserver.solar_history import Observation


class SolarRecordingSource(BaseModel):
    """Administrator-confirmed source contract, never an MCP analysis input."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    control_uuid: str = Field(max_length=128)
    state_uuid: str | None = Field(default=None, max_length=128)
    kind: Literal["irradiance", "temperature", "pv_forecast"]
    unit: Literal["W/m²", "°C", "kWh"]
    sampling_period_seconds: int = Field(default=60, ge=60, le=1800)
    source_reference: str = Field(min_length=1, max_length=256)
    confirmed: Literal[True]

    @field_validator("control_uuid", "state_uuid")
    @classmethod
    def uuid(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None

    @field_validator("source_reference")
    @classmethod
    def reference(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("solar_source_reference_invalid")
        return value

    @model_validator(mode="after")
    def contract(self) -> SolarRecordingSource:
        if (
            self.unit
            != {"irradiance": "W/m²", "temperature": "°C", "pv_forecast": "kWh"}[self.kind]
        ):
            raise ValueError("solar_source_quantity_unit_conflict")
        if (self.state_uuid is None) != (self.kind == "pv_forecast"):
            raise ValueError("solar_source_target_invalid")
        return self

    @property
    def key(self) -> str:
        return f"{self.control_uuid}/{self.state_uuid or 'pv_forecast'}"

    def fingerprint(self, control: Control, installation: str) -> str:
        if control.uuid != self.control_uuid or control.is_hidden or not installation:
            raise ValueError("solar_source_not_visible")
        if self.kind == "pv_forecast":
            if (
                control.control_type != "PvProductionForecast"
                or not dict(control.state_uuids).keys() >= PVPF_STATES
            ):
                raise ValueError("unsupported_pv_forecast_control")
        elif (
            control.control_type != "InfoOnlyAnalog"
            or self.state_uuid != dict(control.state_uuids).get("value")
            or not control.format
            or not control.format.endswith(self.unit)
        ):
            raise ValueError("solar_source_state_or_unit_conflict")
        payload = [
            "solar_observations.v1",
            installation,
            self.model_dump(),
            control.control_type,
            control.state_uuids,
            control.format,
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def parse_sources(value: object) -> tuple[SolarRecordingSource, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("solar_source_limit_exceeded")
    sources = tuple(SolarRecordingSource.model_validate(item) for item in value)
    if len({s.key for s in sources}) != len(sources):
        raise ValueError("duplicate_solar_sources")
    return sources


def initialize_solar(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS solar_samples (id INTEGER PRIMARY KEY, "
        "source_key TEXT NOT NULL, fingerprint TEXT NOT NULL, observed_at REAL NOT NULL, "
        "payload_json TEXT NOT NULL)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS solar_samples_source_time ON "
        "solar_samples(source_key,fingerprint,observed_at,id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS solar_samples_retention ON solar_samples(observed_at,id)"
    )


def prune_solar(db: sqlite3.Connection, cutoff: float) -> int:
    return db.execute("DELETE FROM solar_samples WHERE observed_at<?", (cutoff,)).rowcount


def evict_solar(db: sqlite3.Connection) -> int:
    """Evict an oldest prefix only when it precedes scalar and weather samples."""
    solar = db.execute(
        "SELECT observed_at FROM solar_samples ORDER BY observed_at,id LIMIT 1"
    ).fetchone()
    if solar is None:
        return 0
    other = db.execute(
        "SELECT MIN(t) FROM (SELECT MIN(observed_at) AS t FROM events "
        "UNION ALL SELECT MIN(received_at) FROM weather_deliveries)"
    ).fetchone()[0]
    if other is not None and solar[0] > other:
        return 0
    return db.execute(
        "DELETE FROM solar_samples WHERE id IN (SELECT id FROM solar_samples "
        "WHERE observed_at<=? ORDER BY observed_at,id LIMIT 256)",
        (other if other is not None else math.inf,),
    ).rowcount


class SolarHistory:
    def __init__(self, store: EventHistoryStore):
        self.store = store

    def record(self, rows: list[tuple[str, str, float, str]]) -> None:
        if not rows:
            return
        if len(rows) > 16:
            raise ValueError("solar_recording_batch_limit_exceeded")
        from mcpserver.loxone.event_history import EventHistoryUnavailable

        with self.store._lock, self.store._opened() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.executemany(
                    "INSERT INTO solar_samples(source_key,fingerprint,observed_at,payload_json) "
                    "VALUES (?,?,?,?)",
                    rows,
                )
                pruned = self.store._prune(db, now=time.time())
                db.execute("COMMIT")
                self.store._compact(db, vacuum=pruned)
            except sqlite3.Error as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise EventHistoryUnavailable("solar history recording unavailable") from exc

    def read(
        self,
        source: SolarRecordingSource,
        fingerprint: str,
        start: float,
        end: float,
        *,
        maximum_points: int,
        deadline: float,
    ) -> tuple[list[tuple[float, dict[str, object]]], int]:
        from mcpserver.loxone.event_history import EventHistoryQueryTimeout, EventHistoryUnavailable
        from mcpserver.loxone.weather_history import _read_connection

        if not 0 <= maximum_points <= 100_000 or not 0 < end - start <= 33 * 86400:
            raise ValueError("solar_history_range_or_budget_invalid")
        if time.monotonic() >= deadline:
            raise EventHistoryQueryTimeout("solar analysis deadline exceeded")
        if not self.store.path.exists():
            return [], 0
        try:
            with _read_connection(self.store.path) as db:
                db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                rows = db.execute(
                    "SELECT observed_at,payload_json FROM solar_samples "
                    "INDEXED BY solar_samples_source_time WHERE source_key=? AND fingerprint=? "
                    "AND observed_at>=? AND observed_at<? ORDER BY observed_at,id LIMIT ?",
                    (
                        source.key,
                        fingerprint,
                        max(start, time.time() - self.store.retention_seconds),
                        end,
                        maximum_points + 1,
                    ),
                ).fetchall()
            if len(rows) > maximum_points:
                raise ValueError("solar_analysis_input_point_limit_exceeded")
            result = []
            for at, payload in rows:
                if time.monotonic() >= deadline:
                    raise EventHistoryQueryTimeout("solar analysis deadline exceeded")
                result.append((float(at), json.loads(payload)))
            return result, len(rows)
        except sqlite3.Error as exc:
            if time.monotonic() >= deadline:
                raise EventHistoryQueryTimeout("solar analysis deadline exceeded") from exc
            raise EventHistoryUnavailable("solar history read unavailable") from exc


def observations(rows: list[tuple[float, dict[str, object]]]) -> list[Observation]:
    from mcpserver.solar_history import Observation

    result = []
    for at, payload in rows:
        value = payload.get("value")
        if not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value):
            result.append(Observation(at, float(value)))
    return result


class SolarSampler:
    """Reuse one connected recorder stream; never poll the Miniserver per source."""

    def __init__(
        self,
        sources: tuple[SolarRecordingSource, ...],
        controls: tuple[Control, ...],
        installation: str,
    ):
        self.configured_sources = sources
        by_id = {c.uuid: c for c in controls}
        self.sources = []
        self.needed: set[str] = set()
        self.values: dict[str, object] = {}
        self.last: dict[str, float] = {}
        self.changed: dict[str, float] = {}
        self.forecast_payloads: dict[str, str] = {}
        for source in sources:
            control = by_id.get(source.control_uuid)
            if control is not None:
                try:
                    fingerprint = source.fingerprint(control, installation)
                except ValueError:
                    continue
                self.sources.append((source, control, fingerprint))
                if source.kind == "pv_forecast":
                    self.needed.update(u for n, u in control.state_uuids if n in PVPF_STATES)
                elif source.state_uuid is not None:
                    self.needed.add(source.state_uuid)
                    if "error" in dict(control.state_uuids):
                        self.needed.add(dict(control.state_uuids)["error"])

    def revalidated(self, controls: tuple[Control, ...], installation: str) -> SolarSampler:
        """Keep cached observations only for identically reauthorized source contracts."""
        fresh = SolarSampler(self.configured_sources, controls, installation)
        unchanged = {
            source.key
            for source, _, fingerprint in fresh.sources
            if any(old.key == source.key and prior == fingerprint for old, _, prior in self.sources)
        }
        reusable = {
            uuid
            for source, control, _ in fresh.sources
            if source.key in unchanged
            for _, uuid in control.state_uuids
        }
        fresh.values = {k: v for k, v in self.values.items() if k in reusable and k in fresh.needed}
        fresh.last = {k: v for k, v in self.last.items() if k in unchanged}
        fresh.changed = {k: v for k, v in self.changed.items() if k in unchanged}
        fresh.forecast_payloads = {
            k: v for k, v in self.forecast_payloads.items() if k in unchanged
        }
        return fresh

    def batch(self, values: Mapping[str, object], at: float) -> list[tuple[str, str, float, str]]:
        self.values.update((key, value) for key, value in values.items() if key in self.needed)
        rows = []
        for source, control, fingerprint in self.sources:
            refs = dict(control.state_uuids)
            if source.kind == "pv_forecast" and any(refs.get(n) in values for n in PVPF_STATES):
                self.changed[source.key] = at
            if at - self.last.get(source.key, -math.inf) < source.sampling_period_seconds:
                continue
            if source.kind == "pv_forecast":
                if at - self.changed.get(source.key, at) < 2:
                    continue
                captured = {
                    n: self.values[refs[n]] for n in PVPF_STATES if refs.get(n) in self.values
                }
                if not captured.keys() >= PVPF_STATES:
                    continue
                try:
                    for name in PVPF_STATES:
                        decode_pv_forecast(name, captured[name], captured)
                except ValueError:
                    continue
                payload: dict[str, object] = {"value_origin": "forecast", "states": captured}
            else:
                error_uuid = refs.get("error")
                if error_uuid is not None and self.values.get(error_uuid) not in (0, False):
                    continue
                value = self.values.get(source.state_uuid or "")
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                if not math.isfinite(value) or (source.kind == "irradiance" and value < 0):
                    continue
                payload = {"value_origin": "observed", "value": value, "unit": source.unit}
            encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
            self.last[source.key] = at
            if source.kind == "pv_forecast":
                if self.forecast_payloads.get(source.key) == encoded:
                    continue
                self.forecast_payloads[source.key] = encoded
            rows.append((source.key, fingerprint, at, encoded))
        return rows
