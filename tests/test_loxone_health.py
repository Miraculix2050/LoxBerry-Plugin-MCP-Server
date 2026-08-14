from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.auth.loxone_health import (
    MAX_REJECTED_AUTHENTICATIONS,
    LoxoneTokenHealthStore,
)
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.client import LoxoneCommandRejected, LoxoneToken, MiniserverEndpoint
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable


def _store(tmp_path: Path) -> AtomicJsonAuthStore:
    store = AtomicJsonAuthStore((tmp_path / "auth" / "sessions.json").resolve())
    store.mutate(lambda document: document["families"].update({"family": {"revoked": False}}))
    return store


def test_rejected_authentication_requires_confirmation_and_success_resets(tmp_path: Path) -> None:
    health = LoxoneTokenHealthStore(_store(tmp_path))

    for expected in range(1, MAX_REJECTED_AUTHENTICATIONS):
        result = health.record_rejected_authentication("family")
        assert result.rejected_authentications == expected
        assert result.confirmation_required is False

    result = health.record_rejected_authentication("family")
    assert result.rejected_authentications == MAX_REJECTED_AUTHENTICATIONS
    assert result.confirmation_required is True
    assert health.confirm_retry("family") is True
    assert health.get("family").confirmation_required is False

    health.record_rejected_authentication("family")
    health.record_successful_authentication("family")
    assert health.get("family").rejected_authentications == 0


def test_confirmation_requires_a_blocked_active_family(tmp_path: Path) -> None:
    health = LoxoneTokenHealthStore(_store(tmp_path))

    assert health.confirm_retry("family") is False
    assert health.confirm_retry("missing") is False


def test_legacy_unclassified_rejections_are_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.mutate(
        lambda document: document["families"]["family"].update(
            {
                "loxone_token_confirmation_required": True,
                "loxone_token_rejections": MAX_REJECTED_AUTHENTICATIONS,
            }
        )
    )

    health = LoxoneTokenHealthStore(store)

    assert health.get("family").confirmation_required is False
    assert health.get("family").rejected_authentications == 0

    result = health.record_rejected_authentication("family")
    assert result.rejected_authentications == 1


@pytest.mark.asyncio
async def test_runtime_stops_token_login_attempts_until_admin_confirms(tmp_path: Path) -> None:
    health = LoxoneTokenHealthStore(_store(tmp_path))

    class TokenStore:
        def get(self, *_args: object) -> LoxoneToken:
            return LoxoneToken("jwt", "user", "key", "SHA256", 2_000_000_000)

    class RejectingClient:
        attempts = 0

        async def open_session(self, _token: LoxoneToken) -> object:
            self.attempts += 1
            raise LoxoneCommandRejected("rejected")

    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        TokenStore(),  # type: ignore[arg-type]
        token_health=health,
    )
    client = RejectingClient()
    runtime.client = client  # type: ignore[assignment]

    for _ in range(MAX_REJECTED_AUTHENTICATIONS):
        with pytest.raises(RuntimeUnavailable):
            await runtime.snapshot(access)
    assert client.attempts == MAX_REJECTED_AUTHENTICATIONS

    with pytest.raises(RuntimeUnavailable, match="administrator confirmation"):
        await runtime.snapshot(access)
    assert client.attempts == MAX_REJECTED_AUTHENTICATIONS

    assert health.confirm_retry("family") is True
    with pytest.raises(RuntimeUnavailable):
        await runtime.snapshot(access)
    assert client.attempts == MAX_REJECTED_AUTHENTICATIONS + 1


@pytest.mark.asyncio
async def test_runtime_does_not_count_a_miniserver_source_ip_block(tmp_path: Path) -> None:
    health = LoxoneTokenHealthStore(_store(tmp_path))

    class TokenStore:
        def get(self, *_args: object) -> LoxoneToken:
            return LoxoneToken("jwt", "user", "key", "SHA256", 2_000_000_000)

    class BlockedClient:
        async def open_session(self, _token: LoxoneToken) -> object:
            raise LoxoneCommandRejected("rejected", response_code="4003")

    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        TokenStore(),  # type: ignore[arg-type]
        token_health=health,
    )
    runtime.client = BlockedClient()  # type: ignore[assignment]

    with pytest.raises(RuntimeUnavailable, match="source IP"):
        await runtime.snapshot(access)

    assert health.get("family").rejected_authentications == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_code", "message"),
    [
        ("401", "unauthorized"),
        ("403", "insufficient rights"),
        ("423", "user is disabled"),
        ("429", "rate-limited"),
        ("500", "token authentication was rejected"),
    ],
)
async def test_runtime_reports_sanitized_token_rejection_reason(
    tmp_path: Path, response_code: str, message: str
) -> None:
    class TokenStore:
        def get(self, *_args: object) -> LoxoneToken:
            return LoxoneToken("jwt", "user", "key", "SHA256", 2_000_000_000)

    class RejectingClient:
        async def open_session(self, _token: LoxoneToken) -> object:
            raise LoxoneCommandRejected("rejected", response_code=response_code)

    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        TokenStore(),  # type: ignore[arg-type]
    )
    runtime.client = RejectingClient()  # type: ignore[assignment]

    with pytest.raises(RuntimeUnavailable, match=message):
        await runtime.snapshot(access)
