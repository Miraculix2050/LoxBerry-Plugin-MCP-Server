from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneToken,
    LoxoneWebSocketSession,
    MiniserverEndpoint,
    _close_websocket,
    _loxone_uuid,
    _receive_websocket,
)
from mcpserver.loxone.events import MessageType
from mcpserver.loxone.security import token_hmac


@pytest.mark.parametrize(
    "value",
    [
        "https://192.168.1.10",
        "http://user:pass@192.168.1.10",
        "http://example.test",
        "http://203.0.113.10",
        "http://192.168.1.10/path",
    ],
)
def test_gen1_endpoint_rejects_nonlocal_or_credentialed_values(value: str) -> None:
    with pytest.raises(ValueError):
        MiniserverEndpoint.parse_gen1(value)


@pytest.mark.asyncio
async def test_websocket_close_is_bounded() -> None:
    class BlockingWebSocket:
        async def close(self) -> None:
            await asyncio.Event().wait()

    await _close_websocket(cast(Any, BlockingWebSocket()), 0.001)


@pytest.mark.asyncio
async def test_websocket_receive_returns_complete_payload_without_waiting_again() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[bytes | str] = [
                bytes((3, MessageType.TEXT, 0, 0, 2, 0, 0, 0)),
                "{}",
            ]
            self.receive_count = 0

        async def recv(self) -> bytes | str:
            self.receive_count += 1
            return self.messages.pop(0)

    websocket = FakeWebSocket()

    header, payload = await _receive_websocket(
        cast(Any, websocket), timeout_seconds=0.1, max_payload_bytes=100
    )

    assert header.message_type is MessageType.TEXT
    assert payload == "{}"
    assert websocket.receive_count == 2


@pytest.mark.asyncio
async def test_websocket_receive_skips_estimated_header() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[bytes | str] = [
                bytes((3, MessageType.TEXT, 1, 0, 0, 0, 0, 0)),
                bytes((3, MessageType.TEXT, 0, 0, 2, 0, 0, 0)),
                "{}",
            ]

        async def recv(self) -> bytes | str:
            return self.messages.pop(0)

    header, payload = await _receive_websocket(
        cast(Any, FakeWebSocket()), timeout_seconds=0.1, max_payload_bytes=100
    )

    assert header.estimated is False
    assert payload == "{}"


def test_gen1_endpoint_builds_canonical_websocket_url() -> None:
    endpoint = MiniserverEndpoint.parse_gen1("http://192.168.1.10:8080")

    assert endpoint.websocket_url == "ws://192.168.1.10:8080/ws/rfc6455"


def test_client_uuid_uses_loxone_8_4_4_16_representation() -> None:
    value = UUID("098802e1-02b4-603c-ffff-eee000d80cfd")

    assert _loxone_uuid(value) == "098802e1-02b4-603c-ffffeee000d80cfd"


@pytest.mark.asyncio
async def test_http_errors_suppress_encrypted_request_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )

    class FailingClient:
        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _path: str) -> httpx.Response:
            request = httpx.Request("GET", "http://192.168.1.10/secret-encrypted-path")
            raise httpx.ConnectError("request failed", request=request)

    monkeypatch.setattr(
        "mcpserver.loxone.client.httpx.AsyncClient", lambda **_kwargs: FailingClient()
    )

    with pytest.raises(LoxoneConnectionError) as captured:
        await client._get_json("/secret-encrypted-path")

    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    assert "secret-encrypted-path" not in str(captured.value)


