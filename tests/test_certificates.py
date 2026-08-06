from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mcpserver.certificates import inspect_certificate, renewal_state


def _write_certificates(tmp_path: Path) -> tuple[Path, Path, Path]:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loxberry-test")]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(2)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("loxberry-test"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(__import__("ipaddress").ip_address("192.0.2.10")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Other CA")])
    other_ca = (
        x509.CertificateBuilder()
        .subject_name(other_name)
        .issuer_name(other_name)
        .public_key(other_key.public_key())
        .serial_number(3)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(other_key, hashes.SHA256())
    )
    certificate_path = tmp_path / "wwwcert.pem"
    authority_path = tmp_path / "cacert.pem"
    other_path = tmp_path / "other.pem"
    certificate_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    authority_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    other_path.write_bytes(other_ca.public_bytes(serialization.Encoding.PEM))
    return certificate_path, authority_path, other_path


def test_certificate_status_matches_origin_without_exposing_san_values(tmp_path: Path) -> None:
    certificate, authority, _ = _write_certificates(tmp_path)

    result = inspect_certificate(
        certificate,
        authority,
        public_origin="https://loxberry-test",
        system_hostname="loxberry-test",
        helper_available=True,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert result == {
        "available": True,
        "source": "loxberry_ca",
        "expires_at": 1_788_566_400,
        "days_remaining": 30,
        "dns_san_count": 2,
        "ip_san_count": 1,
        "origin_configured": True,
        "origin_matches": True,
        "hostname_matches": True,
        "renewal_supported": True,
        "renewal": {"state": "idle"},
    }
    serialized = json.dumps(result)
    assert "loxberry-test" not in serialized
    assert "192.0.2.10" not in serialized


def test_certificate_status_supports_ip_origin_and_detects_hostname_mismatch(
    tmp_path: Path,
) -> None:
    certificate, authority, _ = _write_certificates(tmp_path)

    result = inspect_certificate(
        certificate,
        authority,
        public_origin="https://192.0.2.10",
        system_hostname="new-hostname",
        helper_available=True,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert result["origin_matches"] is True
    assert result["hostname_matches"] is False


def test_external_certificate_disables_core_reissue(tmp_path: Path) -> None:
    certificate, _, other_authority = _write_certificates(tmp_path)

    result = inspect_certificate(
        certificate,
        other_authority,
        public_origin="https://loxberry-test",
        system_hostname="loxberry-test",
        helper_available=True,
    )

    assert result["source"] == "external"
    assert result["renewal_supported"] is False


def test_renewal_state_rejects_unknown_or_oversized_content(tmp_path: Path) -> None:
    status = tmp_path / "status.json"
    status.write_text('{"state":"running","private_address":"192.0.2.10"}', encoding="utf-8")
    assert renewal_state(status) == {"state": "running"}

    status.write_text('{"state":"unknown"}', encoding="utf-8")
    assert renewal_state(status) == {"state": "error", "code": "status_unavailable"}

    status.write_bytes(b"x" * 4097)
    assert renewal_state(status) == {"state": "error", "code": "status_unavailable"}
