import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mcpserver.loxone.service_access import ServiceMiniserverConnection


def client_fixture():
    token = SimpleNamespace(destroy=Mock())
    session = SimpleNamespace(close=AsyncMock())
    client = SimpleNamespace(
        acquire_token=AsyncMock(return_value=token), open_session=AsyncMock(return_value=session)
    )
    return client, token, session


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["token", "session", "cancel", "close"])
async def test_failed_or_cancelled_owner_releases_only_acquired_resources(failure):
    client, token, session = client_fixture()
    connection = ServiceMiniserverConnection(client, None, owner="local_admin")
    if failure == "token":
        client.acquire_token.side_effect = RuntimeError("rejected")
    elif failure == "session":
        client.open_session.side_effect = RuntimeError("rejected")
    elif failure == "cancel":
        entered = asyncio.Event()

        async def opening(_token):
            entered.set()
            await asyncio.Future()

        client.open_session.side_effect = opening
        task = asyncio.create_task(connection.connect("test", "test"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        session.close.side_effect = RuntimeError("close failed")
        await connection.connect("test", "test")
    if failure in {"token", "session"}:
        with pytest.raises(RuntimeError):
            await connection.connect("test", "test")
    if failure == "close":
        with pytest.raises(RuntimeError, match="close failed"):
            await connection.close()
    else:
        await connection.close()
    await connection.close()
    assert token.destroy.call_count == (0 if failure == "token" else 1)
    assert session.close.await_count == (1 if failure == "close" else 0)


@pytest.mark.asyncio
async def test_consumers_have_separate_owners_and_no_retained_credentials():
    first_client, first_token, first_session = client_fixture()
    second_client, second_token, second_session = client_fixture()
    first = ServiceMiniserverConnection(first_client, None, owner="runtime_event_stream")
    second = ServiceMiniserverConnection(second_client, None, owner="runtime_event_stream")
    assert await first.connect("test", "test") is first_session
    assert await second.connect("test", "test") is second_session
    await first.close()
    assert first_token.destroy.call_count == 1
    assert second_token.destroy.call_count == 0
    assert second_session.close.await_count == 0
    assert not any("password" in key or "username" in key for key in vars(first))
    await second.close()


@pytest.mark.asyncio
async def test_suppressed_authentication_does_not_start_network_login():
    client, token, session = client_fixture()
    coordinator = SimpleNamespace(attempt=AsyncMock(side_effect=RuntimeError("suppressed")))
    connection = ServiceMiniserverConnection(client, coordinator, owner="local_admin")
    with pytest.raises(RuntimeError, match="suppressed"):
        await connection.connect("test", "test")
    await connection.close()
    client.acquire_token.assert_not_awaited()
    client.open_session.assert_not_awaited()
    token.destroy.assert_not_called()
    session.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_cannot_start_two_authentication_attempts():
    client, token, session = client_fixture()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def acquiring(_username, _password):
        entered.set()
        await release.wait()
        return token

    client.acquire_token.side_effect = acquiring
    connection = ServiceMiniserverConnection(client, None, owner="local_admin")
    pending = asyncio.create_task(connection.connect("test", "test"))
    await entered.wait()
    with pytest.raises(RuntimeError, match="already started"):
        await connection.connect("test", "test")
    release.set()
    assert await pending is session
    await connection.close()
    with pytest.raises(RuntimeError, match="already started"):
        await connection.connect("test", "test")
    assert client.acquire_token.await_count == 1
    assert token.destroy.call_count == 1
