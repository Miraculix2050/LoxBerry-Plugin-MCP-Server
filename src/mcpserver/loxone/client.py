"""Asynchronous Gen. 1 client with strict local transport boundaries."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedOK
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
    normalize_loxone_certificate_chain_pem,
    normalize_rsa_public_key_pem,
    password_hmac,
    token_hmac,
)
from mcpserver.loxone.structure import LoxoneStructureError, normalize_structure

_LOGGER = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS: Final = 10.0
_APP_PERMISSION: Final = 4
_PERCENT_COMMAND = r"(?:100(?:\.0+)?|(?:[0-9]|[1-9][0-9])(?:\.[0-9]+)?)"
_CONTROL_COMMAND = re.compile(
    rf"(?:on|off|pulse|reset|FullUp|FullDown|shade|stop|auto|NoAuto|"
    rf"changeTo/(?:0|[1-9][0-9]{{0,9}})|"
    rf"hsv\((?:360(?:\.0+)?|(?:[0-9]|[1-9][0-9]|[12][0-9][0-9]|3[0-5][0-9])(?:\.[0-9]+)?),{_PERCENT_COMMAND},{_PERCENT_COMMAND}\)|"
    rf"(?:temp|lumitech)\({_PERCENT_COMMAND},(?:[1-9][0-9]{{3,4}})\)|"
    rf"manualPosition/{_PERCENT_COMMAND}|manualLamelle/{_PERCENT_COMMAND}|"
    rf"manualPosBlind/{_PERCENT_COMMAND}/{_PERCENT_COMMAND}|"
    rf"startOverride/[01]/[1-9][0-9]{{0,4}}|stopOverride|"
    rf"override/(?:0|[1-9][0-9]{{0,9}})/[1-9][0-9]{{0,9}}|"
    rf"setTimer/(?:0|[1-9][0-9]{{0,4}}/100/(?:0|[1-9][0-9]{{0,9}})/-1)|"
    rf"startVentilationTimer/(?:0|[1-9][0-9]{{0,9}})|"
    rf"startmodetimer/[0-3]/(?:0|[1-9][0-9]{{0,9}})/0|"
    rf"(?:0|[1-9][0-9]{{0,2}})|{_PERCENT_COMMAND})\Z"
)
_GEN1_IPV4_NETWORKS: Final = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_GEN1_IPV6_NETWORK: Final = ipaddress.ip_network("fc00::/7")


class LoxoneConnectionError(RuntimeError):
    """Sanitized error raised when the Miniserver cannot be used securely."""


class LoxoneCommandRejected(LoxoneConnectionError):
    """Raised when an authenticated Miniserver rejects a control command."""


class _WebSocketIdleTimeout(TimeoutError):
    """No WebSocket header arrived within the configured idle interval."""


def _loxone_uuid(value: UUID) -> str:
    """Serialize a standard UUID using Loxone's 8-4-4-16 representation."""
    first, second, third, fourth, fifth = str(value).split("-")
    return f"{first}-{second}-{third}-{fourth}{fifth}"


@dataclass(frozen=True, slots=True)
class MiniserverEndpoint:
    """A canonical generation-aware Miniserver origin without credentials."""

    origin: str
    host: str
    port: int
    secure: bool = False

    @classmethod
    def parse(cls, value: str) -> MiniserverEndpoint:
        parsed = urlsplit(value)
        if parsed.scheme == "http":
            return cls.parse_gen1(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "%" in parsed.netloc
            or "\\" in parsed.netloc
        ):
            raise ValueError("Gen. 2 endpoint must be an HTTPS origin without credentials")
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            canonical_host = f"[{address}]" if address.version == 6 else str(address)
            host = str(address)
        except ValueError:
            if (
                len(host) > 253
                or host.endswith(".")
                or any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or re.fullmatch(r"[a-z0-9-]+", label) is None
                    for label in host.split(".")
                )
            ):
                raise ValueError("Gen. 2 endpoint contains an invalid hostname") from None
            canonical_host = host
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ValueError("Gen. 2 endpoint contains an invalid port") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Gen. 2 endpoint contains an invalid port")
        origin = f"https://{canonical_host}" if port == 443 else f"https://{canonical_host}:{port}"
        if value.rstrip("/") != origin:
            raise ValueError("Gen. 2 endpoint must use a canonical HTTPS origin")
        return cls(origin=origin, host=host, port=port, secure=True)

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
        return cls(origin=origin, host=str(address), port=port, secure=False)

    @property
    def websocket_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default_port = 443 if self.secure else 80
        authority = host if self.port == default_port else f"{host}:{self.port}"
        scheme = "wss" if self.secure else "ws"
        return f"{scheme}://{authority}/ws/rfc6455"


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
        raise LoxoneCommandRejected("Miniserver rejected the request")
    return wrapper.get("value")


