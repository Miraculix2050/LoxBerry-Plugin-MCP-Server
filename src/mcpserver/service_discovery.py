"""Fixed local Admin projections from a separate, bounded discovery connection.

No OAuth family or recorder socket can enter this path. Visibility requests download
their own complete structure; a separate marker-checked projection reuses display
metadata only. Permission freshness on an uninterrupted connection
has the explicitly accepted, target-dependent residual risk documented in #239.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid5

from websockets.exceptions import ConnectionClosed

from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
from mcpserver.loxone.client import (
    LoxoneAuthenticationRejected,
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    LoxoneWebSocketSession,
    MiniserverEndpoint,
    _WebSocketIdleTimeout,
)
from mcpserver.loxone.events import MessageHeader, MessageType, parse_state_events
from mcpserver.loxone.models import LoxoneStructure
from mcpserver.loxone.presentation import flatten_controls
from mcpserver.loxone.service_access import LoxBerryServiceCredentials, ServiceMiniserverConnection

PATH = "/internal/admin-discovery"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_DISCOVERY_DEADLINES = {"event_history": 35, "emergency_stop": 90, "emergency_stop_display": 90}
_MARKER_COMMAND = "jdev/sps/LoxAPPversion3"
_MAX_INTERLEAVINGS = 32
_MAX_IGNORED_BYTES = 1024 * 1024
_DIAGNOSTIC: ContextVar[dict[str, Any] | None] = ContextVar(
    "admin_discovery_diagnostic", default=None
)


def _phase(value: str) -> None:
    diagnostic = _DIAGNOSTIC.get()
    if diagnostic is not None:
        diagnostic["phase"] = value


def _failure_category(exc: BaseException) -> str:
    from mcpserver.loxone.auth_diagnostics import (
        MiniserverAuthenticationCooldown,
        MiniserverAuthenticationSuppressed,
    )
    from mcpserver.loxone.events import LoxoneProtocolError
    from mcpserver.loxone.service_access import ServiceCredentialsUnavailable

    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, LoxoneSourceIpBlocked):
        return "source_ip_blocked"
    if isinstance(exc, MiniserverAuthenticationCooldown):
        return "authentication_cooldown"
    if isinstance(exc, MiniserverAuthenticationSuppressed):
        return "authentication_busy"
    if isinstance(exc, TimeoutError | _WebSocketIdleTimeout | DiscoveryTimeout):
        return "timeout"
    if isinstance(exc, ConnectionClosed | DiscoveryDisconnected):
        return "disconnect"
    if isinstance(exc, LoxoneProtocolError | DiscoveryProtocolFailure):
        return "protocol"
    if isinstance(exc, DiscoveryPermissionDenied):
        return "permission_denied"
    if isinstance(exc, ServiceCredentialsUnavailable):
        return "credentials_unavailable"
    if isinstance(exc, LoxoneAuthenticationRejected):
        return "authentication_rejected"
    if isinstance(exc, LoxoneConnectionError):
        return "disconnect" if isinstance(exc.__context__, ConnectionClosed) else "connection"
    if isinstance(exc, OSError):
        return "connection"
    if isinstance(exc, DiscoveryIdentityChanged):
        return "identity_changed"
    if isinstance(exc, DiscoveryStopped):
        return "service_stopped"
    if isinstance(exc, DiscoveryUnavailable):
        return "discovery_invalidated"
    return "unknown"


class DiscoveryUnavailable(RuntimeError):
    """Fixed failure without source data."""


class DiscoveryIdentityChanged(DiscoveryUnavailable):
    """Configured identity no longer matches this request."""


class DiscoveryStopped(DiscoveryUnavailable):
    """Service lifecycle no longer permits discovery."""


class DiscoveryTimeout(DiscoveryUnavailable):
    """Receiver deadline expired without a complete response."""


class DiscoveryDisconnected(DiscoveryUnavailable):
    """Receiver ended before completing the pending response."""


class DiscoveryProtocolFailure(DiscoveryUnavailable):
    """Fixed response attribution or frame bounds were violated."""


class DiscoveryPermissionDenied(DiscoveryUnavailable):
    """The marker request was explicitly denied."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def binding(store: AtomicJsonAuthStore, config: PluginConfig, username: str, password: str) -> str:
    return store.pseudonym(
        "admin-discovery-binding-v1", json.dumps(asdict(config), sort_keys=True), username, password
    )


