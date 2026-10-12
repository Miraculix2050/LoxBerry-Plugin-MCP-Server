"""Publication and admission regressions for local work under a fresh snapshot."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeAuthorizationError, RuntimeUnavailable


def access():
    return StoredAccessToken(
        token="opaque",
        client_id="synthetic",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="http://synthetic.local/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def runtime(validator):
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "serial"), "v1", (), (), ())

    class Session:
        async def load_structure(self):
            return structure

        async def state_events(self):
            yield ()
            await asyncio.Event().wait()

        async def close(self):
            pass

    result = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(get=lambda *_args: SimpleNamespace(valid_until=2_000_000_000)),
        validate_access=validator,
        max_parallel_calls=1,
    )
    result.client = SimpleNamespace(open_session=AsyncMock(side_effect=lambda *_args: Session()))
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("use_context", [False, True])
async def test_context_and_legacy_keep_exact_checks_and_source_calls(use_context):
    authorize = AsyncMock(return_value=True)
    current = runtime(authorize)
    try:
        for expected_checks in (7, 5):
            authorize.reset_mock()
            before = current.client.open_session.await_count
            if use_context:
                async with current.snapshot_context(access()) as snapshot:
                    assert snapshot.structure.identity.miniserver_serial == "serial"
                    assert authorize.await_count == expected_checks - 1
                    await asyncio.sleep(0)
            else:
                async with current.call_slot(access()):
                    snapshot = await current.snapshot(access(), fresh_visibility=True)
                    assert snapshot.structure.identity.miniserver_serial == "serial"
            assert authorize.await_count == expected_checks
            assert current.client.open_session.await_count - before == 1
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_revocation_after_local_work_prevents_publication():
    admitted = True

    async def authorize(_access):
        return admitted

    current = runtime(authorize)
    published = False
    try:
        with pytest.raises(RuntimeAuthorizationError):
            async with current.snapshot_context(access()):
                admitted = False
                await asyncio.sleep(0)
            published = True
        assert not published
        assert not current._parallel.locked()
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_revocation_while_waiting_for_admission_blocks_source_access():
    admitted = True
    checked = asyncio.Event()

    async def authorize(_access):
        checked.set()
        return admitted

    current = runtime(authorize)
    await current._admission_lock.acquire()

    async def read():
        async with current.snapshot_context(access()):
            raise AssertionError("revoked caller entered local work")

    task = asyncio.create_task(read())
    try:
        await checked.wait()
        admitted = False
        current._admission_lock.release()
        with pytest.raises(RuntimeAuthorizationError):
            await task
        current.client.open_session.assert_not_awaited()
        assert not current._parallel.locked()
    finally:
        if current._admission_lock.locked():
            current._admission_lock.release()
        await current.close()


@pytest.mark.asyncio
async def test_cancellation_of_local_work_releases_parallel_slot():
    current = runtime(AsyncMock(return_value=True))
    entered = asyncio.Event()

    async def read():
        async with current.snapshot_context(access()):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(read())
    try:
        await entered.wait()
        assert current._parallel.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(1), current.call_slot(access()):
            pass
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_local_read_and_legacy_read_share_bounded_admission():
    current = runtime(AsyncMock(return_value=True))
    legacy_started = asyncio.Event()
    legacy_entered = asyncio.Event()

    async def legacy_read():
        legacy_started.set()
        async with current.call_slot(access()):
            legacy_entered.set()
            return await current.snapshot(access())

    task = None
    try:
        async with current.snapshot_context(access()):
            task = asyncio.create_task(legacy_read())
            await legacy_started.wait()
            assert not legacy_entered.is_set()
        assert (await task).connected
        assert legacy_entered.is_set()
        assert not current._parallel.locked()
    finally:
        if task is not None and not task.done():
            task.cancel()
        await current.close()


@pytest.mark.asyncio
async def test_fresh_refresh_failure_never_enters_local_work():
    current = runtime(AsyncMock(return_value=True))
    try:
        await current.snapshot(access())
        current._refresh_structure = AsyncMock(side_effect=RuntimeUnavailable("refresh failed"))
        with pytest.raises(RuntimeUnavailable):
            async with current.snapshot_context(access()):
                raise AssertionError("failed refresh entered local work")
        assert not current._parallel.locked()
    finally:
        await current.close()
