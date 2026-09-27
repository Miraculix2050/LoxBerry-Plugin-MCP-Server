from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import mcpserver.loxone.runtime as runtime_module
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import LoxoneConnectionError, LoxoneSourceIpBlocked, LoxoneToken
from mcpserver.loxone.events import LoxoneProtocolError, StateEvent
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    ControlOperationError,
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
async def test_fresh_project_visibility_detects_same_marker_rights_change() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    changed_structure = LoxoneStructure(
        LoxoneIdentity("reader", "serial"),
        "current",
        (),
        (),
        (Control("visible", "Visible", "Switch", None, None, None, ()),),
    )

    class RefreshSession(_Session):
        async def structure_version(self) -> str:
            raise AssertionError("fresh visibility must load the filtered structure")

        async def load_structure(self) -> LoxoneStructure:
            return changed_structure

    class Client:
        async def open_session(self, _token: object) -> RefreshSession:
            return RefreshSession()

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(
        _structure("current"), frozenset(), _Session(), task, last_structure_check=10**9
    )
    runtime._records = {"family": record}
    runtime._locks = defaultdict(asyncio.Lock)
    runtime._prune_sessions = lambda _subject: asyncio.sleep(0)  # type: ignore[method-assign]
    runtime.token_store = Store()
    runtime.client = Client()
    runtime.cache = UserStateCache()
    runtime.structure_refresh_seconds = 300

    snapshot = await runtime.snapshot(_access(), fresh_visibility=True)

    assert snapshot.structure is changed_structure
    assert snapshot.structure_generation == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_fresh_project_visibility_timeout_is_unavailable() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    class RefreshSession(_Session):
        async def load_structure(self) -> LoxoneStructure:
            raise TimeoutError("private transport detail")

    class Client:
        async def open_session(self, _token: object) -> RefreshSession:
            return RefreshSession()

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(
        _structure("current"), frozenset(), _Session(), task, last_structure_check=10**9
    )
    runtime._records = {"family": record}
    runtime._locks = defaultdict(asyncio.Lock)
    runtime._prune_sessions = lambda _subject: asyncio.sleep(0)  # type: ignore[method-assign]
    runtime.token_store = Store()
    runtime.client = Client()
    runtime.structure_refresh_seconds = 300

    with pytest.raises(RuntimeUnavailable, match="structure refresh failed"):
        await runtime.snapshot(_access(), fresh_visibility=True)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_history_visibility_loads_structure_without_cached_runtime_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Visible", "Switch", None, None, "action", ())
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "current", (), (), (control,))

    class Session(_Session):
        async def structure_version(self) -> str:
            raise AssertionError("history must not issue an optional marker request")

        async def load_structure(self) -> LoxoneStructure:
            return structure

    session = Session()
    runtime = object.__new__(LoxoneRuntime)
    runtime.history_enabled = True
    runtime.token_store = Store()
    runtime._records = {}

    @asynccontextmanager
    async def call_slot(_access: StoredAccessToken):
        yield

    async def open_session(_token: object, **_kwargs: object) -> Session:
        return session

    runtime.history_call_slot = call_slot  # type: ignore[method-assign]
    runtime._open_session = open_session  # type: ignore[method-assign]
    access = _access()
    access.scopes.append(HISTORY_SCOPE)
    with caplog.at_level(logging.DEBUG):
        async with runtime._history_session(access, "control") as (visible, used_session):
            assert visible is control
            assert used_session is session


