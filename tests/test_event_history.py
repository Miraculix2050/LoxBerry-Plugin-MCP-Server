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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
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
        async def _credentials(self) -> tuple[str, str]:
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
        ("runtime_event_stream", "token_acquisition", True),
        ("runtime_event_stream", "session_establishment", True),
        ("local_admin", "token_acquisition", False),
        ("local_admin", "session_establishment", False),
    ]


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
        async def _credentials(self) -> tuple[str, str]:
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
        async def _credentials(self) -> tuple[str, str]:
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