def admin_key(store: AtomicJsonAuthStore) -> str:
    return store.pseudonym("admin-discovery-local-helper-v1")


def selector_projection(structure: LoxoneStructure) -> dict[str, Any]:
    rooms = {room.uuid: room.name for room in structure.rooms}
    categories = {item.uuid: item.name for item in structure.categories}
    controls: list[dict[str, Any]] = [
        {
            "uuid": control.uuid,
            "name": control.name,
            "type": control.control_type,
            "room_id": control.room_uuid,
            "room": rooms.get(control.room_uuid) if control.room_uuid else None,
            "category_id": control.category_uuid,
            "category": categories.get(control.category_uuid) if control.category_uuid else None,
            "states": [[name, uuid] for name, uuid in control.state_uuids],
        }
        for control in flatten_controls(structure.controls)
        if control.control_type != "Daytimer" and control.state_uuids
    ]
    controls.sort(key=lambda item: (item["name"].casefold(), item["uuid"]))
    return {"last_modified": structure.last_modified, "controls": controls}


def emergency_projection(structure: LoxoneStructure) -> dict[str, Any]:
    options = [
        {"uuid": item.uuid, "name": item.name}
        for item in structure.controls
        if item.control_type in {"VirtualStatus", "InfoOnlyDigital"} and len(item.state_uuids) == 1
    ]
    options.sort(key=lambda item: (item["name"].casefold(), item["uuid"]))
    return {"status": "available", "options": options, "project_marker": structure.last_modified}


