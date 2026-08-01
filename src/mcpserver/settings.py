"""Validated process settings with secure local defaults."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import idna

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
class ServerSettings:
    """Runtime settings for the local MCP process."""

    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

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
        return cls(
            host=host,
            port=port,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
