from __future__ import annotations

import asyncio
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
