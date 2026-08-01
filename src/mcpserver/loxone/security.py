"""Loxone hashing and Command Encryption without credential logging."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import quote

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_AES_BLOCK_BYTES: Final = 16
_SUPPORTED_HASHES: Final = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256}


class LoxoneSecurityError(ValueError):
    """Raised for an unsupported or malformed security response."""


def password_hmac(username: str, password: str, key_hex: str, salt: str, algorithm: str) -> str:
    """Create the getjwt password HMAC exactly as documented by Loxone."""
    digest = _SUPPORTED_HASHES.get(algorithm.upper())
    if digest is None:
        raise LoxoneSecurityError("Miniserver returned an unsupported password hash algorithm")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise LoxoneSecurityError("Miniserver returned an invalid hashing key") from exc
    password_hash = digest(f"{password}:{salt}".encode()).hexdigest().upper()
    return hmac.new(key, f"{username}:{password_hash}".encode(), digest).hexdigest()


def token_hmac(token: str, key_hex: str, algorithm: str = "SHA1") -> str:
    """Hash a token for auth, refresh, check, or kill operations."""
    digest = _SUPPORTED_HASHES.get(algorithm.upper())
    if digest is None:
        raise LoxoneSecurityError("Miniserver returned an unsupported token hash algorithm")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise LoxoneSecurityError("Miniserver returned an invalid hashing key") from exc
    return hmac.new(key, token.encode(), digest).hexdigest()


def _zero_pad(value: bytes) -> bytes:
    remainder = len(value) % _AES_BLOCK_BYTES
    return value if remainder == 0 else value + (b"\0" * (_AES_BLOCK_BYTES - remainder))


def _encrypt_aes_plaintext(plaintext: str, key: bytes, iv: bytes) -> str:
    if len(key) != 32 or len(iv) != 16:
        raise LoxoneSecurityError("Invalid AES session material")
    padded = _zero_pad(plaintext.encode())
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    cipher = encryptor.update(padded) + encryptor.finalize()
    return quote(base64.b64encode(cipher).decode("ascii"), safe="")


def encrypt_aes_command(command: str, key: bytes, iv: bytes, salt: str) -> str:
    """Encrypt a salted command and return URI-encoded Base64 without line wraps."""
    return _encrypt_aes_plaintext(f"salt/{salt}/{command}", key, iv)


def _canonical_pem(value: str, label: str) -> bytes:
    begin = f"-----BEGIN {label}-----"
    end = f"-----END {label}-----"
    if begin not in value or end not in value:
        raise LoxoneSecurityError("Miniserver returned an invalid public key")
    body = "".join(value.split(begin, 1)[1].split(end, 1)[0].split())
    if not body:
        raise LoxoneSecurityError("Miniserver returned an invalid public key")
    lines = [body[index : index + 64] for index in range(0, len(body), 64)]
    return f"{begin}\n{'\n'.join(lines)}\n{end}\n".encode()


def _pem_der(value: str, label: str) -> bytes:
    begin = f"-----BEGIN {label}-----"
    end = f"-----END {label}-----"
    body = "".join(value.split(begin, 1)[1].split(end, 1)[0].split())
    return base64.b64decode(body, validate=True)


def _load_rsa_public_key(value: str) -> RSAPublicKey:
    loaded: object
    try:
        if "BEGIN CERTIFICATE" in value:
            try:
                loaded = x509.load_pem_x509_certificate(
                    _canonical_pem(value, "CERTIFICATE")
                ).public_key()
            except ValueError:
                # Gen. 1 firmware labels a DER SubjectPublicKeyInfo value as a
                # certificate even though it isn't an X.509 certificate.
                loaded = serialization.load_der_public_key(_pem_der(value, "CERTIFICATE"))
        else:
            loaded = serialization.load_pem_public_key(_canonical_pem(value, "PUBLIC KEY"))
    except (binascii.Error, IndexError, TypeError, ValueError) as exc:
        raise LoxoneSecurityError("Miniserver returned an invalid public key") from exc
    if not isinstance(loaded, RSAPublicKey):
        raise LoxoneSecurityError("Miniserver public key is not RSA")
    return loaded


def normalize_rsa_public_key_pem(value: str) -> str:
    """Accept a raw RSA key or Gen. 1 certificate and return a canonical RSA key."""
    loaded = _load_rsa_public_key(value)
    return loaded.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def encrypt_session_key(public_key_pem: str, key: bytes, iv: bytes) -> str:
    """Encrypt the hexadecimal AES key and IV with RSA PKCS#1 v1.5."""
    loaded = _load_rsa_public_key(public_key_pem)
    payload = f"{key.hex()}:{iv.hex()}".encode("ascii")
    encrypted = loaded.encrypt(payload, asymmetric_padding.PKCS1v15())
    return quote(base64.b64encode(encrypted).decode("ascii"), safe="")


@dataclass(slots=True)
class CommandEncryptor:
    """Ephemeral Command Encryption material for one operation or WebSocket."""

    key: bytes
    iv: bytes
    salt: str
    _used: bool = field(default=False, init=False, repr=False)

    @classmethod
    def generate(cls) -> CommandEncryptor:
        return cls(
            key=secrets.token_bytes(32), iv=secrets.token_bytes(16), salt=secrets.token_hex(8)
        )

    def encrypted_command(self, command: str) -> str:
        if self._used:
            previous = self.salt
            self.salt = secrets.token_hex(8)
            plaintext = f"nextSalt/{previous}/{self.salt}/{command}"
            cipher = _encrypt_aes_plaintext(plaintext, self.key, self.iv)
        else:
            self._used = True
            cipher = encrypt_aes_command(command, self.key, self.iv, self.salt)
        return f"jdev/sys/enc/{cipher}"

    def encrypted_session_key(self, public_key_pem: str) -> str:
        return encrypt_session_key(public_key_pem, self.key, self.iv)

    def encrypted_http_request(self, command: str, public_key_pem: str) -> str:
        session_key = self.encrypted_session_key(public_key_pem)
        return f"/{self.encrypted_command(command)}?sk={session_key}"
