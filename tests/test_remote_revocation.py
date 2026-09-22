from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.remote_revocation import (
    RemoteRevocationState,
    RemoteRevocationStateError,
    process_remote_revocations,
)
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneSourceIpBlocked,
    LoxoneToken,
    LoxoneTokenAuthenticationRejected,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import LoxoneProtocolError

_EPOCH = 1_230_768_000
_ENDPOINT = MiniserverEndpoint.parse_gen1("http://192.168.10.20")


def _store(tmp_path: Path) -> EncryptedLoxoneTokenStore:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    return EncryptedLoxoneTokenStore((tmp_path / "tokens.json").resolve(), key.resolve())


def _queue(store: EncryptedLoxoneTokenStore, family: str, now: int, lifetime: int = 3600) -> None:
    store.put(
        family,
        "miniserver",
        "identity",
        LoxoneToken("jwt", "user", "key", "SHA256", now - _EPOCH + lifetime),
    )
    store.schedule_remote_revoke(family)


def test_rejected_token_is_terminal_and_staggers_other_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _queue(store, "first", 2_000_000_000)
    _queue(store, "second", 2_000_000_000)
    calls = 0

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            nonlocal calls
            calls += 1
            raise LoxoneTokenAuthenticationRejected("rejected", response_code="401")

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: 2_000_000_000)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))

    status = RemoteRevocationState(store.path).summary(store, 2_000_000_000)
    assert calls == 1
    assert store.get("first", "miniserver", "identity") is None
    assert status["pending"] == 1
    assert status["not_before"] == 2_000_003_600
    assert status["unconfirmed"] == 0
    assert "jwt" not in RemoteRevocationState(store.path).path.read_text()
    assert "first" not in RemoteRevocationState(store.path).path.read_text()
    assert RemoteRevocationState(store.path).read()["tombstones"][0]["expires_at"] == (
        2_000_000_000 + 30 * 86_400
    )


def test_new_and_staggered_items_cannot_bypass_queue_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    now = [2_000_000_000]
    _queue(store, "first", now[0])
    calls = 0

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            nonlocal calls
            calls += 1
            raise LoxoneTokenAuthenticationRejected("rejected", response_code="401")

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: now[0])
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    _queue(store, "new", now[0])
    _queue(store, "staggered", now[0])
    store.defer_remote_revoke("staggered", now[0])
    now[0] += 10
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    assert calls == 1
    assert store.remote_revocation_counts(now[0])[0] == 2


def test_status_reports_earliest_record_retry_when_queue_cooldown_has_ended(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    now = 2_000_000_000
    _queue(store, "later", now)
    store.reserve_remote_revoke_attempt("later", now + 600)
    status = RemoteRevocationState(store.path).summary(store, now)
    assert status["pending"] == 1
    assert status["retryable"] == 1
    assert status["not_before"] == now + 600


@pytest.mark.parametrize(
    "error",
    [
        LoxoneCommandRejected("killtoken rejected", response_code="401"),
        LoxoneSourceIpBlocked("blocked"),
        LoxoneProtocolError("bad response"),
        TimeoutError(),
    ],
)
def test_uncertain_outcomes_stop_after_five_network_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    store = _store(tmp_path)
    now = 2_000_000_000
    _queue(store, "family", now, lifetime=1_000_000)
    clock = [now]
    calls = 0

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            nonlocal calls
            calls += 1
            raise error

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: clock[0])
    for _ in range(5):
        asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
        clock[0] += 90_000
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))

    assert calls == 5
    assert store.get("family", "miniserver", "identity") is None
    assert RemoteRevocationState(store.path).summary(store, clock[0])["unconfirmed"] == 1


def test_success_and_nominal_expiry_have_distinct_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    now = 2_000_000_000
    _queue(store, "success", now)
    store.put(
        "expired",
        "miniserver",
        "identity",
        LoxoneToken("jwt", "user", "key", "SHA256", now - _EPOCH - 1),
    )
    store.schedule_remote_revoke("expired")
    calls = 0

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            nonlocal calls
            calls += 1

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: now)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    assert calls == 1
    assert store.remote_revocation_counts(now) == (0, 0, None)
    totals = RemoteRevocationState(store.path).read()["totals"]
    assert totals["confirmed_killed"] == 1
    assert totals["expired_without_confirmation"] == 1


def test_corrupt_status_fail_closes_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _queue(store, "family", 2_000_000_000)
    state = RemoteRevocationState(store.path)
    state.path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: 2_000_000_000)

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("network must not be used")

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    with pytest.raises(RemoteRevocationStateError):
        state.read()
    assert store.remote_revocation_counts(2_000_000_000)[0] == 1


def test_failed_post_attempt_status_write_preserves_attempt_and_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    now = 2_000_000_000
    _queue(store, "family", now)
    calls = 0
    writes = 0
    original_write = RemoteRevocationState.write

    def flaky_write(self: RemoteRevocationState, value: dict[str, object]) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RemoteRevocationStateError("disk unavailable")
        original_write(self, value)

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            nonlocal calls
            calls += 1
            raise TimeoutError()

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    monkeypatch.setattr(RemoteRevocationState, "write", flaky_write)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: now)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1))
    assert calls == 1
    item = store.pending_remote_revocations(now + 300)[0]
    assert item.attempts == 1
    assert item.retry_after == now + 300


def test_open_breaker_prevents_cleanup_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _queue(store, "family", int(time.time()))
    coordinator = MiniserverAuthCoordinator(
        tmp_path / "auth-status.json", initial_probe_seconds=300
    )

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        asyncio.run(coordinator.attempt(blocked, owner="local_admin", phase="token_acquisition"))

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("cleanup must not probe an open breaker")

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", Client)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1, coordinator))
    assert store.remote_revocation_counts(int(time.time()))[0] == 1


def test_coordinator_suppression_does_not_consume_network_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    now = 2_000_000_000
    _queue(store, "family", now)
    coordinator = MiniserverAuthCoordinator(tmp_path / "auth-status.json")

    async def suppress(*_args: object, **_kwargs: object) -> None:
        raise MiniserverAuthenticationSuppressed("suppressed")

    monkeypatch.setattr(coordinator, "attempt", suppress)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: now)
    asyncio.run(process_remote_revocations(_ENDPOINT, store, 1, coordinator))
    assert store.pending_remote_revocations(now + 300)[0].attempts == 0