@pytest.mark.asyncio
async def test_history_visibility_uses_authenticated_marker_for_cached_structure() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Visible", "Switch", None, None, "action", ())
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "current", (), (), (control,))

    class Session(_Session):
        async def structure_version(self) -> str:
            return "current"

        async def load_structure(self) -> LoxoneStructure:
            raise AssertionError("an unchanged marker must reuse the cached structure")

    session = Session()
    runtime = object.__new__(LoxoneRuntime)
    runtime.history_enabled = True
    runtime.token_store = Store()
    task = asyncio.create_task(asyncio.sleep(60))
    runtime._records = {"family": _ConnectionRecord(structure, frozenset(), _Session(), task)}

    @asynccontextmanager
    async def call_slot(_access: StoredAccessToken):
        yield

    async def open_session(_token: object, **_kwargs: object) -> Session:
        return session

    runtime.history_call_slot = call_slot  # type: ignore[method-assign]
    runtime._open_session = open_session  # type: ignore[method-assign]
    access = _access()
    access.scopes.append(HISTORY_SCOPE)
    async with runtime._history_session(access, "control") as (visible, used_session):
        assert visible is control
        assert used_session is session
    assert runtime._records["family"].last_structure_check > 0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_history_marker_change_rejects_newly_hidden_control() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Old right", "Switch", None, None, "action", ())
    old = LoxoneStructure(LoxoneIdentity("reader", "serial"), "old", (), (), (control,))
    current = _structure("new")

    class Session(_Session):
        async def structure_version(self) -> str:
            return "new"

        async def load_structure(self) -> LoxoneStructure:
            return current

    runtime = object.__new__(LoxoneRuntime)
    runtime.history_enabled = True
    runtime.token_store = Store()
    runtime.cache = UserStateCache()
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(old, frozenset(), _Session(), task)
    runtime._records = {"family": record}

    @asynccontextmanager
    async def call_slot(_access: StoredAccessToken):
        yield

    async def open_session(_token: object, **_kwargs: object) -> Session:
        return Session()

    runtime.history_call_slot = call_slot  # type: ignore[method-assign]
    runtime._open_session = open_session  # type: ignore[method-assign]
    access = _access()
    access.scopes.append(HISTORY_SCOPE)
    with pytest.raises(ControlOperationError, match="control is not visible"):
        async with runtime._history_session(access, "control"):
            pytest.fail("revoked control was returned")
    assert record.structure is current
    assert record.generation == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_history_marker_failure_never_returns_cached_control() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Old right", "Switch", None, None, "action", ())
    old = LoxoneStructure(LoxoneIdentity("reader", "serial"), "old", (), (), (control,))

    class Session(_Session):
        async def structure_version(self) -> str:
            raise LoxoneConnectionError("marker unavailable")

        async def load_structure(self) -> LoxoneStructure:
            raise AssertionError("a failed marker must not use the cached structure")

    runtime = object.__new__(LoxoneRuntime)
    runtime.history_enabled = True
    runtime.token_store = Store()
    task = asyncio.create_task(asyncio.sleep(60))
    runtime._records = {"family": _ConnectionRecord(old, frozenset(), _Session(), task)}

    @asynccontextmanager
    async def call_slot(_access: StoredAccessToken):
        yield

    async def open_session(_token: object, **_kwargs: object) -> Session:
        return Session()

    runtime.history_call_slot = call_slot  # type: ignore[method-assign]
    runtime._open_session = open_session  # type: ignore[method-assign]
    access = _access()
    access.scopes.append(HISTORY_SCOPE)
    with pytest.raises(ControlOperationError, match="Miniserver connection failed"):
        async with runtime._history_session(access, "control"):
            pytest.fail("cached control was returned after marker failure")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_concurrent_history_marker_change_downloads_structure_once() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    downloads = 0
    old = _structure("old")
    current = _structure("new")

    class Session(_Session):
        async def structure_version(self) -> str:
            return "new"

        async def load_structure(self) -> LoxoneStructure:
            nonlocal downloads
            downloads += 1
            started.set()
            await release.wait()
            return current

    runtime = object.__new__(LoxoneRuntime)
    runtime.cache = UserStateCache()
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(old, frozenset(), _Session(), task)
    runtime._records = {"family": record}
    first = asyncio.create_task(
        runtime._history_visible_structure(_access(), Session(), "first")  # type: ignore[arg-type]
    )
    await started.wait()
    second = asyncio.create_task(
        runtime._history_visible_structure(_access(), Session(), "second")  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [current, current]
    assert downloads == 1
    assert record.generation == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_history_structure_change_during_marker_check_fails_closed() -> None:
    old = _structure("old")

    class Session(_Session):
        async def structure_version(self) -> str:
            return "new"

        async def load_structure(self) -> LoxoneStructure:
            return _structure("newer")

    runtime = object.__new__(LoxoneRuntime)
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(old, frozenset(), _Session(), task)
    runtime._records = {"family": record}
    with pytest.raises(LoxoneProtocolError, match="changed during History verification"):
        await runtime._history_visible_structure(  # type: ignore[arg-type]
            _access(), Session(), "trace"
        )
    assert record.structure is old
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_project_marker_authentication_respects_shared_breaker(tmp_path: Path) -> None:
    runtime = object.__new__(LoxoneRuntime)
    open_session = AsyncMock(side_effect=LoxoneSourceIpBlocked("blocked"))
    runtime.client = SimpleNamespace(open_session=open_session)
    runtime.auth_coordinator = MiniserverAuthCoordinator(tmp_path / "auth-state.json")
    token = LoxoneToken("opaque", "reader", "", "SHA256", 9_999_999_999)

    with pytest.raises(LoxoneSourceIpBlocked):
        await runtime.project_marker(token)
    with pytest.raises(MiniserverAuthenticationSuppressed):
        await runtime.project_marker(token)
    open_session.assert_awaited_once_with(token)


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
    await record.task


@pytest.mark.asyncio
async def test_connect_fails_closed_when_state_stream_ends_before_initial_batch() -> None:
    closed = False

    class Session(_Session):
        async def load_structure(self) -> LoxoneStructure:
            return _structure("current")

        async def state_events(self):
            raise LoxoneConnectionError("connection closed")
            yield ()  # pragma: no cover - make this an async generator

        async def close(self) -> None:
            nonlocal closed
            closed = True

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

    with pytest.raises(RuntimeUnavailable, match="state subscription failed"):
        await runtime._connect(_access())
    assert closed
    assert runtime.cache.get("family", "state-1").freshness.name == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_connect_cancellation_closes_unregistered_state_session() -> None:
    state_stream_started = asyncio.Event()
    state_stream_release = asyncio.Event()
    closed = False

    class Session(_Session):
        async def load_structure(self) -> LoxoneStructure:
            return _structure("current")

        async def state_events(self):
            state_stream_started.set()
            await state_stream_release.wait()
            yield ()

        async def close(self) -> None:
            nonlocal closed
            closed = True

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
    await state_stream_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert closed
    assert runtime.cache.get("family", "state-1").freshness.name == "UNAVAILABLE"


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
