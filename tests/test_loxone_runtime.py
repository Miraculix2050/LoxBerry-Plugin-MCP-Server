from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
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
from mcpserver.loxone.client import (
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    LoxoneToken,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeUnavailable,
    _ConnectionRecord,
    _FamilyLocks,
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


def _project_runtime(**kwargs) -> LoxoneRuntime:
    return LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(),  # type: ignore[arg-type]
        **kwargs,
    )


def test_structure_reuse_has_only_existing_record_owners() -> None:
    runtime = _project_runtime(max_active_sessions=2)
    first = replace(_structure("current"), parse_identity="exact-input")
    runtime._records = {"first": SimpleNamespace(structure=first)}
    assert runtime._has_received_structure("reader")
    assert not runtime._has_received_structure("other-reader")
    assert runtime._find_received_structure("exact-input") is first
    assert runtime._find_received_structure("different-input") is None
    assert runtime._find_received_structure("") is None
    runtime._records.clear()
    assert runtime._find_received_structure("exact-input") is None
    assert not runtime._has_received_structure("reader")


@pytest.mark.asyncio
async def test_equal_structure_updates_exact_input_without_changing_generation() -> None:
    runtime = _project_runtime()
    task = asyncio.create_task(asyncio.sleep(60))
    previous = replace(_structure("current"), parse_identity="old-bytes")
    received = replace(previous, parse_identity="new-equivalent-bytes")
    assert received == previous
    record = _ConnectionRecord(previous, frozenset(), _Session(), task)
    runtime._records = {"family": record}
    runtime.token_store = SimpleNamespace(get=lambda *_args: object())
    session = SimpleNamespace(load_structure=AsyncMock(return_value=received), close=AsyncMock())
    runtime._open_session = AsyncMock(return_value=session)
    generation = record.generation
    try:
        await runtime._refresh_structure(_access(), record, fresh_visibility=True)
        assert record.structure is received
        assert record.generation == generation
        assert runtime._find_received_structure("old-bytes") is None
        assert runtime._find_received_structure("new-equivalent-bytes") is received
        session.load_structure.assert_awaited_once()
        session.close.assert_awaited_once()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_project_burst_does_not_starve_other_reads() -> None:
    runtime = _project_runtime()
    started, release = asyncio.Event(), asyncio.Event()

    async def active_project() -> None:
        async with runtime.project_call_slot(_access()):
            started.set()
            await release.wait()

    active = asyncio.create_task(active_project())
    await started.wait()
    try:

        async def excess_project(index: int) -> None:
            access = _access().model_copy(update={"family_id": f"family-{index}"})
            with pytest.raises(RuntimeUnavailable, match="already active"):
                async with runtime.project_call_slot(access):
                    pytest.fail("concurrent project work was admitted")

        await asyncio.wait_for(asyncio.gather(*(excess_project(i) for i in range(20))), 1)
        async with asyncio.timeout(1), runtime.call_slot(_access()):
            pass
        assert len(runtime._project_rate) == 1
    finally:
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
    async with runtime.project_call_slot(_access()):
        pass


@pytest.mark.asyncio
async def test_project_rate_is_shared_across_families_and_expires(monkeypatch) -> None:
    runtime = _project_runtime()
    now = 100.0
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now)
    for index in range(12):
        async with runtime.project_call_slot(
            _access().model_copy(update={"family_id": f"family-{index}"})
        ):
            pass
    with pytest.raises(RuntimeUnavailable, match="rate limit") as error:
        async with runtime.project_call_slot(_access()):
            pytest.fail("global project budget was bypassed")
    assert error.value.retry_after_seconds == 60
    async with runtime.call_slot(_access()):
        pass
    now += 60
    async with runtime.project_call_slot(_access()):
        pass


@pytest.mark.asyncio
async def test_project_admission_checks_authorization_and_releases_on_failure() -> None:
    validator = AsyncMock(return_value=False)
    runtime = _project_runtime(validate_access=validator)
    with pytest.raises(PermissionError):
        async with runtime.project_call_slot(_access()):
            pytest.fail("invalid access admitted")
    assert not runtime._project_rate
    validator.return_value = True
    with pytest.raises(ValueError):
        async with runtime.project_call_slot(_access()):
            raise ValueError("failed project")
    assert len(runtime._project_rate) == 1
    async with runtime.project_call_slot(_access()):
        pass
    with pytest.raises(ControlOperationError, match="history"):
        async with runtime.history_project_call_slot(_access()):
            pytest.fail("history scope bypassed")
    history_access = _access().model_copy(update={"scopes": [READ_SCOPE, HISTORY_SCOPE]})
    with pytest.raises(ControlOperationError, match="activation"):
        async with runtime.history_project_call_slot(history_access):
            pytest.fail("history activation bypassed")
    runtime.history_enabled = True
    async with runtime.history_project_call_slot(history_access):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", ["read", "history"])
