"""Internal configured-identity access; never authorizes MCP client operations."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, TypedDict, TypeVar

from mcpserver.config import PluginConfig
from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
from mcpserver.loxone.client import LoxoneClient, LoxoneToken, LoxoneWebSocketSession

_T = TypeVar("_T")


class _ProbeOptions(TypedDict, total=False):
    early_probe: bool


class ServiceCredentialsUnavailable(RuntimeError):
    """Fixed provider reason; provider output must never reach diagnostics."""

    def __init__(self, reason: str) -> None:
        super().__init__("provider unavailable")
        self.reason = reason


class ServiceCredentials(Protocol):
    async def load(self) -> tuple[str, str]: ...


class LoxBerryServiceCredentials:
    """Read configured credentials afresh without retaining secrets."""

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    async def load(self) -> tuple[str, str]:
        directory = Path(os.getenv("MCPSERVER_BIN_DIR", ""))
        if not directory.is_absolute():
            config_path = Path(os.getenv("MCPSERVER_CONFIG", ""))
            plugin_folder = config_path.parent.name if config_path.is_absolute() else ""
            home = Path(os.getenv("LBHOMEDIR", "/opt/loxberry"))
            if re.fullmatch(r"[A-Za-z0-9_-]+", plugin_folder) and home.is_absolute():
                directory = home / "bin" / "plugins" / plugin_folder
        helper = directory / "emergency-stop-miniserver.php"
        if not directory.is_absolute() or not helper.is_file():
            raise ServiceCredentialsUnavailable("helper_missing")
        home = Path(os.getenv("LBHOMEDIR", "/opt/loxberry"))
        perl_library = home / "libs" / "perllib"
        if not home.is_absolute() or not perl_library.is_dir():
            raise ServiceCredentialsUnavailable("perl_runtime_missing")
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
            raise ServiceCredentialsUnavailable(reason)
        if len(result.stdout) > 4096:
            raise ServiceCredentialsUnavailable("response_oversized")
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ServiceCredentialsUnavailable("response_invalid") from exc
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("username"), str)
            or not isinstance(value.get("password"), str)
        ):
            raise ServiceCredentialsUnavailable("response_invalid")
        return value["username"], value["password"]


class ServiceMiniserverConnection:
    """Own exactly one internal token and session, including failed setup."""

    def __init__(
        self,
        client: LoxoneClient,
        coordinator: MiniserverAuthCoordinator | None,
        *,
        owner: str,
        busy_wait_seconds: float = 0,
        manual_retry: bool = False,
        early_probe: bool = False,
        timing: dict[str, float | int] | None = None,
    ) -> None:
        self.client = client
        self.coordinator = coordinator
        self.owner = owner
        self.busy_wait_seconds = busy_wait_seconds
        self.manual_retry = manual_retry
        self.early_probe = early_probe
        self.timing = timing
        self.stage = "token"
        self._started = False
        self._token: LoxoneToken | None = None
        self._session: LoxoneWebSocketSession | None = None

    async def connect(self, username: str, password: str) -> LoxoneWebSocketSession:
        if self._started:
            raise RuntimeError("Service connection already started")
        self._started = True
        deadline = time.monotonic() + self.busy_wait_seconds
        if self.timing is not None:
            self.timing["selector_coordinator_wait_ms"] = 0.0

        async def authenticate(operation: Callable[[], Awaitable[_T]], phase: str) -> _T:
            queued = time.perf_counter_ns() if self.timing is not None else 0
            entered = False

            async def measured_operation() -> _T:
                nonlocal entered
                entered = True
                started = time.perf_counter_ns() if self.timing is not None else 0
                if self.timing is not None and self.coordinator is not None:
                    self.timing["selector_coordinator_wait_ms"] += (started - queued) / 1_000_000
                try:
                    return await operation()
                finally:
                    if self.timing is not None:
                        self.timing[f"selector_{phase}_ms"] = (
                            time.perf_counter_ns() - started
                        ) / 1_000_000

            try:
                if self.coordinator is None:
                    return await measured_operation()
                probe_options: _ProbeOptions = (
                    {"early_probe": True}
                    if self.early_probe and phase == "token_acquisition"
                    else {}
                )
                return await self.coordinator.attempt(
                    measured_operation,
                    owner=self.owner,
                    phase=phase,
                    allow_cooldown_probe=self.manual_retry,
                    **probe_options,
                    busy_wait_seconds=max(0.0, deadline - time.monotonic()),
                )
            finally:
                if self.timing is not None and not entered:
                    self.timing["selector_coordinator_wait_ms"] += (
                        time.perf_counter_ns() - queued
                    ) / 1_000_000

        self.stage = "token"
        self._token = await authenticate(
            lambda: self.client.acquire_token(username, password), "token_acquisition"
        )
        self.stage = "session"
        token = self._token
        self._session = await authenticate(
            lambda: self.client.open_session(token), "session_establishment"
        )
        return self._session

    async def close(self) -> None:
        session, token = self._session, self._token
        self._session = None
        self._token = None
        try:
            if session is not None:
                await session.close()
        finally:
            if token is not None:
                token.destroy()
