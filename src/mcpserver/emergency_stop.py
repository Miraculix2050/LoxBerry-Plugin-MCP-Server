"""Fail-closed service monitor for a configured digital Virtual Status."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from mcpserver.config import PluginConfig
from mcpserver.loxone.client import LoxoneClient

_LOGGER = logging.getLogger("mcpserver.emergency_stop")


@dataclass(slots=True)
class EmergencyStopMonitor:
    """Tracks the one trusted status value; no selection means enabled."""

    config: PluginConfig
    status: str = "enabled"
    _task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        if self.config.emergency_stop_virtual_status_uuid:
            self.status = "unknown"

    @property
    def allows_tool_calls(self) -> bool:
        return self.status == "enabled"

    def apply(self, value: object) -> None:
        if isinstance(value, bool):
            self.status = "enabled" if value else "disabled"
        elif isinstance(value, int | float) and value in {0, 1}:
            self.status = "enabled" if value == 1 else "disabled"
        else:
            self.status = "unknown"

    def unavailable(self) -> None:
        if self.config.emergency_stop_virtual_status_uuid:
            self.status = "unknown"

    async def start(self) -> None:
        """Start a dedicated LoxBerry-managed read-only state subscription."""
        if self.config.emergency_stop_virtual_status_uuid:
            self._task = asyncio.create_task(self._run())

    async def _credentials(self) -> tuple[str, str]:
        directory = Path(os.getenv("MCPSERVER_BIN_DIR", ""))
        helper = directory / "emergency-stop-miniserver.pl"
        if not directory.is_absolute() or not helper.is_file():
            raise RuntimeError("provider unavailable")
        result = await asyncio.to_thread(
            subprocess.run,
            ["perl", str(helper), self.config.loxone_endpoint],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise RuntimeError("provider unavailable")
        value = json.loads(result.stdout)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("username"), str)
            or not isinstance(value.get("password"), str)
        ):
            raise RuntimeError("provider unavailable")
        return value["username"], value["password"]

    async def _run(self) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        while True:
            token = None
            session = None
            try:
                username, password = await self._credentials()
                client = LoxoneClient(
                    MiniserverEndpoint.parse(self.config.loxone_endpoint),
                    client_uuid=uuid5(
                        NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver/emergency-stop"
                    ),
                    timeout_seconds=self.config.connection_timeout,
                )
                token = await client.acquire_token(username, password)
                session = await client.open_session(token)
                structure = await session.load_structure()
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
                async for batch in session.state_events():
                    for event in batch:
                        if event.uuid == state_uuid:
                            self.apply(event.value)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.unavailable()
                _LOGGER.warning("component=emergency_stop outcome=monitor_unavailable")
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
        return [
            {"uuid": item.uuid, "name": item.name}
            for item in structure.controls
            if item.control_type in {"VirtualStatus", "InfoOnlyDigital"}
            and len(item.state_uuids) == 1
        ]
    except Exception:
        return []
    finally:
        if session is not None:
            await session.close()
        if token is not None:
            token.destroy()
