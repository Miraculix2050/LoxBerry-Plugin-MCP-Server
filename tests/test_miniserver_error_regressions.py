"""Regression coverage for issue #588; all transports are synthetic."""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest
from test_system_messages import access, runtime
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close

from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneCommandRejected,
    LoxoneResponseEnvelopeError,
    LoxoneResponseProtocolError,
    LoxoneSourceIpBlocked,
    LoxoneTokenAuthenticationRejected,
    LoxoneTransportTimeout,
    LoxoneWebSocketClosed,
    LoxoneWebSocketSession,
    MiniserverEndpoint,
    _receive_websocket,
    _response_value,
    _send_websocket,
)
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.runtime import ControlOperationError, RuntimeUnavailable
from mcpserver.service_discovery import _failure_category


def session(socket):
    instance = object.__new__(LoxoneWebSocketSession)
    instance._websocket = socket
    instance._secure_transport = True
    instance._encryptor = object()
    instance._timeout, instance._max_payload = 0.1, 32768
    instance._token = SimpleNamespace(username="synthetic")
    instance._token_credential = AsyncMock(return_value="synthetic")
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [1006, 4003])
@pytest.mark.parametrize("stage", ["send", "header", "payload"])
async def test_close_normalized_at_every_frame_boundary(code, stage):
    error = ConnectionClosedError(Close(code, "private peer reason"), None)
    frames = [error] if stage == "header" else [struct.pack("<BBBBI", 3, 0, 0, 0, 2), error]
    socket = SimpleNamespace(send=AsyncMock(side_effect=error), recv=AsyncMock(side_effect=frames))
    expected = LoxoneSourceIpBlocked if code == 4003 else LoxoneWebSocketClosed
    with pytest.raises(expected) as caught:
        if stage == "send":
            await _send_websocket(socket, "keepalive")
        else:
            await _receive_websocket(socket, timeout_seconds=0.1, max_payload_bytes=100)
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert _failure_category(caught.value) == (
        "source_ip_blocked" if code == 4003 else "disconnect"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args",
    [
        ("load_structure", ()),
        ("control_history", ("synthetic",)),
        ("control_notes", ("synthetic",)),
        ("legacy_statistic_data", ("synthetic", "20261025")),
        ("keepalive", ()),
    ],
)
async def test_direct_sends_use_sanitized_close(method, args):
    socket = SimpleNamespace(
        send=AsyncMock(side_effect=ConnectionClosedError(Close(4003, "private"), None))
    )
    with pytest.raises(LoxoneSourceIpBlocked):
        await getattr(session(socket), method)(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["send", "header", "payload", "credential"])
@pytest.mark.parametrize("normal", [True, False])
async def test_killtoken_terminal_close_only_after_successful_send(stage, normal):
    close = (
        ConnectionClosedOK(Close(1000, "private"), Close(1000, ""), True)
        if normal
        else ConnectionClosedError(Close(1006, "private"), None)
    )
    frames = [close] if stage != "payload" else [struct.pack("<BBBBI", 3, 0, 0, 0, 2), close]
    socket = SimpleNamespace(
        send=AsyncMock(side_effect=close if stage == "send" else None),
        recv=AsyncMock(side_effect=frames),
    )
    current = session(socket)
    if stage == "credential":
        current._token_credential.side_effect = LoxoneWebSocketClosed("fixed", normal_close=normal)
    if normal and stage in {"header", "payload"}:
        await current.kill_token()
    else:
        with pytest.raises(LoxoneWebSocketClosed):
            await current.kill_token()
    assert socket.send.await_count == (0 if stage == "credential" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["session", "read"])
@pytest.mark.parametrize(
    "code,expected",
    [
        ("401", "permission_denied"),
        ("403", "permission_denied"),
        ("500", "temporarily_unavailable"),
    ],
)
async def test_message_command_failure_does_not_damage_token_health(phase, code, expected):
    instance, native, _token = runtime()
    instance._require_access = AsyncMock()
    instance.token_health = SimpleNamespace(
        get=Mock(return_value=SimpleNamespace(confirmation_required=False)),
        record_successful_authentication=Mock(),
        record_rejected_authentication=Mock(),
    )
    (
        instance._open_session if phase == "session" else native.system_messages
    ).side_effect = LoxoneCommandRejected("fixed", response_code=code)
    with pytest.raises(ControlOperationError) as caught:
        async with instance.message_source_session(access()):
            pass
    assert caught.value.code == expected
    instance.token_health.record_rejected_authentication.assert_not_called()


