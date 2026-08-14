from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.remote_revocation import process_remote_revocations
from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneSourceIpBlocked,
    LoxoneToken,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import LoxoneProtocolError


def _store(tmp_path: Path) -> EncryptedLoxoneTokenStore:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    return EncryptedLoxoneTokenStore((tmp_path / "tokens.json").resolve(), key.resolve())


def test_remote_revoke_keeps_token_after_failure_and_removes_it_after_success(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    store.put("family", "miniserver", "identity", LoxoneToken("jwt", "user", "key", "SHA256", 1))
    store.schedule_remote_revoke("family")

    class FailingClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            raise LoxoneProtocolError("failed")

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", FailingClient)
    endpoint = MiniserverEndpoint.parse_gen1("http://192.168.10.20")
    asyncio.run(process_remote_revocations(endpoint, store, 0.1))
    assert store.get("family", "miniserver", "identity") is not None

    class SuccessfulClient(FailingClient):
        async def kill_token(self, _token: LoxoneToken) -> None:
            pass

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", SuccessfulClient)
    store.defer_remote_revoke("family", -10)
    asyncio.run(process_remote_revocations(endpoint, store, 0.1))
    assert store.get("family", "miniserver", "identity") is None


@pytest.mark.parametrize(
    "error",
    [
        LoxoneCommandRejected("rejected", response_code="401"),
        LoxoneSourceIpBlocked("blocked"),
    ],
)
def test_remote_revoke_authentication_failures_suspend_all_pending_attempts(
    tmp_path: Path, monkeypatch, error: Exception
) -> None:
    store = _store(tmp_path)
    for family_id in ("first", "second"):
        store.put(
            family_id,
            "miniserver",
            "identity",
            LoxoneToken("jwt", "user", "key", "SHA256", 1),
        )
        store.schedule_remote_revoke(family_id)
    calls: list[str] = []

    class RejectingClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def kill_token(self, _token: LoxoneToken) -> None:
            calls.append("attempt")
            raise error

    monkeypatch.setattr("mcpserver.auth.remote_revocation.LoxoneClient", RejectingClient)
    monkeypatch.setattr("mcpserver.auth.remote_revocation.time.time", lambda: 100)
    endpoint = MiniserverEndpoint.parse_gen1("http://192.168.10.20")
    asyncio.run(process_remote_revocations(endpoint, store, 100))

    assert calls == ["attempt"]
    assert store.pending_remote_revocations(3_699) == ()
    assert [item.family_id for item in store.pending_remote_revocations(3_700)] == [
        "first",
        "second",
    ]
