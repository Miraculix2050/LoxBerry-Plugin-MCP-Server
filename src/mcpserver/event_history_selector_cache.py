"""Private, bounded cross-process projection for Event History Admin selection."""

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
_MAX_BYTES: Final = 32 * 1024 * 1024
_LOCK_WAIT_SECONDS: Final = 45


class SelectorCacheError(Exception):
    """The selector projection cannot be read or refreshed safely."""


class _UidProvider(Protocol):
    def geteuid(self) -> int: ...


class EventHistorySelectorCache:
    """Store only visible selector fields; each page still requests fresh discovery."""

    def __init__(self, auth_store_path: Path, profile: str) -> None:
        if not auth_store_path.is_absolute() or auth_store_path.suffix != ".json":
            raise ValueError("invalid Admin auth store path")
        self.path = auth_store_path.parent / "event-history-selector.json"
        self.lock_path = auth_store_path.parent / ".event-history-selector.lock"
        self.profile = profile

    def read(self) -> dict[str, Any] | None:
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_BYTES:
                return None
            if os.name != "nt":
                import posix

                if (
                    metadata.st_mode & 0o077
                    or metadata.st_uid != cast(_UidProvider, posix).geteuid()
                ):
                    return None
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        if not isinstance(document, dict) or document.get("schema") != _SCHEMA:
            return None
        if document.get("profile") != self.profile:
            return None
        if not isinstance(document.get("generation"), str):
            return None
        if not isinstance(document.get("verified_at"), int):
            return None
        if not isinstance(document.get("last_modified"), str):
            return None
        controls = document.get("controls")
        if not isinstance(controls, list) or len(controls) > 20_000:
            return None
        for item in controls:
            if (
                not isinstance(item, dict)
                or set(item)
                != {"uuid", "name", "type", "room_id", "room", "category_id", "category", "states"}
                or any(not isinstance(item[key], str) for key in ("uuid", "name", "type"))
                or any(
                    item[key] is not None and not isinstance(item[key], str)
                    for key in ("room_id", "room", "category_id", "category")
                )
                or not isinstance(item["states"], list)
                or any(
                    not isinstance(state, list)
                    or len(state) != 2
                    or any(not isinstance(value, str) for value in state)
                    for state in item["states"]
                )
            ):
                return None
        if sum(len(item["states"]) for item in controls) > 100_000:
            return None
        index = document.get("control_index")
        if (
            not isinstance(index, dict)
            or len(index) != len(controls)
            or any(
                not isinstance(value, int)
                or value < 0
                or value >= len(controls)
                or controls[value]["uuid"] != key
                for key, value in index.items()
            )
        ):
            return None
        return document

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
                        raise TimeoutError("event-history selector refresh is busy") from None
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
        controls = document["controls"]
        if (
            len(controls) > 20_000
            or sum(len(item["states"]) for item in controls) > 100_000
            or len(document["control_index"]) != len(controls)
        ):
            raise SelectorCacheError("event-history selector projection is invalid or oversized")
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                size = 0
                # Repeated group names must not materialize one expanded JSON payload in memory.
                encoder = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False)
                for chunk in encoder.iterencode(document):
                    encoded = chunk.encode("utf-8")
                    size += len(encoded)
                    if size > _MAX_BYTES:
                        raise SelectorCacheError(
                            "event-history selector projection exceeds size limit"
                        )
                    handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def refresh(self, discover: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Join a concurrent refresh, but start a new one on a later page visit."""
        before = self.read()
        generation = before["generation"] if before else None
        with self._locked():
            current = self.read()
            if current is not None and current["generation"] != generation:
                return current
            # A failed fresh visibility check must not leave old names queryable.
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise SelectorCacheError("selector cache cannot be invalidated") from exc
            projection = discover()
            unchanged = (
                current is not None
                and current["last_modified"] == projection["last_modified"]
                and current["controls"] == projection["controls"]
            )
            document = {
                "schema": _SCHEMA,
                "profile": self.profile,
                "generation": (
                    current["generation"]
                    if unchanged and current is not None
                    else secrets.token_hex(12)
                ),
                "verified_at": int(time.time()),
                "last_modified": projection["last_modified"],
                "controls": projection["controls"],
                "control_index": {
                    item["uuid"]: index for index, item in enumerate(projection["controls"])
                },
            }
            self._write(document)
            return document
