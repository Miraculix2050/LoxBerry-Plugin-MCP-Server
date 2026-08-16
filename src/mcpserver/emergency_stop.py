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
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from mcpserver.config import PluginConfig
from mcpserver.loxone.client import LoxoneClient

_LOGGER = logging.getLogger("mcpserver.emergency_stop")


class _ProviderUnavailable(RuntimeError):
    """Identify one fixed provider failure without exposing provider output."""

    def __init__(self, reason: str) -> None:
        super().__init__("provider unavailable")
        self.reason = reason


def _sorted_virtual_status_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    """Order display labels deterministically while retaining the UUID tie-breaker."""
    return sorted(options, key=lambda option: (option["name"].casefold(), option["uuid"]))


@dataclass(slots=True)
class EmergencyStopMonitor:
    """Tracks the one trusted status value; no selection means enabled."""

    config: PluginConfig
    status: str = "enabled"
    status_changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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
                token = await client.acquire_token(username, password)
                stage = "session"
                session = await client.open_session(token)
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


async def virtual_status_options(config: PluginConfig) -> list[dict[str, str]]:
    """Return selectable visible digital statuses without retaining credentials."""
    if not config.loxone_endpoint:
        return []
    monitor = EmergencyStopMonitor(config)
    token = None
    session = None
    try:
        username, password = await monitor._credentials()
        from mcpserver.loxone.client import MiniserverEndpoint

        client = LoxoneClient(
            MiniserverEndpoint.parse(config.loxone_endpoint),
            client_uuid=uuid5(
                NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/emergency-stop"
            ),
            timeout_seconds=config.connection_timeout,
        )
        token = await client.acquire_token(username, password)
        session = await client.open_session(token)
        structure = await session.load_structure()
        return _sorted_virtual_status_options(
            [
                {"uuid": item.uuid, "name": item.name}
                for item in structure.controls
                if item.control_type in {"VirtualStatus", "InfoOnlyDigital"}
                and len(item.state_uuids) == 1
            ]
        )
    except Exception:
        return []
    finally:
        if session is not None:
            await session.close()
        if token is not None:
            token.destroy()