async def _receive_websocket(
    websocket: ClientConnection,
    *,
    timeout_seconds: float,
    max_payload_bytes: int,
) -> tuple[MessageHeader, str | bytes | None]:
    while True:
        try:
            raw_header = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        except TimeoutError:
            raise _WebSocketIdleTimeout from None
        if not isinstance(raw_header, bytes):
            raise LoxoneProtocolError("Expected a binary WebSocket header")
        header = parse_header(raw_header, max_payload_bytes=max_payload_bytes)
        if header.estimated:
            continue
        if header.message_type in {MessageType.OUT_OF_SERVICE, MessageType.KEEPALIVE}:
            return header, None
        payload = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        if isinstance(payload, str):
            actual_sizes = {len(payload), len(payload.encode("utf-8"))}
            if max(actual_sizes) > max_payload_bytes:
                raise LoxoneProtocolError("WebSocket text payload exceeds the configured limit")
            if header.payload_length not in actual_sizes:
                raise LoxoneProtocolError("WebSocket payload length does not match its header")
            return header, payload
        if len(payload) != header.payload_length:
            raise LoxoneProtocolError("WebSocket payload length does not match its header")
        return header, payload


async def _close_websocket(websocket: ClientConnection, timeout_seconds: float) -> None:
    """Close without allowing an unresponsive peer to block cleanup indefinitely."""
    try:
        await asyncio.wait_for(websocket.close(), timeout=timeout_seconds)
    except (OSError, TimeoutError) as exc:  # pragma: no cover - transport dependent
        _LOGGER.debug("WebSocket close failed: %s", type(exc).__name__)


