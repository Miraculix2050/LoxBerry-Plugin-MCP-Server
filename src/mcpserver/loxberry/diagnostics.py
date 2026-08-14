"""Fixed-source LoxBerry diagnostics with no shell execution."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, Final


class DiagnosticsUnavailable(RuntimeError):
    """A permitted diagnostic source could not be read safely."""


_SYSTEM_CONFIG_MAX_BYTES: Final = 256 * 1024
_PROC_MAX_BYTES: Final = 64 * 1024
_SYSTEMCTL_MAX_BYTES: Final = 16 * 1024
_SERVICE: Final = "loxberry-mcpserver.service"
_SYSTEMCTL_PROPERTIES: Final = ("LoadState", "ActiveState", "SubState")
_SERVICE_LOG_MAX_BYTES: Final = 512 * 1024
_MAX_SERVICE_EVENTS: Final = 100
_EVENT_LINE: Final = re.compile(
    r"^(?P<timestamp>.{1,40}?) component=(?P<component>[a-z_.]{1,96}) "
    r"severity=(?P<severity>DEBUG|INFO|WARNING|ERROR|CRITICAL)(?P<fields>.*)$"
)
_EVENT_FIELD: Final = re.compile(
    r" (?P<name>trace_id|outcome|code|error_type)=(?P<value>[^ ]{1,128})"
)
_EVENT_COMPONENTS: Final = frozenset(
    {
        "mcpserver.tools",
        "mcpserver.service",
        "mcpserver.auth.provider",
        "mcpserver.auth.remote_revocation",
        "mcpserver.loxone.client",
        "mcpserver.loxone.runtime",
    }
)


class LoxBerryDiagnostics:
    """Read only explicitly approved local system sources."""

    def __init__(self, home: Path) -> None:
        if not home.is_absolute():
            raise ValueError("LoxBerry home path must be absolute")
        self._home = home

    @staticmethod
    def _read_limited(path: Path, maximum: int) -> bytes:
        try:
            # Diagnostic sources are fixed by code. Refuse indirection even if a
            # plugin-owned log directory is writable by the service account.
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("diagnostic source is not a regular file")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                result = handle.read(maximum + 1)
        except OSError as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        if len(result) > maximum:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        return result

    def _version(self) -> str:
        raw = self._read_limited(
            self._home / "config/system/general.json", _SYSTEM_CONFIG_MAX_BYTES
        )
        try:
            value = json.loads(raw.decode("utf-8"))
            version = value["Base"]["Version"]
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        if not isinstance(version, str) or not version or len(version) > 128:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        return version

    @staticmethod
    def _number(value: str) -> float:
        try:
            result = float(value)
        except ValueError as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        if result < 0 or not result < float("inf"):
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        return result

    def system_status(self) -> dict[str, Any]:
        uptime = (
            self._read_limited(Path("/proc/uptime"), _PROC_MAX_BYTES)
            .decode("ascii", "strict")
            .split()
        )
        load = (
            self._read_limited(Path("/proc/loadavg"), _PROC_MAX_BYTES)
            .decode("ascii", "strict")
            .split()
        )
        meminfo = self._read_limited(Path("/proc/meminfo"), _PROC_MAX_BYTES).decode(
            "ascii", "strict"
        )
        if not uptime or not load:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        memory: dict[str, float] = {}
        for line in meminfo.splitlines():
            key, separator, value = line.partition(":")
            fields = value.split()
            if separator and len(fields) >= 2 and fields[1] == "kB":
                memory[key] = self._number(fields[0]) / 1024
        total = memory.get("MemTotal")
        available = memory.get("MemAvailable")
        processors = os.cpu_count()
        if total is None or available is None or total <= 0 or available > total or not processors:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        try:
            stats = getattr(os, "statvfs")(self._home)  # noqa: B009
            storage_total = stats.f_frsize * stats.f_blocks / (1024 * 1024)
            storage_available = stats.f_frsize * stats.f_bavail / (1024 * 1024)
        except OSError as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        if storage_total <= 0 or storage_available < 0 or storage_available > storage_total:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        return {
            "loxberry_version": self._version(),
            "uptime_seconds": int(self._number(uptime[0])),
            "cpu": {"logical_processors": processors, "load_1m": round(self._number(load[0]), 2)},
            "memory": {
                "total_mib": round(total, 2),
                "available_mib": round(available, 2),
                "used_percent": round((total - available) / total * 100, 2),
            },
            "storage": {
                "total_mib": round(storage_total, 2),
                "available_mib": round(storage_available, 2),
                "used_percent": round((storage_total - storage_available) / storage_total * 100, 2),
            },
        }

    def service_health(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    "/bin/systemctl",
                    "show",
                    *[f"--property={property_name}" for property_name in _SYSTEMCTL_PROPERTIES],
                    "--no-pager",
                    _SERVICE,
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        if len(result.stdout) > _SYSTEMCTL_MAX_BYTES:
            raise DiagnosticsUnavailable("diagnostic source unavailable")
        properties = {
            key: value
            for line in result.stdout.decode("utf-8", "replace").splitlines()
            if "=" in line
            for key, value in (line.split("=", 1),)
        }
        load_state = properties.get("LoadState", "unknown")
        active_state = properties.get("ActiveState", "unknown")
        sub_state = properties.get("SubState", "unknown")
        installed = result.returncode == 0 and load_state not in {"not-found", "unknown", ""}
        return {
            "service_name": "loxberry-mcpserver",
            "installed": installed,
            "active_state": active_state or "unknown",
            "sub_state": sub_state or "unknown",
            "healthy": installed and active_state == "active",
        }

    def service_events(self, *, limit: int) -> list[dict[str, str]]:
        """Return only allowlisted fields from this plugin's bounded service log."""
        if not 1 <= limit <= _MAX_SERVICE_EVENTS:
            raise ValueError("event limit is invalid")
        # This is a fixed plugin-owned path, deliberately not an MCP argument.
        raw = self._read_limited(
            self._home / "log/plugins/mcpserver/service.log", _SERVICE_LOG_MAX_BYTES
        )
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise DiagnosticsUnavailable("diagnostic source unavailable") from exc
        events: list[dict[str, str]] = []
        for line in text.splitlines():
            match = _EVENT_LINE.fullmatch(line)
            if match is None or match["component"] not in _EVENT_COMPONENTS:
                continue
            event = {
                "timestamp": match["timestamp"],
                "component": match["component"],
                "severity": match["severity"].lower(),
            }
            for field in _EVENT_FIELD.finditer(match["fields"]):
                event[field["name"]] = field["value"]
            events.append(event)
        return events[-limit:]