async def test_throttled_family_cannot_exhaust_other_families_project_budget(budget) -> None:
    runtime = _project_runtime(
        requests_per_minute=1 if budget == "read" else 60,
        history_requests_per_minute=1,
        history_enabled=True,
    )
    access = _access().model_copy(update={"scopes": [READ_SCOPE, HISTORY_SCOPE]})
    slot = runtime.project_call_slot if budget == "read" else runtime.history_project_call_slot
    family_slot = runtime.call_slot if budget == "read" else runtime.history_call_slot
    async with family_slot(access):
        pass
    for _ in range(12):
        with pytest.raises((RuntimeUnavailable, ControlOperationError)):
            async with slot(access):
                pytest.fail("throttled family admitted project work")
    assert not runtime._project_rate
    other = access.model_copy(update={"family_id": "other-family"})
    async with slot(other):
        pass
    assert len(runtime._project_rate) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [False, True])
async def test_project_budget_is_not_charged_when_current_access_is_rejected(history) -> None:
    validator = AsyncMock(side_effect=[True, False])
    runtime = _project_runtime(validate_access=validator, history_enabled=True)
    access = _access().model_copy(update={"scopes": [READ_SCOPE, HISTORY_SCOPE]})
    slot = runtime.history_project_call_slot if history else runtime.project_call_slot
    with pytest.raises((PermissionError, ControlOperationError)):
        async with slot(access):
            pytest.fail("invalid current access admitted project work")
    assert not runtime._project_rate
    assert not runtime._project_admission.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [False, True])
async def test_cancelled_project_wait_does_not_charge_global_budget(history) -> None:
    runtime = _project_runtime(max_parallel_calls=1, history_enabled=True)
    access = _access().model_copy(update={"scopes": [READ_SCOPE, HISTORY_SCOPE]})
    slot = runtime.history_project_call_slot if history else runtime.project_call_slot

    async def waiting_project() -> None:
        async with slot(access):
            pytest.fail("occupied shared slot was bypassed")

    async with runtime.call_slot(access.model_copy(update={"family_id": "holding-family"})):
        task = asyncio.create_task(waiting_project())
        try:
            async with asyncio.timeout(1):
                while not runtime._project_admission.locked():
                    await asyncio.sleep(0)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not runtime._project_rate
        assert not runtime._project_admission.locked()
    async with slot(access):
        pass
    assert len(runtime._project_rate) == 1


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
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._closed = False
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
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._closed = False
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
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._closed = False
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
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._closed = False
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
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._closed = False
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
async def test_history_same_marker_rights_change_rejects_cached_control() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Old right", "Switch", None, None, "action", ())
    old = LoxoneStructure(LoxoneIdentity("reader", "serial"), "same", (), (), (control,))
    current = _structure("same")

    class Session(_Session):
        async def structure_version(self) -> str:
            raise AssertionError("the marker cannot establish current History visibility")

        async def load_structure(self) -> LoxoneStructure:
            return current

    runtime = object.__new__(LoxoneRuntime)
    runtime.history_enabled = True
    runtime.token_store = Store()
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
    assert record.structure is old
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_history_fresh_visibility_failure_never_returns_cached_control() -> None:
    class Store:
        def get(self, *_parts: str) -> object:
            return object()

    control = Control("control", "Old right", "Switch", None, None, "action", ())
    old = LoxoneStructure(LoxoneIdentity("reader", "serial"), "same", (), (), (control,))

    class Session(_Session):
        async def load_structure(self) -> LoxoneStructure:
            raise LoxoneConnectionError("structure unavailable")

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
            pytest.fail("cached control was returned after fresh structure failure")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_native_history_normalization_skips_invalid_and_bounds_entries() -> None:
    raw = [{"ts": 123, "what": "valid", "trigger": "", "triggerType": "", "impacts": []}]
    raw += [{"ts": True, "what": "invalid"}] * 1001
    entries = runtime_module.normalize_control_history_entries(raw)
    assert len(entries) == 1
    assert entries[0].what == "valid"


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_window_current_readability_does_not_establish_native_history(available):
    control = Control(
        "monitor",
        "Window overview",
        "WindowMonitor",
        None,
        None,
        "action",
        (("windowStates", "state"),),
        has_history=available,
    )
    session = SimpleNamespace(
        control_history=AsyncMock(
            return_value=[
                {
                    "ts": 123,
                    "what": "Contact changed",
                    "trigger": "",
                    "triggerType": "",
                    "impacts": [],
                }
            ]
        )
    )

    @asynccontextmanager
    async def history_session(*_args):
        yield control, session

    runtime = object.__new__(LoxoneRuntime)
    runtime._history_session = history_session
    if available:
        returned, entries = await runtime.get_control_history(_access(), "monitor")
        assert returned is control and entries[0].what == "Contact changed"
        assert not hasattr(entries[0], "semantic_value")
        session.control_history.assert_awaited_once_with("action")
    else:
        with pytest.raises(ControlOperationError) as exc:
            await runtime.get_control_history(_access(), "monitor")
        assert exc.value.code == "not_found"
        session.control_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_marker_authentication_respects_shared_breaker(tmp_path: Path) -> None:
    runtime = object.__new__(LoxoneRuntime)
    open_session = AsyncMock(side_effect=LoxoneSourceIpBlocked("blocked"))
    runtime.client = SimpleNamespace(open_session=open_session, timeout_seconds=10)
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

    async def disconnect(family_id: str, *, reason: str = "local_disconnect") -> None:
        closed.append(family_id)

    runtime._records = {"one": object(), "two": object()}
    runtime._admission_lock = asyncio.Lock()
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
async def test_connect_waits_for_the_initial_state_batch(caplog) -> None:
    caplog.set_level("INFO", logger="mcpserver.auth.lifecycle")
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
    events = [
        entry.getMessage().split(" event=")[1].split()[0]
        for entry in caplog.records
        if entry.name == "mcpserver.auth.lifecycle"
    ]
    assert events == ["connection_opened", "connection_closed"]


