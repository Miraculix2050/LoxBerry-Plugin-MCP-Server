"""Event-controlled lifecycle interleavings; timeouts only bound deadlocks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Freshness, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable, _ConnectionRecord


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