class DiscoveryReceiver:
    """One receiver, no response queue, and one outstanding fixed marker or file.

    Only this dedicated socket may use it; state subscriptions and arbitrary
    commands are never sent. Binary gzip/unknown files are always terminal.
    """

    def __init__(
        self,
        session: LoxoneWebSocketSession,
        *,
        on_source_ip_blocked: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.session = session
        self.pending: asyncio.Future[tuple[MessageHeader, str | bytes | None]] | None = None
        self.operation = "structure"
        self.marker_controls: set[str] = set()
        self.task = asyncio.create_task(self._run())
        self.failure: BaseException | None = None
        self.interleavings = 0
        self.ignored_bytes = 0
        self.on_source_ip_blocked = on_source_ip_blocked
        self.observation: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        keepalive_pending = False
        try:
            while True:
                try:
                    # Includes estimated headers which otherwise loop internally.
                    async with asyncio.timeout(self.session._timeout):
                        header, payload = await self.session._receive()
                except (_WebSocketIdleTimeout, TimeoutError):
                    if self.pending is not None or keepalive_pending:
                        raise DiscoveryTimeout("discovery response timed out") from None
                    await self.session._websocket.send("keepalive")
                    keepalive_pending = True
                    continue
                if header.message_type == MessageType.KEEPALIVE:
                    keepalive_pending = False
                elif header.message_type in {
                    MessageType.VALUE_STATES,
                    MessageType.TEXT_STATES,
                    MessageType.DAYTIMER_STATES,
                    MessageType.WEATHER_STATES,
                }:
                    if not isinstance(payload, bytes):
                        raise DiscoveryProtocolFailure("invalid asynchronous frame")
                    if self.ignored_bytes + len(payload) > _MAX_IGNORED_BYTES:
                        raise DiscoveryProtocolFailure("asynchronous frame limit exceeded")
                    parse_state_events(header.message_type, payload)
                elif header.message_type in {MessageType.TEXT, MessageType.BINARY_FILE}:
                    if self.pending is None or self.pending.done() or not isinstance(payload, str):
                        raise DiscoveryProtocolFailure("unattributed file or response")
                    try:
                        document = json.loads(payload)
                    except (ValueError, TypeError):
                        raise DiscoveryProtocolFailure("invalid structure response") from None
                    if not isinstance(document, dict):
                        raise DiscoveryProtocolFailure("unexpected text response")
                    if self.operation == "marker":
                        reply = document.get("LL")
                        if (
                            header.message_type != MessageType.TEXT
                            or not isinstance(reply, dict)
                            or not isinstance(reply.get("control"), str)
                            or reply["control"] not in self.marker_controls
                        ):
                            raise DiscoveryProtocolFailure("unattributed marker response")
                    elif not isinstance(document.get("controls"), dict):
                        raise DiscoveryProtocolFailure("unexpected text response")
                    self.pending.set_result((header, payload))
                    continue
                else:
                    raise DiscoveryDisconnected("discovery disconnected")
                self.interleavings += 1
                self.ignored_bytes += len(payload) if payload is not None else 0
                if (
                    self.interleavings > _MAX_INTERLEAVINGS
                    or self.ignored_bytes > _MAX_IGNORED_BYTES
                ):
                    raise DiscoveryProtocolFailure("asynchronous frame limit exceeded")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, ConnectionClosed) and exc.rcvd is not None and exc.rcvd.code == 4003:
                exc = LoxoneSourceIpBlocked("Miniserver source IP is blocked")
            self.failure = exc
            if isinstance(exc, LoxoneSourceIpBlocked) and self.on_source_ip_blocked is not None:
                callback = self.on_source_ip_blocked

                async def observe() -> None:
                    await callback()

                self.observation = asyncio.create_task(observe())
                await asyncio.shield(self.observation)
            if self.pending is not None and not self.pending.done():
                self.pending.set_exception(exc)

    async def _request(self, operation: str) -> tuple[MessageHeader, str | bytes | None]:
        """Receive only the fixed marker command; never call the socket reader twice."""
        if self.failure is not None:
            raise self.failure
        if self.pending is not None:
            raise DiscoveryProtocolFailure("concurrent discovery request")
        self.operation = operation
        self.interleavings = self.ignored_bytes = 0
        pending: asyncio.Future[tuple[MessageHeader, str | bytes | None]] = (
            asyncio.get_running_loop().create_future()
        )
        self.pending = pending
        try:
            outgoing = (
                _MARKER_COMMAND
                if self.session._secure_transport
                else self.session._encryptor.encrypted_command(_MARKER_COMMAND)
            )
            # Gen. 1 echoes the encrypted command with URI escapes decoded.
            # Match this exact request, never an arbitrary encryption prefix.
            self.marker_controls = {_MARKER_COMMAND, outgoing, unquote(outgoing)}
            await self.session._websocket.send(outgoing)
            return await pending
        finally:
            if not pending.done():
                pending.cancel()
            else:
                with suppress(asyncio.CancelledError):
                    pending.exception()
            self.pending = None
            self.marker_controls.clear()

    async def marker(self) -> str | None:
        _, payload = await self._request("marker")
        assert isinstance(payload, str)
        reply = json.loads(payload)["LL"]
        code = str(reply.get("Code", reply.get("code", "")))
        if code == "4003":
            if self.on_source_ip_blocked is not None:
                callback = self.on_source_ip_blocked

                async def observe() -> None:
                    await callback()

                self.observation = asyncio.create_task(observe())
                await asyncio.shield(self.observation)
            raise LoxoneSourceIpBlocked("Miniserver source IP is blocked")
        if code in {"401", "403"}:
            raise DiscoveryPermissionDenied("marker permission denied")
        if code not in {"200", "404"}:
            raise DiscoveryProtocolFailure("marker command rejected")
        value = reply.get("value")
        return value if code == "200" and isinstance(value, str) and 0 < len(value) <= 128 else None

    async def load(self) -> LoxoneStructure:
        if self.failure is not None:
            raise self.failure
        if self.pending is not None:
            raise DiscoveryProtocolFailure("concurrent file request")
        self.interleavings = self.ignored_bytes = 0
        self.operation = "structure"
        self.pending = asyncio.get_running_loop().create_future()
        pending = self.pending

        async def receive() -> tuple[MessageHeader, str | bytes | None]:
            return await pending

        try:
            return await self.session.load_structure(receive=receive)
        finally:
            if not pending.done():
                pending.cancel()
            else:
                # Retrieve an exception even when send failed before receive.
                with suppress(asyncio.CancelledError):
                    pending.exception()
            self.pending = None

    async def close(self) -> None:
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
        if self.observation is not None:
            await asyncio.shield(self.observation)


