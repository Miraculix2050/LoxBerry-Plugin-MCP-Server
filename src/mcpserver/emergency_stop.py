"""Fail-closed service monitor for a configured digital Virtual Status."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from mcpserver.config import PluginConfig
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneToken,
    LoxoneWebSocketSession,
)

_LOGGER = logging.getLogger("mcpserver.emergency_stop")


async def _acquire_token(client: LoxoneClient, username: str, password: str) -> LoxoneToken:
    return await client.acquire_token(username, password)


async def _open_session(client: LoxoneClient, token: LoxoneToken) -> LoxoneWebSocketSession:
    return await client.open_session(token)


class _ProviderUnavailable(RuntimeError):
    """Identify one fixed provider failure without exposing provider output."""

    def __init__(self, reason: str) -> None:
        super().__init__("provider unavailable")
        self.reason = reason


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

    async def _credentials(self) -> tuple[str, str]:
        directory = Path(os.getenv("MCPSERVER_BIN_DIR", ""))
        if not directory.is_absolute():
            config_path = Path(os.getenv("MCPSERVER_CONFIG", ""))
            plugin_folder = config_path.parent.name if config_path.is_absolute() else ""
            home = Path(os.getenv("LBHOMEDIR", "/opt/loxberry"))
            if re.fullmatch(r"[A-Za-z0-9_-]+", plugin_folder) and home.is_absolute():
                directory = home / "bin" / "plugins" / plugin_folder
        helper = directory / "emergency-stop-miniserver.php"
        if not directory.is_absolute() or not helper.is_file():
            raise _ProviderUnavailable("helper_missing")
        home = Path(os.getenv("LBHOMEDIR", "/opt/loxberry"))
        perl_library = home / "libs" / "perllib"
        if not home.is_absolute() or not perl_library.is_dir():
            raise _ProviderUnavailable("perl_runtime_missing")
        provider_environment = os.environ.copy()
        provider_environment["LBHOMEDIR"] = str(home)
        provider_environment["PERL5LIB"] = str(perl_library)
        result = await asyncio.to_thread(
            subprocess.run,
            ["perl", "-I", str(perl_library), str(helper), self.config.loxone_endpoint],
            check=False,
            capture_output=True,
            env=provider_environment,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            reason = {
                2: "request_rejected",
                3: "credentials_missing",
                4: "endpoint_not_found",
            }.get(result.returncode, "helper_failed")
            raise _ProviderUnavailable(reason)
        if len(result.stdout) > 4096:
            raise _ProviderUnavailable("response_oversized")
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise _ProviderUnavailable("response_invalid") from exc
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("username"), str)
            or not isinstance(value.get("password"), str)
        ):
            raise _ProviderUnavailable("response_invalid")
        return value["username"], value["password"]

    async def _run(self) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        while True:
            token = None
            session = None
            stage = "credentials"
            try:
                username, password = await self._credentials()
                client = LoxoneClient(
                    MiniserverEndpoint.parse(self.config.loxone_endpoint),
                    client_uuid=uuid5(
                        NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/emergency-stop"
                    ),
                    timeout_seconds=self.config.connection_timeout,
                )
                stage = "token"
                if self.auth_coordinator is None:
                    token = await client.acquire_token(username, password)
                    session = await client.open_session(token)
                else:
                    token = await self.auth_coordinator.attempt(
                        partial(_acquire_token, client, username, password),
                        owner="runtime_event_stream",
                        phase="token_acquisition",
                    )
                    session = await self.auth_coordinator.attempt(
                        partial(_open_session, client, token),
                        owner="runtime_event_stream",
                        phase="session_establishment",
                    )
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
                    f"{stage}_{exc.reason}" if isinstance(exc, _ProviderUnavailable) else stage
                )
                _LOGGER.warning(
                    "component=emergency_stop outcome=monitor_unavailable code=%s error_type=%s",
                    failure_code,
                    type(exc).__name__,
                )
                await asyncio.sleep(5)
            finally:
                if session is not None:
                    await session.close()
                if token is not None:
                    token.destroy()

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
    monitor = EmergencyStopMonitor(config)
    token = None
    session = None
    stage = "credentials"
    try:
        username, password = await monitor._credentials()
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
        if auth_coordinator is None:
            token = await client.acquire_token(username, password)
        else:
            token = await auth_coordinator.attempt(
                partial(_acquire_token, client, username, password),
                owner="local_admin",
                phase="token_acquisition",
                allow_cooldown_probe=manual_retry,
            )
        stage = "session"
        if auth_coordinator is None:
            session = await client.open_session(token)
        else:
            session = await auth_coordinator.attempt(
                partial(_open_session, client, token),
                owner="local_admin",
                phase="session_establishment",
                allow_cooldown_probe=manual_retry,
            )
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
        if isinstance(exc, MiniserverAuthenticationSuppressed):
            reason = "authentication_suppressed"
        elif stage == "credentials" or isinstance(exc, _ProviderUnavailable):
            reason = "credentials_unavailable"
        elif stage == "structure":
            reason = "structure_failed"
        elif isinstance(exc, LoxoneConnectionError | TimeoutError | OSError):
            reason = "connection_failed"
        else:
            reason = "structure_failed" if stage == "structure" else "connection_failed"
        breaker = auth_coordinator.current_status() if auth_coordinator is not None else None
        retry_at = (
            breaker.get("retry_not_before")
            if breaker is not None and breaker.get("breaker_state") != "closed"
            else None
        )
        return VirtualStatusOptions(
            status="unavailable",
            options=(),
            failure_code=reason,
            retry_not_before=retry_at if isinstance(retry_at, int) else None,
        )
    finally:
        if session is not None:
            await session.close()
        if token is not None:
            token.destroy()
