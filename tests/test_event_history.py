from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from mcpserver.config import PluginConfig
from mcpserver.loxone.event_history import (
    EventHistoryMonitor,
    EventHistoryStore,
    EventHistoryUnavailable,
)
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure


def test_store_records_typed_transitions_and_pages_them(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    started_at = time.time() - 30
    store.initialize()
    store.begin_coverage((source,), started_at=started_at)
    store.record_transition(*source, observed_at=started_at + 10, old_value=False, new_value=True)
    store.record_transition(
        *source, observed_at=started_at + 20, old_value="closed", new_value="open"
    )

    page = store.page(*source, start=started_at, end=time.time(), limit=10)

    assert page.coverage == "complete"
    assert [(item.old_value, item.new_value) for item in page.entries] == [
        ("closed", "open"),
        (False, True),
    ]
    assert store.snapshot((source,)).sources[0].logical_value_bytes == len(
        b'falsetrue"closed""open"'
    )


def test_source_inventory_page_filters_before_limiting_many_hidden_sources(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    store.initialize()
    now = time.time()
    for index in range(260):
        control, state = f"control-{index:03}", f"state-{index:03}"
        store.record_transition(control, state, observed_at=now, old_value=0, new_value=1)
        store.mark_removed(control, state, removed_at=None)
    visible = {("control-257", "state-257"), ("control-259", "state-259")}

    first, cursor = store.source_inventory_page((), offset=0, limit=1, visible_sources=visible)
    second, end = store.source_inventory_page((), offset=cursor, limit=1, visible_sources=visible)

    assert first == (("control-257", "state-257", False, None),)
    assert second == (("control-259", "state-259", False, None),)
    assert end is None
    assert store.source_inventory_page((), offset=0, limit=1, visible_sources=set()) == (
        (),
        None,
    )


def test_chart_page_is_read_only_and_detects_history_mutations(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "chart.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source,), started_at=now - 30)
    store.record_transition(*source, observed_at=now - 20, old_value=False, new_value=True)
    store.record_transition(*source, observed_at=now - 10, old_value=True, new_value=False)
    monkeypatch.setattr(store, "_prune", lambda *_args, **_kwargs: pytest.fail("maintenance"))

    first = store.chart_page(*source, start=now - 40, end=now, limit=1)
    second = store.chart_page(*source, start=now - 40, end=now, after_id=first["next_id"])
    assert [event["new_value"] for event in first["events"] + second["events"]] == [
        True,
        False,
    ]
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert first["generation"] == second["generation"]
    store.mark_removed(*source, removed_at=now)
    removed = store.chart_page(*source, start=now - 40, end=now)
    assert removed["generation"] == first["generation"]
    assert removed["recording_ended_at"] == now
    with sqlite3.connect(store.path) as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM events INDEXED BY events_source_time "
            "WHERE control_uuid = ? AND state_uuid = ? AND observed_at >= ? "
            "AND observed_at <= ? ORDER BY id LIMIT 501",
            (*source, now - 40, now),
        ).fetchall()
        assert any("events_source_time" in row[3] for row in plan)

    store.clear()
    cleared = store.chart_page(*source, start=now - 40, end=now)
    assert cleared["events"] == []
    assert cleared["generation"] > first["generation"]


def test_dense_chart_sample_retains_extrema_and_boolean_transitions(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source,), started_at=now - 5000)
    with sqlite3.connect(store.path) as db:
        db.executemany(
            "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, new_value) "
            "VALUES (?, ?, ?, '0', ?)",
            (
                (
                    *source,
                    now - 4002 + index,
                    str(
                        10**500
                        if index == 10
                        else -999
                        if index == 2000
                        else 999
                        if index == 2001
                        else index % 2
                    ),
                )
                for index in range(4002)
            ),
        )
    result = store.chart_page(*source, start=now - 5000, end=now)
    values = [event["new_value"] for event in result["events"]]
    assert result["reduced"] is True
    assert result["has_more"] is False
    assert len(result["events"]) <= 384
    assert {-999, 999, 0, 1} <= {value for value in values if isinstance(value, int)}
    assert {"integer_decimal": str(10**500)} in values


def test_chart_page_preserves_unsafe_integers_for_browser(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart-integer.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.record_transition(*source, observed_at=now - 1, old_value=2**53, new_value=2**53 + 1)
    event = store.chart_page(*source, start=now - 10, end=now)["events"][0]
    assert "old_value" not in event
    assert event["new_value"] == {"integer_decimal": str(2**53 + 1)}


def test_dense_chart_sample_retains_middle_spikes_and_boolean_states(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart-middle.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.executemany(
            "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, new_value) "
            "VALUES (?, ?, ?, '0', ?)",
            (
                (
                    *source,
                    now - 50 + index / 10000,
                    "-999"
                    if index == 3000
                    else "999"
                    if index == 3001
                    else "true"
                    if index == 3002
                    else "false"
                    if index == 3003
                    else "1",
                )
                for index in range(6000)
            ),
        )
    result = store.chart_page(*source, start=now - 64, end=now)
    assert all("old_value" not in event for event in result["events"])
    values = [event["new_value"] for event in result["events"]]
    assert -999 in values and 999 in values
    assert any(value is True for value in values)
    assert any(value is False for value in values)
    assert len(result["events"]) <= 384


def test_dense_chart_sample_orders_huge_integer_extrema_exactly(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart-huge.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.executemany(
            "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, new_value) "
            "VALUES (?, ?, ?, '0', ?)",
            (
                (
                    *source,
                    now - 50 + index / 10000,
                    str(
                        10**600
                        if index == 3000
                        else 10**500
                        if index == 3001
                        else -(10**600)
                        if index == 3002
                        else -(10**500)
                        if index == 3003
                        else 1
                    ),
                )
                for index in range(6000)
            ),
        )
    result = store.chart_page(*source, start=now - 64, end=now)
    values = [event["new_value"] for event in result["events"]]
    assert result["reduced"] is True
    assert {"integer_decimal": str(10**600)} in values
    assert {"integer_decimal": str(-(10**600))} in values
    assert len(result["events"]) <= 384


def test_chart_cursor_does_not_skip_events_after_window_end(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart-cursor.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.record_transition(*source, observed_at=now - 1, old_value=0, new_value=1)
    store.record_transition(*source, observed_at=now + 1, old_value=1, new_value=2)
    first = store.chart_page(*source, start=now - 10, end=now)
    assert [event["new_value"] for event in first["events"]] == [1]
    second = store.chart_page(*source, start=now - 10, end=now + 2, after_id=first["latest_id"])
    assert [event["new_value"] for event in second["events"]] == [2]


def test_chart_page_bounds_old_range_before_newer_ids(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart-old-range.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.executemany(
            "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, new_value) "
            "VALUES (?, ?, ?, '0', '1')",
            (
                (
                    *source,
                    now - 3600 + index,
                )
                for index in range(501)
            ),
        )
        db.executemany(
            "INSERT INTO events(control_uuid, state_uuid, observed_at, old_value, new_value) "
            "VALUES (?, ?, ?, '0', '2')",
            (
                (
                    *source,
                    now - 60 + index / 100,
                )
                for index in range(2000)
            ),
        )
    first = store.chart_page(*source, start=now - 3600, end=now - 3000)
    second = store.chart_page(*source, start=now - 3600, end=now - 3000, after_id=first["next_id"])
    assert len(first["events"]) == 500 and first["has_more"] is True
    assert len(second["events"]) == 1 and second["has_more"] is False
    assert first["latest_id"] == second["latest_id"] == 501


def test_chart_read_upgrades_v5_and_empty_store_without_maintenance(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "chart.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    assert store.chart_page(*source, start=1, end=2)["events"] == []
    assert not store.path.exists()
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.execute("DROP INDEX events_source_id")
        db.execute("ALTER TABLE history_metadata DROP COLUMN mutation_generation")
        db.execute("PRAGMA user_version = 5")
    monkeypatch.setattr(store, "_prune", lambda *_args, **_kwargs: pytest.fail("maintenance"))
    assert store.prepare_chart_read() == 0
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            db.execute("SELECT mutation_generation FROM history_metadata WHERE id = 1").fetchone()[
                0
            ]
            == 0
        )
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name = 'events_source_id'").fetchone()
            is not None
        )


def test_chart_generation_changes_only_when_recorded_events_are_removed(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "chart.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    store.initialize()
    store.record_transition(*source, observed_at=time.time(), old_value=0, new_value=1)
    generation = store.prepare_chart_read()
    store.begin_coverage((source,), started_at=time.time())
    store.end_coverage((source,), ended_at=time.time(), outcome="stopped")
    store.mark_removed(*source, removed_at=time.time())
    assert store.prepare_chart_read() == generation
    store.purge_source(*source)
    assert store.prepare_chart_read() > generation


def test_source_inventory_page_upgrades_v5_store(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.execute("DROP INDEX events_source_id")
        db.execute("ALTER TABLE history_metadata DROP COLUMN mutation_generation")
        db.execute("PRAGMA user_version = 5")

    page, cursor = store.source_inventory_page((source,), offset=0, limit=10)

    assert page == (("control", "state", True, None),)
    assert cursor is None
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6


def test_v4_logical_bytes_migrate_in_bounded_batches_with_concurrent_writes(tmp_path):
    path = (tmp_path / "history.sqlite3").resolve()
    store = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    source = ("control", "state")
    removed = ("removed", "state")
    now = time.time()
    store.initialize()
    store.record_transition(*source, observed_at=now - 3, old_value="ä", new_value="ö")
    store.record_transition(*source, observed_at=now - 2, old_value=0, new_value=1)
    store.record_transition(*removed, observed_at=now - 2, old_value=4, new_value=5)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE events DROP COLUMN logical_value_bytes")
        connection.execute("ALTER TABLE source_totals DROP COLUMN logical_value_bytes")
        connection.execute("ALTER TABLE source_totals DROP COLUMN unmeasured_events")
        connection.execute("ALTER TABLE history_metadata DROP COLUMN backfill_last_id")
        connection.execute("PRAGMA user_version = 4")

    assert store.snapshot((source,)).sources[0].logical_value_bytes is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE logical_value_bytes IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
    assert store.backfill_payload_batch(limit=1) is True
    assert store.snapshot((source,)).sources[0].logical_value_bytes is None
    store.record_transition(*source, observed_at=now - 1, old_value=2, new_value=3)
    assert store.purge_source(*removed)[0] == 1
    assert store.backfill_payload_batch(limit=1) is True
    assert store.backfill_payload_batch(limit=1) is False
    expected = len('"ä""ö"'.encode()) + len(b"01") + len(b"23")
    assert store.snapshot((source,)).sources[0].logical_value_bytes == expected
    assert store.backfill_payload_batch(limit=1) is False


def test_logical_bytes_do_not_include_wal_growth(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.record_transition(*source, observed_at=now, old_value=False, new_value=True)
    expected = store.snapshot((source,)).sources[0].logical_value_bytes
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO coverage(control_uuid, state_uuid, started_at, outcome) "
            "VALUES (?, ?, ?, 'active')",
            (*source, now),
        )
        connection.commit()
        summary = store.snapshot((source,))
        assert summary.wal_bytes > 0
        assert summary.sources[0].logical_value_bytes == expected


def test_logical_bytes_follow_removal_pruning_purge_and_clear(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=1, maximum_mib=16
    )
    source = ("control", "state")
    other = ("other", "state")
    now = time.time()
    store.initialize()
    store.record_transition(*source, observed_at=now - 100000, old_value=0, new_value=1)
    store.record_transition(*source, observed_at=now - 10, old_value=2, new_value=3)
    store.record_transition(*other, observed_at=now - 10, old_value=4, new_value=5)
    store.mark_removed(*source, removed_at=now - 5)
    assert store.snapshot(()).sources[0].logical_value_bytes == 2
    with store._lock, store._opened() as connection:
        store._prune(connection, now=now)
    assert store.snapshot(()).sources[0].logical_value_bytes == 2
    assert store.purge_source(*source)[0] == 1
    assert store.snapshot(()).sources[0].control_uuid == "other"
    assert store.clear() == 1
    assert store.snapshot((source,)).sources[0].logical_value_bytes == 0


def test_store_reports_not_recorded_and_removes_data(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    started_at = time.time()
    store.initialize()

    assert store.page(*source, start=0.0, end=1.0, limit=10).coverage == "not_recorded"
    store.begin_coverage((source,), started_at=started_at)
    store.record_transition(*source, observed_at=started_at + 1, old_value=1.0, new_value=2.0)
    assert store.clear() == 1
    assert (
        store.page(*source, start=started_at, end=started_at + 20, limit=10).coverage
        == "not_recorded"
    )


def test_removed_source_retains_evidence_and_readd_keeps_coverage_gap(tmp_path):
    path = (tmp_path / "event-history.sqlite3").resolve()
    store = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    source = ("control", "state")
    other = ("other", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source, other), started_at=now - 60)
    store.record_transition(*source, observed_at=now - 50, old_value=False, new_value=True)
    store.record_transition(*other, observed_at=now - 50, old_value=False, new_value=True)
    store.end_coverage((source,), ended_at=now - 40, outcome="stopped")
    store.mark_removed(*source, removed_at=now - 40)
    store.mark_removed(*source, removed_at=None)

    removed = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    page = removed.page(*source, start=now - 60, end=now - 30, limit=10)
    assert page.has_evidence and page.recording_ended_at == now - 40
    assert len(page.entries) == 1 and page.coverage == "partial_coverage"

    removed.begin_coverage((source,), started_at=now - 10)
    assert removed.page(*source, start=now - 60, end=now, limit=10).coverage == "partial_coverage"
    assert removed.page(*source, start=now - 60, end=now, limit=10).recording_ended_at is None
    assert removed.purge_source(*source) == (1, 2)
    assert not removed.page(*source, start=now - 60, end=now, limit=10).has_evidence
    assert removed.page(*other, start=now - 60, end=now, limit=10).has_evidence


def test_removed_source_can_be_marked_without_guessing_its_end_time(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source,), started_at=now - 20)
    store.end_coverage((source,), ended_at=now - 10, outcome="stopped")
    store.mark_removed(*source, removed_at=None)

    page = store.page(*source, start=now - 20, end=now - 10, limit=10)
    assert page.has_evidence and page.recording_ended_at is None
    store.mark_removed("missing", "state", removed_at=None)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM removed_sources").fetchone()[0] == 1


def test_purge_reports_unknown_if_compaction_fails_after_commit(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source,), started_at=now - 20)
    store.record_transition(*source, observed_at=now - 10, old_value=0, new_value=1)
    store.end_coverage((source,), ended_at=now - 5, outcome="stopped")
    store.mark_removed(*source, removed_at=now - 5)

    def fail_size() -> int:
        raise OSError("file stat failed")

    monkeypatch.setattr(store, "_size", fail_size)
    with pytest.raises(EventHistoryUnavailable, match="maintenance is unavailable"):
        store.purge_source(*source)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM coverage").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM removed_sources").fetchone()[0] == 0


def test_schema_v1_migration_preserves_evidence_without_inventing_removal_time(tmp_path):
    path = (tmp_path / "event-history.sqlite3").resolve()
    store = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    source = ("control", "state")
    now = time.time()
    store.initialize()
    store.begin_coverage((source,), started_at=now - 20)
    store.end_coverage((source,), ended_at=now - 10, outcome="stopped")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE removed_sources")
        connection.execute("PRAGMA user_version = 1")
    store.initialize()
    page = store.page(*source, start=now - 20, end=now - 10, limit=10)
    assert page.has_evidence and page.recording_ended_at is None


def test_removed_source_is_pruned_by_global_retention(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=1, maximum_mib=16
    )
    source = ("control", "state")
    store.initialize()
    store.begin_coverage((source,), started_at=100.0)
    store.record_transition(*source, observed_at=110.0, old_value=0, new_value=1)
    store.end_coverage((source,), ended_at=120.0, outcome="stopped")
    store.mark_removed(*source, removed_at=120.0)
    monkeypatch.setattr("mcpserver.loxone.event_history.time.time", lambda: 200000.0)
    page = store.page(*source, start=100.0, end=120.0, limit=10)
    assert not page.has_evidence and page.recording_ended_at is None


def test_store_reports_batched_coverage_without_exposing_event_values(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    complete = ("control-complete", "state-complete")
    partial = ("control-partial", "state-partial")
    missing = ("control-missing", "state-missing")
    now = time.time()
    store.initialize()
    store.begin_coverage((complete,), started_at=now - 30)
    store.begin_coverage((partial,), started_at=now - 5)
    store.record_transition(*complete, observed_at=now - 10, old_value=False, new_value=True)

    coverage = store.coverage_many((complete, partial, missing), start=now - 20, end=now)

    assert coverage[complete].coverage == "complete"
    assert coverage[complete].has_events is True
    assert coverage[partial].coverage == "partial_coverage"
    assert coverage[partial].has_events is False
    assert coverage[missing].coverage == "not_recorded"
    assert coverage[missing].capture_started_at is None


def test_store_closes_orphaned_coverage_when_a_new_process_initializes(tmp_path, monkeypatch):
    path = (tmp_path / "event-history.sqlite3").resolve()
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    first = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    first.initialize()
    first.begin_coverage((source,), started_at=10.0)

    second = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    monkeypatch.setattr("mcpserver.loxone.event_history.time.time", lambda: 20.0)
    second.initialize()
    second.begin_coverage((source,), started_at=30.0)

    assert second.page(*source, start=10.0, end=30.0, limit=10).coverage == "partial_coverage"


def test_retention_pruning_keeps_active_coverage(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=1, maximum_mib=16
    )
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    store.initialize()
    store.begin_coverage((source,), started_at=0.0)

    monkeypatch.setattr("mcpserver.loxone.event_history.time.time", lambda: 172800.0)

    assert store.page(*source, start=172700.0, end=172800.0, limit=10).coverage == "complete"


def test_retention_pruning_limits_completed_coverage_to_retained_window(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=1, maximum_mib=16
    )
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    store.initialize()
    store.begin_coverage((source,), started_at=0.0)
    store.end_coverage((source,), ended_at=100000.0, outcome="stopped")

    monkeypatch.setattr("mcpserver.loxone.event_history.time.time", lambda: 172800.0)

    assert store.page(*source, start=80000.0, end=90000.0, limit=10).coverage == "partial_coverage"


def test_size_eviction_advances_only_coverage_for_its_source(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    busy = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    quiet = ("00000000-0000-0000-0000-0000000000000003", "00000000-0000-0000-0000-0000000000000004")
    store.initialize()
    store.begin_coverage((busy, quiet), started_at=0.0)
    store.record_transition(*busy, observed_at=10.0, old_value=False, new_value=True)
    measurements = iter((store.maximum_bytes + 1, 0))
    monkeypatch.setattr(store, "_used_database_bytes", lambda _connection: next(measurements))

    with store._lock, store._opened() as connection:
        store._prune(connection, now=100.0)
        coverage = dict(
            connection.execute(
                "SELECT control_uuid, started_at FROM coverage ORDER BY control_uuid"
            ).fetchall()
        )

    assert coverage[busy[0]] > 10.0
    assert coverage[quiet[0]] == 0.0
    assert store.snapshot((busy, quiet)).sources[0].logical_value_bytes == 0


def test_store_translates_parent_creation_failures_to_a_store_error(tmp_path, monkeypatch):
    store = EventHistoryStore(
        (tmp_path / "unavailable" / "event-history.sqlite3").resolve(),
        retention_days=90,
        maximum_mib=16,
    )

    def fail_mkdir(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(EventHistoryUnavailable, match="history is unavailable"):
        store.initialize()


@pytest.mark.asyncio
async def test_monitor_skips_miniserver_when_no_sources_and_starts_after_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        def initialize(self) -> None:
            pass

        def backfill_payload_batch(self) -> bool:
            return False

    started = asyncio.Event()
    attempts = 0
    monitor = EventHistoryMonitor(
        PluginConfig(event_history_enabled=True),
        Store(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    async def run() -> None:
        nonlocal attempts
        attempts += 1
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(monitor, "_run", run)
    await monitor.start()
    assert attempts == 0
    assert monitor._task is None

    await monitor.update_config(
        PluginConfig(event_history_enabled=True, event_history_sources=(("control", "state"),))
    )
    await asyncio.wait_for(started.wait(), 1)
    assert attempts == 1

    await monitor.update_config(PluginConfig(event_history_enabled=True))
    assert attempts == 1
    assert monitor._task is None or monitor._task.done()


@pytest.mark.asyncio
async def test_monitor_update_wait_wakes_only_after_notification(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    monitor = EventHistoryMonitor(PluginConfig(event_history_enabled=False), store, object())  # type: ignore[arg-type]
    initial = await monitor.wait_for_update("", timeout=0.01)
    assert initial["changed"] is True
    waiting = asyncio.create_task(monitor.wait_for_update(str(initial["token"]), timeout=1))
    await asyncio.sleep(0)
    assert not waiting.done()
    monitor._notify_update()
    changed = await asyncio.wait_for(waiting, 1)
    assert changed["changed"] is True
    assert changed["token"] != initial["token"]
    quiet = await monitor.wait_for_update(str(changed["token"]), timeout=0.01)
    assert quiet["changed"] is False


@pytest.mark.asyncio
async def test_monitor_close_cancels_payload_backfill(monkeypatch, tmp_path) -> None:
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    monitor = EventHistoryMonitor(
        PluginConfig(event_history_enabled=True),
        store,
        object(),  # type: ignore[arg-type]
    )
    started = asyncio.Event()

    async def backfill() -> None:
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(monitor, "_backfill", backfill)
    await monitor.start()
    await asyncio.wait_for(started.wait(), 1)
    await monitor.close()
    assert monitor._backfill_task is None


@pytest.mark.asyncio
async def test_disabled_monitor_backfills_existing_legacy_store_without_stream(
    monkeypatch, tmp_path
) -> None:
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("control", "state")
    store.initialize()
    store.record_transition(*source, observed_at=time.time(), old_value=0, new_value=1)
    with sqlite3.connect(store.path) as connection:
        connection.execute("ALTER TABLE events DROP COLUMN logical_value_bytes")
        connection.execute("ALTER TABLE source_totals DROP COLUMN logical_value_bytes")
        connection.execute("ALTER TABLE source_totals DROP COLUMN unmeasured_events")
        connection.execute("ALTER TABLE history_metadata DROP COLUMN backfill_last_id")
        connection.execute("PRAGMA user_version = 4")
    monitor = EventHistoryMonitor(
        PluginConfig(event_history_enabled=False),
        store,
        object(),  # type: ignore[arg-type]
    )

    async def unexpected_stream() -> None:
        pytest.fail("disabled history must not start a Miniserver stream")

    monkeypatch.setattr(monitor, "_run", unexpected_stream)
    await monitor.start()
    assert monitor._backfill_task is not None
    await asyncio.wait_for(monitor._backfill_task, 2)
    assert monitor._task is None
    assert monitor.status == "disabled"
    assert store.snapshot((source,)).sources[0].logical_value_bytes == 2
    await monitor.close()


@pytest.mark.asyncio
async def test_monitor_records_updates_following_the_initial_baseline_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ("control", "state")
    recorded: list[tuple[object, object]] = []
    transition_recorded = threading.Event()

    class Store:
        def initialize(self) -> None:
            pass

        def begin_coverage(self, _sources: object, *, started_at: float) -> None:
            assert started_at > 0

        def record_transition(
            self,
            _control_uuid: str,
            _state_uuid: str,
            *,
            old_value: object,
            new_value: object,
            **_: object,
        ) -> None:
            recorded.append((old_value, new_value))
            transition_recorded.set()

        def end_coverage(self, _sources: object, *, ended_at: float, outcome: str) -> None:
            assert ended_at > 0
            assert outcome == "disconnected"

    class Token:
        def destroy(self) -> None:
            pass

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return LoxoneStructure(
                identity=LoxoneIdentity("service", "serial"),
                last_modified="",
                rooms=(),
                categories=(),
                controls=(
                    Control(
                        *source[:1], "Control", "Switch", None, None, None, (("State", source[1]),)
                    ),
                ),
            )

        async def state_events(self):
            yield (StateEvent(uuid="state", value=0.0), StateEvent(uuid="state", value=1.0))
            await asyncio.Future()

        async def close(self) -> None:
            pass

    class Client:
        async def acquire_token(self, _username: str, _password: str) -> Token:
            return Token()

        async def open_session(self, _token: Token) -> Session:
            return Session()

    class Credentials:
        async def load(self) -> tuple[str, str]:
            return "service", "password"

    attempts: list[tuple[str, str, bool]] = []

    class Coordinator:
        async def attempt(
            self,
            operation: object,
            *,
            owner: str,
            phase: str,
            allow_cooldown_probe: bool = True,
            busy_wait_seconds: float = 0,
        ) -> object:
            attempts.append((owner, phase, allow_cooldown_probe))
            return await operation()  # type: ignore[operator]

    monkeypatch.setattr("mcpserver.loxone.client.LoxoneClient", lambda *_args, **_kwargs: Client())
    monitor = EventHistoryMonitor(
        PluginConfig(
            loxone_endpoint="https://miniserver.example",
            event_history_enabled=True,
            event_history_sources=(source,),
        ),
        Store(),  # type: ignore[arg-type]
        Credentials(),
        Coordinator(),  # type: ignore[arg-type]
    )
    task = asyncio.create_task(monitor._run())

    assert await asyncio.to_thread(transition_recorded.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert recorded == [(0.0, 1.0)]
    assert await monitor.validate_source(*source) == ("Control", "Switch", "State")
    assert attempts == [
        ("runtime_event_stream", "session_establishment", True),
        ("local_admin", "session_establishment", False),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("busy_phase", ["session_establishment"])
async def test_admin_structure_waits_for_concurrent_authentication(
    tmp_path, monkeypatch, busy_phase
):
    from mcpserver.loxone.auth_diagnostics import (
        MiniserverAuthCoordinator,
        _interprocess_lock,
    )

    path = (tmp_path / "auth-diagnostics.json").resolve()
    coordinator = MiniserverAuthCoordinator(path)
    lock_path = path.with_name(f".{path.name}.lock")
    lock = _interprocess_lock(lock_path)
    released = asyncio.Event()
    release_task = None
    loaded = []
    cleaned = []

    async def occupy():
        nonlocal release_task
        lock.__enter__()

        async def release():
            await asyncio.sleep(0.2)
            lock.__exit__(None, None, None)
            released.set()

        release_task = asyncio.create_task(release())

    class Token:
        def destroy(self):
            cleaned.append("token")

    class Session:
        async def load_structure(self):
            loaded.append(released.is_set())
            return LoxoneStructure(LoxoneIdentity("service", "serial"), "", (), (), ())

        async def close(self):
            cleaned.append("session")

    class Client:
        async def acquire_token(self, _username, _password):
            return Token()

        async def open_session(self, _token):
            return Session()

    class Credentials:
        async def load(self):
            return "service", "password"

    class Coordinator:
        async def attempt(self, operation, **kwargs):
            if kwargs["phase"] == busy_phase:
                await occupy()
            return await coordinator.attempt(operation, **kwargs)

    monkeypatch.setattr("mcpserver.loxone.client.LoxoneClient", lambda *_a, **_kw: Client())
    monitor = EventHistoryMonitor(
        PluginConfig(loxone_endpoint="https://miniserver.example"),
        EventHistoryStore(
            (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
        ),
        Credentials(),
        Coordinator(),  # type: ignore[arg-type]
    )
    try:
        await monitor.visible_structure()
        assert loaded == [True]
        assert cleaned == ["session", "token"]
    finally:
        if release_task is not None:
            await release_task


@pytest.mark.asyncio
async def test_admin_structure_authentication_shares_one_wait_deadline(tmp_path, monkeypatch):
    from mcpserver.loxone.auth_diagnostics import MiniserverAuthenticationSuppressed

    clock = [100.0]
    waits = []
    cleaned = []

    class Token:
        def destroy(self):
            cleaned.append("token")

    class Client:
        async def acquire_token(self, _username, _password):
            pytest.fail("an exhausted authentication wait must not acquire a token")

        async def open_session(self, _token):
            pytest.fail("an exhausted authentication wait must not open a session")

    class Credentials:
        async def load(self):
            return "service", "password"

    class Coordinator:
        async def attempt(self, operation, **kwargs):
            waits.append(kwargs["busy_wait_seconds"])
            assert kwargs["allow_cooldown_probe"] is False
            raise MiniserverAuthenticationSuppressed("busy")

    # Replace only this module's clock, not the event loop or coordinator clock.
    from types import SimpleNamespace

    monkeypatch.setattr(
        "mcpserver.loxone.service_access.time",
        SimpleNamespace(monotonic=lambda: clock[0], time=time.time),
    )
    monkeypatch.setattr("mcpserver.loxone.client.LoxoneClient", lambda *_a, **_kw: Client())
    monitor = EventHistoryMonitor(
        PluginConfig(loxone_endpoint="https://miniserver.example"),
        EventHistoryStore(
            (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
        ),
        Credentials(),
        Coordinator(),  # type: ignore[arg-type]
    )
    with pytest.raises(MiniserverAuthenticationSuppressed):
        await monitor.visible_structure()
    assert waits == [15.0]
    assert cleaned == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_reason"),
    [
        ("local event history is unavailable", "store_unavailable"),
        ("local event history size limit cannot be enforced", "size_enforcement_failed"),
    ],
)
async def test_monitor_reports_storage_failure_during_run(
    monkeypatch: pytest.MonkeyPatch, message: str, expected_reason: str
) -> None:
    backoff_started = asyncio.Event()

    class Store:
        def initialize(self) -> None:
            raise EventHistoryUnavailable(message)

    class Credentials:
        async def load(self) -> tuple[str, str]:
            pytest.fail("storage failure must stop before authentication")

    async def backoff(_seconds: float) -> None:
        backoff_started.set()
        await asyncio.Future()

    monkeypatch.setattr("mcpserver.loxone.event_history.asyncio.sleep", backoff)
    monitor = EventHistoryMonitor(
        PluginConfig(event_history_enabled=True, event_history_sources=(("control", "state"),)),
        Store(),  # type: ignore[arg-type]
        Credentials(),
    )
    task = asyncio.create_task(monitor._run())
    await asyncio.wait_for(backoff_started.wait(), 1)
    assert monitor.runtime_status()["reason"] == expected_reason
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_monitor_preserves_unsupported_value_reason_during_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ("control", "state")
    backoff_started = asyncio.Event()

    class Store:
        def initialize(self) -> None:
            pass

    class Token:
        def destroy(self) -> None:
            pass

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return LoxoneStructure(
                identity=LoxoneIdentity("service", "serial"),
                last_modified="",
                rooms=(),
                categories=(),
                controls=(
                    Control(
                        "control", "Control", "Switch", None, None, None, (("State", "state"),)
                    ),
                ),
            )

        async def state_events(self):
            yield (StateEvent(uuid="state", value={"unsupported": True}),)

        async def close(self) -> None:
            pass

    class Client:
        async def acquire_token(self, _username: str, _password: str) -> Token:
            return Token()

        async def open_session(self, _token: Token) -> Session:
            return Session()

    class Credentials:
        async def load(self) -> tuple[str, str]:
            return "service", "password"

    async def backoff(_seconds: float) -> None:
        backoff_started.set()
        await asyncio.Future()

    monkeypatch.setattr("mcpserver.loxone.client.LoxoneClient", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr("mcpserver.loxone.event_history.asyncio.sleep", backoff)
    monitor = EventHistoryMonitor(
        PluginConfig(
            loxone_endpoint="https://miniserver.example",
            event_history_enabled=True,
            event_history_sources=(source,),
        ),
        Store(),  # type: ignore[arg-type]
        Credentials(),
    )
    task = asyncio.create_task(monitor._run())
    await asyncio.wait_for(backoff_started.wait(), 1)
    assert monitor.runtime_status()["reason"] == "unsupported_value"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("coordinated", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "credentials",
        "client",
        "token_acquisition",
        "session_establishment",
        "structure_load",
        "wait",
        "cancel",
    ],
)
async def test_admin_structure_numeric_subphases(tmp_path, monkeypatch, coordinated, failure):
    from types import SimpleNamespace

    from mcpserver.loxone.auth_diagnostics import MiniserverAuthenticationBusy

    clock = [0]
    cleaned = []

    def advance(ms):
        clock[0] += ms * 1_000_000

    def fail(phase):
        if failure == phase:
            raise RuntimeError("private-token-name-endpoint-project-uuid")

    class Token:
        def destroy(self):
            cleaned.append("token")

    class Session:
        async def load_structure(self):
            advance(7)
            if failure == "cancel":
                raise asyncio.CancelledError
            fail("structure_load")
            return LoxoneStructure(LoxoneIdentity("private-name", "private-serial"), "", (), (), ())

        async def close(self):
            advance(11)
            cleaned.append("session")

    class Client:
        async def acquire_token(self, username, password):
            advance(3)
            fail("token_acquisition")
            return Token()

        async def open_session(self, token):
            advance(5)
            fail("session_establishment")
            return Session()

    class Credentials:
        async def load(self):
            fail("credentials")
            return "private-name", "private-password"

    class Coordinator:
        async def attempt(self, operation, **kwargs):
            advance(13)
            if failure == "wait":
                raise MiniserverAuthenticationBusy("private-endpoint")
            result = await operation()
            advance(17)  # Post-operation persistence is not coordinator wait.
            return result

    monkeypatch.setattr(
        "mcpserver.loxone.event_history.time",
        SimpleNamespace(
            perf_counter_ns=lambda: clock[0],
            monotonic=lambda: clock[0] / 1e9,
            time=time.time,
        ),
    )

    from mcpserver.loxone import event_history

    monkeypatch.setattr("mcpserver.loxone.service_access.time", event_history.time)

    def client(*_a, **_kw):
        fail("client")
        return Client()

    monkeypatch.setattr("mcpserver.loxone.client.LoxoneClient", client)
    monitor = EventHistoryMonitor(
        PluginConfig(loxone_endpoint="https://private-endpoint.example"),
        EventHistoryStore(
            (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
        ),
        Credentials(),
        Coordinator() if coordinated else None,
    )
    timing = {}
    effective_failure = failure if failure != "wait" or coordinated else None
    if effective_failure:
        error = (
            asyncio.CancelledError
            if failure == "cancel"
            else (MiniserverAuthenticationBusy if failure == "wait" else RuntimeError)
        )
        with pytest.raises(error):
            await monitor.visible_structure(timing=timing)
    else:
        await monitor.visible_structure(timing=timing)
    expected = {"selector_coordinator_wait_ms": 0.0}
    if effective_failure in {"credentials", "client"}:
        expected = {}
    elif effective_failure == "wait":
        expected["selector_coordinator_wait_ms"] = 13.0
    else:
        expected["selector_token_acquisition_ms"] = 3.0
        if coordinated:
            expected["selector_coordinator_wait_ms"] += 13.0
        if effective_failure != "token_acquisition":
            expected["selector_session_establishment_ms"] = 5.0
            if effective_failure != "session_establishment":
                expected["selector_structure_load_ms"] = 7.0
    assert timing == expected
    assert "private" not in repr(timing)
    assert cleaned == (
        []
        if effective_failure in {"credentials", "client", "wait", "token_acquisition"}
        else (["token"] if effective_failure == "session_establishment" else ["session", "token"])
    )
