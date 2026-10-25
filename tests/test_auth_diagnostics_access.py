"""Read-only OAuth validation used by authentication diagnostics."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from mcpserver.auth.provider import Phase0OAuthProvider
from mcpserver.auth.store import AtomicJsonAuthStore

RESOURCE = "https://public.example/plugins/mcpserver/mcp"
REDIRECT = "http://127.0.0.1:9010/callback"


async def _authorized(tmp_path: Path) -> tuple[Phase0OAuthProvider, str, list[object]]:
    callbacks: list[object] = []
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "sessions.json"),
        issuer="https://public.example/plugins/mcpserver/oauth",
        resource=RESOURCE,
        clock=lambda: 1_800_000_000,
        on_family_ended=lambda *args: callbacks.append(args),
        on_family_expired=callbacks.append,
    )
    client = OAuthClientInformationFull(
        client_id="registered-app",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="loxone:read",
    )
    await provider.register_client(client)
    raw_code = provider.issue_authorization_code(
        client_id="registered-app",
        redirect_uri=REDIRECT,
        code_challenge="synthetic-challenge",
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None
    tokens = await provider.exchange_authorization_code(client, code)
    return provider, tokens.access_token, callbacks


@pytest.mark.asyncio
async def test_readonly_validation_preserves_unrelated_expired_families(tmp_path: Path) -> None:
    provider, token, callbacks = await _authorized(tmp_path)
    provider.store.mutate(
        lambda data: data["families"].update(
            {"expired": {"expires_at": 1, "client_id": "other-app"}}
        )
    )
    before = provider.store.path.read_bytes()
    access = await provider.load_access_token_readonly(token)
    assert access is not None
    assert access.client_id == "registered-app"
    assert access.identity_id == "identity"
    assert access.miniserver_id == "miniserver"
    assert provider.store.path.read_bytes() == before
    assert callbacks == []
    # The public OAuth provider retains its existing cleanup behavior.
    assert await provider.load_access_token(token) is not None
    assert "expired" not in provider.store.snapshot()["families"]
    assert callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("access_tokens", "status", "revoked"),
        ("access_tokens", "expires_at", 1_800_000_000),
        ("access_tokens", "resource", "https://other.example/mcp"),
        ("families", "revoked", True),
        ("families", "expires_at", 1_800_000_000),
        ("families", "client_id", "different-app"),
        ("families", "identity_id", "different-identity"),
        ("families", "miniserver_id", "different-miniserver"),
        ("families", "resource", "https://other.example/mcp"),
        ("families", "scope", ""),
    ],
)
async def test_readonly_validation_rejects_changed_authorization(
    tmp_path: Path, collection: str, field: str, value: Any
) -> None:
    provider, token, callbacks = await _authorized(tmp_path)
    access = await provider.load_access_token_readonly(token)
    assert access is not None
    key = (
        hashlib.sha256(token.encode()).hexdigest()
        if collection == "access_tokens"
        else access.family_id
    )
    provider.store.mutate(lambda data: data[collection][key].update({field: value}))
    before = provider.store.path.read_bytes()
    assert await provider.load_access_token_readonly(token) is None
    assert provider.store.path.read_bytes() == before
    assert callbacks == []


@pytest.mark.asyncio
async def test_transport_verifier_uses_readonly_validation(tmp_path: Path) -> None:
    from mcpserver.server import _Phase0TokenVerifier

    provider, token, callbacks = await _authorized(tmp_path)
    provider.store.mutate(
        lambda data: data["families"].update(
            {"expired": {"expires_at": 1, "client_id": "other-app"}}
        )
    )
    before = provider.store.path.read_bytes()
    assert await _Phase0TokenVerifier(provider).verify_token(token) is not None
    assert provider.store.path.read_bytes() == before
    assert callbacks == []
