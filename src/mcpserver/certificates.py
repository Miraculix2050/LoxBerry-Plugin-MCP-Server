"""Read-only inspection of the LoxBerry web-server certificate."""

from __future__ import annotations

import ipaddress
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature

_MAX_CERTIFICATE_BYTES: Final = 1024 * 1024
_MAX_STATUS_BYTES: Final = 4096
_RENEWAL_STATES: Final = frozenset({"idle", "scheduled", "running", "success", "error"})


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ValueError("file is unexpectedly large")
    return content


def _dns_matches(pattern: str, hostname: str) -> bool:
    pattern = pattern.rstrip(".").lower()
    hostname = hostname.rstrip(".").lower()
    if "*" not in pattern:
        return pattern == hostname
    labels = pattern.split(".")
    host_labels = hostname.split(".")
    return (
        len(labels) == len(host_labels)
        and labels[0] == "*"
        and all("*" not in label for label in labels[1:])
        and labels[1:] == host_labels[1:]
        and host_labels[0] != ""
    )


def _identity_matches(
    hostname: str,
    dns_names: tuple[str, ...],
    ip_addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return any(_dns_matches(pattern, hostname) for pattern in dns_names)
    return address in ip_addresses


def _issued_by(certificate: x509.Certificate, authority: x509.Certificate) -> bool:
    try:
        certificate.verify_directly_issued_by(authority)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def renewal_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"state": "idle"}
    try:
        document = json.loads(_read_bounded(path, _MAX_STATUS_BYTES))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {"state": "error", "code": "status_unavailable"}
    if not isinstance(document, dict) or document.get("state") not in _RENEWAL_STATES:
        return {"state": "error", "code": "status_unavailable"}
    result: dict[str, Any] = {"state": document["state"]}
    code = document.get("code")
    if isinstance(code, str) and code in {
        "core_unavailable",
        "renew_failed",
        "verification_failed",
    }:
        result["code"] = code
    updated_at = document.get("updated_at")
    if isinstance(updated_at, int) and 0 <= updated_at <= 4_102_444_799:
        result["updated_at"] = updated_at
    return result


def inspect_certificate(
    certificate_path: Path,
    authority_path: Path,
    *,
    public_origin: str,
    system_hostname: str,
    helper_available: bool,
    status_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return UI-safe certificate metadata without exposing SAN values."""
    state = renewal_state(status_path)
    try:
        certificate = x509.load_pem_x509_certificate(
            _read_bounded(certificate_path, _MAX_CERTIFICATE_BYTES)
        )
    except (OSError, ValueError):
        return {
            "available": False,
            "renewal_supported": False,
            "renewal": state,
        }

    dns_names: tuple[str, ...] = ()
    ip_addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...] = ()
    try:
        alternative_names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        dns_names = tuple(alternative_names.get_values_for_type(x509.DNSName))
        ip_addresses = tuple(
            value
            for value in alternative_names.get_values_for_type(x509.IPAddress)
            if isinstance(value, ipaddress.IPv4Address | ipaddress.IPv6Address)
        )
    except x509.ExtensionNotFound:
        pass

    origin_hostname = (urlsplit(public_origin).hostname or "") if public_origin else ""
    normalized_hostname = system_hostname.strip().rstrip(".").lower()
    authority_matches = False
    try:
        authority = x509.load_pem_x509_certificate(
            _read_bounded(authority_path, _MAX_CERTIFICATE_BYTES)
        )
        authority_matches = _issued_by(certificate, authority)
    except (OSError, ValueError):
        pass

    current_time = now or datetime.now(UTC)
    expires_at = certificate.not_valid_after_utc
    remaining_seconds = int((expires_at - current_time).total_seconds())
    return {
        "available": True,
        "source": "loxberry_ca" if authority_matches else "external",
        "expires_at": int(expires_at.timestamp()),
        "days_remaining": remaining_seconds // 86_400,
        "dns_san_count": len(dns_names),
        "ip_san_count": len(ip_addresses),
        "origin_configured": bool(origin_hostname),
        "origin_matches": bool(origin_hostname)
        and _identity_matches(origin_hostname, dns_names, ip_addresses),
        "hostname_matches": bool(normalized_hostname)
        and _identity_matches(normalized_hostname, dns_names, ip_addresses),
        "renewal_supported": authority_matches and helper_available,
        "renewal": state,
    }
