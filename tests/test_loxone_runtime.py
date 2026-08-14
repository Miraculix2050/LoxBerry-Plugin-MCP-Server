from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace

import pytest

import mcpserver.loxone.runtime as runtime_module
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import LoxoneConnectionError
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    LoxoneRuntime,
    RuntimeUnavailable,
    _ConnectionRecord,
)


def _access() -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def _structure(last_modified: str) -> LoxoneStructure:
    return LoxoneStructure(
        identity=LoxoneIdentity("reader", "serial"),
        last_modified=last_modified,
        rooms=(),
        categories=(),
        controls=(),
    )


class _Session:
    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_due_structure_refresh_is_single_flight_and_increments_generation() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    class RefreshSession(_Session):
        async def structure_version(self) -> str:
            return "new"

        async def load_structure(self) -> LoxoneStructure:
            return _structure("new")

    class Client:
        async def open_session(self, _token: object) -> RefreshSession:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return RefreshSession()

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(
        _structure("old"), frozenset(), _Session(), task, last_structure_check=0
    )
    runtime._records = {"family": record}
    runtime._locks = defaultdict(asyncio.Lock)
    runtime._prune_sessions = lambda _subject: asyncio.sleep(0)  # type: ignore[method-assign]
    runtime.token_store = Store()
    runtime.client = Client()
    runtime.cache = UserStateCache()
    runtime.structure_refresh_seconds = 1

    first = asyncio.create_task(runtime.snapshot(_access()))
    await started.wait()
    second = asyncio.create_task(runtime.snapshot(_access()))
    await asyncio.sleep(0)
    assert calls == 1
    release.set()

    snapshots = await asyncio.gather(first, second)
    assert calls == 1
    assert [snapshot.structure_generation for snapshot in snapshots] == [2, 2]
    assert all(snapshot.structure.last_modified == "new" for snapshot in snapshots)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_due_structure_refresh_fails_closed() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    class Client:
        async def open_session(self, _token: object) -> object:
            raise LoxoneConnectionError("unreachable")

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    runtime._records = {
        "family": _ConnectionRecord(
            _structure("old"), frozenset(), _Session(), task, last_structure_check=0
        )
    }
    runtime._locks = defaultdict(asyncio.Lock)
    runtime._prune_sessions = lambda _subject: asyncio.sleep(0)  # type: ignore[method-assign]
    runtime.token_store = Store()
    runtime.client = Client()
    runtime.cache = UserStateCache()
    runtime.structure_refresh_seconds = 1

    with pytest.raises(RuntimeUnavailable, match="structure refresh failed"):
        await runtime.snapshot(_access())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_due_structure_refresh_checks_version_without_reloading_unchanged_structure() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    class RefreshSession(_Session):
        async def structure_version(self) -> str:
            return "current"

        async def load_structure(self) -> LoxoneStructure:
            raise AssertionError("unchanged structure must not be downloaded")

    class Client:
        async def open_session(self, _token: object) -> RefreshSession:
            return RefreshSession()

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(
        _structure("current"), frozenset(), _Session(), task, last_structure_check=0
    )
    runtime._records = {"family": record}
    runtime._locks = defaultdict(asyncio.Lock)
    runtime._prune_sessions = lambda _subject: asyncio.sleep(0)  # type: ignore[method-assign]
    runtime.token_store = Store()
    runtime.client = Client()
    runtime.cache = UserStateCache()
    runtime.structure_refresh_seconds = 1

    snapshot = await runtime.snapshot(_access())

    assert snapshot.structure_generation == 1
    assert snapshot.structure.last_modified == "current"
    assert record.last_structure_check > 0

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runtime_close_disconnects_all_records_without_revoking_tokens() -> None:
    runtime = object.__new__(LoxoneRuntime)
    closed: list[str] = []

    async def disconnect(family_id: str) -> None:
        closed.append(family_id)

    runtime._records = {"one": object(), "two": object()}
    runtime.disconnect = disconnect  # type: ignore[method-assign]

    await runtime.close()

    assert closed == ["one", "two"]


@pytest.mark.asyncio
async def test_event_stream_failure_is_logged_without_payload_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = object.__new__(LoxoneRuntime)
    runtime.cache = UserStateCache()
    runtime.cache.begin_connection("family")

    async def failed_pump(_subject: str, _record: _ConnectionRecord) -> None:
        raise LoxoneConnectionError("private endpoint detail")

    runtime._pump_events = failed_pump  # type: ignore[method-assign]
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("current"), frozenset(), _Session(), task)

    with caplog.at_level("WARNING", logger="mcpserver.loxone.runtime"):
        await runtime._maintain(_access(), SimpleNamespace(valid_until=2_000_000_000), record)

    assert record.connected is False
    assert runtime.cache.get("family", "state-1").freshness.name == "UNAVAILABLE"
    assert (
        "component=state_cache outcome=event_stream_failed error_type=LoxoneConnectionError"
        in caplog.text
    )
    assert "private endpoint detail" not in caplog.text

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_state_batch_populates_cache_before_marking_initial_batch_ready() -> None:
    class EventSession(_Session):
        async def state_events(self):
            yield (StateEvent(uuid="state-1", value=1.0),)

    runtime = object.__new__(LoxoneRuntime)
    runtime.cache = UserStateCache()
    runtime.cache.begin_connection("family")
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("current"), frozenset({"state-1"}), EventSession(), task)

    await runtime._pump_events("family", record)

    assert record.initial_state_batch.is_set()
    assert runtime.cache.get("family", "state-1").value == 1.0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_connect_waits_for_the_initial_state_batch() -> None:
    release = asyncio.Event()

    class Session(_Session):
        async def load_structure(self) -> LoxoneStructure:
            return _structure("current")

        async def state_events(self):
            await release.wait()
            yield ()

    class Client:
        async def open_session(self, _token: object) -> Session:
            return Session()

    runtime = object.__new__(LoxoneRuntime)
    runtime.token_health = None
    runtime.token_store = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(valid_until=2_000_000_000)
    )
    runtime.client = Client()
    runtime.cache = UserStateCache()
    runtime._initial_state_timeout_seconds = 1.0
    task = asyncio.create_task(runtime._connect(_access()))
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    record = await task
    assert record.initial_state_batch.is_set()
    record.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await record.task


@pytest.mark.asyncio
async def test_session_pruning_prefers_idle_then_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object.__new__(LoxoneRuntime)
    runtime.session_idle_seconds = 10
    runtime.max_active_sessions = 2
    runtime._records = {
        "idle": _ConnectionRecord(
            _structure("1"),
            frozenset(),
            _Session(),
            asyncio.create_task(asyncio.sleep(60)),
            last_used=0,
        ),
        "old": _ConnectionRecord(
            _structure("1"),
            frozenset(),
            _Session(),
            asyncio.create_task(asyncio.sleep(60)),
            last_used=100,
        ),
        "new": _ConnectionRecord(
            _structure("1"),
            frozenset(),
            _Session(),
            asyncio.create_task(asyncio.sleep(60)),
            last_used=101,
        ),
    }
    disconnected: list[str] = []

    async def disconnect(family_id: str) -> None:
        disconnected.append(family_id)
        record = runtime._records.pop(family_id)
        record.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await record.task

    runtime.disconnect = disconnect  # type: ignore[method-assign]

    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 110)
    await runtime._prune_sessions("keep")

    assert disconnected == ["idle", "old"]
    runtime._records["new"].task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runtime._records["new"].task