async def _websocket_command(
    websocket: ClientConnection,
    encryptor: CommandEncryptor,
    command: str,
    *,
    encrypted: bool,
    timeout_seconds: float,
    max_payload_bytes: int,
) -> Any:
    outgoing = encryptor.encrypted_command(command) if encrypted else command
    await websocket.send(outgoing)
    header, payload = await _receive_websocket(
        websocket,
        timeout_seconds=timeout_seconds,
        max_payload_bytes=max_payload_bytes,
    )
    if header.message_type is not MessageType.TEXT or not isinstance(payload, str):
        raise LoxoneProtocolError("Miniserver command response is not text")
    try:
        response = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise LoxoneProtocolError("Miniserver command response is not JSON") from exc
    if not isinstance(response, Mapping):
        raise LoxoneProtocolError("Miniserver command response is invalid")
    return _response_value(response)


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
        max_structure_controls: int = 20_000,
        max_structure_state_references: int = 100_000,
        max_structure_depth: int = 32,
    ) -> None:
        self.endpoint = endpoint
        self.client_uuid = client_uuid
        self.client_name = client_name
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_structure_controls = max_structure_controls
        self.max_structure_state_references = max_structure_state_references
        self.max_structure_depth = max_structure_depth

    async def _get_json(self, path: str) -> Mapping[str, Any]:
        body, _encoding = await self._get_bytes(path)
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LoxoneConnectionError("Miniserver request failed") from None
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver returned an invalid response")
        return value

    async def _get_text(self, path: str) -> str:
        body, encoding = await self._get_bytes(path)
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            raise LoxoneConnectionError("Miniserver request failed") from None

    async def _get_bytes(self, path: str) -> tuple[bytes, str]:
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.endpoint.origin,
                    follow_redirects=False,
                    timeout=self.timeout_seconds,
                    trust_env=False,
                ) as client,
                client.stream("GET", path) as response,
            ):
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self.max_response_bytes:
                        raise LoxoneConnectionError(
                            "Miniserver response exceeds the configured limit"
                        )
                    body.extend(chunk)
                return bytes(body), response.encoding or "utf-8"
        except httpx.HTTPError:
            # httpx exceptions may contain the complete encrypted request URL.
            # Suppress the cause so callers and logs only see this fixed text.
            raise LoxoneConnectionError("Miniserver request failed") from None

    async def probe(self) -> ProbeResult:
        value = _response_value(await self._get_json("/jdev/cfg/apiKey"))
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                # Gen. 1 returns this fixed, flat object with JavaScript-style
                # single-quoted keys and strings instead of valid JSON.
                if not value.startswith("{'") or '"' in value:
                    raise LoxoneConnectionError(
                        "Miniserver probe returned an invalid value"
                    ) from None
                try:
                    value = json.loads(value.replace("'", '"'))
                except json.JSONDecodeError:
                    raise LoxoneConnectionError(
                        "Miniserver probe returned an invalid value"
                    ) from None
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver probe returned an invalid value")
        https_status = value.get("httpsStatus")
        if not self.endpoint.secure and https_status not in {None, 0, "0"}:
            raise LoxoneConnectionError("TLS-capable Miniservers require the Gen. 2 HTTPS adapter")
        if self.endpoint.secure and https_status in {None, 0, "0"}:
            raise LoxoneConnectionError("Gen. 2 endpoint did not confirm TLS support")
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

    async def websocket_public_key(self) -> str:
        value = await self._get_text("/jdev/sys/getcertificate")
        try:
            return normalize_loxone_certificate_chain_pem(value)
        except LoxoneSecurityError as exc:
            raise LoxoneConnectionError("Miniserver returned an invalid certificate chain") from exc

    async def _connect_websocket(self) -> ClientConnection:
        try:
            return await asyncio.wait_for(
                connect(
                    self.endpoint.websocket_url,
                    subprotocols=[Subprotocol("remotecontrol")],
                    max_size=self.max_response_bytes,
                    open_timeout=self.timeout_seconds,
                    close_timeout=self.timeout_seconds,
                    proxy=None,
                ),
                timeout=self.timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            raise LoxoneConnectionError("Miniserver WebSocket connection failed") from exc

    async def acquire_token(self, username: str, password: str) -> LoxoneToken:
        escaped_user = quote(username, safe="")
        websocket = await self._connect_websocket()
        encryptor = CommandEncryptor.generate()
        try:
            if not self.endpoint.secure:
                public_key = await self.websocket_public_key()
                session_key = encryptor.encrypted_session_key(public_key)
                await _websocket_command(
                    websocket,
                    encryptor,
                    f"jdev/sys/keyexchange/{session_key}",
                    encrypted=False,
                    timeout_seconds=self.timeout_seconds,
                    max_payload_bytes=self.max_response_bytes,
                )
            key_value = await _websocket_command(
                websocket,
                encryptor,
                f"jdev/sys/getkey2/{escaped_user}",
                encrypted=not self.endpoint.secure,
                timeout_seconds=self.timeout_seconds,
                max_payload_bytes=self.max_response_bytes,
            )
            if not isinstance(key_value, Mapping):
                raise LoxoneConnectionError("Miniserver returned invalid hashing parameters")
            key = key_value.get("key")
            salt = key_value.get("salt")
            algorithm = key_value.get("hashAlg")
            if (
                not isinstance(key, str)
                or not isinstance(salt, str)
                or not isinstance(algorithm, str)
            ):
                raise LoxoneConnectionError("Miniserver returned invalid hashing parameters")
            credential_hash = password_hmac(username, password, key, salt, algorithm)
            info = quote(self.client_name, safe="")
            command = (
                f"jdev/sys/getjwt/{credential_hash}/{escaped_user}/{_APP_PERMISSION}/"
                f"{_loxone_uuid(self.client_uuid)}/{info}"
            )
            token_value = await _websocket_command(
                websocket,
                encryptor,
                command,
                encrypted=not self.endpoint.secure,
                timeout_seconds=self.timeout_seconds,
                max_payload_bytes=self.max_response_bytes,
            )
        finally:
            await _close_websocket(websocket, self.timeout_seconds)
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
        session = await self.open_session(token)
        try:
            await session.kill_token()
        finally:
            await session.close()
            token.destroy()

    async def open_session(self, token: LoxoneToken) -> LoxoneWebSocketSession:
        if not token.value:
            raise LoxoneConnectionError("Loxone token is no longer available")
        public_key = ""
        if not self.endpoint.secure:
            public_key = await self.websocket_public_key()
        websocket = await self._connect_websocket()
        session = LoxoneWebSocketSession(
            websocket,
            public_key=public_key,
            token=token,
            timeout_seconds=self.timeout_seconds,
            max_payload_bytes=self.max_response_bytes,
            secure_transport=self.endpoint.secure,
            max_structure_controls=self.max_structure_controls,
            max_structure_state_references=self.max_structure_state_references,
            max_structure_depth=self.max_structure_depth,
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
        secure_transport: bool = False,
        max_structure_controls: int = 20_000,
        max_structure_state_references: int = 100_000,
        max_structure_depth: int = 32,
    ) -> None:
        self._websocket = websocket
        self._public_key = public_key
        self._token = token
        self._timeout = timeout_seconds
        self._max_payload = max_payload_bytes
        self._secure_transport = secure_transport
        self._max_structure_controls = max_structure_controls
        self._max_structure_state_references = max_structure_state_references
        self._max_structure_depth = max_structure_depth
        self._encryptor = CommandEncryptor.generate()

    async def _receive(self) -> tuple[MessageHeader, str | bytes | None]:
        return await _receive_websocket(
            self._websocket,
            timeout_seconds=self._timeout,
            max_payload_bytes=self._max_payload,
        )

    async def _command(self, command: str, *, encrypted: bool = False) -> Any:
        return await _websocket_command(
            self._websocket,
            self._encryptor,
            command,
            encrypted=encrypted,
            timeout_seconds=self._timeout,
            max_payload_bytes=self._max_payload,
        )

    async def authenticate(self) -> None:
        if not self._secure_transport:
            session_key = self._encryptor.encrypted_session_key(self._public_key)
            await self._command(f"jdev/sys/keyexchange/{session_key}")
        digest = await self._fresh_token_digest()
        await self._command(
            f"authwithtoken/{digest}/{quote(self._token.username, safe='')}",
            encrypted=not self._secure_transport,
        )

    async def _fresh_token_digest(self) -> str:
        key = await self._command("jdev/sys/getkey", encrypted=not self._secure_transport)
        if not isinstance(key, str):
            raise LoxoneConnectionError("Miniserver returned an invalid token hashing key")
        return token_hmac(self._token.value, key, self._token.hash_algorithm)

    async def load_structure(self) -> LoxoneStructure:
        await self._websocket.send("data/LoxAPP3.json")
        header, payload = await self._receive()
        if header.message_type not in {MessageType.TEXT, MessageType.BINARY_FILE} or not isinstance(
            payload, str
        ):
            raise LoxoneProtocolError("Miniserver structure response is not text")
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LoxoneProtocolError("Miniserver structure response is not JSON") from exc
        if not isinstance(document, Mapping):
            raise LoxoneProtocolError("Miniserver structure response is invalid")
        try:
            return normalize_structure(
                document,
                username=self._token.username,
                max_controls=self._max_structure_controls,
                max_state_references=self._max_structure_state_references,
                max_depth=self._max_structure_depth,
            )
        except LoxoneStructureError as exc:
            _LOGGER.error(
                "component=structure outcome=rejected reason=%s",
                str(exc).replace(" ", "_"),
            )
            raise LoxoneProtocolError("Miniserver structure response is invalid") from exc

    async def structure_version(self) -> str:
        """Return the current LoxAPP3 modification marker without downloading it."""
        value = await self._command("jdev/sps/LoxAPPversion3", encrypted=not self._secure_transport)
        if not isinstance(value, str) or not value or len(value) > 128:
            raise LoxoneProtocolError("Miniserver structure version response is invalid")
        return value

    async def refresh_token(self) -> None:
        """Rotate the in-memory JWT over the authenticated encrypted WebSocket."""
        digest = await self._fresh_token_digest()
        user = quote(self._token.username, safe="")
        value = await self._command(
            f"jdev/sys/refreshjwt/{digest}/{user}", encrypted=not self._secure_transport
        )
        if not isinstance(value, Mapping):
            raise LoxoneConnectionError("Miniserver returned an invalid refreshed token")
        refreshed = value.get("token")
        valid_until = value.get("validUntil")
        if not isinstance(refreshed, str) or not isinstance(valid_until, int):
            raise LoxoneConnectionError("Miniserver returned an invalid refreshed token")
        self._token.value = refreshed
        self._token.valid_until = valid_until

    async def kill_token(self) -> None:
        """Invalidate the current token over this authenticated session."""
        digest = await self._fresh_token_digest()
        user = quote(self._token.username, safe="")
        try:
            await self._command(
                f"jdev/sys/killtoken/{digest}/{user}", encrypted=not self._secure_transport
            )
        except ConnectionClosedOK:
            # A Miniserver may close the authenticated connection immediately
            # after invalidating the connection token. A normal close is the
            # successful terminal response in that case.
            return

    async def operate_control(self, action_uuid: str, command: str) -> None:
        """Execute one command prepared by the bounded control contract."""
        if (
            not action_uuid
            or len(action_uuid) > 128
            or not command
            or len(command) > 128
            or _CONTROL_COMMAND.fullmatch(command) is None
        ):
            raise ValueError("invalid control operation")
        await self._command(
            f"jdev/sps/io/{quote(action_uuid, safe='')}/{quote(command, safe='/')}",
            encrypted=not self._secure_transport,
        )

    async def control_history(self, action_uuid: str) -> list[Mapping[str, Any]]:
        """Read one documented control-history response."""
        if not action_uuid or len(action_uuid) > 128:
            raise ValueError("invalid control history target")
        command = f"jdev/sps/io/{quote(action_uuid, safe='')}/gethistory"
        outgoing = (
            self._encryptor.encrypted_command(command) if not self._secure_transport else command
        )
        await self._websocket.send(outgoing)
        header, payload = await self._receive()
        if header.message_type is not MessageType.TEXT or not isinstance(payload, str):
            raise LoxoneProtocolError("Miniserver control history response is invalid")
        try:
            response = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LoxoneProtocolError("Miniserver control history response is invalid") from exc
        value = _response_value(response) if isinstance(response, Mapping) else response
        if (
            not isinstance(value, list)
            or len(value) > 1000
            or any(not isinstance(item, Mapping) for item in value)
        ):
            raise LoxoneProtocolError("Miniserver control history is invalid")
        return value

    async def control_notes(self, action_uuid: str) -> str:
        """Read the bounded plaintext notes for one visible control."""
        if not action_uuid or len(action_uuid) > 128:
            raise ValueError("invalid control notes target")
        command = f"jdev/sps/io/{quote(action_uuid, safe='')}/controlnotes"
        outgoing = (
            self._encryptor.encrypted_command(command) if not self._secure_transport else command
        )
        await self._websocket.send(outgoing)
        header, payload = await self._receive()
        if header.message_type is not MessageType.TEXT or not isinstance(payload, str):
            raise LoxoneProtocolError("Miniserver control notes response is invalid")
        value: object = payload
        try:
            response = json.loads(payload)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(response, Mapping) and "LL" in response:
                value = _response_value(response)
            elif isinstance(response, str):
                value = response
        if not isinstance(value, str) or len(value) > 500:
            raise LoxoneProtocolError("Miniserver control notes are invalid")
        return value

    async def statistic_info(self, control_uuid: str) -> list[Mapping[str, Any]]:
        """Read the bounded availability metadata for one visible control."""
        if not control_uuid or len(control_uuid) > 128:
            raise ValueError("invalid statistic target")
        value = await self._command(
            f"jdev/sps/getStatisticInfo/{quote(control_uuid, safe='')}",
            encrypted=not self._secure_transport,
        )
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise LoxoneProtocolError("Miniserver statistic info is invalid") from exc
        if (
            not isinstance(value, list)
            or len(value) > 64
            or any(not isinstance(item, Mapping) for item in value)
        ):
            raise LoxoneProtocolError("Miniserver statistic info is invalid")
        return value

    async def statistic_data(
        self,
        control_uuid: str,
        *,
        mode: str,
        start: int,
        end: int,
        unit: str,
        group_id: str,
        output: str,
    ) -> bytes:
        """Read one single-output StatisticV2 binary response."""
        if (
            not control_uuid
            or len(control_uuid) > 128
            or mode not in {"raw", "diff"}
            or unit not in {"all", "hour", "day", "month", "year"}
            or not 0 <= start <= end <= 4_102_444_800
            or not group_id.isdecimal()
            or len(group_id) > 10
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", output)
        ):
            raise ValueError("invalid statistic request")
        command = (
            f"dev/sps/getStatistic/{quote(control_uuid, safe='')}/{mode}/{start}/{end}/"
            f"{unit}/{group_id}/{quote(output, safe='')}"
        )
        # Binary file responses cannot be transported through the Gen. 1
        # command-encryption envelope. The session is already token-authenticated,
        # matching the plaintext structure-file request on the same local socket.
        await self._websocket.send(command)
        header, payload = await self._receive()
        if header.message_type is MessageType.BINARY_FILE and isinstance(payload, bytes):
            return payload
        if header.message_type is MessageType.TEXT and isinstance(payload, str):
            try:
                response = json.loads(payload)
            except json.JSONDecodeError as exc:
                _LOGGER.warning(
                    "component=statistics outcome=invalid_response frame=text payload_bytes=%d",
                    len(payload.encode("utf-8")),
                )
                raise LoxoneProtocolError("Miniserver statistic response is invalid") from exc
            if isinstance(response, Mapping):
                try:
                    _response_value(response)
                except (LoxoneConnectionError, LoxoneCommandRejected):
                    _LOGGER.warning(
                        "component=statistics outcome=command_rejected frame=text payload_bytes=%d",
                        len(payload.encode("utf-8")),
                    )
                    raise
        payload_size = len(payload) if isinstance(payload, str | bytes) else 0
        _LOGGER.warning(
            "component=statistics outcome=invalid_response frame=%s payload_type=%s "
            "payload_bytes=%d",
            header.message_type.name.lower(),
            type(payload).__name__,
            payload_size,
        )
        raise LoxoneProtocolError("Miniserver statistic response is not binary")

    async def legacy_statistic_data(self, control_uuid: str, date: str) -> bytes:
        """Read one documented legacy statistic binary file on the authenticated socket."""
        if (
            not control_uuid
            or len(control_uuid) > 128
            or re.fullmatch(r"(?:20[0-9]{2})(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])?", date)
            is None
        ):
            raise ValueError("invalid legacy statistic request")
        command = f"binstatisticdata/{quote(control_uuid, safe='')}/{date}"
        await self._websocket.send(command)
        header, payload = await self._receive()
        if header.message_type is MessageType.BINARY_FILE and isinstance(payload, bytes):
            return payload
        if header.message_type is MessageType.TEXT and isinstance(payload, str):
            try:
                response = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise LoxoneProtocolError(
                    "Miniserver legacy statistic response is invalid"
                ) from exc
            if isinstance(response, Mapping):
                _response_value(response)
        raise LoxoneProtocolError("Miniserver legacy statistic response is not binary")

    async def state_events(self) -> AsyncIterator[tuple[StateEvent, ...]]:
        await self._command("jdev/sps/enablebinstatusupdate")
        keepalive_pending = False
        while True:
            try:
                header, payload = await self._receive()
            except _WebSocketIdleTimeout:
                if keepalive_pending:
                    raise LoxoneConnectionError("Miniserver did not respond to keepalive") from None
                await self._websocket.send("keepalive")
                keepalive_pending = True
                continue
            keepalive_pending = False
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
        await _close_websocket(self._websocket, self._timeout)
