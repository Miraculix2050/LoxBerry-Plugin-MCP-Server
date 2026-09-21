from __future__ import annotations

import time

from mcpserver.loxone.event_history import EventHistoryStore


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