@pytest.mark.asyncio
async def test_probe_accepts_gen1_nested_json_value(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )

    async def fake_get_json(path: str) -> dict[str, object]:
        assert path == "/jdev/cfg/apiKey"
        return {
            "LL": {
                "Code": "200",
                "value": (
                    "{'version':'17.1.7.27','snr':'000000000000','local':true,'hasEventSlots':true}"
                ),
            }
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    result = await client.probe()

    assert result.firmware == "17.1.7.27"
    assert result.serial == "000000000000"
    assert result.is_local is True
    assert result.has_event_slots is True


@pytest.mark.asyncio
async def test_probe_rejects_tls_capable_miniserver(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )

    async def fake_get_json(path: str) -> dict[str, object]:
        assert path == "/jdev/cfg/apiKey"
        return {
            "LL": {
                "Code": "200",
                "value": {
                    "version": "17.1.7.27",
                    "snr": "000000000000",
                    "httpsStatus": 1,
                },
            }
        }

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    with pytest.raises(LoxoneConnectionError, match="Gen. 2"):
        await client.probe()


@pytest.mark.asyncio
async def test_token_acquisition_encrypts_credentials_and_retains_hash_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    commands: list[tuple[str, bool]] = []

    class FakeWebSocket:
        closed = False

        async def close(self) -> None:
            self.closed = True

    websocket = FakeWebSocket()

    async def fake_websocket_public_key() -> str:
        return public_pem

    async def fake_connect_websocket() -> Any:
        return websocket

    async def fake_websocket_command(
        _websocket: Any,
        _encryptor: Any,
        command: str,
        *,
        encrypted: bool,
        timeout_seconds: float,
        max_payload_bytes: int,
    ) -> object:
        assert timeout_seconds == client.timeout_seconds
        assert max_payload_bytes == client.max_response_bytes
        commands.append((command, encrypted))
        if not encrypted:
            assert command.startswith("jdev/sys/keyexchange/")
            return "OK"
        if command == "jdev/sys/getkey2/restricted-reader":
            return {"key": "00112233", "salt": "a1b2", "hashAlg": "SHA256"}
        assert command.startswith("jdev/sys/getjwt/")
        assert "/restricted-reader/4/098802e1-02b4-603c-ffffeee000d80cfd/" in command
        return {"token": "jwt-secret", "key": "44556677", "validUntil": 123}

    monkeypatch.setattr(client, "websocket_public_key", fake_websocket_public_key)
    monkeypatch.setattr(client, "_connect_websocket", fake_connect_websocket)
    monkeypatch.setattr("mcpserver.loxone.client._websocket_command", fake_websocket_command)

    token = await client.acquire_token("restricted-reader", "password-secret")

    assert token.hash_algorithm == "SHA1"
    assert "jwt-secret" not in repr(token)
    assert "password-secret" not in "".join(command for command, _ in commands)
    assert commands[0][1] is False
    assert commands[1] == ("jdev/sys/getkey2/restricted-reader", True)
    assert commands[2][1] is True
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_token_acquisition_closes_websocket_when_keyexchange_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    class FakeWebSocket:
        closed = False

        async def close(self) -> None:
            self.closed = True

    websocket = FakeWebSocket()

    async def fake_websocket_public_key() -> str:
        return public_pem

    async def fake_connect_websocket() -> Any:
        return websocket

    async def fail_command(*_args: object, **_kwargs: object) -> object:
        raise LoxoneConnectionError("Miniserver rejected the request")

    monkeypatch.setattr(client, "websocket_public_key", fake_websocket_public_key)
    monkeypatch.setattr(client, "_connect_websocket", fake_connect_websocket)
    monkeypatch.setattr("mcpserver.loxone.client._websocket_command", fail_command)

    with pytest.raises(LoxoneConnectionError, match="rejected"):
        await client.acquire_token("restricted-reader", "password-secret")

    assert websocket.closed is True


@pytest.mark.asyncio
async def test_token_revocation_uses_encrypted_websocket_and_destroys_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LoxoneClient(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        client_uuid=UUID("098802e1-02b4-603c-ffff-eee000d80cfd"),
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    commands: list[tuple[str, bool]] = []

    class FakeWebSocket:
        closed = False

        async def close(self) -> None:
            self.closed = True

    websocket = FakeWebSocket()

    async def fake_websocket_public_key() -> str:
        return public_pem

    async def fake_connect_websocket() -> Any:
        return websocket

    async def fake_websocket_command(
        _websocket: Any,
        _encryptor: Any,
        command: str,
        *,
        encrypted: bool,
        timeout_seconds: float,
        max_payload_bytes: int,
    ) -> object:
        assert timeout_seconds == client.timeout_seconds
        assert max_payload_bytes == client.max_response_bytes
        commands.append((command, encrypted))
        return "OK"

    monkeypatch.setattr(client, "websocket_public_key", fake_websocket_public_key)
    monkeypatch.setattr(client, "_connect_websocket", fake_connect_websocket)
    monkeypatch.setattr("mcpserver.loxone.client._websocket_command", fake_websocket_command)
    token = LoxoneToken("jwt-secret", "restricted-reader", "00112233", "SHA1", 123)

    await client.kill_token(token)

    assert commands[0][0].startswith("jdev/sys/keyexchange/")
    assert commands[0][1] is False
    assert commands[1][0].startswith("jdev/sys/killtoken/")
    assert commands[1][1] is True
    assert "jwt-secret" not in commands[1][0]
    assert websocket.closed is True
    assert token.value == ""


@pytest.mark.asyncio
async def test_refresh_rotates_in_memory_token_with_dynamic_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = LoxoneToken("old-secret", "reader", "00112233", "SHA256", 100)
    session = LoxoneWebSocketSession(
        cast(Any, object()),
        public_key="unused",
        token=token,
        timeout_seconds=1,
        max_payload_bytes=100,
    )

    async def fake_command(command: str, *, encrypted: bool = False) -> dict[str, object]:
        expected = token_hmac("old-secret", "00112233", "SHA256")
        assert command == f"jdev/sys/refreshjwt/{expected}/reader"
        assert encrypted is True
        return {"token": "new-secret", "validUntil": 200}

    monkeypatch.setattr(session, "_command", fake_command)

    await session.refresh_token()

    assert token.value == "new-secret"
    assert token.valid_until == 200
    assert "new-secret" not in repr(token)
