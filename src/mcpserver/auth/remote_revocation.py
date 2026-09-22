"""Bounded cleanup of Loxone tokens after local OAuth revocation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import stat
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    LoxoneTokenAuthenticationRejected,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import LoxoneProtocolError

_LOGGER = logging.getLogger("mcpserver.auth.remote_revocation")
_POLL_SECONDS: Final = 5
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")
_LOXONE_EPOCH: Final = 1_230_768_000
_DAY: Final = 86_400
_MAX_ATTEMPTS: Final = 5
_RETRY_DELAYS: Final = (300, 1800, 7200, 43_200, 86_400)
_INVALID_DELAYS: Final = (3600, 7200, 14_400, 28_800, 86_400)
_OUTCOMES: Final = frozenset(
    {"confirmed_killed", "already_invalid", "unconfirmed", "expired_without_confirmation"}
)
_FAILURES: Final = frozenset(
    {"authentication_rejected", "source_ip_blocked", "transport_failed", "command_rejected"}
)


class RemoteRevocationStateError(RuntimeError):
    """The sanitized cleanup state cannot be trusted or persisted."""


class RemoteRevocationState:
    """Single-writer, atomically replaced status beside the encrypted token store."""

    def __init__(self, token_store_path: Path) -> None:
        self.path = token_store_path.with_name("remote-revocation-status.json")

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "not_before": 0,
            "invalid_streak": 0,
            "last_failure_category": None,
            "last_failure_at": None,
            "totals": {outcome: 0 for outcome in _OUTCOMES},
            "tombstones": [],
        }

    @staticmethod
    def _validate(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != set(RemoteRevocationState._empty()):
            raise RemoteRevocationStateError("cleanup status is invalid")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or any(
                not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 0
                for key in ("not_before", "invalid_streak")
            )
        ):
            raise RemoteRevocationStateError("cleanup status is invalid")
        if value["last_failure_category"] is not None and (
            not isinstance(value["last_failure_category"], str)
            or value["last_failure_category"] not in _FAILURES
        ):
            raise RemoteRevocationStateError("cleanup status is invalid")
        if value["last_failure_at"] is not None and (
            type(value["last_failure_at"]) is not int or value["last_failure_at"] < 0
        ):
            raise RemoteRevocationStateError("cleanup status is invalid")
        totals, tombstones = value["totals"], value["tombstones"]
        if (
            not isinstance(totals, dict)
            or set(totals) != _OUTCOMES
            or any(
                not isinstance(count, int) or isinstance(count, bool) or count < 0
                for count in totals.values()
            )
        ):
            raise RemoteRevocationStateError("cleanup status is invalid")
        if not isinstance(tombstones, list) or len(tombstones) > 10_000:
            raise RemoteRevocationStateError("cleanup status is invalid")
        for item in tombstones:
            if (
                not isinstance(item, dict)
                or set(item) != {"outcome", "expires_at"}
                or not isinstance(item["outcome"], str)
                or item["outcome"] not in _OUTCOMES
                or type(item["expires_at"]) is not int
                or item["expires_at"] < 0
            ):
                raise RemoteRevocationStateError("cleanup status is invalid")
        return value

    def read(self) -> dict[str, Any]:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return self._empty()
        except OSError as exc:
            raise RemoteRevocationStateError("cleanup status is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode) or self.path.is_symlink():
            raise RemoteRevocationStateError("cleanup status path is unsafe")
        try:
            return self._validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, UnicodeError) as exc:
            raise RemoteRevocationStateError("cleanup status is unavailable") from exc

    def write(self, value: dict[str, Any]) -> None:
        self._validate(value)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise RemoteRevocationStateError("cleanup status cannot be saved") from exc

    def summary(self, store: EncryptedLoxoneTokenStore, now: int) -> dict[str, Any]:
        value = self.read()
        pending, retryable, scheduled = store.remote_revocation_counts(now)
        next_attempt = max(now, value["not_before"], scheduled or 0) if pending else None
        return {
            "pending": pending,
            "retryable": retryable,
            "unconfirmed": sum(
                item["outcome"] == "unconfirmed" and item["expires_at"] > now
                for item in value["tombstones"]
            ),
            "not_before": next_attempt,
            "last_failure_category": value["last_failure_category"],
            "last_failure_at": value["last_failure_at"],
        }


def _terminal(
    state: RemoteRevocationState,
    value: dict[str, Any],
    store: EncryptedLoxoneTokenStore,
    family_id: str,
    outcome: str,
    now: int,
    valid_until: int,
) -> None:
    if outcome == "already_invalid":
        expires_at = now + 30 * _DAY
    elif outcome == "unconfirmed":
        expires_at = min(max(now + _DAY, valid_until + _LOXONE_EPOCH + _DAY), now + 180 * _DAY)
    else:
        expires_at = now + _DAY
    value["tombstones"] = [item for item in value["tombstones"] if item["expires_at"] > now][-9999:]
    value["tombstones"].append({"outcome": outcome, "expires_at": expires_at})
    value["totals"][outcome] += 1
    state.write(value)
    store.complete_remote_revoke(family_id)


async def process_remote_revocations(
    endpoint: MiniserverEndpoint,
    store: EncryptedLoxoneTokenStore,
    timeout_seconds: float,
    auth_coordinator: MiniserverAuthCoordinator | None = None,
) -> None:
    """Process at most one network attempt; local OAuth revocation already happened."""
    now = int(time.time())
    state = RemoteRevocationState(store.path)
    try:
        value = state.read()
        if value["not_before"] > now:
            return
        pending = store.pending_remote_revocations(now)
        if not pending:
            return
        if auth_coordinator is not None:
            breaker = auth_coordinator.current_status()
            if breaker["breaker_state"] != "closed":
                retry_at = breaker["retry_not_before"]
                value["not_before"] = max(now + _POLL_SECONDS, retry_at or now)
                state.write(value)
                return
        item = pending[0]
        if item.token.valid_until + _LOXONE_EPOCH <= now:
            _terminal(
                state,
                value,
                store,
                item.family_id,
                "expired_without_confirmation",
                now,
                item.token.valid_until,
            )
            return
        if item.attempts >= _MAX_ATTEMPTS:
            _terminal(
                state, value, store, item.family_id, "unconfirmed", now, item.token.valid_until
            )
            return
        # Reserve the attempt and cooldown in both durable stores before authentication.
        # A later status or token-store failure must never create an uncounted retry.
        reserved_delay = _RETRY_DELAYS[min(item.attempts, 4)]
        value["not_before"] = now + reserved_delay
        state.write(value)
        attempts = store.reserve_remote_revoke_attempt(item.family_id, now + reserved_delay)
        if attempts == 0:
            return
        client = LoxoneClient(endpoint, client_uuid=_CLIENT_UUID, timeout_seconds=timeout_seconds)

        async def revoke() -> None:
            await asyncio.wait_for(client.kill_token(item.token), timeout=timeout_seconds + 5)

        try:
            if auth_coordinator is None:
                await revoke()
            else:
                await auth_coordinator.attempt(
                    revoke,
                    owner="runtime_event_stream",
                    phase="remote_token_revocation",
                    allow_cooldown_probe=False,
                )
        except MiniserverAuthenticationSuppressed:
            retry_at = (
                auth_coordinator.current_status()["retry_not_before"]
                if auth_coordinator is not None
                else None
            )
            value["not_before"] = max(now + _POLL_SECONDS, retry_at or now)
            state.write(value)
            store.release_suppressed_remote_revoke_attempt(
                item.family_id,
                reserved_attempts=attempts,
                previous_retry_after=item.retry_after,
            )
            return
        except LoxoneTokenAuthenticationRejected:
            value["invalid_streak"] += 1
            delay = _INVALID_DELAYS[min(value["invalid_streak"] - 1, 4)]
            value["not_before"] = now + delay
            value["last_failure_category"] = "authentication_rejected"
            value["last_failure_at"] = now
            _terminal(
                state, value, store, item.family_id, "already_invalid", now, item.token.valid_until
            )
            return
        except (TimeoutError, LoxoneConnectionError, LoxoneProtocolError) as exc:
            category = (
                "source_ip_blocked"
                if isinstance(exc, LoxoneSourceIpBlocked)
                or (isinstance(exc, LoxoneCommandRejected) and exc.response_code == "4003")
                else "command_rejected"
                if isinstance(exc, LoxoneCommandRejected)
                else "transport_failed"
            )
            value["last_failure_category"] = category
            value["last_failure_at"] = now
            delay = _RETRY_DELAYS[min(attempts - 1, 4)]
            if category == "source_ip_blocked":
                delay = max(delay, 3600)
                if auth_coordinator is not None:
                    retry_at = auth_coordinator.current_status()["retry_not_before"]
                    delay = max(delay, retry_at - now if isinstance(retry_at, int) else 0)
            value["not_before"] = now + delay
            if attempts >= _MAX_ATTEMPTS:
                _terminal(
                    state, value, store, item.family_id, "unconfirmed", now, item.token.valid_until
                )
                return
            state.write(value)
            store.suspend_remote_revoke(item.family_id, now, delay_seconds=delay)
            _LOGGER.warning("component=remote_revocation outcome=%s", category)
            return
        value["invalid_streak"] = 0
        value["not_before"] = 0
        _terminal(
            state, value, store, item.family_id, "confirmed_killed", now, item.token.valid_until
        )
        _LOGGER.info("component=remote_revocation outcome=confirmed_killed")
    except (LoxoneTokenStoreError, RemoteRevocationStateError) as exc:
        _LOGGER.warning(
            "component=remote_revocation outcome=queue_unavailable error_type=%s",
            type(exc).__name__,
        )


async def run_remote_revocation_worker(
    endpoint: MiniserverEndpoint,
    store: EncryptedLoxoneTokenStore,
    timeout_seconds: float,
    auth_coordinator: MiniserverAuthCoordinator | None = None,
) -> None:
    while True:
        await process_remote_revocations(endpoint, store, timeout_seconds, auth_coordinator)
        await asyncio.sleep(_POLL_SECONDS)
