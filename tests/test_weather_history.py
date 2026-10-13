"""Delivery provenance, shared storage bounds and weather-only admission."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mcpserver.config import ConfigError, PluginConfig
from mcpserver.loxone.event_history import (
    EventHistoryMonitor,
    EventHistoryStore,
    EventHistoryUnavailable,
)
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import GlobalMetadata, LoxoneIdentity, LoxoneStructure, WeatherMetadata
from mcpserver.loxone.weather_history import (
    LOXONE_EPOCH,
    WeatherHistory,
    WeatherHistorySource,
    selected_delivery,
    source_fingerprint,
)
from mcpserver.weather_history_tools import WeatherHistoryOptions

UUID = "00000001-0000-0000-0000000000000001"
SOURCE = WeatherHistorySource(UUID, "forecast", ("solar_radiation", "temperature"))


@pytest.mark.asyncio
async def test_disabled_scalar_and_empty_weather_do_not_start_connection(history, monkeypatch):
    store, _weather = history
    credentials = SimpleNamespace(load=None)
    monitor = EventHistoryMonitor(
        PluginConfig(
            event_history_enabled=False,
            event_history_sources=(("c", "s"),),
            weather_history_enabled=True,
        ),
        store,
        credentials,
    )

    async def forbidden():
        raise AssertionError("No enabled source may start a connection")

    monkeypatch.setattr(monitor, "_run", forbidden)
    await monitor.start()
    assert monitor._task is None
    await monitor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("storage_failure", [False, True])
async def test_same_uuid_modes_record_and_close_at_failure_not_retry(
    history, monkeypatch, storage_failure
):
    store, weather = history
    actual = WeatherHistorySource(UUID, "actual", SOURCE.fields)
    both = LoxoneStructure(
        LoxoneIdentity("service", "serial"),
        "1",
        (),
        (),
        (),
        global_metadata=(
            GlobalMetadata("weather_state", "actual", "Actual", state_uuid=UUID),
            GlobalMetadata("weather_state", "forecast", "Forecast", state_uuid=UUID),
        ),
    )
    retry_started = asyncio.Event()
    clock = [time.time()]
    source_delivery = delivery(clock[0] - 1, count=1)

    class Session:
        async def load_structure(self):
            return both

        async def state_events(self):
            yield (StateEvent(UUID, source_delivery),)
            clock[0] += 1
            raise (
                EventHistoryUnavailable("synthetic store failure")
                if storage_failure
                else OSError("synthetic disconnect")
            )

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self, *args):
            return Session()

        async def close(self):
            pass

    async def credentials():
        return "fixture", "fixture"

    async def retry(_seconds):
        retry_started.set()
        clock[0] += 5
        await asyncio.Future()

    monkeypatch.setattr("mcpserver.loxone.event_history.ServiceMiniserverConnection", Connection)
    monkeypatch.setattr("mcpserver.loxone.event_history.asyncio.sleep", retry)
    monkeypatch.setattr("mcpserver.loxone.event_history.time.time", lambda: clock[0])
    monitor = EventHistoryMonitor(
        PluginConfig(
            loxone_endpoint="https://synthetic.local",
            weather_history_enabled=True,
            weather_history_sources=(actual, SOURCE),
        ),
        store,
        SimpleNamespace(load=credentials),
    )
    task = asyncio.create_task(monitor._run())
    await asyncio.wait_for(retry_started.wait(), 2)
    failure_at = clock[0] - 5
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with store._opened() as db:
        phases = db.execute(
            "SELECT mode,ended_at,outcome FROM weather_captures ORDER BY mode"
        ).fetchall()
        modes = db.execute("SELECT mode FROM weather_points ORDER BY mode").fetchall()
    assert modes == [("actual",), ("forecast",)]
    assert phases == [
        (mode, failure_at, "storage_error" if storage_failure else "disconnected")
        for mode in ("actual", "forecast")
    ]


def structure(formats=(), uuid=UUID, texts=()):
    return LoxoneStructure(
        LoxoneIdentity("caller", "serial"),
        "1",
        (),
        (),
        (),
        global_metadata=(GlobalMetadata("weather_state", "forecast", "Forecast", state_uuid=uuid),),
        weather=WeatherMetadata(formats, texts),
    )


def delivery(at, value=12, updated=None, count=2):
    return {
        "last_update": int((at if updated is None else updated) - LOXONE_EPOCH),
        "entries": [
            {
                "timestamp": int(at - LOXONE_EPOCH) + i * 3600,
                "solar_radiation": value,
                "temperature": 20.0,
            }
            for i in range(count)
        ],
    }


@pytest.fixture
def history(tmp_path):
    store = EventHistoryStore(tmp_path / "state-events.sqlite3", retention_days=1, maximum_mib=16)
    store.initialize()
    return store, WeatherHistory(store)


def test_opt_in_config_roundtrip_and_scalar_independence():
    config = PluginConfig.defaults()
    assert not config.weather_history_enabled and not config.weather_history_sources
    doc = config.to_document()
    doc["tools"]["loxone_history_enabled"] = True
    doc["event_history"].update(weather_enabled=True, weather_sources=[SOURCE.document()])
    parsed = PluginConfig.from_document(doc)
    assert parsed.weather_history_enabled and not parsed.event_history_enabled
    assert PluginConfig.from_document(parsed.to_document()) == parsed
    doc["tools"]["loxone_history_enabled"] = False
    with pytest.raises(ConfigError):
        PluginConfig.from_document(doc)


@pytest.mark.parametrize(
    "change",
    [
        {"fields": []},
        {"fields": ["temperature", "temperature"]},
        {"fields": ["unknown"]},
        {"mode": "history"},
        {"state_uuid": "fake"},
        {"control_uuid": UUID},
    ],
)
def test_source_configuration_is_strict(change):
    with pytest.raises((ValueError, TypeError)):
        WeatherHistorySource.parse({**SOURCE.document(), **change})


def test_duplicate_source_keys_rejected():
    doc = PluginConfig.defaults().to_document()
    doc["event_history"]["weather_sources"] = [SOURCE.document(), SOURCE.document()]
    with pytest.raises(ConfigError):
        PluginConfig.from_document(doc)


def test_fingerprint_only_relevant_metadata_and_exact_installation():
    first = source_fingerprint(SOURCE, structure((("temperature", "%.1f °C"),)), "installation-A")
    unrelated = source_fingerprint(
        SOURCE, structure((("temperature", "%.1f °C"), ("windSpeed", "%f"))), "installation-A"
    )
    assert first == unrelated
    assert first != source_fingerprint(
        SOURCE, structure((("temperature", "%.1f °F"),)), "installation-A"
    )
    assert first != source_fingerprint(
        SOURCE, structure((("temperature", "%.1f °C"),)), "installation-B"
    )
    with pytest.raises(ValueError):
        source_fingerprint(
            SOURCE, structure(uuid="00000002-0000-0000-0000000000000002"), "installation-A"
        )


def test_delivery_versions_and_forecast_not_observation(history):
    store, weather = history
    now = time.time()
    fp = source_fingerprint(SOURCE, structure(), "installation")
    capture = weather.begin(SOURCE, fp, now)
    value = delivery(now + 3600, updated=now - 86400)
    assert weather.record(capture, SOURCE, value, now + 1)
    assert not weather.record(capture, SOURCE, value, now + 2)
    assert weather.record(
        capture, SOURCE, delivery(now + 3600, value=15, updated=now - 86400), now + 3
    )
    result = weather.page(SOURCE, fp, now, now + 10, limit=96)
    assert len(result["items"]) == 4
    assert result["items"][0]["point_at"] > result["items"][0]["received_at"]
    assert result["items"][0]["reported_update_at"] < now
    assert result["coverage"] == "deliveries_only"
    assert result["axis"] == "received_at"
    assert all(set(x["fields"]) == set(SOURCE.fields) for x in result["items"])
    assert weather.page(SOURCE, "different-generation", now, now + 10, limit=96)["items"] == []


def test_keyset_pages_no_duplicates_and_clear_invalidates(history):
    store, weather = history
    now = time.time()
    capture = weather.begin(SOURCE, "fp", now)
    weather.record(capture, SOURCE, delivery(now + 3600, count=5), now + 1)
    one = weather.page(SOURCE, "fp", now, now + 5, limit=2)
    two = weather.page(
        SOURCE, "fp", now, now + 5, limit=2, anchor=one["anchor"], generation=one["generation"]
    )
    assert len(one["items"]) == len(two["items"]) == 2
    assert not ({x["point_at"] for x in one["items"]} & {x["point_at"] for x in two["items"]})
    assert store.clear() == 0
    with pytest.raises(ValueError, match="changed"):
        weather.page(
            SOURCE, "fp", now, now + 5, limit=2, anchor=one["anchor"], generation=one["generation"]
        )
    new_capture = weather.begin(SOURCE, "fp", now + 2)
    assert new_capture != capture
    with pytest.raises(EventHistoryUnavailable, match="cleared"):
        weather.record(capture, SOURCE, delivery(now + 3600), now + 3)


def test_actual_projection_has_no_backfill_and_no_future(history):
    _store, weather = history
    now = time.time()
    source = replace(SOURCE, mode="actual")
    capture = weather.begin(source, "fp", now)
    assert weather.record(capture, source, delivery(now - 3600), now + 1)
    with pytest.raises(ValueError, match="future"):
        weather.record(capture, source, delivery(now + 3600), now + 1)
    assert weather.record(capture, source, delivery(now + 10), now + 11)
    page = weather.page(source, "fp", now, now + 20, limit=96)
    assert len(page["items"]) == 2
    assert page["items"][1]["point_predates_capture"] is True
    assert page["items"][0]["point_predates_capture"] is False
    assert page["capture_intervals"][0]["started_at"] == now
    assert weather.page(source, "fp", now - 7200, now, limit=96)["items"] == []


def test_shared_retention_uses_received_time_not_future_points(history):
    store, weather = history
    now = time.time()
    capture = weather.begin(SOURCE, "fp", now - 172800)
    weather.record(capture, SOURCE, delivery(now + 86400), now - 172799)
    assert weather.record(capture, SOURCE, delivery(now + 172800), now)
    page = weather.page(SOURCE, "fp", now - 86400, now + 1, limit=96)
    assert len(page["items"]) == 2
    with store._opened() as db:
        assert db.execute("SELECT count(*) FROM weather_deliveries").fetchone()[0] == 1


def test_schema_migration_restart_and_scalar_data_retained(history):
    store, weather = history
    now = time.time()
    store.begin_coverage(((UUID, UUID),), started_at=now, initial_values={(UUID, UUID): (now, 0)})
    store.record_transition(UUID, UUID, observed_at=now + 1, old_value=0, new_value=1)
    capture = weather.begin(SOURCE, "fp", now)
    weather.record(capture, SOURCE, delivery(now + 3600), now + 1)
    store.initialize()
    store.initialize()
    with store._opened() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM weather_points").fetchone()[0] == 2
        assert db.execute("SELECT outcome FROM weather_captures").fetchone()[0] == "interrupted"
    with pytest.raises(EventHistoryUnavailable):
        weather.record(capture, SOURCE, delivery(now + 7200), now + 2)


def test_weather_summary_preserves_active_capture(history):
    store, weather = history
    capture = weather.begin(SOURCE, "fp", time.time())
    assert weather.summary() == {"deliveries": 0, "points": 0}
    with store._opened() as db:
        assert db.execute(
            "SELECT ended_at,outcome FROM weather_captures WHERE id=?", (capture,)
        ).fetchone() == (None, "receiving")


@pytest.mark.parametrize("entry", ["snapshot", "chart", "inventory", "weather_summary"])
def test_direct_v7_read_migrates_to_v8_without_losing_scalar(history, entry):
    store, _weather = history
    now = time.time()
    store.record_transition(UUID, UUID, observed_at=now - 1, old_value=0, new_value=1)
    with store._opened() as db:
        db.execute("DROP TABLE weather_points")
        db.execute("DROP TABLE weather_deliveries")
        db.execute("DROP TABLE weather_captures")
        db.execute("PRAGMA user_version=7")
    if entry == "snapshot":
        assert store.snapshot(((UUID, UUID),)).sources[0].event_count == 1
    elif entry == "chart":
        store.prepare_chart_read()
        assert len(store.chart_page(UUID, UUID, start=now - 10, end=now)["events"]) == 1
    elif entry == "inventory":
        rows, _next = store.source_inventory_page(
            ((UUID, UUID),), visible_sources={(UUID, UUID)}, offset=0, limit=10
        )
        assert rows
    else:
        assert _weather.summary() == {"deliveries": 0, "points": 0}
    with store._opened() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "12"])
def test_nonfinite_or_untyped_selected_fields_rejected(value):
    now = time.time()
    raw = delivery(now)
    raw["entries"][0]["temperature"] = value
    with pytest.raises(ValueError):
        selected_delivery(SOURCE, raw, started_at=now - 1, received_at=now + 1)


def test_point_size_duplicate_and_unknown_schema_limits(history):
    store, weather = history
    now = time.time()
    with pytest.raises(ValueError):
        selected_delivery(SOURCE, delivery(now, count=97), started_at=now, received_at=now)
    raw = delivery(now)
    raw["entries"][1]["timestamp"] = raw["entries"][0]["timestamp"]
    with pytest.raises(ValueError, match="duplicate"):
        selected_delivery(SOURCE, raw, started_at=now, received_at=now)
    with store._opened() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(EventHistoryUnavailable, match="migration"):
        weather.page(SOURCE, "fp", now - 1, now + 1, limit=96)


def test_weather_only_size_limit_eviction_and_foreign_keys(history):
    store, weather = history
    now = time.time()
    capture = weather.begin(SOURCE, "fp", now)
    for n in range(20):
        weather.record(capture, SOURCE, delivery(now + 3600 + n, value=n, count=96), now + n + 1)
    store.maximum_bytes = 100 * 1024
    with store._opened() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store._prune(db, now=now + 30)
        db.execute("COMMIT")
        store._compact(db, vacuum=True)
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert store.path.stat().st_size <= store.maximum_bytes


def test_history_range_received_axis_past_gate():
    now = time.time()

    def iso(t):
        return datetime.fromtimestamp(t, UTC).isoformat()

    options = WeatherHistoryOptions(
        state_uuid=UUID, stored_mode="forecast", start=iso(now - 3600), end=iso(now)
    )
    assert options.period()[1] == pytest.approx(now, abs=1e-6)
    for start, end in [
        (iso(now - 32 * 86400), iso(now)),
        (iso(now), iso(now + 3600)),
        ("2026-10-11", iso(now)),
    ]:
        with pytest.raises(ValueError):
            WeatherHistoryOptions(
                state_uuid=UUID, stored_mode="actual", start=start, end=end
            ).period()


def test_source_time_index_is_used(history):
    store, _weather = history
    with closing(sqlite3.connect(store.path)) as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM weather_points WHERE state_uuid=? AND mode=? "
            "AND fingerprint=? AND received_at>=? AND received_at<? "
            "ORDER BY received_at DESC,id DESC LIMIT 97",
            (UUID, "forecast", "fp", 0, time.time()),
        ).fetchall()
    assert "weather_point_source_received" in str(plan)
    assert "TEMP B-TREE" not in str(plan)


def test_capture_only_writes_enforce_retention_size_and_never_reuse_ids(history):
    store, weather = history
    now = time.time()
    stale = weather.begin(SOURCE, "old", now - store.retention_seconds - 60)
    weather.end(stale, now - store.retention_seconds - 30, "unsupported_value")
    current = weather.begin(SOURCE, "new", now)
    with store._opened() as db:
        assert db.execute("SELECT id FROM weather_captures WHERE id=?", (stale,)).fetchone() is None
    assert current > stale
    weather.end(current, now, "unsupported_value")
    store.maximum_bytes = 144 * 1024
    for n in range(500):
        capture = weather.begin(SOURCE, "f" * 64, now + n)
        with pytest.raises(ValueError):
            weather.record(capture, SOURCE, {"entries": []}, now + n)
        weather.end(capture, now + n, "unsupported_value")
    assert store._size() <= store.maximum_bytes
    with store._opened() as db:
        assert db.execute("SELECT count(*) FROM weather_points").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM weather_captures").fetchone()[0] < 500
    with pytest.raises(EventHistoryUnavailable):
        weather.record(stale, SOURCE, delivery(now), now + 501)


def test_analysis_reads_latest_versions_once_and_counts_all_inputs(history):
    store, weather = history
    source = WeatherHistorySource(UUID, "actual", SOURCE.fields)
    now = float(int(time.time()))
    capture = weather.begin(source, "generation", now - 1)
    weather.record(capture, source, delivery(now, value=1, count=1), now + 1)
    weather.record(capture, source, delivery(now, value=3, count=1), now + 2)
    points, count = weather.analysis_points(
        source, "generation", now - 1, now + 10, maximum_points=10, deadline=time.monotonic() + 5
    )
    assert count == 2
    assert len(points) == 1
    assert points[0]["fields"]["solar_radiation"] == 3
    with pytest.raises(ValueError, match="input point limit"):
        weather.analysis_points(
            source, "generation", now - 1, now + 10, maximum_points=1, deadline=time.monotonic() + 5
        )
    assert weather.analysis_points(
        source,
        "other-generation",
        now - 1,
        now + 10,
        maximum_points=10,
        deadline=time.monotonic() + 5,
    ) == ([], 0)


def test_analysis_does_not_backfill_old_points_or_late_receptions(history):
    store, weather = history
    source = WeatherHistorySource(UUID, "actual", SOURCE.fields)
    now = float(int(time.time()))
    capture = weather.begin(source, "generation", now)
    weather.record(capture, source, delivery(now - 3600, value=2, count=1), now + 1)
    weather.record(capture, source, delivery(now, value=2, count=1), now + 20)
    points, count = weather.analysis_points(
        source, "generation", now - 7200, now + 10, maximum_points=10, deadline=time.monotonic() + 5
    )
    assert count == 1
    assert not points


def test_analysis_rejects_forecasts_and_expired_deadlines(history):
    from mcpserver.loxone.event_history import EventHistoryQueryTimeout

    store, weather = history
    now = time.time()
    with pytest.raises(ValueError):
        weather.analysis_points(
            SOURCE, "generation", now - 10, now, maximum_points=10, deadline=time.monotonic() + 5
        )
    source = WeatherHistorySource(UUID, "actual", SOURCE.fields)
    with pytest.raises(EventHistoryQueryTimeout):
        weather.analysis_points(
            source, "generation", now - 10, now, maximum_points=10, deadline=time.monotonic() - 1
        )
