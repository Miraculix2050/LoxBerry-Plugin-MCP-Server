"""Validated, atomically persisted Phase 1 plugin configuration."""

from __future__ import annotations

import copy
import json
import os
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import idna

from mcpserver.loxone.client import MiniserverEndpoint

SCHEMA_VERSION: Final = 4
DEFAULT_CONNECTION_TIMEOUT: Final = 10.0
DEFAULT_REQUESTS_PER_MINUTE: Final = 60
DEFAULT_MAX_PARALLEL_CALLS: Final = 4
DEFAULT_CONTROL_REQUESTS_PER_MINUTE: Final = 10
DEFAULT_LOXBERRY_REQUESTS_PER_MINUTE: Final = 30
DEFAULT_HISTORY_REQUESTS_PER_MINUTE: Final = 12
DEFAULT_LOXBERRY_OPERATE_REQUESTS_PER_MINUTE: Final = 3
DEFAULT_STATISTICS_MEMORY_MAX_MIB: Final = 128
DEFAULT_STRUCTURE_REFRESH_SECONDS: Final = 300
DEFAULT_MAX_ACTIVE_RUNTIME_SESSIONS: Final = 16
DEFAULT_RUNTIME_SESSION_IDLE_SECONDS: Final = 900
DEFAULT_MAX_STRUCTURE_CONTROLS: Final = 20_000
DEFAULT_MAX_STRUCTURE_STATE_REFERENCES: Final = 100_000
DEFAULT_MAX_STRUCTURE_DEPTH: Final = 32
DEFAULT_MAX_STATES_PER_IDENTITY: Final = 20_000
MAX_LOXBERRY_BINDINGS: Final = 64
DEFAULT_LOG_LEVEL: Final = "warning"
SUPPORTED_LOG_LEVELS: Final = frozenset({"off", "error", "warning", "info", "debug"})


class ConfigError(ValueError):
    """The plugin configuration is invalid or cannot be persisted safely."""


def _mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ConfigError(f"{name} must be an object")
    return value


