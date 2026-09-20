"""Strict, dependency-light Miniserver endpoint validation."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

_GEN1_IPV4_NETWORKS: Final = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_GEN1_IPV6_NETWORK: Final = ipaddress.ip_network("fc00::/7")


@dataclass(frozen=True, slots=True)
class MiniserverEndpoint:
    """A canonical generation-aware Miniserver origin without credentials."""

    origin: str
    host: str
    port: int
    secure: bool = False

    @classmethod
    def parse(cls, value: str) -> MiniserverEndpoint:
        parsed = urlsplit(value)
        if parsed.scheme == "http":
            return cls.parse_gen1(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "%" in parsed.netloc
            or "\\" in parsed.netloc
        ):
            raise ValueError("Gen. 2 endpoint must be an HTTPS origin without credentials")
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            canonical_host = f"[{address}]" if address.version == 6 else str(address)
            host = str(address)
        except ValueError:
            if (
                len(host) > 253
                or host.endswith(".")
                or any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or re.fullmatch(r"[a-z0-9-]+", label) is None
                    for label in host.split(".")
                )
            ):
                raise ValueError("Gen. 2 endpoint contains an invalid hostname") from None
            canonical_host = host
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ValueError("Gen. 2 endpoint contains an invalid port") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Gen. 2 endpoint contains an invalid port")
        origin = f"https://{canonical_host}" if port == 443 else f"https://{canonical_host}:{port}"
        if value.rstrip("/") != origin:
            raise ValueError("Gen. 2 endpoint must use a canonical HTTPS origin")
        return cls(origin=origin, host=host, port=port, secure=True)

    @classmethod
    def parse_gen1(cls, value: str) -> MiniserverEndpoint:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Gen. 1 endpoint must be a plain HTTP origin without credentials")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            port = parsed.port or 80
        except ValueError as exc:
            raise ValueError("Gen. 1 endpoint must use a literal private IP address") from exc
        is_allowed = (
            any(address in network for network in _GEN1_IPV4_NETWORKS)
            if isinstance(address, ipaddress.IPv4Address)
            else address in _GEN1_IPV6_NETWORK
        )
        if not is_allowed:
            raise ValueError("Gen. 1 endpoint must use a private local IP address")
        host = f"[{address}]" if address.version == 6 else str(address)
        origin = f"http://{host}" if port == 80 else f"http://{host}:{port}"
        if value.rstrip("/") != origin:
            raise ValueError("Gen. 1 endpoint must use a canonical origin")
        return cls(origin=origin, host=str(address), port=port, secure=False)

    @property
    def websocket_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default_port = 443 if self.secure else 80
        authority = host if self.port == default_port else f"{host}:{self.port}"
        scheme = "wss" if self.secure else "ws"
        return f"{scheme}://{authority}/ws/rfc6455"
