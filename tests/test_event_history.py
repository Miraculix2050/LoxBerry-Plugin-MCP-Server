from __future__ import annotations

from mcpserver.loxone.event_history import EventHistoryStore


def test_store_records_typed_transitions_and_pages_them(tmp_path):
    store = EventHistoryStore(
        (tmp_path / "event-history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    source = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
    store.initialize()
    store.begin_coverage((source,), started_at=100.0)
    store.record_transition(*source, observed_at=110.0, old_value=False, new_value=True)
    store.record_transition(*source, observed_at=120.0, old_value="closed", new_value="open")

    page = store.page(*source, start=100.0, end=130.0, limit=10)

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
    store.initialize()

    assert store.page(*source, start=0.0, end=1.0, limit=10).coverage == "not_recorded"
    store.begin_coverage((source,), started_at=10.0)
    store.record_transition(*source, observed_at=11.0, old_value=1.0, new_value=2.0)
    assert store.clear() == 1
    assert store.page(*source, start=0.0, end=20.0, limit=10).coverage == "not_recorded"


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
