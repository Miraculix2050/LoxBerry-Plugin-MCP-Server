"""Asynchronous Gen. 1 client with strict local transport boundaries."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Subprotocol

from mcpserver.loxone.events import (
    LoxoneProtocolError,
    MessageHeader,
    MessageType,
    StateEvent,
    parse_header,
    parse_state_events,
)
from mcpserver.loxone.models import LoxoneStructure
from mcpserver.loxone.security import (
    CommandEncryptor,
    LoxoneSecurityError,
    normalize_rsa_public_key_pem,
    password_hmac,
    token_hmac,
)
from mcpserver.loxone.structure import normalize_structure

_LOGGER = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS: Final = 10.0
_APP_PERMISSION: Final = 4
_GEN1_IPV4_NETWORKS: Final = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_GEN1_IPV6_NETWORK: Final = ipaddress.ip_network("fc00::/7")


class LoxoneConnectionError(RuntimeError):
    """Sanitized error raised when the Miniserver cannot be used securely."""


def _loxone_uuid(value: UUID) -> str:
    """Serialize a standard UUID using Loxone's 8-4-4-16 representation."""
    first, second, third, fourth, fifth = str(value).split("-")
    return f"{first}-{second}-{third}-{fourth}{fifth}"


@dataclass(frozen=True, slots=True)
class MiniserverEndpoint:
    """A literal private Gen. 1 HTTP endpoint without path or credentials."""

    origin: str
    host: str
    port: int

    @classmethod
    def parse_gen1(cls, value: str) -> MiniserverEndpoint:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Gen. 1 endpoint must be a plain HTTP origin without credentials")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            port = parsed.port or 80
        except ValueError as exc:
            raise ValueError("Gen. 1 endpoint must use a literal private IP address") from exc
        is_allowed = (
            any(address in network for network in _GEN1_IPV4_NETWORKS)
            if isinstance(address, ipaddress.IPv4Address)
            else address in _GEN1_IPV6_NETWORK
        )
        if not is_allowed:
            raise ValueError("Gen. 1 endpoint must use a private local IP address")
        host = f"[{address}]" if address.version == 6 else str(address)
        origin = f"http://{host}" if port == 80 else f"http://{host}:{port}"
        if value.rstrip("/") != origin:
            raise ValueError("Gen. 1 endpoint must use a canonical origin")
        return cls(origin=origin, host=str(address), port=port)

    @property
    def websocket_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        authority = host if self.port == 80 else f"{host}:{self.port}"
        return f"ws://{authority}/ws/rfc6455"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    firmware: str
    serial: str
    is_local: bool | None
    has_event_slots: bool | None


@dataclass(slots=True)
class LoxoneToken:
    """Ephemeral JWT and the hash key returned with it."""

    value: str = field(repr=False)
    username: str
    hash_key: str = field(repr=False)
    hash_algorithm: str
    valid_until: int

    def destroy(self) -> None:
        self.value = ""
        self.hash_key = ""
        self.hash_algorithm = ""


def _response_value(document: Mapping[str, Any]) -> Any:
    wrapper = document.get("LL")
    if not isinstance(wrapper, Mapping):
        raise LoxoneConnectionError("Miniserver returned an invalid response")
    code = wrapper.get("Code", wrapper.get("code"))
    if str(code) != "200":
        raise LoxoneConnectionError("Miniserver rejected the request")
    return wrapper.get("value")


