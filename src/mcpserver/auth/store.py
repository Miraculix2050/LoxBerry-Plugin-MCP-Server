"""Small atomic JSON store for opaque OAuth credentials."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, BinaryIO, Final, Protocol, TypeVar, cast

from mcpserver.persistence import fsync_parent_directory

_SCHEMA_VERSION: Final = 1
_COLLECTIONS: Final = ("clients", "codes", "access_tokens", "refresh_tokens", "families")
_MAX_STORE_BYTES: Final = 4 * 1024 * 1024
T = TypeVar("T")


_LIFECYCLE_LOGGER = logging.getLogger("mcpserver.auth.lifecycle")
_REVOCATION_REASONS = frozenset(
    {
        "unknown",
        "oauth_revocation",
        "explorer_logout",
        "refresh_reuse",
        "refresh_invalid_state",
        "admin_session",
        "admin_all_sessions",
        "approval_read_removed",
        "approval_operate_removed",
        "scope_disabled",
    }
)
_LIFECYCLE_SOURCES = frozenset(
    {"unknown", "oauth", "admin", "configuration", "maintenance", "runtime", "remote_worker"}
)
_LIFECYCLE_EVENTS = frozenset(
    {
        "client_registered",
        "client_removed",
        "family_created",
        "family_revoked",
        "family_removed",
        "token_rotated",
        "token_issued",
        "refresh_rejected",
        "approval_granted",
        "approval_removed",
        "approval_match",
        "remote_cleanup",
        "connection_opened",
        "connection_closed",
        "connection_close_requested",
        "runtime_closed",
        "service_started",
        "service_stopped",
        "family_expired",
        "batch_summary",
    }
)
_LIFECYCLE_REASONS = _REVOCATION_REASONS | frozenset(
    {
        "retention_cleanup",
        "family_expired",
        "refresh_rotation",
        "authorization_code",
        "exact_match",
        "no_exact_match",
        "capability_disabled",
        "explorer_logout",
        "transport_failed",
        "teardown_failed",
        "stream_ended",
        "token_refresh",
        "idle_eviction",
        "capacity_eviction",
        "shutdown",
        "local_disconnect",
        "confirmed_killed",
        "already_invalid",
        "expired_without_confirmation",
        "unconfirmed",
        "queued",
        "attempt_reserved",
        "authentication_suppressed",
        "source_ip_blocked",
        "command_rejected",
        "read",
        "operate",
    }
)
_LIFECYCLE_OUTCOMES = frozenset(
    {
        "unknown",
        "committed",
        "removed",
        "accepted",
        "rejected",
        "opened",
        "closed",
        "pending",
        "completed",
        "failed",
        "suppressed",
        "matched",
        "unmatched",
    }
)


def lifecycle_reference(kind: str, value: str) -> str:
    """Domain-separated reference for opaque random family IDs or existing binding hashes."""
    if not value or kind not in {"family", "binding"}:
        return "-"
    return hashlib.sha256(f"auth-lifecycle-v1\0{kind}\0{value}".encode()).hexdigest()[:24]


def lifecycle_client_reference(document: dict[str, Any], client_id: str) -> str:
    """Key client references so chosen client identifiers cannot be dictionary-matched."""
    if not client_id:
        return "-"
    key = base64.urlsafe_b64decode(document["subject_key"].encode("ascii"))
    return hmac.new(
        key, f"auth-lifecycle-client-v1\0{client_id}".encode(), hashlib.sha256
    ).hexdigest()[:24]


def revocation_details(family: dict[str, Any]) -> tuple[str, str]:
    reason, source = family.get("revocation_reason"), family.get("revocation_source")
    return (
        reason if isinstance(reason, str) and reason in _REVOCATION_REASONS else "unknown",
        source if isinstance(source, str) and source in _LIFECYCLE_SOURCES else "unknown",
    )


def mark_family_revoked(family: dict[str, Any], *, now: int, reason: str, source: str) -> bool:
    """Record only the first transition; never attribute a historical revocation retroactively."""
    if reason not in _REVOCATION_REASONS or source not in _LIFECYCLE_SOURCES:
        raise ValueError("Unsupported revocation cause")
    if family.get("revoked", False):
        return False
    family.update(revoked=True, revoked_at=now, revocation_reason=reason, revocation_source=source)
    return True


def lifecycle_event(
    event: str,
    *,
    family_id: str = "",
    client_ref: str = "-",
    binding_id: str = "",
    reason: str = "unknown",
    source: str = "unknown",
    outcome: str = "unknown",
    count: int = 1,
    capability: str = "-",
    debug: bool = False,
) -> None:
    """Emit only fixed fields, never source IDs, names, token material or exception text."""
    if event not in _LIFECYCLE_EVENTS:
        return
    family_ref = lifecycle_reference("family", family_id)
    binding_ref = lifecycle_reference("binding", binding_id)
    if len(client_ref) != 24 or any(c not in "0123456789abcdef" for c in client_ref):
        client_ref = "-"
    reason = reason if reason in _LIFECYCLE_REASONS else "unknown"
    source = source if source in _LIFECYCLE_SOURCES else "unknown"
    outcome = outcome if outcome in _LIFECYCLE_OUTCOMES else "unknown"
    capability = capability if capability in {"read", "operate"} else "-"
    correlation = next((ref for ref in (family_ref, binding_ref, client_ref) if ref != "-"), "-")
    # Diagnostic failure must not change an authorization or persistence result.
    with suppress(Exception):
        _LIFECYCLE_LOGGER.log(
            logging.DEBUG if debug else logging.WARNING if outcome == "failed" else logging.INFO,
            "component=auth_lifecycle event=%s trace_id=%s family_ref=%s client_ref=%s "
            "binding_ref=%s capability=%s reason=%s source=%s outcome=%s count=%d",
            event,
            correlation,
            family_ref,
            client_ref,
            binding_ref,
            capability,
            reason,
            source,
            outcome,
            max(0, min(count, 10000)),
        )


@contextmanager
def admin_lifecycle_logging():  # type: ignore[no-untyped-def]
    """Bound stderr below a small pipe budget; CGI forwards only its fixed safe grammar."""

    class Handler(logging.Handler):
        emitted = 0
        dropped = 0

        def emit(self, record: logging.LogRecord) -> None:
            text = f"mcpserver_auth_lifecycle={record.levelname} {record.getMessage()}"
            if self.emitted < 6 and len(text.encode("ascii", "replace")) <= 512:
                sys.stderr.write(text + "\n")
                self.emitted += 1
            else:
                self.dropped += 1

    handler = Handler()
    prior_level, prior_propagate = _LIFECYCLE_LOGGER.level, _LIFECYCLE_LOGGER.propagate
    _LIFECYCLE_LOGGER.setLevel(logging.DEBUG)
    _LIFECYCLE_LOGGER.propagate = False
    _LIFECYCLE_LOGGER.addHandler(handler)
    try:
        yield
    finally:
        if handler.dropped:
            with suppress(Exception):
                sys.stderr.write(
                    "mcpserver_auth_lifecycle=INFO component=auth_lifecycle event=batch_summary "
                    "trace_id=- family_ref=- client_ref=- binding_ref=- capability=- "
                    "reason=unknown source=admin outcome=unknown "
                    f"count={min(handler.dropped, 10000)}\n"
                )
        _LIFECYCLE_LOGGER.removeHandler(handler)
        _LIFECYCLE_LOGGER.setLevel(prior_level)
        _LIFECYCLE_LOGGER.propagate = prior_propagate


def _committed_lifecycle_events(
    original: dict[str, Any], document: dict[str, Any], *, now: int
) -> None:
    """Derive rare lifecycle transitions from the committed store delta, bounded per mutation."""
    emitted = 0
    total = 0

    def emit(event: str, **fields: Any) -> None:
        nonlocal emitted, total
        total += 1
        if emitted < 32:
            lifecycle_event(event, **fields)
            emitted += 1

    before_clients, clients = original["clients"], document["clients"]
    for client_id in clients.keys() - before_clients.keys():
        emit(
            "client_registered",
            client_ref=lifecycle_client_reference(document, client_id),
            source="oauth",
            outcome="committed",
        )
    for client_id in before_clients.keys() - clients.keys():
        emit(
            "client_removed",
            client_ref=lifecycle_client_reference(document, client_id),
            source="maintenance",
            reason="retention_cleanup",
            outcome="removed",
        )
    before, families = original["families"], document["families"]
    for family_id, family in families.items():
        if not isinstance(family, dict):
            continue
        fields = {
            "family_id": family_id,
            "client_ref": lifecycle_client_reference(document, str(family.get("client_id", ""))),
        }
        prior = before.get(family_id)
        if prior is None:
            emit("family_created", **fields, source="oauth", outcome="committed")
        if family.get("revoked") and (not isinstance(prior, dict) or not prior.get("revoked")):
            reason, source = revocation_details(family)
            emit("family_revoked", **fields, reason=reason, source=source, outcome="committed")
    for family_id in before.keys() - families.keys():
        family = before[family_id]
        expired = (
            isinstance(family, dict)
            and type(family.get("expires_at")) is int
            and family["expires_at"] <= now
        )
        emit(
            "family_expired" if expired else "family_removed",
            family_id=family_id,
            source="maintenance",
            reason="family_expired" if expired else "retention_cleanup",
            outcome="removed",
        )
    rotated = {
        record.get("family_id")
        for digest, record in document["refresh_tokens"].items()
        if isinstance(record, dict)
        and record.get("status") == "consumed"
        and original["refresh_tokens"].get(digest, {}).get("status") == "active"
    }
    issued = {
        record.get("family_id")
        for digest, record in document["access_tokens"].items()
        if digest not in original["access_tokens"] and isinstance(record, dict)
    }
    for family_id in issued:
        if isinstance(family_id, str):
            emit(
                "token_rotated" if family_id in rotated else "token_issued",
                family_id=family_id,
                reason="refresh_rotation" if family_id in rotated else "authorization_code",
                source="oauth",
                outcome="accepted",
                debug=True,
            )
    if total > emitted:
        lifecycle_event(
            "batch_summary", source="maintenance", outcome="committed", count=total - emitted
        )


def lifecycle_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Bounded local-admin diagnostics; no raw records or identifiers are exported."""
    families = document.get("families")
    if not isinstance(families, dict) or "subject_key" not in document:
        return {"availability": "unavailable"}
    counts: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for family_id, family in families.items():
        if not isinstance(family, dict) or not family.get("revoked"):
            continue
        reason, source = revocation_details(family)
        counts[reason] = counts.get(reason, 0) + 1
        at = family.get("revoked_at")
        recent.append(
            {
                "family_ref": lifecycle_reference("family", family_id),
                "client_ref": lifecycle_client_reference(
                    document, str(family.get("client_id", ""))
                ),
                "reason": reason,
                "source": source,
                "revoked_at": at if type(at) is int and 0 <= at <= 253402300799 else None,
            }
        )
    recent.sort(
        key=lambda item: item["revoked_at"] if item["revoked_at"] is not None else -1, reverse=True
    )
    return {
        "availability": "available",
        "retained_revoked": sum(counts.values()),
        "reason_counts": counts,
        "recent_revocations": recent[:20],
    }


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
            if self.path.stat().st_size > _MAX_STORE_BYTES:
                raise AuthStoreError("Auth store exceeds its size limit")
            raw = self.path.read_text(encoding="utf-8")
            return self._validate(json.loads(raw))
        except AuthStoreError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthStoreError("Auth store is unreadable or corrupt") from exc

    def _write_unlocked(self, document: dict[str, Any]) -> None:
        self._validate(document)
        serialized = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(serialized.encode("utf-8")) + 1 > _MAX_STORE_BYTES:
            raise AuthStoreError("Auth store exceeds its size limit")
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            fsync_parent_directory(self.path)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise AuthStoreError("Auth store update failed") from exc

    def snapshot(self) -> dict[str, Any]:
        """Return an isolated validated snapshot."""
        with self._locked():
            return copy.deepcopy(self._read_unlocked())

    def mutate(
        self, operation: Callable[[dict[str, Any]], T], *, lifecycle_now: int | None = None
    ) -> T:
        """Apply and durably commit one operation while holding both locks."""
        result: T | None = None
        failure: BaseException | None = None
        committed: tuple[dict[str, Any], dict[str, Any]] | None = None
        with self._locked():
            try:
                document = self._read_unlocked()
                original = copy.deepcopy(document)
                result = operation(document)
                if document != original:
                    self._write_unlocked(document)
                    committed = (original, document)
            except BaseException as exc:
                failure = exc
        if failure is not None:
            raise failure
        if committed is not None:
            with suppress(Exception):
                _committed_lifecycle_events(
                    *committed, now=int(time.time()) if lifecycle_now is None else lifecycle_now
                )
        return result  # type: ignore[return-value]

    def pseudonym(self, *parts: str) -> str:
        """Create a stable store-local identifier without retaining source values."""
        document = self.snapshot()
        key = base64.urlsafe_b64decode(document["subject_key"].encode("ascii"))
        canonical = "\0".join(parts).encode("utf-8")
        return hmac.new(key, canonical, hashlib.sha256).hexdigest()