@pytest.mark.asyncio
async def test_connect_fails_closed_when_state_stream_ends_before_initial_batch(caplog) -> None:
    caplog.set_level("INFO", logger="mcpserver.auth.lifecycle")
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
    events = [
        entry.getMessage().split(" event=")[1].split()[0]
        for entry in caplog.records
        if entry.name == "mcpserver.auth.lifecycle"
    ]
    assert events == ["connection_opened", "connection_closed"]
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

    async def disconnect(family_id: str, *, reason: str = "local_disconnect") -> None:
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,reason",
    [
        (LoxoneConnectionError, "structure_refresh_connection"),
        (runtime_module.LoxoneProtocolError, "structure_refresh_protocol"),
        (runtime_module.LoxoneTokenStoreError, "structure_refresh_token"),
        (TimeoutError, "structure_refresh_timeout"),
        (ValueError, "structure_refresh_unknown"),
    ],
)
@pytest.mark.parametrize(
    "phase",
    [
        "token_lookup",
        "session_establishment",
        "structure_version",
        "structure_load",
        "session_close",
    ],
)
async def test_refresh_availability_categories_and_phases(failure, reason, phase, caplog) -> None:
    secret = "private-token@192.0.2.9/hidden-control"

    def fail_at(current):
        if phase == current:
            raise failure(secret)

    class Store:
        def get(self, *_parts):
            fail_at("token_lookup")
            return object()

    class Session:
        async def structure_version(self):
            fail_at("structure_version")
            return "new"

        async def load_structure(self):
            fail_at("structure_load")
            return _structure("new")

        async def close(self):
            fail_at("session_close")

    class Client:
        async def open_session(self, _token):
            fail_at("session_establishment")
            return Session()

    runtime = object.__new__(LoxoneRuntime)
    runtime.token_store = Store()
    runtime.client = Client()
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("old"), frozenset(), _Session(), task)
    runtime._records = {"family": record}
    try:
        with pytest.raises(RuntimeUnavailable) as caught:
            await runtime._refresh_structure(_access(), record)
        exc = caught.value
        assert exc.reason == reason
        assert exc.phase == phase
        assert exc.retry_after_seconds is None
        assert str(exc) == "Miniserver structure refresh failed"
        assert secret not in caplog.text
        assert record.structure.last_modified == "old"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_local_budget_retry_is_rounded_bounded_and_family_scoped(monkeypatch) -> None:
    from collections import defaultdict, deque

    runtime = object.__new__(LoxoneRuntime)
    runtime._rate = defaultdict(
        deque, {"family": deque([100.25, 105.0]), "other": deque([130.0, 130.0])}
    )
    runtime._rate_limit = 2
    runtime._parallel = asyncio.Semaphore(1)
    runtime._prune_rate_state = lambda _now: None
    runtime._require_access = AsyncMock()
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 140.0)
    with pytest.raises(RuntimeUnavailable) as caught:
        async with runtime.call_slot(_access()):
            pytest.fail("rejected budget entered call")
    assert caught.value.reason == "local_rate_limit"
    assert caught.value.phase == "local_budget"
    assert caught.value.retry_after_seconds == 21
    assert list(runtime._rate["family"]) == [100.25, 105.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 160.25)
    async with runtime.call_slot(_access()):
        pass
    assert list(runtime._rate["family"]) == [105.0, 160.25]
    assert list(runtime._rate["other"]) == [130.0, 130.0]


