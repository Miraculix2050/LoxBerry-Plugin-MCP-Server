"""Deterministic family churn and holder/waiter cleanup regressions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import mcpserver.loxone.runtime as runtime_module
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    HISTORY_SCOPE,
    READ_SCOPE,
    Phase0OAuthProvider,
    StoredAccessToken,
)
from mcpserver.auth.store import AtomicJsonAuthStore, token_digest
from mcpserver.loxone.client import LoxoneToken, MiniserverEndpoint
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeUnavailable,
    _ConnectionRecord,
)


def _access(family: str = "family") -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE, HISTORY_SCOPE, CONTROL_SCOPE],
        expires_at=2_000_000_000,
        resource="https://example.test/mcp",
        subject="identity",
        claims={},
        family_id=family,
        identity_id="identity",
        miniserver_id="miniserver",
    )


def _runtime(**options: object) -> LoxoneRuntime:
    return LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(get=lambda *_args: None),  # type: ignore[arg-type]
        control_enabled=True,
        history_enabled=True,
        **options,  # type: ignore[arg-type]
    )


def _counts(runtime: LoxoneRuntime) -> tuple[int, ...]:
    return tuple(
        len(getattr(runtime, name))
        for name in (
            "_locks",
            "_control_locks",
            "_rate",
            "_control_rate",
            "_history_rate",
        )
    )


def _authorized_runtime(tmp_path: Path):
    access = _access()
    clock = [1_900_000_000.0]
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    tokens = EncryptedLoxoneTokenStore((tmp_path / "tokens.enc").resolve(), key.resolve())
    tokens.put(
        "family",
        "miniserver",
        "identity",
        LoxoneToken("test-token", "reader", "key", "SHA256", 2_000_000_000),
    )
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    auth.mutate(
        lambda document: document["families"].update(
            {
                "family": {"revoked": False, "expires_at": access.expires_at},
            }
        )
    )
    auth.mutate(
        lambda document: document["access_tokens"].update(
            {
                token_digest(access.token): {
                    "status": "active",
                    "expires_at": access.expires_at,
                    "family_id": access.family_id,
                    "client_id": access.client_id,
                    "scopes": access.scopes,
                    "resource": access.resource,
                    "identity_id": access.identity_id,
                    "miniserver_id": access.miniserver_id,
                },
            }
        )
    )
    cleanup: list[asyncio.Task[None]] = []

    def revoke(family: str) -> None:
        tokens.schedule_remote_revoke(family)
        cleanup.append(asyncio.create_task(runtime.revoke(family)))

    provider = Phase0OAuthProvider(
        auth,
        issuer="https://example.test/oauth",
        resource=access.resource,
        clock=lambda: clock[0],
        on_family_revoked=revoke,
    )

    async def validate(candidate: StoredAccessToken) -> bool:
        current = await provider.load_access_token(candidate.token)
        return bool(
            current is not None
            and current.family_id == candidate.family_id
            and current.identity_id == candidate.identity_id
            and current.miniserver_id == candidate.miniserver_id
        )

    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        tokens,
        max_parallel_calls=1,
        history_enabled=True,
        control_enabled=True,
        validate_access=validate,
    )
    return runtime, provider, tokens, cleanup, clock


@pytest.mark.asyncio
async def test_failed_connections_and_recordless_calls_do_not_retain_old_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    runtime = _runtime()
    for index in range(80):
        access = _access(f"family-{index}")
        with pytest.raises(RuntimeUnavailable, match="authorization"):
            await runtime.snapshot(access)
        async with runtime.call_slot(access), runtime.history_call_slot(access):
            pass
        with pytest.raises(ControlOperationError, match="authorization"):
            await runtime.operate_control(access, "control", "on")
        await runtime.revoke(access.family_id)
    assert _counts(runtime) == (0, 0, 80, 80, 80)
    assert runtime._records == {}
    clock[0] += 60
    # Any new call sweeps all three rate maps, even families with no record.
    async with runtime.call_slot(_access("next")):
        pass
    assert _counts(runtime) == (0, 0, 1, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["disconnect", "revoke", "expiry", "idle", "capacity"])
async def test_connected_family_churn_cleans_locks_and_expired_rates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ending: str,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    runtime = _runtime(max_active_sessions=1, session_idle_seconds=10)
    closed: list[str] = []
    cleanup_tasks: list[asyncio.Task[None]] = []
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    provider = Phase0OAuthProvider(
        store,
        issuer="https://example.test/oauth",
        resource="https://example.test/mcp",
        clock=lambda: clock[0],
        on_family_revoked=lambda family: cleanup_tasks.append(
            asyncio.create_task(runtime.revoke(family))
        ),
    )

    async def connect(access: StoredAccessToken) -> _ConnectionRecord:
        async def maintain() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(access.family_id)

        task = asyncio.create_task(maintain())
        await asyncio.sleep(0)
        return _ConnectionRecord(
            LoxoneStructure(LoxoneIdentity("reader", "serial"), "1", (), (), ()),
            frozenset(),
            SimpleNamespace(),
            task,
            last_structure_check=clock[0],
            last_used=clock[0],
        )

    monkeypatch.setattr(runtime, "_connect", connect)
    for index in range(40):
        access = _access(f"family-{index}")
        async with runtime.call_slot(access), runtime.history_call_slot(access):
            await runtime.snapshot(access)
        if ending == "expiry":
            store.mutate(
                lambda document, access=access: document["families"].update(
                    {
                        access.family_id: {"expires_at": int(clock[0])},
                    }
                )
            )
            await provider.get_client("missing")
            assert len(cleanup_tasks) == index + 1
            await cleanup_tasks[-1]
            assert not store.snapshot()["families"]
        elif ending == "revoke":
            await runtime.revoke(access.family_id)
        elif ending == "disconnect":
            await runtime.disconnect(access.family_id)
        elif ending == "idle":
            clock[0] += 10
            await runtime._prune_sessions("next")
        else:
            await runtime._prune_sessions("next")
        assert not runtime._records
        clock[0] += 60
    await runtime.disconnect("unused")
    assert _counts(runtime) == (0, 0, 0, 0, 0)
    assert len(closed) == 40


@pytest.mark.asyncio
async def test_cancelled_connection_holder_releases_family_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    entered = asyncio.Event()

    async def connect(_access: StoredAccessToken) -> _ConnectionRecord:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(runtime, "_connect", connect)
    task = asyncio.create_task(runtime.snapshot(_access()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runtime._locks
    assert not runtime._records


@pytest.mark.asyncio
async def test_expired_rate_keys_are_swept_without_connection_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    runtime = _runtime(control_requests_per_minute=1)
    for index in range(80):
        access = _access(f"family-{index}")
        async with runtime.history_call_slot(access):
            pass
        with pytest.raises(ControlOperationError, match="authorization"):
            await runtime.operate_control(access, "control", "on")
        await runtime.disconnect(access.family_id)
        with pytest.raises(ControlOperationError, match="control rate limit"):
            await runtime.operate_control(access, "control", "on")
    assert len(runtime._rate) == len(runtime._control_rate) == len(runtime._history_rate) == 80
    clock[0] += 60
    await runtime.disconnect("unused")
    assert not runtime._rate
    assert not runtime._control_rate
    assert not runtime._history_rate


@pytest.mark.asyncio
async def test_disconnect_waits_for_connect_and_preserves_waiter_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime, provider, tokens, cleanup_tasks, _clock = _authorized_runtime(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()

    class Session:
        async def load_structure(self):
            return LoxoneStructure(LoxoneIdentity("reader", "serial"), "1", (), (), ())

        async def state_events(self):
            yield ()
            await asyncio.Event().wait()

        async def close(self):
            closed.set()

    async def open_session(_token):
        entered.set()
        await release.wait()
        return Session()

    opening = AsyncMock(side_effect=open_session)
    monkeypatch.setattr(runtime.client, "open_session", opening)
    first = asyncio.create_task(runtime.snapshot(_access()))
    await entered.wait()
    lock = runtime._locks["family"]
    await provider.revoke_token(_access())
    cleanup = cleanup_tasks[-1]
    await asyncio.sleep(0)
    waiter = asyncio.create_task(runtime.snapshot(_access()))
    await asyncio.sleep(0)
    assert not cleanup.done()
    assert runtime._locks["family"] is lock
    release.set()
    with pytest.raises(RuntimeUnavailable, match="authorization"):
        await first
    await cleanup
    with pytest.raises(RuntimeUnavailable, match="authorization"):
        await waiter
    assert opening.await_count == 1
    assert closed.is_set()
    assert tokens.get("family", "miniserver", "identity") is not None
    assert not runtime._records
    assert not runtime._locks


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "history", "control"])
@pytest.mark.parametrize("ending", ["revoke", "expiry"])
async def test_queued_calls_cannot_reconnect_with_retained_revocation_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    ending: str,
) -> None:
    runtime, provider, tokens, cleanup, clock = _authorized_runtime(tmp_path)
    opening = AsyncMock(side_effect=AssertionError("revoked call opened a connection"))
    monkeypatch.setattr(runtime.client, "open_session", opening)
    await runtime._parallel.acquire()

    async def call() -> None:
        if mode == "control":
            await runtime.operate_control(_access(), "control", "on")
        else:
            slot = runtime.history_call_slot if mode == "history" else runtime.call_slot
            async with slot(_access()):
                await runtime.snapshot(_access())

    waiting = asyncio.create_task(call())
    await asyncio.sleep(0)
    assert not waiting.done()
    if ending == "revoke":
        await provider.revoke_token(_access())
    else:
        clock[0] = 2_000_000_001
        await provider.get_client("missing")
    await asyncio.gather(*cleanup)
    assert not runtime._records
    assert tokens.get("family", "miniserver", "identity") is not None
    assert len(tokens.pending_remote_revocations(int(clock[0]))) == 1
    runtime._parallel.release()
    error = RuntimeUnavailable if mode == "read" else ControlOperationError
    with pytest.raises(error, match="authorization"):
        await waiting
    with pytest.raises(RuntimeUnavailable, match="authorization"):
        await runtime.snapshot(_access())
    assert opening.await_count == 0
    assert not runtime._records
    assert not runtime._locks
    assert not runtime._control_locks


@pytest.mark.asyncio
async def test_control_waiters_share_lock_through_disconnect_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(max_parallel_calls=4)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def snapshot(_access: StoredAccessToken):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        raise RuntimeUnavailable("authorization revoked")

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    first = asyncio.create_task(runtime.operate_control(_access(), "control", "on"))
    await entered.wait()
    lock = runtime._control_locks["family"]
    cancelled = asyncio.create_task(runtime.operate_control(_access(), "control", "on"))
    waiter = asyncio.create_task(runtime.operate_control(_access(), "control", "on"))
    await asyncio.sleep(0)
    await runtime.disconnect("family")
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert calls == 1
    assert runtime._control_locks["family"] is lock
    release.set()
    for task in (first, waiter):
        with pytest.raises(ControlOperationError, match="revoked"):
            await task
    assert calls == 2
    assert not runtime._control_locks


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [False, True])
async def test_live_rate_window_survives_cleanup_and_waiting_calls(
    monkeypatch: pytest.MonkeyPatch,
    history: bool,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    runtime = _runtime(requests_per_minute=1, history_requests_per_minute=1, max_parallel_calls=1)
    slot = runtime.history_call_slot if history else runtime.call_slot
    await runtime._parallel.acquire()
    waiting = asyncio.create_task(slot(_access()).__aenter__())
    await asyncio.sleep(0)
    await runtime.revoke("family")
    error = ControlOperationError if history else RuntimeUnavailable
    with pytest.raises(error, match="rate limit"):
        async with slot(_access()):
            pass
    waiting.cancel()
    with suppress(asyncio.CancelledError):
        await waiting
    runtime._parallel.release()
    assert len(runtime._rate["family"]) == 1
    clock[0] += 60
    async with slot(_access("next")):
        pass
    assert "family" not in runtime._rate
    assert "family" not in runtime._history_rate
