"""Validated process settings with secure local defaults."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import idna

from mcpserver.config import DEFAULT_LOG_LEVEL, AtomicConfigStore, PluginConfig
from mcpserver.loxone.client import MiniserverEndpoint

SERVER_PORT: Final = 8765


def _fixed_port_from_environment() -> int:
    if os.getenv("MCPSERVER_PORT", str(SERVER_PORT)) != str(SERVER_PORT):
        raise ValueError(f"MCPSERVER_PORT must remain {SERVER_PORT} to match the Apache proxy")
    return SERVER_PORT


def _parse_csv(value: str, *, setting: str) -> tuple[str, ...]:
    entries = tuple(item.strip() for item in value.split(",") if item.strip())
    if any(any(ord(character) < 32 for character in item) for item in entries):
        raise ValueError(f"{setting} contains a control character")
    return entries


def _canonical_hostname(host: str, *, setting: str) -> str:
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            # URL hosts serialize IPv4-mapped IPv6 addresses as hexadecimal
            # hextets, while ipaddress uses a dotted-decimal suffix.
            pieces = [
                int.from_bytes(address.packed[index : index + 2]) for index in range(0, 16, 2)
            ]
            best_start = 0
            best_length = 0
            start = 0
            while start < len(pieces):
                if pieces[start] != 0:
                    start += 1
                    continue
                end = start
                while end < len(pieces) and pieces[end] == 0:
                    end += 1
                if end - start > best_length:
                    best_start = start
                    best_length = end - start
                start = end

            before = ":".join(f"{piece:x}" for piece in pieces[:best_start])
            after = ":".join(f"{piece:x}" for piece in pieces[best_start + best_length :])
            return f"{before}::{after}"
        return str(address)
    except ValueError:
        numeric_label = host.rstrip(".").rsplit(".", 1)[-1].lower()
        looks_numeric = numeric_label.isdigit() or (
            numeric_label.startswith("0x")
            and len(numeric_label) > 2
            and all(character in "0123456789abcdef" for character in numeric_label[2:])
        )
        if looks_numeric or host.endswith("."):
            raise ValueError(f"{setting} contains a noncanonical numeric hostname") from None
        try:
            canonical = idna.encode(host, uts46=True, std3_rules=True).decode("ascii")
        except idna.IDNAError as exc:
            raise ValueError(f"{setting} contains an invalid hostname") from exc

        labels = canonical.split(".")
        if (
            len(canonical) > 253
            or any(not label or len(label) > 63 for label in labels)
            or any(label.startswith("-") or label.endswith("-") for label in labels)
            or any(
                not (character.isascii() and (character.isalnum() or character == "-"))
                for label in labels
                for character in label
            )
        ):
            raise ValueError(f"{setting} contains an invalid hostname") from None
        return canonical


def _validate_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    for entry in hosts:
        wildcard_port = entry.endswith(":*")
        value = entry[:-2] if wildcard_port else entry
        if not value or "%" in value or "\\" in value:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS contains an invalid Host value")

        parsed = urlsplit(f"//{value}")
        if (
            parsed.hostname is None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("MCPSERVER_ALLOWED_HOSTS contains an invalid Host value")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS contains an invalid port") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS contains an invalid port")
        if wildcard_port and port is not None:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS contains an invalid wildcard port")

        host = _canonical_hostname(parsed.hostname, setting="MCPSERVER_ALLOWED_HOSTS")
        if ":" in host:
            host = f"[{host}]"
        canonical = f"{host}:*" if wildcard_port else host
        if port is not None:
            canonical = f"{canonical}:{port}"
        if entry != canonical:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS entries must use canonical Host values")
    return hosts


def _validate_origins(origins: tuple[str, ...]) -> tuple[str, ...]:
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.hostname is None:
            raise ValueError("MCPSERVER_ALLOWED_ORIGINS must contain HTTP(S) origins")
        if "%" in parsed.netloc or "\\" in parsed.netloc:
            raise ValueError(
                "MCPSERVER_ALLOWED_ORIGINS entries must not contain encoded or backslash delimiters"
            )
        if (
            parsed.path != ""
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "MCPSERVER_ALLOWED_ORIGINS entries must not contain paths or credentials"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("MCPSERVER_ALLOWED_ORIGINS contains an invalid port") from exc

        host = _canonical_hostname(parsed.hostname, setting="MCPSERVER_ALLOWED_ORIGINS")
        if ":" in host:
            host = f"[{host}]"
        default_port = 80 if parsed.scheme == "http" else 443
        authority = host if port in {None, default_port} else f"{host}:{port}"
        canonical = f"{parsed.scheme}://{authority}"
        if origin != canonical:
            raise ValueError("MCPSERVER_ALLOWED_ORIGINS entries must use canonical origins")
    return origins


@dataclass(frozen=True, slots=True)
class Phase0AuthSettings:
    """Validated OAuth and Loxone runtime paths (name retained for compatibility)."""

    public_origin: str
    store_path: Path
    loxone_endpoint: MiniserverEndpoint
    loxone_store_path: Path | None = None
    install_key_path: Path | None = None
    config_path: Path | None = None
    plugin_config: PluginConfig | None = None

    @property
    def resource_url(self) -> str:
        return f"{self.public_origin}/plugins/mcpserver/mcp"

    @property
    def issuer_url(self) -> str:
        return f"{self.public_origin}/plugins/mcpserver/oauth"


def _phase0_auth_from_environment() -> Phase0AuthSettings | None:
    names = (
        "MCPSERVER_PUBLIC_ORIGIN",
        "MCPSERVER_AUTH_STORE",
        "MCPSERVER_LOXONE_ENDPOINT",
    )
    values = tuple(os.getenv(name, "").strip() for name in names)
    if not any(values):
        return None
    if not all(values):
        raise ValueError(f"{', '.join(names)} must be configured together")

    public_origin = _validate_origins((values[0],))[0]
    if not public_origin.startswith("https://"):
        raise ValueError("MCPSERVER_PUBLIC_ORIGIN must use HTTPS")

    store_path = Path(values[1])
    if not store_path.is_absolute() or store_path.name in {"", ".", ".."}:
        raise ValueError("MCPSERVER_AUTH_STORE must be an absolute JSON file path")
    if store_path.suffix.lower() != ".json":
        raise ValueError("MCPSERVER_AUTH_STORE must name a JSON file")

    return Phase0AuthSettings(
        public_origin=public_origin,
        store_path=store_path,
        loxone_endpoint=MiniserverEndpoint.parse(values[2]),
    )


def _phase1_auth_from_environment(
    base: Phase0AuthSettings | None,
    config: PluginConfig | None,
) -> tuple[Phase0AuthSettings | None, bool]:
    token_value = os.getenv("MCPSERVER_LOXONE_TOKEN_STORE", "").strip()
    key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
    if bool(token_value) != bool(key_value):
        raise ValueError(
            "MCPSERVER_LOXONE_TOKEN_STORE and MCPSERVER_INSTALL_KEY are required together"
        )
    if config is not None:
        if not config.enabled:
            return None, False
        if base is None:
            public_origin = config.public_origin or os.getenv("MCPSERVER_PUBLIC_ORIGIN", "").strip()
            auth_store = os.getenv("MCPSERVER_AUTH_STORE", "").strip()
            if not public_origin or not auth_store or not config.loxone_endpoint:
                raise ValueError("OAuth settings are required when the plugin is enabled")
            public_origin = _validate_origins((public_origin,))[0]
            if not public_origin.startswith("https://"):
                raise ValueError("MCPSERVER_PUBLIC_ORIGIN must use HTTPS")
            store_path = Path(auth_store)
            if not store_path.is_absolute() or store_path.suffix.lower() != ".json":
                raise ValueError("MCPSERVER_AUTH_STORE must be an absolute JSON file path")
            base = Phase0AuthSettings(
                public_origin=public_origin,
                store_path=store_path,
                loxone_endpoint=MiniserverEndpoint.parse(config.loxone_endpoint),
            )
    if base is None:
        return None, True
    endpoint = base.loxone_endpoint
    if config is not None and config.loxone_endpoint:
        endpoint = MiniserverEndpoint.parse(config.loxone_endpoint)
    return (
        replace(
            base,
            loxone_endpoint=endpoint,
            loxone_store_path=Path(token_value) if token_value else None,
            install_key_path=Path(key_value) if key_value else None,
            config_path=Path(os.getenv("MCPSERVER_CONFIG", ""))
            if os.getenv("MCPSERVER_CONFIG", "").strip()
            else None,
            plugin_config=config,
        ),
        True,
    )


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """Runtime settings for the local MCP process."""

    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    phase0_auth: Phase0AuthSettings | None = None
    service_enabled: bool = True
    log_level: str = DEFAULT_LOG_LEVEL
    plugin_config: PluginConfig | None = None

    @classmethod
    def from_environment(cls) -> ServerSettings:
        port = _fixed_port_from_environment()
        host = os.getenv("MCPSERVER_HOST", "127.0.0.1").strip()
        if host != "127.0.0.1":
            raise ValueError("MCPSERVER_HOST must remain 127.0.0.1")

        default_hosts = f"127.0.0.1:{port},localhost:{port}"
        allowed_hosts = _validate_hosts(
            _parse_csv(
                os.getenv("MCPSERVER_ALLOWED_HOSTS", default_hosts),
                setting="MCPSERVER_ALLOWED_HOSTS",
            )
        )
        if not allowed_hosts:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS must not be empty")

        allowed_origins = _validate_origins(
            _parse_csv(
                os.getenv("MCPSERVER_ALLOWED_ORIGINS", ""),
                setting="MCPSERVER_ALLOWED_ORIGINS",
            )
        )
        config_value = os.getenv("MCPSERVER_CONFIG", "").strip()
        plugin_config: PluginConfig | None = None
        if config_value:
            config_path = Path(config_value)
            if not config_path.is_absolute():
                raise ValueError("MCPSERVER_CONFIG must be an absolute path")
            plugin_config = AtomicConfigStore(config_path).load()
        phase_auth, service_enabled = _phase1_auth_from_environment(
            None if config_value else _phase0_auth_from_environment(), plugin_config
        )
        if phase_auth is not None and phase_auth.plugin_config is not None:
            public = urlsplit(phase_auth.public_origin)
            public_host = public.hostname or ""
            if ":" in public_host:
                public_host = f"[{public_host}]"
            if public.port is not None and public.port != 443:
                public_host = f"{public_host}:{public.port}"
            if public_host not in allowed_hosts:
                allowed_hosts = (*allowed_hosts, public_host)
            if phase_auth.public_origin not in allowed_origins:
                allowed_origins = (*allowed_origins, phase_auth.public_origin)
        return cls(
            host=host,
            port=port,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
            phase0_auth=phase_auth,
            service_enabled=service_enabled,
            log_level=plugin_config.log_level if plugin_config is not None else DEFAULT_LOG_LEVEL,
            plugin_config=plugin_config,
        )
