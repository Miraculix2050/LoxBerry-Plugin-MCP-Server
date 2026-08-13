"""AES-GCM protected storage for renewable Loxone JWTs."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import sys
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mcpserver.loxone.client import LoxoneToken

_SCHEMA_VERSION: Final = 1


def _lock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":  # pragma: win32 cover
        import msvcrt

        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:  # pragma: posix cover
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":  # pragma: win32 cover
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: posix cover
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class LoxoneTokenStoreError(RuntimeError):
    """The encrypted Loxone token store cannot be used safely."""


@dataclass(frozen=True)
class ExplorerSession:
    """Encrypted server-side credentials for one browser Explorer session."""

    session_id: str
    family_id: str
    client_id: str
    resource: str
    scope: str
    access_token: str
    access_expires_at: int
    refresh_token: str
    expires_at: int


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decoded(value: object) -> bytes:
    if not isinstance(value, str):
        raise LoxoneTokenStoreError("encrypted token store is invalid")
    try:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise LoxoneTokenStoreError("encrypted token store is invalid") from exc


class EncryptedLoxoneTokenStore:
    """Persist individual Loxone tokens with record-bound authenticated encryption."""

    def __init__(self, path: Path, key_path: Path) -> None:
        if not path.is_absolute() or not key_path.is_absolute():
            raise ValueError("token and key paths must be absolute")
        self.path = path
        self.key_path = key_path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self._lock = threading.RLock()
        self._key = self._read_key()
        self._prepare()

    def _read_key(self) -> bytes:
        try:
            metadata = self.key_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.key_path.is_symlink():
                raise LoxoneTokenStoreError("installation key is not a regular file")
            key = self.key_path.read_bytes()
        except LoxoneTokenStoreError:
            raise
        except OSError as exc:
            raise LoxoneTokenStoreError("installation key is unavailable") from exc
        if len(key) != 32:
            raise LoxoneTokenStoreError("installation key has an invalid length")
        return key

    def _prepare(self) -> None:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
            with self._locked():
                if not self.path.exists():
                    self._write(
                        {"schema_version": _SCHEMA_VERSION, "tokens": {}, "explorer_sessions": {}}
                    )
                else:
                    self._read()
        except LoxoneTokenStoreError:
            raise
        except OSError as exc:
            raise LoxoneTokenStoreError("encrypted token store cannot be prepared") from exc

    @contextmanager
    def _locked(self):  # type: ignore[no-untyped-def]
        with self._lock:
            try:
                with self.lock_path.open("a+b") as handle:
                    os.chmod(self.lock_path, 0o600)
                    _lock_file(handle)
                    try:
                        yield
                    finally:
                        _unlock_file(handle)
            except LoxoneTokenStoreError:
                raise
            except OSError as exc:
                raise LoxoneTokenStoreError("encrypted token store lock failed") from exc

    @staticmethod
    def _validate(document: object) -> dict[str, Any]:
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "tokens", "explorer_sessions"}
            or document.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(document.get("tokens"), dict)
            or not isinstance(document.get("explorer_sessions"), dict)
        ):
            raise LoxoneTokenStoreError("encrypted token store is invalid")
        return document

    def _read(self) -> dict[str, Any]:
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.path.is_symlink():
                raise LoxoneTokenStoreError("encrypted token store path is unsafe")
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(document, dict) and set(document) == {"schema_version", "tokens"}:
                document["explorer_sessions"] = {}
            return self._validate(document)
        except LoxoneTokenStoreError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LoxoneTokenStoreError("encrypted token store is unreadable") from exc

    def _write(self, document: dict[str, Any]) -> None:
        self._validate(document)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    document, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise LoxoneTokenStoreError("encrypted token store update failed") from exc

    @staticmethod
    def _aad(family_id: str, miniserver_id: str, identity_id: str) -> bytes:
        return f"{_SCHEMA_VERSION}\0{family_id}\0{miniserver_id}\0{identity_id}".encode()

    def put(
        self,
        family_id: str,
        miniserver_id: str,
        identity_id: str,
        token: LoxoneToken,
    ) -> None:
        if not all((family_id, miniserver_id, identity_id, token.value, token.username)):
            raise ValueError("token metadata must not be empty")
        plaintext = json.dumps(
            {
                "value": token.value,
                "username": token.username,
                "hash_key": token.hash_key,
                "hash_algorithm": token.hash_algorithm,
                "valid_until": token.valid_until,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, plaintext, self._aad(family_id, miniserver_id, identity_id)
        )
        with self._locked():
            document = self._read()
            document["tokens"][family_id] = {
                "miniserver_id": miniserver_id,
                "identity_id": identity_id,
                "nonce": _encoded(nonce),
                "ciphertext": _encoded(ciphertext),
            }
            self._write(document)

    def get(self, family_id: str, miniserver_id: str, identity_id: str) -> LoxoneToken | None:
        with self._locked():
            record = self._read()["tokens"].get(family_id)
        if record is None:
            return None
        if (
            not isinstance(record, dict)
            or record.get("miniserver_id") != miniserver_id
            or record.get("identity_id") != identity_id
        ):
            raise LoxoneTokenStoreError("encrypted token binding is invalid")
        try:
            plaintext = AESGCM(self._key).decrypt(
                _decoded(record.get("nonce")),
                _decoded(record.get("ciphertext")),
                self._aad(family_id, miniserver_id, identity_id),
            )
            value = json.loads(plaintext)
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("value"), str)
                or not isinstance(value.get("username"), str)
                or not isinstance(value.get("hash_key"), str)
                or not isinstance(value.get("hash_algorithm"), str)
                or not isinstance(value.get("valid_until"), int)
            ):
                raise LoxoneTokenStoreError("decrypted Loxone token is invalid")
        except LoxoneTokenStoreError:
            raise
        except Exception as exc:
            raise LoxoneTokenStoreError("encrypted Loxone token cannot be decrypted") from exc
        return LoxoneToken(
            value["value"],
            value["username"],
            value["hash_key"],
            value["hash_algorithm"],
            value["valid_until"],
        )

    def delete(self, family_id: str) -> None:
        with self._locked():
            document = self._read()
            if document["tokens"].pop(family_id, None) is not None:
                self._write(document)

    @staticmethod
    def _explorer_aad(session_id: str, family_id: str, client_id: str) -> bytes:
        return f"{_SCHEMA_VERSION}\0explorer\0{session_id}\0{family_id}\0{client_id}".encode()

    def put_explorer_session(self, session: ExplorerSession) -> None:
        if not all(
            (
                session.session_id,
                session.family_id,
                session.client_id,
                session.resource,
                session.scope,
                session.access_token,
                session.refresh_token,
            )
        ):
            raise ValueError("explorer session fields must not be empty")
        plaintext = json.dumps(
            {
                "resource": session.resource,
                "scope": session.scope,
                "access_token": session.access_token,
                "access_expires_at": session.access_expires_at,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext,
            self._explorer_aad(session.session_id, session.family_id, session.client_id),
        )
        with self._locked():
            document = self._read()
            document["explorer_sessions"][session.session_id] = {
                "family_id": session.family_id,
                "client_id": session.client_id,
                "nonce": _encoded(nonce),
                "ciphertext": _encoded(ciphertext),
            }
            self._write(document)

    def get_explorer_session(self, session_id: str) -> ExplorerSession | None:
        with self._locked():
            record = self._read()["explorer_sessions"].get(session_id)
        if record is None:
            return None
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("family_id"), str)
            or not isinstance(record.get("client_id"), str)
        ):
            raise LoxoneTokenStoreError("encrypted Explorer session binding is invalid")
        family_id, client_id = record["family_id"], record["client_id"]
        try:
            plaintext = AESGCM(self._key).decrypt(
                _decoded(record.get("nonce")),
                _decoded(record.get("ciphertext")),
                self._explorer_aad(session_id, family_id, client_id),
            )
            value = json.loads(plaintext)
            expected = {
                "resource": str,
                "scope": str,
                "access_token": str,
                "access_expires_at": int,
                "refresh_token": str,
                "expires_at": int,
            }
            if not isinstance(value, dict) or not all(
                isinstance(value.get(key), kind) for key, kind in expected.items()
            ):
                raise ValueError
        except Exception as exc:
            raise LoxoneTokenStoreError("encrypted Explorer session is invalid") from exc
        return ExplorerSession(
            session_id,
            family_id,
            client_id,
            value["resource"],
            value["scope"],
            value["access_token"],
            value["access_expires_at"],
            value["refresh_token"],
            value["expires_at"],
        )

    def delete_explorer_session(self, session_id: str) -> None:
        with self._locked():
            document = self._read()
            if document["explorer_sessions"].pop(session_id, None) is not None:
                self._write(document)

    def delete_explorer_family(self, family_id: str) -> None:
        with self._locked():
            document = self._read()
            removed = [
                key
                for key, value in document["explorer_sessions"].items()
                if value.get("family_id") == family_id
            ]
            for key in removed:
                document["explorer_sessions"].pop(key, None)
            if removed:
                self._write(document)

    def family_ids(self) -> tuple[str, ...]:
        with self._locked():
            return tuple(sorted(self._read()["tokens"]))