class AdminDiscovery:
    """Lazy service owner; no stale response or failed-read reconnect."""

    def __init__(
        self,
        store: AtomicJsonAuthStore,
        config_loader: Callable[[], PluginConfig],
        coordinator_factory: Callable[[PluginConfig], MiniserverAuthCoordinator],
    ) -> None:
        self.store = store
        self.config_loader = config_loader
        self.coordinator_factory = coordinator_factory
        self.lock = asyncio.Lock()
        self.connection: ServiceMiniserverConnection | None = None
        self.receiver: DiscoveryReceiver | None = None
        self.profile = ""
        self.created = 0.0
        self.last_used = 0.0
        self.closed = False
        self.idle_task: asyncio.Task[None] | None = None
        self.disposal: asyncio.Task[None] | None = None
        self.coordinator: MiniserverAuthCoordinator | None = None
        self.coordinator_key: tuple[str, int, int] | None = None
        self.pending_requests = 0

    def retry_not_before(self) -> int | None:
        value = (
            self.coordinator.current_status().get("next_auth_attempt_at")
            if self.coordinator
            else None
        )
        return value if type(value) is int else None

    async def _drop(self) -> None:
        if self.disposal is None:
            receiver, connection = self.receiver, self.connection
            self.receiver = self.connection = None
            self.profile = ""

            async def dispose() -> None:
                try:
                    if receiver is not None:
                        await receiver.close()
                finally:
                    if connection is not None:
                        await connection.close()

            self.disposal = asyncio.create_task(dispose())
        task = self.disposal
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Keep an owned cleanup task even if cancellation is repeated.
            with suppress(asyncio.CancelledError):
                await asyncio.shield(task)
            raise
        finally:
            if task.done():
                self.disposal = None

    async def _identity(self) -> tuple[PluginConfig, str, str, str]:
        config = await asyncio.to_thread(self.config_loader)
        username, password = await LoxBerryServiceCredentials(config).load()
        return config, username, password, binding(self.store, config, username, password)

    async def project(
        self,
        kind: str,
        expected: str,
        *,
        manual_retry: bool = False,
        early_probe: bool = False,
        request_id: str = "-",
    ) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "phase": "discovery_wait",
            "timing": {},
            "started": time.monotonic(),
        }
        token = _DIAGNOSTIC.set(diagnostic)
        started = time.monotonic()
        self.pending_requests += 1
        try:
            return await self._project(
                kind, expected, manual_retry=manual_retry, early_probe=early_probe
            )
        except BaseException as exc:
            timing = diagnostic["timing"]
            logging.getLogger("mcpserver.service").warning(
                "component=admin_discovery request_id=%s projection=%s outcome=failed "
                "phase=%s code=%s duration_ms=%.1f pending_requests=%d "
                "session_mode=%s session_age_ms=%.1f discovery_wait_ms=%.1f "
                "coordinator_wait_ms=%.1f token_acquisition_ms=%.1f session_establishment_ms=%.1f",
                request_id if re.fullmatch(r"[0-9a-f]{1,16}-[0-9a-f]{1,16}", request_id) else "-",
                kind if kind in _DISCOVERY_DEADLINES else "unknown",
                diagnostic["phase"],
                _failure_category(exc),
                (time.monotonic() - started) * 1000,
                self.pending_requests,
                diagnostic.get("session_mode", "none"),
                diagnostic.get("session_age_ms", 0.0),
                diagnostic.get("discovery_wait_ms", (time.monotonic() - started) * 1000),
                timing.get("selector_coordinator_wait_ms", 0.0),
                timing.get("selector_token_acquisition_ms", 0.0),
                timing.get("selector_session_establishment_ms", 0.0),
            )
            raise
        finally:
            self.pending_requests -= 1
            _DIAGNOSTIC.reset(token)

    async def _project(
        self,
        kind: str,
        expected: str,
        *,
        manual_retry: bool = False,
        early_probe: bool = False,
    ) -> dict[str, Any]:
        if kind not in _DISCOVERY_DEADLINES:
            raise DiscoveryUnavailable("invalid projection")
        async with asyncio.timeout(_DISCOVERY_DEADLINES[kind]), self.lock:
            try:
                diagnostic = _DIAGNOSTIC.get()
                assert diagnostic is not None
                diagnostic["discovery_wait_ms"] = (time.monotonic() - diagnostic["started"]) * 1000
                diagnostic["session_mode"] = "held" if self.connection is not None else "none"
                diagnostic["session_age_ms"] = (
                    max(0.0, (time.monotonic() - self.created) * 1000)
                    if self.connection is not None
                    else 0.0
                )
                _phase("identity_check")
                if self.closed:
                    raise DiscoveryStopped("service stopped")
                config, username, password, profile = await self._identity()
                if not config.enabled or not config.loxone_endpoint:
                    raise DiscoveryStopped("service disabled or unconfigured")
                if not hmac.compare_digest(profile, expected):
                    raise DiscoveryIdentityChanged("configuration changed")
                key = (
                    config.loxone_endpoint,
                    config.miniserver_auth_probe_initial_seconds,
                    config.miniserver_auth_probe_max_seconds,
                )
                if self.coordinator is None or self.coordinator_key != key:
                    self.coordinator = self.coordinator_factory(config)
                    self.coordinator_key = key
                coordinator = self.coordinator
                if (
                    self.receiver is not None
                    and coordinator.current_status()["breaker_state"] != "closed"
                ):
                    raise LoxoneSourceIpBlocked("Miniserver source IP is blocked")
                now = time.monotonic()
                if (
                    self.profile != profile
                    or now - self.created >= 300
                    or now - self.last_used >= 60
                ):
                    _phase("session_close")
                    await self._drop()
                _phase("receiver_state")
                if self.receiver is not None and self.receiver.failure is not None:
                    _phase("receiver_state")
                    # Fail this request, rather than silently re-authenticating.
                    raise self.receiver.failure
                timing: dict[str, float | int] = {
                    "selector_coordinator_wait_ms": 0.0,
                    "selector_token_acquisition_ms": 0.0,
                    "selector_session_establishment_ms": 0.0,
                    "selector_auth_count": 0,
                }
                diagnostic["timing"] = timing
                diagnostic["session_mode"] = "held" if self.connection is not None else "new"
                diagnostic["session_age_ms"] = (
                    max(0.0, (now - self.created) * 1000) if self.connection is not None else 0.0
                )
                if self.connection is None:
                    client = LoxoneClient(
                        MiniserverEndpoint.parse(config.loxone_endpoint),
                        client_uuid=uuid5(
                            NAMESPACE_URL,
                            "https://loxberry.local/plugins/mcpserver/admin-discovery",
                        ),
                        timeout_seconds=config.connection_timeout,
                    )
                    self.connection = ServiceMiniserverConnection(
                        client,
                        coordinator,
                        owner="local_admin",
                        busy_wait_seconds=15,
                        manual_retry=manual_retry,
                        early_probe=early_probe,
                        timing=timing,
                        diagnostic_phase=_phase,
                    )
                    session = await self.connection.connect(username, password)
                    self.receiver = DiscoveryReceiver(
                        session, on_source_ip_blocked=coordinator.observe_source_ip_blocked
                    )
                    self.profile = profile
                    self.created = now
                    timing["selector_auth_count"] = 1
                    if self.idle_task is None:
                        self.idle_task = asyncio.create_task(self._expire())
                from mcpserver.emergency_options_cache import EmergencyOptionsCache

                display_cache = EmergencyOptionsCache(
                    self.store.path,
                    self.store.pseudonym(
                        "emergency-stop-options-v1", config.loxone_endpoint, username, password
                    ),
                )
                del username, password
                assert self.receiver is not None
                tick = time.perf_counter_ns()
                cached = None
                marker = None
                if kind == "emergency_stop_display":
                    _phase("marker_check")
                    marker = await self.receiver.marker()
                    cached = await asyncio.to_thread(display_cache.read)
                    if not (
                        marker
                        and cached
                        and cached["has_options"]
                        and cached["result"]["status"] == "available"
                        and cached.get("project_marker") == marker
                    ):
                        cached = None
                timing["selector_marker_check_ms"] = (
                    (time.perf_counter_ns() - tick) / 1_000_000
                    if kind == "emergency_stop_display"
                    else 0.0
                )
                tick = time.perf_counter_ns()
                _phase("structure_load")
                structure = None if cached is not None else await self.receiver.load()
                timing["selector_structure_load_ms"] = (
                    (time.perf_counter_ns() - tick) / 1_000_000 if structure is not None else 0.0
                )
                timing["selector_structure_load_count"] = 0 if structure is None else 1
                _phase("identity_recheck")
                _, username, password, current = await self._identity()
                del username, password
                if self.receiver.failure is not None:
                    raise self.receiver.failure
                if coordinator.current_status()["breaker_state"] != "closed":
                    raise LoxoneSourceIpBlocked("Miniserver source IP is blocked")
                if self.closed:
                    raise DiscoveryStopped("service stopped during discovery")
                if not hmac.compare_digest(current, profile):
                    raise DiscoveryIdentityChanged("identity changed during discovery")
                if cached is not None:
                    # Display metadata only; a marker is not an authorization proof.
                    result = {
                        "status": "available",
                        "options": cached["options"],
                        "cached": True,
                        "project_marker": marker,
                    }
                else:
                    assert structure is not None
                    result = (
                        selector_projection(structure)
                        if kind == "event_history"
                        else emergency_projection(structure)
                    )
                self.last_used = time.monotonic()
                return {"projection": result, "timing": timing}
            except BaseException:
                await self._drop()
                raise

    async def _expire(self) -> None:
        while True:
            await asyncio.sleep(5)
            async with self.lock:
                if self.receiver is not None and (
                    self.receiver.failure is not None
                    or time.monotonic() - self.last_used >= 60
                    or time.monotonic() - self.created >= 300
                ):
                    await self._drop()

    async def close(self) -> None:
        self.closed = True
        if self.idle_task is not None:
            self.idle_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.idle_task
        async with self.lock:
            await self._drop()


