"""Private, cross-process cache for local Admin emergency-stop options."""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Protocol, cast

_SCHEMA: Final = 1
_MAX_BYTES: Final = 2 * 1024 * 1024
_MAX_OPTIONS: Final = 20_000
_LOCK_WAIT_SECONDS: Final = 95


class _UidProvider(Protocol):
    def geteuid(self) -> int: ...


def _valid_options(value: object) -> bool:
    if not isinstance(value, list) or len(value) > _MAX_OPTIONS:
        return False
    for option in value:
        if not isinstance(option, dict) or set(option) != {"uuid", "name"}:
            return False
        uuid = option["uuid"]
        name = option["name"]
        if (
            not isinstance(uuid, str)
            or not uuid
            or len(uuid) > 128
            or any(ord(character) < 32 for character in uuid)
            or not isinstance(name, str)
            or len(name) > 512
        ):
            return False
    return True


class EmergencyOptionsCache:
    """Keep only the last good option projection and most recent attempt result."""

    def __init__(self, auth_store_path: Path, profile: str) -> None:
        if not auth_store_path.is_absolute() or auth_store_path.suffix != ".json":
            raise ValueError("invalid Admin auth store path")
        self.path = auth_store_path.parent / "emergency-stop-options.json"
        self.lock_path = auth_store_path.parent / ".emergency-stop-options.lock"
        self.profile = profile

    def read(self) -> dict[str, Any] | None:
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_BYTES:
                return None
            if os.name != "nt":
                import posix

                current_uid = cast(_UidProvider, posix).geteuid()
                if metadata.st_mode & 0o077 or metadata.st_uid != current_uid:
                    return None
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        if not isinstance(document, dict) or document.get("schema") != _SCHEMA:
            return None
        if document.get("profile") != self.profile:
            return None
        if not isinstance(document.get("generation"), int) or document["generation"] < 1:
            return None
        if not isinstance(document.get("has_options"), bool):
            return None
        if not _valid_options(document.get("options")):
            return None
        result = document.get("result")
        if not isinstance(result, dict) or result.get("status") not in {
            "available",
            "unavailable",
            "not_configured",
        }:
            return None
        if result.get("failure_code") is not None and not isinstance(result["failure_code"], str):
            return None
        if result.get("retry_not_before") is not None and not isinstance(
            result["retry_not_before"], int
        ):
            return None
        return document

    @staticmethod
    def response(document: dict[str, Any] | None, *, cached_only: bool) -> dict[str, Any]:
        if document is None:
            return {"status": "not_loaded", "options": []}
        options = document["options"] if document["has_options"] else []
        result = document["result"]
        if cached_only:
            return {
                "status": "available" if document["has_options"] else "not_loaded",
                "options": options,
                "cached": document["has_options"],
                "stale": result["status"] != "available",
            }
        response = {
            "status": result["status"],
            "options": options,
            "cached": document["has_options"] and result["status"] != "available",
            "stale": document["has_options"] and result["status"] != "available",
        }
        if result.get("failure_code") is not None:
            response["discovery_failure_code"] = result["failure_code"]
        if result.get("retry_not_before") is not None:
            response["retry_not_before"] = result["retry_not_before"]
        return response

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            os.chmod(self.lock_path, 0o600)
            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while True:
                try:
                    if sys.platform == "win32":  # pragma: win32 cover
                        import msvcrt

                        handle.seek(0)
                        if handle.read(1) == b"":
                            handle.seek(0)
                            handle.write(b"0")
                            handle.flush()
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:  # pragma: posix cover
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("emergency-stop option refresh is busy") from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                if sys.platform == "win32":  # pragma: win32 cover
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: posix cover
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, document: dict[str, Any]) -> None:
        payload = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(payload) > _MAX_BYTES:
            raise ValueError("emergency-stop option cache exceeds size limit")
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def refresh(self, discover: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        before = self.read()
        generation = before["generation"] if before is not None else 0
        with self._locked():
            current = self.read()
            if current is not None and current["generation"] != generation:
                return self.response(current, cached_only=False)
            result = discover()
            status = result.get("status")
            if status not in {"available", "unavailable", "not_configured"}:
                raise ValueError("invalid emergency-stop discovery status")
            options = result.get("options", [])
            if status == "available" and not _valid_options(options):
                raise ValueError("invalid emergency-stop discovery options")
            has_options = status == "available" or bool(current and current["has_options"])
            document = {
                "schema": _SCHEMA,
                "profile": self.profile,
                "generation": generation + 1,
                "has_options": has_options,
                "options": (
                    options if status == "available" else current["options"] if current else []
                ),
                "result": {
                    "status": status,
                    "failure_code": result.get("discovery_failure_code"),
                    "retry_not_before": result.get("retry_not_before"),
                },
            }
            self._write(document)
            return self.response(document, cached_only=False)
