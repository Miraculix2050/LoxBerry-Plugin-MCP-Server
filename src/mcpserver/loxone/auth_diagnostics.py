"""Bounded, sanitized coordination of Miniserver authentication attempts."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeVar

from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
)

_T = TypeVar("_T")
_MAX_EVENTS: Final = 200
_RETENTION_SECONDS: Final = 30 * 24 * 60 * 60
_SCHEMA_VERSION: Final = 1


class _InterprocessLockUnavailable(RuntimeError):
    """Another process is already evaluating an authentication attempt."""


@contextmanager
def _interprocess_lock(path: Path) -> Iterator[None]:
    """Serialize state reloads and updates across the service and Admin process."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        locked = False
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
            locked = True
        except OSError as exc:
            raise _InterprocessLockUnavailable from exc
        try:
            yield
        finally:
            if locked:
                if sys.platform == "win32":  # pragma: win32 cover
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: posix cover
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class MiniserverAuthenticationSuppressed(LoxoneConnectionError):
    """A confirmed source-IP block deliberately prevented a new login."""


@dataclass(frozen=True, slots=True)
class AttemptProvenance:
    """Only a request that starts an attempt may provide this context."""

    trace_id: str | None = None
    binding_id: str | None = None


class MiniserverAuthCoordinator:
    """One single-flight circuit breaker for a configured Miniserver profile."""

    def __init__(
        self,
        path: Path,
        *,
        initial_probe_seconds: int = 900,
        maximum_probe_seconds: int = 86_400,
        profile_id: str = "default",
    ) -> None:
        if initial_probe_seconds < 300 or maximum_probe_seconds < initial_probe_seconds:
            raise ValueError("invalid Miniserver authentication probe limits")
        self._path = path
        self._initial = initial_probe_seconds
        self._maximum = maximum_probe_seconds
        self._profile_id = profile_id
        self._lock = asyncio.Lock()
        self._last_suppression_persisted = 0.0
        self._state = self._load()
        self._retain_open_state = False

    def _load(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "breaker_state": "closed",
            "opened_at": None,
            "backoff_level": 0,
            "suppressed_attempts": 0,
            "sequence": 0,
            "events": [],
            "profile_id": self._profile_id,
        }
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return fallback
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != _SCHEMA_VERSION
            or value.get("profile_id") != self._profile_id
        ):
            return fallback
        for key, default in fallback.items():
            value.setdefault(key, default)
        if value["breaker_state"] not in {"closed", "open_source_ip_blocked"}:
            return fallback
        return value

    def _save(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        payload = json.dumps(self._state, separators=(",", ":"), sort_keys=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)
        os.chmod(self._path, 0o600)
        self._retain_open_state = False

    def _save_best_effort(self) -> None:
        """Keep a confirmed in-memory breaker when diagnostics cannot be written."""
        try:
            self._save()
        except OSError:
            self._retain_open_state = self._state["breaker_state"] == "open_source_ip_blocked"

    def _reload_state(self) -> None:
        """Reload persisted diagnostics unless an unwritten local breaker is stricter."""
        if self._retain_open_state and self._state["breaker_state"] == "open_source_ip_blocked":
            return
        self._state = self._load()

    def _delay(self) -> int:
        return int(min(self._initial * (2 ** int(self._state["backoff_level"])), self._maximum))

    def _retry_not_before(self) -> int | None:
        opened_at = self._state.get("opened_at")
        return opened_at + self._delay() if isinstance(opened_at, int) else None

    def status(self) -> dict[str, int | str | None]:
        return {
            "breaker_state": self._state["breaker_state"],
            "opened_at": self._state.get("opened_at"),
            "retry_not_before": self._retry_not_before(),
            "backoff_seconds": self._delay() if self._state["breaker_state"] != "closed" else None,
            "suppressed_attempts": int(self._state["suppressed_attempts"]),
        }

    def events_for(self, binding_id: str | None) -> list[dict[str, Any]]:
        if not binding_id:
            return []
        return [
            dict(event)
            for event in self._state["events"]
            if event.get("binding_id") == binding_id
            and event.get("connection_owner") == "tool_request"
        ]

    def _record(
        self,
        *,
        owner: str,
        phase: str,
        outcome: str,
        provenance: AttemptProvenance | None,
        transition: str | None = None,
    ) -> None:
        now = int(time.time())
        self._state["sequence"] = int(self._state["sequence"]) + 1
        event: dict[str, Any] = {
            "timestamp": now,
            "sequence": self._state["sequence"],
            "connection_owner": owner,
            "phase": phase,
            "outcome": outcome,
        }
        if transition is not None:
            event["breaker_transition"] = transition
        if provenance is not None and owner == "tool_request":
            if provenance.trace_id:
                event["trace_id"] = provenance.trace_id
            if provenance.binding_id:
                event["binding_id"] = provenance.binding_id
        events = deque(self._state["events"], maxlen=_MAX_EVENTS)
        events.append(event)
        self._state["events"] = [
            item
            for item in events
            if isinstance(item.get("timestamp"), int)
            and item["timestamp"] >= now - _RETENTION_SECONDS
        ]

    def _open_source_ip_breaker(
        self,
        *,
        now: int,
        owner: str,
        phase: str,
        provenance: AttemptProvenance | None,
    ) -> None:
        was_open = self._state["breaker_state"] == "open_source_ip_blocked"
        self._state["breaker_state"] = "open_source_ip_blocked"
        self._state["opened_at"] = now
        self._state["backoff_level"] = min(
            int(self._state["backoff_level"]) + (1 if was_open else 0), 31
        )
        self._record(
            owner=owner,
            phase=phase,
            outcome="source_ip_blocked",
            provenance=provenance,
            transition="reopened" if was_open else "opened",
        )

    def _refresh_failed_probe(
        self,
        *,
        now: int,
        owner: str,
        phase: str,
        outcome: str,
        provenance: AttemptProvenance | None,
    ) -> None:
        """Keep a confirmed block gated until a probe succeeds."""
        transition = None
        if self._state["breaker_state"] == "open_source_ip_blocked":
            self._state["opened_at"] = now
            transition = "probe_failed"
        self._record(
            owner=owner,
            phase=phase,
            outcome=outcome,
            provenance=provenance,
            transition=transition,
        )

    async def attempt(
        self,
        operation: Callable[[], Awaitable[_T]],
        *,
        owner: str,
        phase: str,
        provenance: AttemptProvenance | None = None,
        force_probe: bool = False,
        allow_cooldown_probe: bool = True,
    ) -> _T:
        """Run one authorized authentication attempt, or fail before networking."""
        if owner not in {"runtime_event_stream", "tool_request", "local_admin"}:
            raise ValueError("invalid connection owner")
        async with self._lock:
            try:
                with _interprocess_lock(self._path.with_name(f".{self._path.name}.lock")):
                    self._reload_state()
                    return await self._attempt_locked(
                        operation,
                        owner=owner,
                        phase=phase,
                        provenance=provenance,
                        force_probe=force_probe,
                        allow_cooldown_probe=allow_cooldown_probe,
                    )
            except _InterprocessLockUnavailable as exc:
                raise MiniserverAuthenticationSuppressed(
                    "Miniserver authentication is already being coordinated"
                ) from exc

    async def _attempt_locked(
        self,
        operation: Callable[[], Awaitable[_T]],
        *,
        owner: str,
        phase: str,
        provenance: AttemptProvenance | None,
        force_probe: bool,
        allow_cooldown_probe: bool,
    ) -> _T:
        """Execute one attempt while both coordinator locks are held."""
        now = int(time.time())
        if self._state["breaker_state"] == "open_source_ip_blocked":
            retry_at = self._retry_not_before()
            if not force_probe and (not allow_cooldown_probe or retry_at is None or now < retry_at):
                self._state["suppressed_attempts"] = int(self._state["suppressed_attempts"]) + 1
                if time.monotonic() - self._last_suppression_persisted >= 60:
                    self._record(
                        owner=owner,
                        phase=phase,
                        outcome="attempt_suppressed",
                        provenance=provenance,
                    )
                    self._save_best_effort()
                    self._last_suppression_persisted = time.monotonic()
                raise MiniserverAuthenticationSuppressed(
                    "Miniserver authentication is temporarily suppressed"
                )
        self._record(owner=owner, phase=phase, outcome="attempt_started", provenance=provenance)
        try:
            result = await operation()
        except LoxoneSourceIpBlocked:
            self._open_source_ip_breaker(now=now, owner=owner, phase=phase, provenance=provenance)
            self._save_best_effort()
            raise
        except LoxoneCommandRejected as exc:
            if exc.response_code == "4003":
                self._open_source_ip_breaker(
                    now=now, owner=owner, phase=phase, provenance=provenance
                )
                self._save_best_effort()
                raise
            if self._state["breaker_state"] == "open_source_ip_blocked":
                self._refresh_failed_probe(
                    now=now,
                    owner=owner,
                    phase=phase,
                    outcome="authentication_rejected",
                    provenance=provenance,
                )
            else:
                self._record(
                    owner=owner,
                    phase=phase,
                    outcome="authentication_rejected",
                    provenance=provenance,
                )
            self._save_best_effort()
            raise exc
        except Exception:
            self._refresh_failed_probe(
                now=now,
                owner=owner,
                phase=phase,
                outcome="transport_failed",
                provenance=provenance,
            )
            self._save_best_effort()
            raise
        transition = None
        if self._state["breaker_state"] == "open_source_ip_blocked":
            self._state["breaker_state"] = "closed"
            self._state["opened_at"] = None
            self._state["backoff_level"] = 0
            transition = "closed"
        self._record(
            owner=owner,
            phase=phase,
            outcome="recovery_confirmed" if transition else "authenticated",
            provenance=provenance,
            transition=transition,
        )
        self._save_best_effort()
        return result
