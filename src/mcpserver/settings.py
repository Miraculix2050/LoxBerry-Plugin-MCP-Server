"""Validated process settings with secure local defaults."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _parse_port(value: str) -> int:
    try:
        port = int(value, 10)
    except ValueError as exc:
        raise ValueError("MCPSERVER_PORT must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise ValueError("MCPSERVER_PORT must be between 1024 and 65535")
    return port


def _parse_csv(value: str, *, setting: str) -> tuple[str, ...]:
    entries = tuple(item.strip() for item in value.split(",") if item.strip())
    if any(any(ord(character) < 32 for character in item) for item in entries):
        raise ValueError(f"{setting} contains a control character")
    return entries


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

        host = parsed.hostname
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            numeric_label = host.rstrip(".").rsplit(".", 1)[-1].lower()
            looks_numeric = numeric_label.isdigit() or (
                numeric_label.startswith("0x")
                and len(numeric_label) > 2
                and all(character in "0123456789abcdef" for character in numeric_label[2:])
            )
            if looks_numeric or host.endswith("."):
                raise ValueError(
                    "MCPSERVER_ALLOWED_ORIGINS contains a noncanonical numeric hostname"
                ) from None
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ValueError("MCPSERVER_ALLOWED_ORIGINS contains an invalid hostname") from exc
        if ":" in host:
            host = f"[{host}]"
        default_port = 80 if parsed.scheme == "http" else 443
        authority = host if port in {None, default_port} else f"{host}:{port}"
        canonical = f"{parsed.scheme}://{authority}"
        if origin != canonical:
            raise ValueError("MCPSERVER_ALLOWED_ORIGINS entries must use canonical origins")
    return origins


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """Runtime settings for the local MCP process."""

    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> ServerSettings:
        port = _parse_port(os.getenv("MCPSERVER_PORT", "8765"))
        host = os.getenv("MCPSERVER_HOST", "127.0.0.1").strip()
        if host != "127.0.0.1":
            raise ValueError("MCPSERVER_HOST must remain 127.0.0.1")

        default_hosts = f"127.0.0.1:{port},localhost:{port}"
        allowed_hosts = _parse_csv(
            os.getenv("MCPSERVER_ALLOWED_HOSTS", default_hosts),
            setting="MCPSERVER_ALLOWED_HOSTS",
        )
        if not allowed_hosts:
            raise ValueError("MCPSERVER_ALLOWED_HOSTS must not be empty")

        allowed_origins = _validate_origins(
            _parse_csv(
                os.getenv("MCPSERVER_ALLOWED_ORIGINS", ""),
                setting="MCPSERVER_ALLOWED_ORIGINS",
            )
        )
        return cls(
            host=host,
            port=port,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