class LoxoneClient:
    """Acquire an ephemeral JWT and open user-filtered WebSocket sessions."""

    def __init__(
        self,
        endpoint: MiniserverEndpoint,
        *,
        client_uuid: UUID,
        client_name: str = "LoxBerry MCP Server",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        self.endpoint = endpoint
        self.client_uuid = client_uuid
        self.client_name = client_name
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    async def _get_json(self, path: str) -> Mapping[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.endpoint.origin,
                follow_redirects=False,
                timeout=self.timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                if len(response.content) > self.max_response_bytes:
                    raise LoxoneConnectionError("Miniserver response exceeds the configured limit")
                value = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            # httpx exceptions may contain the complete encrypted request URL.
            # Suppress the cause so callers and logs only see this fixed text.
            raise LoxoneConnectionError("Miniserver request failed") from None
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver returned an invalid response")
        return value

    async def probe(self) -> ProbeResult:
        value = _response_value(await self._get_json("/jdev/cfg/apiKey"))
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver probe returned an invalid value")
        https_status = value.get("httpsStatus")
        if https_status not in {None, 0, "0"}:
            raise LoxoneConnectionError("TLS-capable Miniservers require the Gen. 2 HTTPS adapter")
        firmware = value.get("version", value.get("versionStr"))
        serial = value.get("snr", value.get("serialNr"))
        if not isinstance(firmware, str) or not isinstance(serial, str):
            raise LoxoneConnectionError("Miniserver probe omitted identity data")
        local = value.get("local")
        if local is False or local == 0:
            raise LoxoneConnectionError("Gen. 1 connections must be local")
        slots = value.get("hasEventSlots")
        return ProbeResult(
            firmware=firmware,
            serial=serial,
            is_local=local if isinstance(local, bool) else None,
            has_event_slots=slots if isinstance(slots, bool) else None,
        )

    async def public_key(self) -> str:
        value = _response_value(await self._get_json("/jdev/sys/getPublicKey"))
        if not isinstance(value, str):
            raise LoxoneConnectionError("Miniserver returned an invalid public key")
        try:
            return normalize_rsa_public_key_pem(value)
        except LoxoneSecurityError as exc:
            raise LoxoneConnectionError("Miniserver returned an invalid public key") from exc

    async def acquire_token(self, username: str, password: str) -> LoxoneToken:
        public_key = await self.public_key()
        escaped_user = quote(username, safe="")
        key_value = _response_value(await self._get_json(f"/jdev/sys/getkey2/{escaped_user}"))
        if not isinstance(key_value, Mapping):
            raise LoxoneConnectionError("Miniserver returned invalid hashing parameters")
        key = key_value.get("key")
        salt = key_value.get("salt")
        algorithm = key_value.get("hashAlg")
        if not isinstance(key, str) or not isinstance(salt, str) or not isinstance(algorithm, str):
            raise LoxoneConnectionError("Miniserver returned invalid hashing parameters")
        credential_hash = password_hmac(username, password, key, salt, algorithm)
        info = quote(self.client_name, safe="")
        command = (
            f"jdev/sys/getjwt/{credential_hash}/{escaped_user}/{_APP_PERMISSION}/"
            f"{_loxone_uuid(self.client_uuid)}/{info}"
        )
        encrypted_path = CommandEncryptor.generate().encrypted_http_request(command, public_key)
        token_value = _response_value(await self._get_json(encrypted_path))
        if not isinstance(token_value, Mapping):
            raise LoxoneConnectionError("Miniserver returned an invalid token")
        token = token_value.get("token")
        token_key = token_value.get("key")
        valid_until = token_value.get("validUntil")
        if (
            not isinstance(token, str)
            or not isinstance(token_key, str)
            or not isinstance(valid_until, int)
        ):
            raise LoxoneConnectionError("Miniserver returned an invalid token")
        return LoxoneToken(token, username, token_key, algorithm, valid_until)

    async def kill_token(self, token: LoxoneToken) -> None:
        if not token.value:
            return
        public_key = await self.public_key()
        digest = token_hmac(token.value, token.hash_key, token.hash_algorithm)
        user = quote(token.username, safe="")
        command = f"jdev/sys/killtoken/{digest}/{user}"
        try:
            encrypted_path = CommandEncryptor.generate().encrypted_http_request(command, public_key)
            _response_value(await self._get_json(encrypted_path))
        finally:
            token.destroy()

    async def open_session(self, token: LoxoneToken) -> LoxoneWebSocketSession:
        if not token.value:
            raise LoxoneConnectionError("Loxone token is no longer available")
        public_key = await self.public_key()
        try:
            websocket = await asyncio.wait_for(
                connect(
                    self.endpoint.websocket_url,
                    subprotocols=[Subprotocol("remotecontrol")],
                    max_size=self.max_response_bytes,
                    open_timeout=self.timeout_seconds,
                    proxy=None,
                ),
                timeout=self.timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            raise LoxoneConnectionError("Miniserver WebSocket connection failed") from exc
        session = LoxoneWebSocketSession(
            websocket,
            public_key=public_key,
            token=token,
            timeout_seconds=self.timeout_seconds,
            max_payload_bytes=self.max_response_bytes,
        )
        try:
            await session.authenticate()
        except Exception:
            await session.close()
            raise
        return session


class LoxoneWebSocketSession:
    """One authenticated, user-bound WebSocket session."""

    def __init__(
        self,
        websocket: ClientConnection,
        *,
        public_key: str,
        token: LoxoneToken,
        timeout_seconds: float,
        max_payload_bytes: int,
    ) -> None:
        self._websocket = websocket
        self._public_key = public_key
        self._token = token
        self._timeout = timeout_seconds
        self._max_payload = max_payload_bytes
        self._encryptor = CommandEncryptor.generate()

    async def _receive(self) -> tuple[MessageHeader, str | bytes | None]:
        while True:
            raw_header = await asyncio.wait_for(self._websocket.recv(), timeout=self._timeout)
            if not isinstance(raw_header, bytes):
                raise LoxoneProtocolError("Expected a binary WebSocket header")
            header = parse_header(raw_header, max_payload_bytes=self._max_payload)
            if header.estimated:
                continue
            if header.message_type in {MessageType.OUT_OF_SERVICE, MessageType.KEEPALIVE}:
                return header, None
            payload = await asyncio.wait_for(self._websocket.recv(), timeout=self._timeout)
            actual_size = len(payload.encode() if isinstance(payload, str) else payload)
            if actual_size != header.payload_length:
                raise LoxoneProtocolError("WebSocket payload length does not match its header")
            return header, payload

    async def _command(self, command: str, *, encrypted: bool = False) -> Any:
        outgoing = self._encryptor.encrypted_command(command) if encrypted else command
        await self._websocket.send(outgoing)
        header, payload = await self._receive()
        if header.message_type is not MessageType.TEXT or not isinstance(payload, str):
            raise LoxoneProtocolError("Miniserver command response is not text")
        try:
            response = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LoxoneProtocolError("Miniserver command response is not JSON") from exc
        if not isinstance(response, Mapping):
            raise LoxoneProtocolError("Miniserver command response is invalid")
        return _response_value(response)

    async def authenticate(self) -> None:
        session_key = self._encryptor.encrypted_session_key(self._public_key)
        await self._command(f"jdev/sys/keyexchange/{session_key}")
        digest = token_hmac(
            self._token.value,
            self._token.hash_key,
            self._token.hash_algorithm,
        )
        await self._command(
            f"authwithtoken/{digest}/{quote(self._token.username, safe='')}",
            encrypted=True,
        )

    async def load_structure(self) -> LoxoneStructure:
        await self._websocket.send("data/LoxAPP3.json")
        header, payload = await self._receive()
        if header.message_type is not MessageType.TEXT or not isinstance(payload, str):
            raise LoxoneProtocolError("Miniserver structure response is not text")
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LoxoneProtocolError("Miniserver structure response is not JSON") from exc
        if not isinstance(document, Mapping):
            raise LoxoneProtocolError("Miniserver structure response is invalid")
        return normalize_structure(document, username=self._token.username)

    async def refresh_token(self) -> None:
        """Rotate the in-memory JWT over the authenticated encrypted WebSocket."""
        digest = token_hmac(
            self._token.value,
            self._token.hash_key,
            self._token.hash_algorithm,
        )
        user = quote(self._token.username, safe="")
        value = await self._command(f"jdev/sys/refreshjwt/{digest}/{user}", encrypted=True)
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver returned an invalid refreshed token")
        refreshed = value.get("token")
        valid_until = value.get("validUntil")
        if not isinstance(refreshed, str) or not isinstance(valid_until, int):
            raise LoxoneConnectionError("Miniserver returned an invalid refreshed token")
        self._token.value = refreshed
        self._token.valid_until = valid_until

    async def state_events(self) -> AsyncIterator[tuple[StateEvent, ...]]:
        await self._command("jdev/sps/enablebinstatusupdate")
        while True:
            header, payload = await self._receive()
            if header.message_type is MessageType.OUT_OF_SERVICE:
                raise LoxoneConnectionError("Miniserver is temporarily out of service")
            if header.message_type in {
                MessageType.VALUE_STATES,
                MessageType.TEXT_STATES,
                MessageType.DAYTIMER_STATES,
                MessageType.WEATHER_STATES,
            }:
                if not isinstance(payload, bytes):
                    raise LoxoneProtocolError("State event payload is not binary")
                yield parse_state_events(header.message_type, payload)

    async def keepalive(self) -> None:
        await self._websocket.send("keepalive")
        header, _ = await self._receive()
        if header.message_type is not MessageType.KEEPALIVE:
            raise LoxoneProtocolError("Miniserver did not acknowledge keepalive")

    async def close(self) -> None:
        try:
            await self._websocket.close()
        except Exception as exc:  # pragma: no cover - best effort close
            _LOGGER.debug("WebSocket close failed: %s", type(exc).__name__)