@pytest.mark.asyncio
async def test_missing_refresh_token_has_token_diagnostic_without_session() -> None:
    runtime = object.__new__(LoxoneRuntime)
    runtime.token_store = SimpleNamespace(get=lambda *_args: None)
    runtime.client = SimpleNamespace(open_session=AsyncMock())
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("old"), frozenset(), _Session(), task)
    runtime._records = {"family": record}
    try:
        with pytest.raises(RuntimeUnavailable) as caught:
            await runtime._refresh_structure(_access(), record, fresh_visibility=True)
        assert caught.value.reason == "structure_refresh_token"
        assert caught.value.phase == "token_lookup"
        assert caught.value.retry_after_seconds is None
        runtime.client.open_session.assert_not_awaited()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_cancelled_refresh_is_not_converted_to_availability() -> None:
    runtime = object.__new__(LoxoneRuntime)
    session = SimpleNamespace(
        load_structure=AsyncMock(side_effect=asyncio.CancelledError), close=AsyncMock()
    )
    runtime.token_store = SimpleNamespace(get=lambda *_args: object())
    runtime.client = SimpleNamespace(open_session=AsyncMock(return_value=session))
    task = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("old"), frozenset(), _Session(), task)
    runtime._records = {"family": record}
    try:
        with pytest.raises(asyncio.CancelledError):
            await runtime._refresh_structure(_access(), record, fresh_visibility=True)
        session.close.assert_awaited_once()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("delay", [0, 61, -1, True, 1.5])
def test_availability_retry_rejects_invalid_delays(delay) -> None:
    from mcpserver.availability import AvailabilityReason

    assert (
        RuntimeUnavailable(
            "unavailable", reason=AvailabilityReason.LOCAL_RATE_LIMIT, retry_after_seconds=delay
        ).retry_after_seconds
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("close_reason", ["shutdown", "idle_eviction", "oauth_revocation"])
async def test_disconnect_logs_one_terminal_close_with_initiating_reason(close_reason, caplog):
    access = _access()
    access.family_id = "private-disconnect-family"
    runtime = object.__new__(LoxoneRuntime)
    runtime.cache = UserStateCache()
    runtime._locks = runtime_module._FamilyLocks()
    runtime._prune_rate_state = lambda now: None
    started = asyncio.Event()

    async def pump(subject, record):
        started.set()
        await asyncio.Event().wait()

    runtime._pump_events = pump
    placeholder = asyncio.create_task(asyncio.sleep(0))
    record = _ConnectionRecord(_structure("current"), frozenset(), _Session(), placeholder)
    record.task = asyncio.create_task(
        runtime._maintain(access, SimpleNamespace(valid_until=2000000000), record)
    )
    runtime._records = {access.family_id: record}
    await started.wait()
    caplog.set_level("INFO", logger="mcpserver.auth.lifecycle")
    await runtime.disconnect(access.family_id, reason=close_reason)
    await runtime.disconnect(access.family_id, reason=close_reason)
    closes = [entry for entry in caplog.records if "event=connection_closed " in entry.getMessage()]
    assert len(closes) == 1
    assert f"reason={close_reason}" in closes[0].getMessage()
    assert "outcome=closed" in closes[0].getMessage()
    assert access.family_id not in closes[0].getMessage()