def request_projection(
    config: PluginConfig,
    store: AtomicJsonAuthStore,
    kind: str,
    *,
    timing: dict[str, float | int] | None = None,
    manual_retry: bool = False,
    early_probe: bool = False,
) -> dict[str, Any]:
    """Authenticated local helper; unavailable service never falls back to login."""
    from mcpserver.admin import AdminError

    try:
        return _request_projection(
            config, store, kind, timing=timing, manual_retry=manual_retry, early_probe=early_probe
        )
    except AdminError:
        raise
    except Exception:
        raise AdminError("Admin discovery unavailable", code="temporarily_unavailable") from None


def _request_projection(
    config: PluginConfig,
    store: AtomicJsonAuthStore,
    kind: str,
    *,
    timing: dict[str, float | int] | None = None,
    manual_retry: bool = False,
    early_probe: bool = False,
) -> dict[str, Any]:
    username, password = asyncio.run(LoxBerryServiceCredentials(config).load())
    expected = binding(store, config, username, password)
    del username, password
    request = Request(
        "http://127.0.0.1:8765" + PATH,
        data=json.dumps(
            {
                "projection": kind,
                "binding": expected,
                "manual_retry": manual_retry,
                "early_probe": early_probe,
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "X-LoxBerry-Admin-Discovery": admin_key(store),
            "X-LoxBerry-Admin-Request": (
                os.getenv("MCPSERVER_ADMIN_REQUEST_ID", "-")
                if re.fullmatch(
                    r"[0-9a-f]{1,16}-[0-9a-f]{1,16}", os.getenv("MCPSERVER_ADMIN_REQUEST_ID", "-")
                )
                else "-"
            ),
        },
        method="POST",
    )
    # Local-helper credentials must never follow redirects or environment proxies.
    with build_opener(ProxyHandler({}), _NoRedirect()).open(
        request, timeout=_DISCOVERY_DEADLINES[kind] + 1
    ) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DiscoveryUnavailable("projection too large")
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("ok") is not True:
        from mcpserver.admin import AdminError

        code = (
            document.get("error", "temporarily_unavailable")
            if isinstance(document, dict)
            else "temporarily_unavailable"
        )
        if code not in {"authentication_busy", "authentication_cooldown", "source_ip_blocked"}:
            code = "temporarily_unavailable"
        if kind in {"emergency_stop", "emergency_stop_display"}:
            reason = {
                "authentication_busy": "authentication_busy",
                "authentication_cooldown": "authentication_cooldown",
                "source_ip_blocked": "authentication_suppressed",
            }.get(code, "connection_failed")
            result: dict[str, Any] = {
                "status": "unavailable",
                "options": [],
                "discovery_failure_code": reason,
            }
            retry = document.get("retry_not_before")
            if type(retry) is int and retry > 0:
                result["retry_not_before"] = retry
            return result
        raise AdminError("Admin discovery unavailable", code=code)
    if timing is not None:
        timing.update(document["timing"])
    return dict(document["projection"])


def configured_loader() -> PluginConfig:
    return AtomicConfigStore(Path(os.environ["MCPSERVER_CONFIG"])).load()
