import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver import tools
from mcpserver.attention_tools import register_attention_tools
from mcpserver.loxone.client import LoxoneClient
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.message_tools import NotificationsEnvelope, SystemMessagesEnvelope
from mcpserver.tools import ActiveAlertsEnvelope


def readers(monkeypatch, *, large=False, client=None):
    monkeypatch.setattr(tools, "_access", lambda: object())
    alerts = tools._result(
        ActiveAlertsEnvelope,
        {
            "structure_generation": 1,
            "findings": [],
            "known_active": 0,
            "total_active": 0,
            "returned": 0,
            "truncated": False,
            "complete": True,
            "coverage": {
                "candidate_controls": 0,
                "evaluated_controls": 0,
                "unsupported_controls": 0,
                "unavailable_controls": 0,
                "scan_complete": True,
                "complete": True,
                "reasons": [],
                "reasons_truncated": False,
            },
        },
    )
    messages = tools._result(
        SystemMessagesEnvelope,
        {
            "firmware": "17.2.8.28",
            "miniserver_serial": "001122334455",
            "message_center_uuid": "11111111-1111-1111-1111111111111111",
            "source_revision": "revision",
            "source_total": 0,
            "records": [],
            "mode": "current",
            "selected_total": 0,
            "returned": 0,
            "cursor": None,
            "truncated": False,
            "page_complete": True,
        },
    )
    if large:
        messages.warnings = ["x" * 22_000]
    notifications = tools._error(NotificationsEnvelope, "unsupported_source", "Unavailable")
    server = FastMCP("overview")
    calls = []

    @server.tool(name="loxone_get_active_alerts")
    async def get_alerts(limit: int = 5) -> ActiveAlertsEnvelope:
        if client is not None:
            await client.websocket_public_key()
        calls.append(("alerts", limit))
        return alerts

    @server.tool(name="loxone_get_system_messages")
    async def get_messages(mode: str = "current", limit: int = 5) -> SystemMessagesEnvelope:
        if client is not None:
            await client.websocket_public_key()
        calls.append(("messages", mode, limit))
        if mode == "all":
            return tools._error(SystemMessagesEnvelope, "permission_denied", "History denied")
        return messages

    @server.tool(name="loxone_get_notifications")
    async def get_notifications() -> NotificationsEnvelope:
        if client is not None:
            await client.websocket_public_key()
        calls.append(("notifications",))
        return notifications

    runtime = SimpleNamespace(_require_access=AsyncMock(), client=client)
    register_attention_tools(server, runtime)
    return server._tool_manager.get_tool("loxone_get_attention_overview"), runtime, calls, alerts


@pytest.mark.asyncio
async def test_overview_retains_independent_contracts_and_partial_failure(monkeypatch):
    tool, runtime, calls, alerts = readers(monkeypatch)
    result = await tool.fn()
    assert result.ok and result.stale
    assert result.data.active_alerts == alerts
    assert result.data.coverage.notifications == "unavailable"
    assert result.data.notifications.data.error == "unsupported_source"
    assert result.data.coverage_complete is False and result.data.simultaneous is False
    assert calls == [("alerts", 5), ("messages", "current", 5), ("notifications",)]
    runtime._require_access.assert_awaited_once()
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint


@pytest.mark.asyncio
async def test_history_denial_is_preserved_without_promoting_other_sources(monkeypatch):
    tool, runtime, calls, alerts = readers(monkeypatch)
    result = await tool.fn(include_history=True)
    assert result.ok and result.data.system_message_mode == "all"
    assert result.data.coverage.system_messages == "unavailable"
    assert result.data.system_messages.data.error == "permission_denied"
    assert result.data.active_alerts == alerts


@pytest.mark.asyncio
async def test_large_source_requires_dedicated_reader_without_oversize_overview(monkeypatch):
    tool, runtime, calls, alerts = readers(monkeypatch, large=True)
    result = await tool.fn()
    assert result.data.system_messages.data.error == "response_too_large"
    assert result.data.coverage.system_messages == "unavailable"
    assert len(result.model_dump_json().encode()) < 65_536
    assert result.data.active_alerts == alerts


@pytest.mark.asyncio
async def test_revocation_discards_all_overview_data(monkeypatch):
    tool, runtime, calls, alerts = readers(monkeypatch)
    runtime._require_access.side_effect = PermissionError()
    result = await tool.fn()
    assert not result.ok and result.data.error == "permission_denied"
    assert not hasattr(result.data, "system_messages")


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 11}, {"include_history": 1}])
async def test_invalid_input_precedes_every_source(monkeypatch, kwargs):
    tool, runtime, calls, alerts = readers(monkeypatch)
    result = await tool.fn(**kwargs)
    assert not result.ok and result.data.error == "invalid_input"
    assert calls == []


@pytest.fixture
def overview_client(monkeypatch):
    client = LoxoneClient(MiniserverEndpoint.parse("http://192.168.1.1"), client_uuid=UUID(int=1))
    holders = []

    async def fetch(_path):
        holders.append(client._certificate_scope.get())
        await asyncio.sleep(0)
        return "public certificate"

    fetch_mock = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(client, "_get_text", fetch_mock)
    monkeypatch.setattr(
        "mcpserver.loxone.client.normalize_loxone_certificate_chain_pem", lambda value: value
    )
    return client, fetch_mock, holders


@pytest.mark.asyncio
async def test_overview_reuses_only_certificate_and_rechecks_access(monkeypatch, overview_client):
    client, fetch, holders = overview_client
    tool, runtime, calls, _ = readers(monkeypatch, client=client)
    for _ in range(2):
        result = await tool.fn(limit=3, include_history=True)
        assert result.ok and result.data.system_messages.data.error == "permission_denied"
    assert fetch.await_count == 2
    assert calls == [("alerts", 3), ("messages", "all", 3), ("notifications",)] * 2
    assert runtime._require_access.await_count == 2
    assert len({id(holder) for holder in holders}) == 2
    assert all(
        holder.purpose == "attention" and not holder.active and holder.pem is None
        for holder in holders
    )
    assert client._certificate_scope.get() is None


@pytest.mark.asyncio
async def test_overview_concurrent_calls_have_separate_holders(monkeypatch, overview_client):
    client, fetch, holders = overview_client
    tool, runtime, calls, _ = readers(monkeypatch, client=client)
    await asyncio.gather(tool.fn(), tool.fn())
    assert fetch.await_count == 2 and runtime._require_access.await_count == 2
    assert holders[0] is not holders[1]
    assert all(not holder.active and holder.pem is None for holder in holders)


@pytest.mark.asyncio
async def test_overview_revocation_and_cancellation_clear_certificate(monkeypatch, overview_client):
    client, fetch, holders = overview_client
    tool, runtime, calls, _ = readers(monkeypatch, client=client)
    runtime._require_access.side_effect = PermissionError()
    assert not (await tool.fn()).ok
    assert not holders[0].active and holders[0].pem is None
    started = asyncio.Event()

    async def blocked(_path):
        holders.append(client._certificate_scope.get())
        started.set()
        await asyncio.Event().wait()

    fetch.side_effect = blocked
    task = asyncio.create_task(tool.fn())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(not holder.active and holder.pem is None for holder in holders)