def _boolean(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _number(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ConfigError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ConfigError(f"{name} is outside the supported range")
    return result


def _integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ConfigError(f"{name} is outside the supported range")
    return value


def _log_level(value: object) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_LOG_LEVELS:
        raise ConfigError("logging.level is unsupported")
    return value


def _bindings(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_LOXBERRY_BINDINGS:
        raise ConfigError(f"{name} is unsupported")
    bindings: list[str] = []
    for binding in value:
        if not isinstance(binding, str) or len(binding) != 64:
            raise ConfigError(f"{name} is unsupported")
        try:
            int(binding, 16)
        except ValueError as exc:
            raise ConfigError(f"{name} is unsupported") from exc
        if binding.lower() != binding or binding in bindings:
            raise ConfigError(f"{name} is unsupported")
        bindings.append(binding)
    return tuple(bindings)


@dataclass(frozen=True, slots=True)
class PluginConfig:
    """The small public Phase 1 configuration contract."""

    enabled: bool = False
    public_origin: str = ""
    loxone_endpoint: str = ""
    connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT
    loxone_read_enabled: bool = True
    loxone_control_enabled: bool = False
    loxberry_read_enabled: bool = False
    loxone_history_enabled: bool = False
    loxberry_operate_enabled: bool = False
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    control_requests_per_minute: int = DEFAULT_CONTROL_REQUESTS_PER_MINUTE
    loxberry_requests_per_minute: int = DEFAULT_LOXBERRY_REQUESTS_PER_MINUTE
    history_requests_per_minute: int = DEFAULT_HISTORY_REQUESTS_PER_MINUTE
    loxberry_operate_requests_per_minute: int = DEFAULT_LOXBERRY_OPERATE_REQUESTS_PER_MINUTE
    max_parallel_calls: int = DEFAULT_MAX_PARALLEL_CALLS
    log_level: str = DEFAULT_LOG_LEVEL
    loxberry_read_bindings: tuple[str, ...] = ()
    loxberry_operate_bindings: tuple[str, ...] = ()
    statistics_memory_max_mib: int = DEFAULT_STATISTICS_MEMORY_MAX_MIB
    structure_refresh_seconds: int = DEFAULT_STRUCTURE_REFRESH_SECONDS
    max_active_runtime_sessions: int = DEFAULT_MAX_ACTIVE_RUNTIME_SESSIONS
    runtime_session_idle_seconds: int = DEFAULT_RUNTIME_SESSION_IDLE_SECONDS
    max_structure_controls: int = DEFAULT_MAX_STRUCTURE_CONTROLS
    max_structure_state_references: int = DEFAULT_MAX_STRUCTURE_STATE_REFERENCES
    max_structure_depth: int = DEFAULT_MAX_STRUCTURE_DEPTH
    max_states_per_identity: int = DEFAULT_MAX_STATES_PER_IDENTITY
    _source: dict[str, Any] | None = None

    @classmethod
    def defaults(cls) -> PluginConfig:
        return cls(_source={})

    @classmethod
    def from_document(cls, document: object) -> PluginConfig:
        root = _mapping(document, name="configuration")
        if root.get("schema_version") not in {1, 2, 3, SCHEMA_VERSION}:
            raise ConfigError("schema_version is unsupported")
        server = _mapping(root.get("server", {}), name="server")
        loxone = _mapping(root.get("loxone", {}), name="loxone")
        tools = _mapping(root.get("tools", {}), name="tools")
        limits = _mapping(root.get("limits", {}), name="limits")
        policies = _mapping(root.get("policies", {}), name="policies")
        cache = _mapping(root.get("cache", {}), name="cache")
        logging_config = _mapping(root.get("logging", {}), name="logging")

        enabled = _boolean(server.get("enabled", False), name="server.enabled")
        public_origin_value = server.get("public_origin", "")
        if not isinstance(public_origin_value, str) or len(public_origin_value) > 512:
            raise ConfigError("server.public_origin must be text")
        public_origin = public_origin_value.strip()
        if public_origin:
            parsed_origin = urlsplit(public_origin)
            if (
                parsed_origin.scheme != "https"
                or parsed_origin.hostname is None
                or parsed_origin.path
                or parsed_origin.query
                or parsed_origin.fragment
                or parsed_origin.username is not None
                or parsed_origin.password is not None
            ):
                raise ConfigError("server.public_origin must be an HTTPS origin")
            try:
                origin_host = idna.encode(
                    parsed_origin.hostname, uts46=True, std3_rules=True
                ).decode("ascii")
                origin_port = parsed_origin.port
            except (idna.IDNAError, ValueError) as exc:
                raise ConfigError("server.public_origin is not canonical") from exc
            if ":" in origin_host:
                origin_host = f"[{origin_host}]"
            authority = (
                origin_host if origin_port in {None, 443} else f"{origin_host}:{origin_port}"
            )
            if public_origin != f"https://{authority}":
                raise ConfigError("server.public_origin is not canonical")
        endpoint_value = loxone.get("endpoint", "")
        if not isinstance(endpoint_value, str) or len(endpoint_value) > 512:
            raise ConfigError("loxone.endpoint must be text")
        endpoint = endpoint_value.strip()
        if endpoint:
            try:
                MiniserverEndpoint.parse(endpoint)
            except ValueError as exc:
                raise ConfigError(str(exc)) from exc
        if enabled and (not endpoint or not public_origin):
            raise ConfigError("server.public_origin and loxone.endpoint are required when enabled")

        timeout = _number(
            loxone.get("connection_timeout", DEFAULT_CONNECTION_TIMEOUT),
            name="loxone.connection_timeout",
            minimum=1,
            maximum=60,
        )
        read_enabled = _boolean(
            tools.get("loxone_read_enabled", True), name="tools.loxone_read_enabled"
        )
        control_enabled = _boolean(
            tools.get("loxone_control_enabled", False), name="tools.loxone_control_enabled"
        )
        loxberry_read_enabled = _boolean(
            tools.get("loxberry_read_enabled", False), name="tools.loxberry_read_enabled"
        )
        loxone_history_enabled = _boolean(
            tools.get("loxone_history_enabled", False), name="tools.loxone_history_enabled"
        )
        loxberry_operate_enabled = _boolean(
            tools.get("loxberry_operate_enabled", False), name="tools.loxberry_operate_enabled"
        )
        if loxberry_operate_enabled and not loxone_history_enabled:
            raise ConfigError("tools.loxberry_operate_enabled requires loxone history")
        if enabled and not read_enabled:
            raise ConfigError("the Phase 1 service requires tools.loxone_read_enabled")
        if control_enabled and endpoint and MiniserverEndpoint.parse(endpoint).secure:
            raise ConfigError("Loxone control is supported only for Gen. 1 HTTP endpoints")
        requests = _integer(
            limits.get("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE),
            name="limits.requests_per_minute",
            minimum=1,
            maximum=600,
        )
        control_requests = _integer(
            limits.get("control_requests_per_minute", DEFAULT_CONTROL_REQUESTS_PER_MINUTE),
            name="limits.control_requests_per_minute",
            minimum=1,
            maximum=60,
        )
        loxberry_requests = _integer(
            limits.get("loxberry_requests_per_minute", DEFAULT_LOXBERRY_REQUESTS_PER_MINUTE),
            name="limits.loxberry_requests_per_minute",
            minimum=1,
            maximum=60,
        )
        history_requests = _integer(
            limits.get("history_requests_per_minute", DEFAULT_HISTORY_REQUESTS_PER_MINUTE),
            name="limits.history_requests_per_minute",
            minimum=1,
            maximum=60,
        )
        operate_requests = _integer(
            limits.get(
                "loxberry_operate_requests_per_minute",
                DEFAULT_LOXBERRY_OPERATE_REQUESTS_PER_MINUTE,
            ),
            name="limits.loxberry_operate_requests_per_minute",
            minimum=1,
            maximum=30,
        )
        parallel = _integer(
            limits.get("max_parallel_calls", DEFAULT_MAX_PARALLEL_CALLS),
            name="limits.max_parallel_calls",
            minimum=1,
            maximum=32,
        )
        structure_refresh_seconds = _integer(
            limits.get("structure_refresh_seconds", DEFAULT_STRUCTURE_REFRESH_SECONDS),
            name="limits.structure_refresh_seconds",
            minimum=60,
            maximum=3600,
        )
        max_active_runtime_sessions = _integer(
            limits.get("max_active_runtime_sessions", DEFAULT_MAX_ACTIVE_RUNTIME_SESSIONS),
            name="limits.max_active_runtime_sessions",
            minimum=1,
            maximum=128,
        )
        runtime_session_idle_seconds = _integer(
            limits.get("runtime_session_idle_seconds", DEFAULT_RUNTIME_SESSION_IDLE_SECONDS),
            name="limits.runtime_session_idle_seconds",
            minimum=60,
            maximum=86_400,
        )
        max_structure_controls = _integer(
            limits.get("max_structure_controls", DEFAULT_MAX_STRUCTURE_CONTROLS),
            name="limits.max_structure_controls",
            minimum=1_000,
            maximum=100_000,
        )
        max_structure_state_references = _integer(
            limits.get("max_structure_state_references", DEFAULT_MAX_STRUCTURE_STATE_REFERENCES),
            name="limits.max_structure_state_references",
            minimum=10_000,
            maximum=500_000,
        )
        max_structure_depth = _integer(
            limits.get("max_structure_depth", DEFAULT_MAX_STRUCTURE_DEPTH),
            name="limits.max_structure_depth",
            minimum=4,
            maximum=128,
        )
        max_states_per_identity = _integer(
            limits.get("max_states_per_identity", DEFAULT_MAX_STATES_PER_IDENTITY),
            name="limits.max_states_per_identity",
            minimum=1_000,
            maximum=100_000,
        )
        log_level = _log_level(logging_config.get("level", DEFAULT_LOG_LEVEL))
        loxberry_read_bindings = _bindings(
            policies.get("loxberry_read_bindings", []), name="policies.loxberry_read_bindings"
        )
        loxberry_operate_bindings = _bindings(
            policies.get("loxberry_operate_bindings", []),
            name="policies.loxberry_operate_bindings",
        )
        cache_max_mib = _integer(
            cache.get("statistics_memory_max_mib", DEFAULT_STATISTICS_MEMORY_MAX_MIB),
            name="cache.statistics_memory_max_mib",
            minimum=16,
            maximum=512,
        )
        return cls(
            enabled=enabled,
            public_origin=public_origin,
            loxone_endpoint=endpoint,
            connection_timeout=timeout,
            loxone_read_enabled=read_enabled,
            loxone_control_enabled=control_enabled,
            loxberry_read_enabled=loxberry_read_enabled,
            loxone_history_enabled=loxone_history_enabled,
            loxberry_operate_enabled=loxberry_operate_enabled,
            requests_per_minute=requests,
            control_requests_per_minute=control_requests,
            loxberry_requests_per_minute=loxberry_requests,
            history_requests_per_minute=history_requests,
            loxberry_operate_requests_per_minute=operate_requests,
            max_parallel_calls=parallel,
            log_level=log_level,
            loxberry_read_bindings=loxberry_read_bindings,
            loxberry_operate_bindings=loxberry_operate_bindings,
            statistics_memory_max_mib=cache_max_mib,
            structure_refresh_seconds=structure_refresh_seconds,
            max_active_runtime_sessions=max_active_runtime_sessions,
            runtime_session_idle_seconds=runtime_session_idle_seconds,
            max_structure_controls=max_structure_controls,
            max_structure_state_references=max_structure_state_references,
            max_structure_depth=max_structure_depth,
            max_states_per_identity=max_states_per_identity,
            _source=copy.deepcopy(root),
        )

    def to_document(self) -> dict[str, Any]:
        document = copy.deepcopy(self._source) if self._source is not None else {}
        document["schema_version"] = SCHEMA_VERSION
        for key in ("server", "loxone", "tools", "limits", "logging", "policies", "cache"):
            current = document.get(key)
            if not isinstance(current, dict):
                document[key] = {}
        document["server"]["enabled"] = self.enabled
        document["server"]["public_origin"] = self.public_origin
        document["loxone"]["endpoint"] = self.loxone_endpoint
        document["loxone"]["connection_timeout"] = self.connection_timeout
        document["tools"]["loxone_read_enabled"] = self.loxone_read_enabled
        document["tools"]["loxone_control_enabled"] = self.loxone_control_enabled
        document["tools"]["loxberry_read_enabled"] = self.loxberry_read_enabled
        document["tools"]["loxone_history_enabled"] = self.loxone_history_enabled
        document["tools"]["loxberry_operate_enabled"] = self.loxberry_operate_enabled
        document["limits"]["requests_per_minute"] = self.requests_per_minute
        document["limits"]["control_requests_per_minute"] = self.control_requests_per_minute
        document["limits"]["loxberry_requests_per_minute"] = self.loxberry_requests_per_minute
        document["limits"]["history_requests_per_minute"] = self.history_requests_per_minute
        document["limits"]["loxberry_operate_requests_per_minute"] = (
            self.loxberry_operate_requests_per_minute
        )
        document["limits"]["max_parallel_calls"] = self.max_parallel_calls
        document["limits"]["structure_refresh_seconds"] = self.structure_refresh_seconds
        document["limits"]["max_active_runtime_sessions"] = self.max_active_runtime_sessions
        document["limits"]["runtime_session_idle_seconds"] = self.runtime_session_idle_seconds
        document["limits"]["max_structure_controls"] = self.max_structure_controls
        document["limits"]["max_structure_state_references"] = self.max_structure_state_references
        document["limits"]["max_structure_depth"] = self.max_structure_depth
        document["limits"]["max_states_per_identity"] = self.max_states_per_identity
        document["logging"]["level"] = self.log_level
        document["logging"].pop("debug_until", None)
        document["policies"]["loxberry_read_bindings"] = list(self.loxberry_read_bindings)
        document["policies"]["loxberry_operate_bindings"] = list(self.loxberry_operate_bindings)
        document["cache"].pop("statistics_mode", None)
        document["cache"].pop("statistics_max_mib", None)
        document["cache"]["statistics_memory_max_mib"] = self.statistics_memory_max_mib
        return document


class AtomicConfigStore:
    """Read and atomically replace the authoritative JSON configuration."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path.suffix.lower() != ".json":
            raise ValueError("configuration path must be an absolute JSON file")
        self.path = path

    def load(self) -> PluginConfig:
        if not self.path.exists():
            return PluginConfig.defaults()
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.path.is_symlink():
                raise ConfigError("configuration path is not a regular file")
            return PluginConfig.from_document(json.loads(self.path.read_text(encoding="utf-8")))
        except ConfigError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError("configuration is unreadable") from exc

    def save(self, config: PluginConfig) -> None:
        document = config.to_document()
        PluginConfig.from_document(document)
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=True, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
            raise ConfigError("configuration update failed") from exc
