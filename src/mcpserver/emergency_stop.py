"""Fail-closed service monitor for a configured digital Virtual Status."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from mcpserver.config import PluginConfig
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
)
from mcpserver.loxone.service_access import (
    LoxBerryServiceCredentials,
    ServiceCredentialsUnavailable,
    ServiceMiniserverConnection,
)

_LOGGER = logging.getLogger("mcpserver.emergency_stop")
_ADMIN_AUTH_BUSY_WAIT_SECONDS = 15


def _sorted_virtual_status_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    """Order display labels deterministically while retaining the UUID tie-breaker."""
    return sorted(options, key=lambda option: (option["name"].casefold(), option["uuid"]))


def mqtt_emergency_stop_status(*, signal_uuid: str | None, monitor_status: str) -> str:
    """Translate the monitor state to the stable MQTT status vocabulary."""
    if not signal_uuid:
        return "not_configured"
    return {
        "enabled": "clear",
        "disabled": "active",
        "unknown": "unknown",
    }.get(monitor_status, "unknown")


@dataclass(frozen=True, slots=True)
class VirtualStatusOptions:
    """Bounded, UI-safe result of an on-demand Virtual Status discovery."""

    status: str
    options: tuple[dict[str, str], ...]
    failure_code: str | None = None
    retry_not_before: int | None = None


@dataclass(slots=True)
class EmergencyStopMonitor:
    """Tracks the one trusted status value; no selection means enabled."""

    config: PluginConfig
    status: str = "enabled"
    status_changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    signal_name: str | None = None
    auth_coordinator: MiniserverAuthCoordinator | None = None
    _task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        if self.config.emergency_stop_virtual_status_uuid:
            self.status = "unknown"

    def _set_status(self, status: str) -> None:
        if self.status != status:
            self.status = status
            self.status_changed_at = datetime.now(UTC)

    @property
    def allows_tool_calls(self) -> bool:
        return self.status == "enabled"

    def apply(self, value: object) -> None:
        if isinstance(value, bool):
            self._set_status("enabled" if value else "disabled")
        elif isinstance(value, int | float) and value in {0, 1}:
            self._set_status("enabled" if value == 1 else "disabled")
        else:
            self._set_status("unknown")

    def unavailable(self) -> None:
        if self.config.emergency_stop_virtual_status_uuid:
            self._set_status("unknown")

    def blocked_status(self) -> dict[str, str]:
        """Return sanitized current blocker metadata for a rejected MCP request."""
        return {
            "status": self.status,
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "blocked_since": self.status_changed_at.isoformat().replace("+00:00", "Z"),
        }

    def runtime_status(self) -> dict[str, str | None]:
        """Return the service's own selected signal and MQTT-compatible state."""
        return {
            "signal_uuid": self.config.emergency_stop_virtual_status_uuid or None,
            "signal_name": self.signal_name,
            "status": mqtt_emergency_stop_status(
                signal_uuid=self.config.emergency_stop_virtual_status_uuid,
                monitor_status=self.status,
            ),
        }

    async def start(self) -> None:
        """Start a dedicated LoxBerry-managed read-only state subscription."""
        if self.config.emergency_stop_virtual_status_uuid:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        while True:
            connection = None
            session = None
            stage = "credentials"
            try:
                username, password = await LoxBerryServiceCredentials(self.config).load()
                client = LoxoneClient(
                    MiniserverEndpoint.parse(self.config.loxone_endpoint),
                    client_uuid=uuid5(
                        NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/emergency-stop"
                    ),
                    timeout_seconds=self.config.connection_timeout,
                )
                stage = "token"
                connection = ServiceMiniserverConnection(
                    client, self.auth_coordinator, owner="runtime_event_stream", manual_retry=True
                )
                session = await connection.connect(username, password)
                stage = "session"
                assert session is not None
                stage = "structure"
                structure = await session.load_structure()
                stage = "selection"
                control = next(
                    (
                        item
                        for item in structure.controls
                        if item.uuid == self.config.emergency_stop_virtual_status_uuid
                        and item.control_type in {"VirtualStatus", "InfoOnlyDigital"}
                    ),
                    None,
                )
                if control is None or len(control.state_uuids) != 1:
                    raise RuntimeError("selected status unavailable")
                self.signal_name = control.name
                state_uuid = control.state_uuids[0][1]
                stage = "subscription"
                async for batch in session.state_events():
                    stage = "events"
                    for event in batch:
                        if event.uuid == state_uuid:
                            self.apply(event.value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.unavailable()
                failure_code = (
                    f"{stage}_{exc.reason}"
                    if isinstance(exc, ServiceCredentialsUnavailable)
                    else stage
                )
                _LOGGER.warning(
                    "component=emergency_stop outcome=monitor_unavailable code=%s error_type=%s",
                    failure_code,
                    type(exc).__name__,
                )
                await asyncio.sleep(5)
            finally:
                if connection is not None:
                    await connection.close()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task


async def virtual_status_options(
    config: PluginConfig,
    auth_coordinator: MiniserverAuthCoordinator | None = None,
    *,
    manual_retry: bool = False,
) -> VirtualStatusOptions:
    """Return selectable visible digital statuses without retaining credentials."""
    if not config.loxone_endpoint:
        return VirtualStatusOptions(status="not_configured", options=())
    credentials = LoxBerryServiceCredentials(config)
    connection = None
    session = None
    stage = "credentials"
    try:
        username, password = await credentials.load()
        from mcpserver.loxone.client import MiniserverEndpoint

        stage = "endpoint"
        client = LoxoneClient(
            MiniserverEndpoint.parse(config.loxone_endpoint),
            client_uuid=uuid5(
                NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/emergency-stop"
            ),
            timeout_seconds=config.connection_timeout,
        )
        stage = "token"
        connection = ServiceMiniserverConnection(
            client,
            auth_coordinator,
            owner="local_admin",
            busy_wait_seconds=_ADMIN_AUTH_BUSY_WAIT_SECONDS,
            manual_retry=manual_retry,
        )
        session = await connection.connect(username, password)
        stage = "structure"
        structure = await session.load_structure()
        return VirtualStatusOptions(
            status="available",
            options=tuple(
                _sorted_virtual_status_options(
                    [
                        {"uuid": item.uuid, "name": item.name}
                        for item in structure.controls
                        if item.control_type in {"VirtualStatus", "InfoOnlyDigital"}
                        and len(item.state_uuids) == 1
                    ]
                )
            ),
        )
    except Exception as exc:
        if connection is not None and stage == "token":
            stage = connection.stage
        breaker = auth_coordinator.current_status() if auth_coordinator is not None else None
        if isinstance(exc, MiniserverAuthenticationSuppressed):
            reason = (
                "authentication_suppressed"
                if breaker is not None and breaker.get("breaker_state") != "closed"
                else "authentication_busy"
            )
        elif stage == "credentials" or isinstance(exc, ServiceCredentialsUnavailable):
            reason = "credentials_unavailable"
        elif stage == "structure":
            reason = "structure_failed"
        elif isinstance(exc, LoxoneConnectionError | TimeoutError | OSError):
            reason = "connection_failed"
        else:
            reason = "structure_failed" if stage == "structure" else "connection_failed"
        retry_at = (
            breaker.get("retry_not_before")
            if breaker is not None and breaker.get("breaker_state") != "closed"
            else int(time.time()) + 5
            if reason == "authentication_busy"
            else None
        )
        return VirtualStatusOptions(
            status="unavailable",
            options=(),
            failure_code=reason,
            retry_not_before=retry_at if isinstance(retry_at, int) else None,
        )
    finally:
        if connection is not None:
            await connection.close()
