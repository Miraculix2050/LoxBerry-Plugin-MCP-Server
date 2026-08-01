from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import NameOID

from mcpserver.loxone.security import (
    CommandEncryptor,
    LoxoneSecurityError,
    encrypt_aes_command,
    encrypt_session_key,
    normalize_rsa_public_key_pem,
    password_hmac,
)


def test_password_hmac_uses_server_selected_sha256() -> None:
    result = password_hmac("reader", "correct horse", "00112233", "a1b2", "SHA256")

    password_hash = hashlib.sha256(b"correct horse:a1b2").hexdigest().upper()
    expected = hmac.new(
        bytes.fromhex("00112233"), f"reader:{password_hash}".encode(), hashlib.sha256
    )
    assert result == expected.hexdigest()


def test_password_hmac_rejects_unknown_algorithm_without_echoing_it() -> None:
    with pytest.raises(LoxoneSecurityError, match="unsupported"):
        password_hmac("reader", "secret", "0011", "salt", "MD5-secret")


def test_session_key_uses_rsa_pkcs1_v15() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    encoded = encrypt_session_key(public_pem, b"k" * 32, b"i" * 16)
    plaintext = private_key.decrypt(base64.b64decode(unquote(encoded)), padding.PKCS1v15())

    assert plaintext == f"{'6b' * 32}:{'69' * 16}".encode()


def test_gen1_certificate_without_line_breaks_yields_rsa_public_key() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Miniserver")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    compact = certificate.public_bytes(serialization.Encoding.PEM).decode().replace("\n", "")

    normalized = normalize_rsa_public_key_pem(compact)
    loaded = serialization.load_pem_public_key(normalized.encode())

    assert isinstance(loaded, rsa.RSAPublicKey)
    assert loaded.public_numbers() == private_key.public_key().public_numbers()


def test_gen1_mislabelled_der_public_key_yields_rsa_public_key() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    mislabelled = (
        "-----BEGIN CERTIFICATE-----" + base64.b64encode(der).decode() + "-----END CERTIFICATE-----"
    )

    normalized = normalize_rsa_public_key_pem(mislabelled)
    loaded = serialization.load_pem_public_key(normalized.encode())

    assert isinstance(loaded, rsa.RSAPublicKey)
    assert loaded.public_numbers() == private_key.public_key().public_numbers()


def test_aes_command_validates_session_material() -> None:
    with pytest.raises(LoxoneSecurityError, match="session material"):
        encrypt_aes_command("jdev/test", b"short", b"short", "salt")


def test_websocket_encryptor_rotates_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    encryptor = CommandEncryptor(key=b"k" * 32, iv=b"i" * 16, salt="first")
    monkeypatch.setattr("mcpserver.loxone.security.secrets.token_hex", lambda _size: "second")

    first = encryptor.encrypted_command("auth")
    second = encryptor.encrypted_command("refresh")

    first_cipher = base64.b64decode(unquote(first.rsplit("/", 1)[1]))
    second_cipher = base64.b64decode(unquote(second.rsplit("/", 1)[1]))
    decryptor = Cipher(algorithms.AES(b"k" * 32), modes.CBC(b"i" * 16)).decryptor()
    first_plaintext = (decryptor.update(first_cipher) + decryptor.finalize()).rstrip(b"\0")
    decryptor = Cipher(algorithms.AES(b"k" * 32), modes.CBC(b"i" * 16)).decryptor()
    second_plaintext = (decryptor.update(second_cipher) + decryptor.finalize()).rstrip(b"\0")

    assert first_plaintext == b"salt/first/auth"
    assert second_plaintext == b"nextSalt/first/second/refresh"
    assert encryptor.salt == "second"
