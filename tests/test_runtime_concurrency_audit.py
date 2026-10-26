"""Event-controlled lifecycle interleavings; timeouts only bound deadlocks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import LoxoneConnectionError, MiniserverEndpoint
from mcpserver.loxone.events import LoxoneProtocolError, StateEvent
from mcpserver.loxone.models import Freshness, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    LoxoneRuntime,
    RuntimeAuthorizationError,
    RuntimeUnavailable,
    _ConnectionRecord,
)


def access(family: str = "one") -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://example.test/mcp",
        subject="identity",
        claims={},
        family_id=family,
        identity_id="identity",
        miniserver_id="miniserver",
    )


def structure(marker: str = "old") -> LoxoneStructure:
    return LoxoneStructure(LoxoneIdentity("reader", "serial"), marker, (), (), ())


def runtime(**options: object) -> LoxoneRuntime:
    return LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(get=lambda *_args: SimpleNamespace(valid_until=2_000_000_000)),
        **options,
    )


class Stream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.batches = asyncio.Queue()
        self.closed = asyncio.Event()
        self.close_calls = 0

    async def state_events(self):
        self.started.set()
        yield (StateEvent(uuid="state", value=1.0),)
        while (item := await self.batches.get()) is not None:
            batch, applied = item
            yield batch
            applied.set()

    async def emit(self, value: float) -> None:
        applied = asyncio.Event()
        self.batches.put_nowait(((StateEvent(uuid="state", value=value),), applied))
        await asyncio.wait_for(applied.wait(), 2)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


async def install(owner: LoxoneRuntime, family: str = "one") -> _ConnectionRecord:
    stream = Stream()
    record = _ConnectionRecord(structure(), frozenset({"state"}), stream, None)
    owner.cache.begin_connection(family)
    record.task = asyncio.create_task(
        owner._maintain(access(family), owner.token_store.get(), record)
    )
    owner._records[family] = record
    await asyncio.wait_for(record.initial_state_batch.wait(), 2)
    return record


@pytest.mark.asyncio
async def test_normal_stream_end_during_read_marks_cached_state_stale() -> None:
    owner = runtime(structure_refresh_seconds=10**12)
    record = await install(owner)
    try:
        snapshot = await owner.snapshot(access())
        assert owner.state(snapshot, "state").freshness is Freshness.CURRENT
        record.session.batches.put_nowait(None)
        await asyncio.wait_for(record.task, 2)
        assert record.session.closed.is_set()
        assert owner.state(snapshot, "state").freshness is Freshness.STALE
        assert not record.connected
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_initial_state_timeout_does_not_publish_empty_live_connection() -> None:
    owner = runtime()
    owner._initial_state_timeout_seconds = 0.01
    baseline = asyncio.all_tasks()

    class SilentStream(Stream):
        async def load_structure(self):
            return structure()

        async def state_events(self):
            self.started.set()
            await asyncio.Event().wait()
            yield ()

    stream = SilentStream()
    owner.client.open_session = AsyncMock(return_value=stream)
    try:
        with pytest.raises(RuntimeUnavailable, match="initial state"):
            await asyncio.wait_for(owner.snapshot(access()), 2)
        assert stream.started.is_set()
        assert stream.closed.is_set()
        assert not owner._records
        assert not owner._locks
        assert not (asyncio.all_tasks() - baseline)
    finally:
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["idle", "capacity", "close"])
async def test_cleanup_during_refresh_does_not_resurrect_cache(cleanup: str) -> None:
    await _cleanup_during_refresh(cleanup, check_cache=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["idle", "capacity", "close"])
async def test_cleanup_during_refresh_closes_owned_sessions(cleanup: str) -> None:
    # Do not let a known cache failure mask independent session-leak evidence.
    await _cleanup_during_refresh(cleanup, check_cache=False)


async def _cleanup_during_refresh(cleanup: str, *, check_cache: bool) -> None:
    owner = runtime(max_active_sessions=1, session_idle_seconds=1)
    record = await install(owner)
    entered, release = asyncio.Event(), asyncio.Event()

    async def load():
        entered.set()
        await release.wait()
        return structure("new")

    refresh = SimpleNamespace(
        structure_version=AsyncMock(return_value="new"),
        load_structure=load,
        close=AsyncMock(),
    )
    owner.client.open_session = AsyncMock(return_value=refresh)
    call = asyncio.create_task(owner.snapshot(access(), fresh_visibility=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert record.refresh_lock.locked()
        if cleanup == "idle":
            record.last_used = 0
        if cleanup == "close":
            await asyncio.wait_for(owner.close(), 2)
        else:
            await asyncio.wait_for(owner._prune_sessions("other"), 2)
        assert record.task.done()
        assert record.session.closed.is_set()
        release.set()
        with pytest.raises(RuntimeUnavailable, match="connection changed"):
            await asyncio.wait_for(call, 2)
        refresh.close.assert_awaited_once()
        if check_cache:
            assert owner.cache.get("one", "state").freshness is Freshness.UNAVAILABLE
            assert "one" not in owner.cache._values
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_concurrent_new_families_respect_session_capacity() -> None:
    owner = runtime(max_active_sessions=1, structure_refresh_seconds=10**12)
    entered = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()
    records = []

    async def connect(candidate):
        entered.set()
        await release.wait()
        # Use the real background-task owner and cleanup path.
        record = await install(owner, candidate.family_id)
        records.append(record)
        return record

    owner._connect = connect

    async def second():
        second_started.set()
        return await owner.snapshot(access("two"))

    calls = [asyncio.create_task(owner.snapshot(access()))]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        calls.append(asyncio.create_task(second()))
        await asyncio.wait_for(second_started.wait(), 2)
        release.set()
        await asyncio.wait_for(asyncio.gather(*calls), 2)
        assert len(owner._records) <= owner.max_active_sessions
    finally:
        release.set()
        await asyncio.gather(*calls, return_exceptions=True)
        await owner.close()
        assert all(record.task.done() and record.session.closed.is_set() for record in records)


@pytest.mark.asyncio
async def test_shutdown_drains_background_tasks_and_is_idempotent() -> None:
    baseline = asyncio.all_tasks()
    owner = runtime()
    records = [await install(owner, family) for family in ("one", "two", "three")]
    await asyncio.wait_for(owner.close(), 2)
    await asyncio.wait_for(owner.close(), 2)
    assert not owner._records
    assert not owner._locks
    assert not owner.cache._values
    assert all(record.task.done() for record in records)
    assert all(record.session.close_calls == 1 for record in records)
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["revoke", "expiry"])
async def test_queued_cached_snapshot_rechecks_access_before_pruning(ending: str) -> None:
    checked = asyncio.Event()
    authorized, clock = [True], [100.0]

    async def validate(candidate):
        valid = authorized[0] and clock[0] < candidate.expires_at
        checked.set()
        return valid

    owner = runtime(validate_access=validate, structure_refresh_seconds=10**12)
    record = await install(owner)
    # A disconnected record is not eligible for the live-record fast path.
    record.connected = False
    owner._prune_sessions = AsyncMock()
    await owner._admission_lock.acquire()
    call = asyncio.create_task(owner.snapshot(access()))
    try:
        await asyncio.wait_for(checked.wait(), 2)
        if ending == "revoke":
            authorized[0] = False
        else:
            clock[0] = 2_000_000_001
        owner._admission_lock.release()
        with pytest.raises(RuntimeAuthorizationError):
            await asyncio.wait_for(call, 2)
        owner._prune_sessions.assert_not_awaited()
        assert "one" in owner._records
    finally:
        if owner._admission_lock.locked():
            owner._admission_lock.release()
        await asyncio.gather(call, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_visibility", [False, True])
async def test_live_snapshot_completes_while_another_family_is_connecting(fresh_visibility):
    owner = runtime(max_active_sessions=2, structure_refresh_seconds=10**12)
    record = await install(owner)
    await owner.snapshot(access())  # Mark the installed fixture as recently used.
    entered, release = asyncio.Event(), asyncio.Event()

    async def connect(candidate):
        entered.set()
        await release.wait()
        return await install(owner, candidate.family_id)

    async def refresh(_access, current, **_options):
        assert current is record
        current.structure = structure("fresh")

    owner._connect = AsyncMock(side_effect=connect)
    owner._refresh_structure = AsyncMock(side_effect=refresh)
    cold = asyncio.create_task(owner.snapshot(access("cold")))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        result = await asyncio.wait_for(
            owner.snapshot(access(), fresh_visibility=fresh_visibility), 1
        )
        assert result.connected
        assert result.structure.last_modified == ("fresh" if fresh_visibility else "old")
        assert owner._refresh_structure.await_count == int(fresh_visibility)
        assert not cold.done() and owner._admission_lock.locked()
        assert len(owner._records) == 1
    finally:
        release.set()
        await asyncio.gather(cold, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_at", [2, 3])
async def test_live_snapshot_fast_path_rechecks_current_access(reject_at):
    validate = AsyncMock(side_effect=[True] * (reject_at - 1) + [False])
    owner = runtime(validate_access=validate, structure_refresh_seconds=10**12)
    await install(owner)
    owner._prune_sessions = AsyncMock()
    try:
        async with owner._admission_lock:
            with pytest.raises(RuntimeAuthorizationError):
                await owner.snapshot(access())
            owner._prune_sessions.assert_not_awaited()
            assert validate.await_count == reject_at
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_live_snapshot_fast_path_rejects_shutdown():
    owner = runtime(structure_refresh_seconds=10**12)
    await install(owner)
    try:
        async with owner._admission_lock:
            owner._closed = True
            with pytest.raises(RuntimeUnavailable, match="closed"):
                await owner.snapshot(access())
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_same_family_connection_waiters_still_share_one_record():
    owner = runtime(structure_refresh_seconds=10**12)
    entered, release = asyncio.Event(), asyncio.Event()

    async def connect(candidate):
        entered.set()
        await release.wait()
        return await install(owner, candidate.family_id)

    owner._connect = AsyncMock(side_effect=connect)
    first = asyncio.create_task(owner.snapshot(access()))
    calls = [first]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(owner.snapshot(access()))
        calls.append(second)
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*calls), 2)
        assert owner._connect.await_count == 1
        assert results[0].structure is results[1].structure
    finally:
        release.set()
        await asyncio.gather(*calls, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_refresh_filters_batches_before_and_after_generation_change() -> None:
    owner = runtime()
    record = await install(owner)
    entered, release = asyncio.Event(), asyncio.Event()

    async def load():
        entered.set()
        await release.wait()
        return structure("new")  # no remaining allowed states

    refresh = SimpleNamespace(load_structure=load, close=AsyncMock())
    owner.client.open_session = AsyncMock(return_value=refresh)
    call = asyncio.create_task(owner.snapshot(access(), fresh_visibility=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)

        # The production pump processes a batch while refresh is suspended.
        await record.session.emit(2.0)
        assert owner.cache.get("one", "state").value == 2.0
        release.set()
        snapshot = await asyncio.wait_for(call, 2)
        assert snapshot.structure_generation == 2
        assert snapshot.structure.last_modified == "new"
        assert not record.allowed_states
        await record.session.emit(3.0)
        assert owner.state(snapshot, "state").value is None
        assert owner.state(snapshot, "state").freshness is Freshness.UNKNOWN
        refresh.close.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_old_refresh_cannot_modify_reconnected_generation_or_cache() -> None:
    owner = runtime()
    old = await install(owner)
    entered, release = asyncio.Event(), asyncio.Event()

    async def load():
        entered.set()
        await release.wait()
        return structure("obsolete-refresh")

    owner.client.open_session = AsyncMock(
        return_value=SimpleNamespace(load_structure=load, close=AsyncMock())
    )
    call = asyncio.create_task(owner.snapshot(access(), fresh_visibility=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(owner.disconnect("one"), 2)
        replacement = await install(owner)
        replacement.structure = structure("replacement")
        replacement.generation = 7
        await replacement.session.emit(7.0)
        release.set()
        with pytest.raises(RuntimeUnavailable, match="connection changed"):
            await asyncio.wait_for(call, 2)
        assert owner._records["one"] is replacement
        assert replacement.generation == 7
        assert replacement.structure.last_modified == "replacement"
        assert owner.cache.get("one", "state").value == 7.0
        assert old.task.done() and old.session.closed.is_set()
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_shutdown_during_unpublished_initial_stream_drains_connection() -> None:
    owner = runtime()
    started, initial, closing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class InitialStream(Stream):
        async def load_structure(self):
            return structure()

        async def state_events(self):
            started.set()
            await initial.wait()
            yield ()
            await asyncio.Event().wait()

    stream = InitialStream()
    owner.client.open_session = AsyncMock(return_value=stream)
    call = asyncio.create_task(owner.snapshot(access()))

    async def shutdown():
        closing.set()
        await owner.close()

    stop = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not owner._records
        stop = asyncio.create_task(shutdown())
        await asyncio.wait_for(closing.wait(), 2)
        initial.set()
        results = await asyncio.wait_for(asyncio.gather(call, stop, return_exceptions=True), 4)
        assert not owner._records
        assert stream.closed.is_set()
        assert isinstance(results[0], RuntimeUnavailable)
        assert results[1] is None
        with pytest.raises(RuntimeUnavailable, match="closed"):
            await owner.snapshot(access("after-close"))
    finally:
        initial.set()
        await asyncio.gather(call, *([stop] if stop is not None else []), return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "protocol", "connection", "unexpected"])
@pytest.mark.parametrize("close_fails", [False, True])
async def test_unpublished_structure_failure_closes_session_and_preserves_failure(
    failure, close_fails
):
    owner = runtime()
    started = asyncio.Event()
    errors = {
        "protocol": LoxoneProtocolError("synthetic protocol"),
        "connection": LoxoneConnectionError("synthetic connection"),
        "unexpected": ValueError("synthetic normalization"),
    }

    async def load():
        started.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        raise errors[failure]

    session = SimpleNamespace(
        load_structure=load,
        close=AsyncMock(side_effect=RuntimeError("synthetic close") if close_fails else None),
    )
    owner._open_session = AsyncMock(return_value=session)
    task = asyncio.create_task(owner.snapshot(access()))
    try:
        await started.wait()
        if failure == "cancel":
            task.cancel()
        expected = (
            asyncio.CancelledError
            if failure == "cancel"
            else RuntimeUnavailable
            if failure == "connection"
            else type(errors[failure])
        )
        with pytest.raises(expected):
            await task
        session.close.assert_awaited_once()
        assert not owner._records and not owner._locks
        assert not owner.cache._values and not owner.cache._available
    finally:
        await asyncio.gather(task, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_failed_initial_subscriptions_do_not_accumulate_orphan_subjects():
    owner = runtime()
    sessions = []

    class EmptyStream(Stream):
        async def load_structure(self):
            return structure()

        async def state_events(self):
            return
            yield ()

    async def open_session(*_args, **_kwargs):
        session = EmptyStream()
        sessions.append(session)
        return session

    owner._open_session = open_session
    for index in range(20):
        with pytest.raises(RuntimeUnavailable, match="subscription"):
            await owner.snapshot(access(f"failed-{index}"))
        assert not owner._records and not owner._locks
        assert not owner.cache._values and not owner.cache._available
    assert all(session.close_calls == 1 for session in sessions)
    owner.cache.begin_connection("orphan")
    await owner.close()
    assert not owner.cache._values and not owner.cache._available


@pytest.mark.asyncio
async def test_failed_reconnect_preserves_owned_disconnected_state():
    owner = runtime(structure_refresh_seconds=10**12)
    record = await install(owner)
    record.session.batches.put_nowait(None)
    await record.task
    assert owner.cache.get("one", "state").freshness is Freshness.STALE

    class EmptyStream(Stream):
        async def load_structure(self):
            return structure()

        async def state_events(self):
            return
            yield ()

    session = EmptyStream()
    owner._open_session = AsyncMock(return_value=session)
    try:
        with pytest.raises(RuntimeUnavailable, match="subscription"):
            await owner.snapshot(access())
        assert owner._records["one"] is record
        assert owner.cache.get("one", "state").freshness is Freshness.STALE
        assert owner.cache.get("one", "state").value == 1.0
        assert session.close_calls == 1
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_cancelled_maintainer_before_start_leaves_session_with_setup(monkeypatch):
    owner = runtime()
    session = Stream()
    session.load_structure = AsyncMock(return_value=structure())
    owner._open_session = AsyncMock(return_value=session)
    create_task = asyncio.create_task

    def cancel_maintainer(coro, *args, **kwargs):
        task = create_task(coro, *args, **kwargs)
        if coro.cr_code.co_name == "_maintain":
            task.cancel()
        return task

    monkeypatch.setattr(asyncio, "create_task", cancel_maintainer)
    try:
        with pytest.raises(asyncio.CancelledError):
            await owner.snapshot(access())
        assert session.close_calls == 1
        assert not owner._records and not owner._locks
        assert not owner.cache._values and not owner.cache._available
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_unpublished_close_clears_orphan_state():
    owner = runtime()
    loading, closing = asyncio.Event(), asyncio.Event()

    async def load():
        loading.set()
        await asyncio.Event().wait()

    async def close():
        closing.set()
        await asyncio.Event().wait()

    session = SimpleNamespace(load_structure=load, close=AsyncMock(side_effect=close))
    owner._open_session = AsyncMock(return_value=session)
    owner.cache.begin_connection("one")
    task = asyncio.create_task(owner.snapshot(access()))
    try:
        await loading.wait()
        task.cancel()
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not owner.cache._values and not owner.cache._available
        assert not owner._records and not owner._locks
        session.close.assert_awaited_once()
    finally:
        await asyncio.gather(task, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_pump_task_allocation_failure_keeps_session_owned_by_setup(monkeypatch):
    owner = runtime()
    session = Stream()
    session.load_structure = AsyncMock(return_value=structure())
    owner._open_session = AsyncMock(return_value=session)
    create_task = asyncio.create_task

    def fail_pump(coro, *args, **kwargs):
        if coro.cr_code.co_name == "_pump_events":
            raise MemoryError("synthetic allocation")
        return create_task(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", fail_pump)
    try:
        with pytest.raises(MemoryError, match="synthetic allocation"):
            await owner.snapshot(access())
        assert session.close_calls == 1
        assert not owner._records and not owner._locks
        assert not owner.cache._values and not owner.cache._available
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_warm_snapshot_does_not_join_fair_lock_handoff_queue():
    owner = runtime(max_active_sessions=2, structure_refresh_seconds=10**12)
    await install(owner)
    await owner.snapshot(access())
    entered, release = asyncio.Event(), asyncio.Event()

    async def connect(candidate):
        entered.set()
        await release.wait()
        return await install(owner, candidate.family_id)

    owner._connect = AsyncMock(side_effect=connect)
    await owner._admission_lock.acquire()
    cold = asyncio.create_task(owner.snapshot(access("cold")))
    try:
        await asyncio.sleep(0)
        assert owner._admission_users == 1
        owner._admission_lock.release()
        assert not owner._admission_lock.locked()
        # Await directly in this task: wait_for would schedule a new task and
        # mask the lock handoff interleaving that caused the original defect.
        async with asyncio.timeout(1):
            result = await owner.snapshot(access())
        assert result.connected and not cold.done() and not entered.is_set()
    finally:
        cold.cancel()
        release.set()
        await asyncio.gather(cold, return_exceptions=True)
        assert owner._admission_users == 0
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_connection_admission_counter_drains_on_cancellation(queued):
    owner = runtime()
    entered = asyncio.Event()
    if queued:
        await owner._admission_lock.acquire()

    async def connect(_access):
        entered.set()
        await asyncio.Event().wait()

    owner._connect = AsyncMock(side_effect=connect)
    task = asyncio.create_task(owner.snapshot(access("cold")))
    try:
        await asyncio.sleep(0)
        assert owner._admission_users == 1
        assert entered.is_set() is (not queued)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner._admission_users == 0
    finally:
        if owner._admission_lock.locked():
            owner._admission_lock.release()
        await owner.close()
