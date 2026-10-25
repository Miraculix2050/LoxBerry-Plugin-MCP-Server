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
    nested = json.dumps(json.dumps({"uid": "one", "message": 'Warning "quoted" \\ path'}))[1:-1]
    assert decode_notification(nested).message == 'Warning "quoted" \\ path'
    sanitized = decode_notification(
        '{"uid":"one","message":"Context","type":"token=secret",'
        '"data":{"lvl":"password=multi word"}}'
    )
    assert sanitized.source_type == "token=[redacted]"
    assert sanitized.source_level == "password=[redacted]"


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
        '{"uid":"\\ud800"}',
        '{"uid":"one","type":"\\ud800"}',
        '{"uid":"token=secret"}',
        '{"uid":"token:actual-secret","message":"Context"}',
        '{"uid":"one"}',
        '{"uid":"one","message":"  "}',
        "x" * 16_385,
    ],
)
def test_invalid_or_read_marker_payload_is_not_a_notification(value: str) -> None:
    with pytest.raises(MessageSourceError):
        decode_notification(value)


def test_notification_text_can_be_serialized_after_surrogate_normalization():
    record = decode_notification('{"uid":"one","message":"Warning\\ud800"}')
    assert record.message == "Warning"
    record.model_dump_json().encode("utf-8")


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
        "11111111-1111-1111-1111111111111111",
        '{"uid":"test","message":"Context"}',
        freshness,
        100.0,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uuid,value",
    [
        ("11111111-1111-1111-1111111111111111", 0.0),
        ("token=secret", '{"uid":"one","message":"Context"}'),
    ],
)
async def test_invalid_current_state_or_source_identity_is_unsupported(monkeypatch, uuid, value):
    monkeypatch.setattr(tools, "_access", lambda: object())
    snapshot = SimpleNamespace(connected=True)
    runtime = SimpleNamespace(
        get_notification_state=AsyncMock(
            return_value=(
                snapshot,
                uuid,
                StateRecord(uuid, value, Freshness.CURRENT, 100.0),
                "17.2.8.28",
            )
        )
    )
    server = FastMCP("notifications")
    register_message_tools(server, runtime)
    result = await server._tool_manager.get_tool("loxone_get_notifications").fn()
    assert not result.ok and result.data.error == "unsupported_source"


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", ["17.2.10.21", "99.0.0.1"])
async def test_notification_source_accepts_changed_firmware(firmware):
    from dataclasses import replace
    from unittest.mock import Mock

    from test_system_messages import access, runtime

    from mcpserver.loxone.models import GlobalMetadata
    from mcpserver.loxone.runtime import RuntimeSnapshot

    instance, session, _token = runtime()
    state = "11111111-1111-1111-1111111111111111"
    structure = replace(
        session.load_structure.return_value,
        global_metadata=(
            GlobalMetadata("global_state", "notifications", "Notifications", state_uuid=state),
        ),
    )
    snapshot = RuntimeSnapshot("family", structure, True)
    instance.snapshot = AsyncMock(return_value=snapshot)
    instance.state = Mock(return_value=StateRecord(state, "", Freshness.CURRENT, 100.0))
    instance.client.probe.return_value.firmware = firmware
    result = await instance.get_notification_state(access())
    assert result[3] == firmware