@pytest.mark.asyncio
async def test_session_server_failure_never_counts_as_bad_token():
    instance, _native, _token = runtime()
    instance.token_health = SimpleNamespace(
        get=Mock(return_value=SimpleNamespace(confirmation_required=False)),
        record_rejected_authentication=Mock(),
    )
    instance._open_session.side_effect = LoxoneCommandRejected("fixed", response_code="500")
    for _ in range(4):
        with pytest.raises(RuntimeUnavailable, match="rejected session establishment"):
            await instance._connect(access())
    instance.token_health.record_rejected_authentication.assert_not_called()
    assert instance._open_session.await_count == 4


@pytest.mark.asyncio
async def test_history_authentication_rejection_is_permission_error():
    instance, _native, _token = runtime()
    instance.history_enabled = True
    instance._open_session.side_effect = LoxoneTokenAuthenticationRejected(
        "fixed", response_code="401"
    )
    identity = access()
    identity.scopes.append("loxone:history")
    with pytest.raises(ControlOperationError) as caught:
        async with instance.history_context(identity):
            pass
    assert caught.value.code == "permission_denied"


class FailContext:
    async def __aenter__(self):
        raise httpx.ReadTimeout("private encrypted URL")

    async def __aexit__(self, *_args):
        pass


class FakeHttp:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    def stream(self, *_args, **_kwargs):
        return FailContext()


@pytest.mark.asyncio
async def test_transport_timeout_and_protocol_categories_are_preserved():
    client = LoxoneClient(
        MiniserverEndpoint.parse("https://miniserver.example"), client_uuid=UUID(int=1)
    )
    with patch("mcpserver.loxone.client.connect", AsyncMock(side_effect=TimeoutError("private"))):
        with pytest.raises(LoxoneTransportTimeout) as caught:
            await client._connect_websocket()
        assert _failure_category(caught.value) == "timeout"
        assert "private" not in str(caught.value)
    with patch("mcpserver.loxone.client.httpx.AsyncClient", FakeHttp):
        with pytest.raises(LoxoneTransportTimeout) as caught:
            await client._get_bytes("/fixed")
        assert _failure_category(caught.value) == "timeout"
        assert caught.value.__suppress_context__
        with pytest.raises(ProjectError) as project:
            await client.download_project(SimpleNamespace(value="synthetic", username="synthetic"))
        assert str(project.value) == "project_timeout"
    client._get_bytes = AsyncMock(return_value=(b"invalid-json", "utf-8"))
    with pytest.raises(LoxoneResponseProtocolError) as caught:
        await client._get_json("/fixed")
    assert _failure_category(caught.value) == "protocol"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected,log",
    [
        ("{}", LoxoneResponseEnvelopeError, "invalid_response"),
        ('{"LL":{"Code":500}}', LoxoneCommandRejected, "command_rejected"),
    ],
)
async def test_statistics_logs_protocol_separately_from_rejection(payload, expected, log, caplog):
    socket = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(side_effect=[struct.pack("<BBBBI", 3, 0, 0, 0, len(payload)), payload]),
    )
    with pytest.raises(expected):
        await session(socket).statistic_data(
            "synthetic", mode="diff", start=0, end=1, unit="hour", group_id="2", output="total"
        )
    assert f"outcome={log}" in caplog.text
    if log == "invalid_response":
        assert "command_rejected" not in caplog.text


@pytest.mark.parametrize("code", [None, True, "private peer detail", {}, ""])
def test_missing_or_malformed_status_is_protocol_not_rejection(code):
    with pytest.raises(LoxoneResponseEnvelopeError) as caught:
        _response_value({"LL": {"Code": code}})
    assert "private" not in str(caught.value)
