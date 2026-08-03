"""Small atomic JSON store for opaque OAuth credentials."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, BinaryIO, Final, Protocol, TypeVar, cast

_SCHEMA_VERSION: Final = 1
_COLLECTIONS: Final = ("clients", "codes", "access_tokens", "refresh_tokens", "families")
T = TypeVar("T")


class _UidProvider(Protocol):
    def geteuid(self) -> int: ...


class AuthStoreError(RuntimeError):
    """The protected auth store cannot be used safely."""


def token_digest(value: str) -> str:
    """Return the only token representation that may be persisted."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


class AtomicJsonAuthStore:
    """Serialize auth updates under a process and platform file lock."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("Auth store path must be absolute")
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self._thread_lock = threading.RLock()
        self._prepare_directory()
        with self._locked():
            if not self.path.exists():
                self._write_unlocked(self._new_document())
            else:
                self._secure_existing_file()
                self._read_unlocked()

    def _prepare_directory(self) -> None:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
        except OSError as exc:
            raise AuthStoreError("Auth store directory cannot be secured") from exc

    @staticmethod
    def _new_document() -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "subject_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
            **{name: {} for name in _COLLECTIONS},
        }

    def _secure_existing_file(self) -> None:
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.path.is_symlink():
                raise AuthStoreError("Auth store path is not a regular file")
            if os.name != "nt":
                import posix

                current_uid = cast(_UidProvider, posix).geteuid()
                if metadata.st_uid != current_uid:
                    raise AuthStoreError("Auth store owner is invalid")
            os.chmod(self.path, 0o600)
        except AuthStoreError:
            raise
        except OSError as exc:
            raise AuthStoreError("Auth store file cannot be secured") from exc

    @contextmanager
    def _locked(self):  # type: ignore[no-untyped-def]
        with self._thread_lock:
            try:
                with self.lock_path.open("a+b") as handle:
                    os.chmod(self.lock_path, 0o600)
                    _lock_file(handle)
                    try:
                        yield
                    finally:
                        _unlock_file(handle)
            except AuthStoreError:
                raise
            except OSError as exc:
                raise AuthStoreError("Auth store lock failed") from exc

    @staticmethod
    def _validate(document: object) -> dict[str, Any]:
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            raise AuthStoreError("Auth store schema is invalid")
        expected = {"schema_version", "subject_key", *_COLLECTIONS}
        if set(document) != expected:
            raise AuthStoreError("Auth store schema is invalid")
        subject_key = document.get("subject_key")
        if not isinstance(subject_key, str):
            raise AuthStoreError("Auth store schema is invalid")
        try:
            decoded = base64.urlsafe_b64decode(subject_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise AuthStoreError("Auth store schema is invalid") from exc
        if len(decoded) != 32 or any(not isinstance(document[name], dict) for name in _COLLECTIONS):
            raise AuthStoreError("Auth store schema is invalid")
        return document

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            return self._validate(json.loads(raw))
        except AuthStoreError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthStoreError("Auth store is unreadable or corrupt") from exc

    def _write_unlocked(self, document: dict[str, Any]) -> None:
        self._validate(document)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    document,
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise AuthStoreError("Auth store update failed") from exc

    def snapshot(self) -> dict[str, Any]:
        """Return an isolated validated snapshot."""
        with self._locked():
            return copy.deepcopy(self._read_unlocked())

    def mutate(self, operation: Callable[[dict[str, Any]], T]) -> T:
        """Apply and durably commit one operation while holding both locks."""
        result: T | None = None
        failure: BaseException | None = None
        with self._locked():
            try:
                document = self._read_unlocked()
                original = copy.deepcopy(document)
                result = operation(document)
                if document != original:
                    self._write_unlocked(document)
            except BaseException as exc:
                failure = exc
        if failure is not None:
            raise failure
        return result  # type: ignore[return-value]

    def pseudonym(self, *parts: str) -> str:
        """Create a stable store-local identifier without retaining source values."""
        document = self.snapshot()
        key = base64.urlsafe_b64decode(document["subject_key"].encode("ascii"))
        canonical = "\0".join(parts).encode("utf-8")
        return hmac.new(key, canonical, hashlib.sha256).hexdigest()
