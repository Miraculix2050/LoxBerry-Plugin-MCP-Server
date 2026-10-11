from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver import tools
from mcpserver.loxone.models import Freshness, LoxoneIdentity, StateRecord
from mcpserver.loxone.notifications import decode_notification
from mcpserver.loxone.system_messages import MessageSourceError
from mcpserver.message_tools import register_message_tools


def test_latest_event_preserves_raw_context_without_severity_inference() -> None:
    record = decode_notification(
        json.dumps(
            {
                "uid": "test-event",
                "title": 'Warning "test"',
                "message": "token=secret https://example.test",
                "type": 99,
                "data": {"uuid": "11111111-1111-1111-1111111111111111", "lvl": 123},
            }
        )
    )
    assert record.title == 'Warning "test"'
    assert record.source_type == 99 and record.source_level == 123
    assert "secret" not in record.message and "https://" not in record.message
    escaped = decode_notification(r"{\"uid\":\"test-event\",\"message\":\"Hello\"}")
    assert escaped.message == "Hello"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "[]",
        '{"uid":true}',
        '{"uid":""}',
        '{"uids":["one"],"type":"read"}',
        '{"uid":"one","data":{"uuid":"../unsafe"}}',
        '{"uid":"one","data":{"lvl":true}}',
        "x" * 16_385,
    ],
)
def test_invalid_or_read_marker_payload_is_not_a_notification(value: str) -> None:
    with pytest.raises(MessageSourceError):
        decode_notification(value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "freshness,connected",
    [
        (Freshness.CURRENT, True),
        (Freshness.STALE, True),
        (Freshness.UNKNOWN, True),
        (Freshness.CURRENT, False),
    ],
)
async def test_mcp_latest_event_and_unavailable_coverage(monkeypatch, freshness, connected):
    monkeypatch.setattr(tools, "_access", lambda: object())
    record = StateRecord(
        "notification-state", '{"uid":"test","message":"Context"}', freshness, 100.0
    )
    snapshot = SimpleNamespace(
        connected=connected,
        structure_generation=1,
        structure=SimpleNamespace(identity=LoxoneIdentity("reader", "serial")),
    )
    runtime = SimpleNamespace(
        get_notification_state=AsyncMock(return_value=(snapshot, record.uuid, record, "17.2.8.28"))
    )
    server = FastMCP("notifications")
    register_message_tools(server, runtime)  # type: ignore[arg-type]
    tool = server._tool_manager.get_tool("loxone_get_notifications")
    result = await tool.fn()
    assert result.ok and result.data.history_available is False
    assert result.data.retention_complete is False and result.data.context_only
    available = freshness is Freshness.CURRENT and connected
    assert (result.data.latest is not None) == available
    assert result.stale == (not available)
    assert result.data.source_state_uuid == record.uuid
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    assert len(result.model_dump_json().encode()) < 65_536
