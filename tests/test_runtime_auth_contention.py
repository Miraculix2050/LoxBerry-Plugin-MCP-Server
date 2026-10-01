"""Fresh visibility while a separate plugin process owns authentication."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_loxone_runtime import _access, _ConnectionRecord, _FamilyLocks, _Session, _structure

import mcpserver.loxone.auth_diagnostics as auth
from mcpserver.auth.provider import CONTROL_SCOPE, HISTORY_SCOPE
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import LoxoneConnectionError, LoxoneSourceIpBlocked, MiniserverEndpoint
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeAuthorizationError,
    RuntimeSnapshot,
    RuntimeUnavailable,
)


@pytest.fixture
def contender(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    coordinator = auth.MiniserverAuthCoordinator(path)
    lock_path = path.with_name(f".{path.name}.lock")
    script = (
        "import sys; from pathlib import Path; "
        "from mcpserver.loxone.auth_diagnostics import _interprocess_lock; "
        "lock = _interprocess_lock(Path(sys.argv[1])); lock.__enter__(); "
        "print('ready', flush=True); sys.stdin.readline(); lock.__exit__(None, None, None)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    waiting = asyncio.Event()
    original = auth._interprocess_lock

    @contextmanager
    def observed(path: Path):
        try:
            with original(path):
                yield
        except auth._InterprocessLockUnavailable:
            waiting.set()
            raise

    monkeypatch.setattr(auth, "_interprocess_lock", observed)

    def release():
        assert process.stdin is not None
        if process.poll() is None:
            process.stdin.write("release\n")
            process.stdin.flush()
            process.wait(timeout=5)

    try:
        yield coordinator, waiting, release
    finally:
        release()
        process.communicate(timeout=5)
        assert process.returncode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["release", "timeout", "cancel", "revoke", "shutdown"])
async def test_fresh_refresh_under_cross_process_lock(contender, outcome):
    coordinator, waiting, release = contender
    runtime = object.__new__(LoxoneRuntime)
    token = object()
    session = SimpleNamespace(
        load_structure=AsyncMock(return_value=_structure("new")), close=AsyncMock()
    )
    runtime.client = SimpleNamespace(
        open_session=AsyncMock(return_value=session), timeout_seconds=0.3
    )
    runtime.auth_coordinator = coordinator
    runtime.token_store = SimpleNamespace(get=lambda *_: token)
    runtime._closed = False
    runtime.cache = UserStateCache()
    runtime._validate_access = AsyncMock(return_value=True)
    background = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("old"), frozenset(), _Session(), background)
    runtime._records = {"family": record}
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._prune_sessions = AsyncMock()
    runtime.structure_refresh_seconds = 300
    request = asyncio.create_task(runtime.snapshot(_access(), fresh_visibility=True))
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        runtime.client.open_session.assert_not_awaited()
        if outcome == "cancel":
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        elif outcome == "timeout":
            with pytest.raises(RuntimeUnavailable) as caught:
                await request
            assert caught.value.reason == "structure_refresh_auth_busy"
            assert caught.value.phase == "session_establishment"
        else:
            if outcome == "revoke":
                runtime._validate_access.return_value = False
            elif outcome == "shutdown":
                runtime._closed = True
            release()
            if outcome == "revoke":
                with pytest.raises(RuntimeAuthorizationError):
                    await request
            elif outcome == "shutdown":
                with pytest.raises(RuntimeUnavailable):
                    await request
            else:
                await request
                runtime.client.open_session.assert_awaited_once_with(token)
                session.load_structure.assert_awaited_once()
                session.close.assert_awaited_once()
                assert record.structure.last_modified == "new"
        if outcome != "release":
            runtime.client.open_session.assert_not_awaited()
            assert record.structure.last_modified == "old"
        release()
        # Cancellation/timeout did not retain either coordinator lock.
        assert (
            await coordinator.attempt(
                AsyncMock(return_value="ok"), owner="local_admin", phase="test"
            )
            == "ok"
        )
    finally:
        request.cancel()
        background.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await request
        with suppress(asyncio.CancelledError):
            await background


@pytest.mark.asyncio
async def test_wait_and_network_share_connection_budget(contender, monkeypatch):
    coordinator, waiting, release = contender
    runtime = object.__new__(LoxoneRuntime)
    entered = asyncio.Event()
    scopes = []
    original_timeout = asyncio.timeout

    def observed_timeout(delay):
        scope = original_timeout(delay)
        scopes.append(scope)
        return scope

    monkeypatch.setattr(asyncio, "timeout", observed_timeout)

    async def slow_login(_):
        assert len(scopes) == 1
        # The first contended poll consumed time from this same deadline;
        # network login has not received a fresh connection budget.
        remaining = scopes[0].when() - asyncio.get_running_loop().time()
        assert 0 < remaining < 1.95
        entered.set()
        await asyncio.Event().wait()

    runtime.client = SimpleNamespace(open_session=slow_login, timeout_seconds=2)
    runtime.auth_coordinator = coordinator
    request = asyncio.create_task(
        runtime._open_session(object(), owner="tool_request", phase="test")
    )
    await asyncio.wait_for(waiting.wait(), 2)
    release()
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(TimeoutError):
        await request
    assert (
        await coordinator.attempt(AsyncMock(return_value="ok"), owner="local_admin", phase="test")
        == "ok"
    )


@pytest.mark.asyncio
async def test_in_process_queue_is_bounded_by_connection_budget(tmp_path):
    runtime = object.__new__(LoxoneRuntime)
    runtime.auth_coordinator = auth.MiniserverAuthCoordinator(tmp_path / "auth.json")
    runtime.client = SimpleNamespace(open_session=AsyncMock(), timeout_seconds=0.1)
    async with runtime.auth_coordinator._lock:
        with pytest.raises(auth.MiniserverAuthenticationBusy):
            await runtime._open_session(object(), owner="tool_request", phase="test")
    runtime.client.open_session.assert_not_awaited()
    await runtime._open_session(object(), owner="tool_request", phase="test")
    runtime.client.open_session.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["revoke", "shutdown"])
async def test_preflight_abort_is_not_a_failed_cooldown_probe(tmp_path, outcome):
    runtime = object.__new__(LoxoneRuntime)
    coordinator = auth.MiniserverAuthCoordinator(tmp_path / "auth.json")
    coordinator._state["breaker_state"] = "open_source_ip_blocked"
    coordinator._state["opened_at"] = 0
    coordinator._save()
    before = coordinator.status()
    runtime.auth_coordinator = coordinator
    runtime.client = SimpleNamespace(open_session=AsyncMock(), timeout_seconds=1)
    runtime._validate_access = AsyncMock(return_value=outcome != "revoke")
    runtime._closed = outcome == "shutdown"
    expected = RuntimeAuthorizationError if outcome == "revoke" else RuntimeUnavailable
    with pytest.raises(expected):
        await runtime._open_session(object(), owner="tool_request", phase="test", access=_access())
    runtime.client.open_session.assert_not_awaited()
    assert coordinator.status() == before
    assert coordinator._state["events"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["control", "history", "notes"])
@pytest.mark.parametrize("outcome", ["revoke", "shutdown"])
async def test_queued_session_callers_preserve_error_contract(contender, path, outcome):
    coordinator, waiting, release = contender
    validate = AsyncMock(return_value=True)
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(get=lambda *_: object()),
        control_enabled=True,
        history_enabled=True,
        auth_coordinator=coordinator,
        validate_access=validate,
    )
    runtime.client = SimpleNamespace(open_session=AsyncMock(), timeout_seconds=2)
    access = _access()
    access.scopes.extend([CONTROL_SCOPE, HISTORY_SCOPE])
    if path == "control":
        runtime.snapshot = AsyncMock(
            return_value=RuntimeSnapshot("family", _structure("old"), True)
        )
        operation = runtime.operate_control(access, "control", "on")
    elif path == "history":
        operation = runtime.get_control_history(access, "control")
    else:
        operation = runtime.get_control_notes(access, "control")
    request = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        if outcome == "revoke":
            validate.return_value = False
        else:
            runtime._closed = True
        release()
        with pytest.raises(ControlOperationError) as caught:
            await request
        assert caught.value.code == (
            "permission_denied" if outcome == "revoke" else "temporarily_unavailable"
        )
        runtime.client.open_session.assert_not_awaited()
        assert coordinator._state["events"] == []
    finally:
        request.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await request


@pytest.mark.asyncio
@pytest.mark.parametrize("same_family", [True, False])
async def test_parallel_fresh_reads_keep_client_tokens(contender, same_family):
    coordinator, waiting, release = contender
    runtime = object.__new__(LoxoneRuntime)
    session = SimpleNamespace(
        load_structure=AsyncMock(return_value=_structure("new")), close=AsyncMock()
    )
    tokens = {"family": object(), "other": object()}
    runtime.client = SimpleNamespace(
        open_session=AsyncMock(return_value=session), timeout_seconds=2
    )
    runtime.token_store = SimpleNamespace(get=lambda family, *_: tokens[family])
    runtime.auth_coordinator = coordinator
    runtime._closed = False
    runtime.cache = UserStateCache()
    runtime._locks = _FamilyLocks()
    runtime._admission_lock = asyncio.Lock()
    runtime._prune_sessions = AsyncMock()
    runtime.structure_refresh_seconds = 300
    background = asyncio.create_task(asyncio.sleep(60))
    runtime._records = {
        family: _ConnectionRecord(_structure("old"), frozenset(), _Session(), background)
        for family in tokens
    }
    second_access = _access()
    if not same_family:
        second_access.family_id = "other"
        second_access.identity_id = "other-reader"
    first = asyncio.create_task(runtime.snapshot(_access(), fresh_visibility=True))
    second = None
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        second = asyncio.create_task(runtime.snapshot(second_access, fresh_visibility=True))
        await asyncio.sleep(0)
        runtime.client.open_session.assert_not_awaited()
        release()
        results = await asyncio.gather(first, second)
        assert all(result.structure.last_modified == "new" for result in results)
        assert session.load_structure.await_count == 2
        assert session.close.await_count == 2
        assert [call.args[0] for call in runtime.client.open_session.await_args_list] == [
            tokens["family"],
            tokens["family" if same_family else "other"],
        ]
    finally:
        for task in (first, second, background):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,reason",
    [
        (LoxoneConnectionError, "structure_refresh_connection"),
        (LoxoneSourceIpBlocked, "structure_refresh_source_ip_suppressed"),
    ],
)
async def test_network_and_breaker_are_distinct_from_local_contention(tmp_path, failure, reason):
    runtime = object.__new__(LoxoneRuntime)
    runtime.client = SimpleNamespace(
        open_session=AsyncMock(side_effect=failure("private-value")), timeout_seconds=1
    )
    runtime.auth_coordinator = auth.MiniserverAuthCoordinator(tmp_path / "auth.json")
    runtime.token_store = SimpleNamespace(get=lambda *_: object())
    background = asyncio.create_task(asyncio.sleep(60))
    record = _ConnectionRecord(_structure("old"), frozenset(), _Session(), background)
    runtime._records = {"family": record}
    try:
        with pytest.raises(RuntimeUnavailable) as caught:
            await runtime._refresh_structure(_access(), record, fresh_visibility=True)
        assert caught.value.reason == reason
        assert "private-value" not in str(caught.value)
        if failure is LoxoneSourceIpBlocked:
            with pytest.raises(RuntimeUnavailable) as suppressed:
                await runtime._refresh_structure(_access(), record, fresh_visibility=True)
            assert suppressed.value.reason == reason
            assert runtime.client.open_session.await_count == 1
    finally:
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background
