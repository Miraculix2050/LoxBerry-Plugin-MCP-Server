from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.server.auth.provider import RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    EXPLORER_CLIENT_NAME,
    EXPLORER_REFRESH_FAMILY_TTL,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
    REFRESH_FAMILY_TTL,
    SCOPE,
    Phase0OAuthProvider,
    normalize_scopes,
)
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.auth.web import LoginTransaction, Phase0OAuthWeb, _limited_body
from mcpserver.loxone.client import (
    LoxoneConnectionError,
    LoxoneToken,
    MiniserverEndpoint,
    ProbeResult,
)
from mcpserver.loxone.events import LoxoneProtocolError

ISSUER = "https://public.example/plugins/mcpserver/oauth"
RESOURCE = "https://public.example/plugins/mcpserver/mcp"


def test_control_scope_is_additive_and_never_granted_alone() -> None:
    assert normalize_scopes(None, control_enabled=False) == (READ_SCOPE,)
    assert normalize_scopes(f"{CONTROL_SCOPE} {READ_SCOPE}", control_enabled=False) == (
        READ_SCOPE,
        CONTROL_SCOPE,
    )
    with pytest.raises(ValueError):
        normalize_scopes(CONTROL_SCOPE, control_enabled=True)


def test_loxberry_scope_is_additive_and_requestable_before_approval() -> None:
    assert normalize_scopes(
        f"{LOXBERRY_READ_SCOPE} {READ_SCOPE}",
        control_enabled=False,
        loxberry_read_enabled=False,
    ) == (READ_SCOPE, LOXBERRY_READ_SCOPE)
    with pytest.raises(ValueError):
        normalize_scopes(LOXBERRY_READ_SCOPE, control_enabled=False, loxberry_read_enabled=True)


def test_phase_four_scopes_are_additive_canonical_and_requestable_before_enablement() -> None:
    value = f"{LOXBERRY_OPERATE_SCOPE} {READ_SCOPE} {HISTORY_SCOPE}"
    assert normalize_scopes(
        value,
        control_enabled=False,
        history_enabled=False,
        loxberry_operate_enabled=False,
    ) == (READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE)
    assert normalize_scopes(
        f"{READ_SCOPE} {HISTORY_SCOPE}",
        control_enabled=False,
    ) == (READ_SCOPE, HISTORY_SCOPE)
    with pytest.raises(ValueError):
        normalize_scopes(
            f"{READ_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
            control_enabled=False,
            loxberry_operate_enabled=True,
        )


@pytest.mark.asyncio
async def test_loxberry_authorization_code_requires_local_binding(tmp_path: Path) -> None:
    allowed = False
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        loxberry_read_enabled=True,
        loxberry_read_allowed=lambda client, identity, miniserver: allowed,
    )
    client = OAuthClientInformationFull(
        client_id="diagnostic-client",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
    )
    await provider.register_client(client)
    with pytest.raises(TokenError, match="local approval"):
        provider.issue_authorization_code(
            client_id="diagnostic-client",
            redirect_uri=REDIRECT,
            code_challenge=CHALLENGE,
            resource=RESOURCE,
            identity_id="identity",
            miniserver_id="miniserver",
            scopes=(READ_SCOPE, LOXBERRY_READ_SCOPE),
        )
    allowed = True
    assert provider.issue_authorization_code(
        client_id="diagnostic-client",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
        scopes=(READ_SCOPE, LOXBERRY_READ_SCOPE),
    )


@pytest.mark.asyncio
async def test_loxberry_operate_authorization_code_requires_separate_local_binding(
    tmp_path: Path,
) -> None:
    allowed = False
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        history_enabled=True,
        loxberry_operate_enabled=True,
        loxberry_operate_allowed=lambda *_: allowed,
    )
    client = OAuthClientInformationFull(
        client_id="operate-client",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
    )
    await provider.register_client(client)
    kwargs = {
        "client_id": "operate-client",
        "redirect_uri": REDIRECT,
        "code_challenge": CHALLENGE,
        "resource": RESOURCE,
        "identity_id": "identity",
        "miniserver_id": "miniserver",
        "scopes": (READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE),
    }
    with pytest.raises(TokenError, match="local approval"):
        provider.issue_authorization_code(**kwargs)  # type: ignore[arg-type]
    allowed = True
    assert provider.issue_authorization_code(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_pending_loxberry_request_keeps_granted_control_scope(tmp_path: Path) -> None:
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        control_enabled=True,
        loxberry_read_enabled=True,
        loxberry_read_allowed=lambda *_: False,
    )
    client = OAuthClientInformationFull(
        client_id="pending-client",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {CONTROL_SCOPE} {LOXBERRY_READ_SCOPE}",
    )
    await provider.register_client(client)

    provider.issue_authorization_code(
        client_id="pending-client",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
        scopes=(READ_SCOPE, CONTROL_SCOPE, LOXBERRY_READ_SCOPE),
        pending_loxberry_read=True,
    )
    family = next(iter(provider.store.snapshot()["families"].values()))
    assert family["scope"] == f"{READ_SCOPE} {CONTROL_SCOPE} {LOXBERRY_READ_SCOPE}"
    assert family["pending_loxberry_read"] is True


def test_disabled_control_scope_is_locally_revoked_without_deleting_remote_token(
    tmp_path: Path,
) -> None:
    deleted: list[str] = []
    store = AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json")
    provider = Phase0OAuthProvider(
        store,
        issuer=ISSUER,
        resource=RESOURCE,
        on_family_revoked=deleted.append,
    )

    def add_control_family(document: dict[str, object]) -> None:
        families = document["families"]
        access_tokens = document["access_tokens"]
        assert isinstance(families, dict)
        assert isinstance(access_tokens, dict)
        families["family"] = {
            "scope": f"{READ_SCOPE} {CONTROL_SCOPE}",
            "revoked": False,
        }
        access_tokens["access"] = {"family_id": "family", "status": "active"}

    store.mutate(add_control_family)

    assert provider.revoke_scope_locally(CONTROL_SCOPE) == 1
    snapshot = store.snapshot()
    assert snapshot["families"]["family"]["revoked"] is True
    assert snapshot["access_tokens"]["access"]["status"] == "revoked"
    assert deleted == []


REDIRECT = "http://127.0.0.1:48765/callback"
EXPLORER_REDIRECT = "https://public.example/admin/plugins/mcpserver/explorer_callback.cgi"
VERIFIER = "v" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


class Clock:
    def __init__(self) -> None:
        self.value = 1_800_000_000

    def __call__(self) -> float:
        return float(self.value)


def _provider(
    tmp_path: Path,
    clock: Clock | None = None,
    *,
    explorer_origins: tuple[str, ...] = (),
) -> Phase0OAuthProvider:
    return Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=clock or Clock(),
        explorer_origins=explorer_origins,
    )


async def _client(provider: Phase0OAuthProvider) -> OAuthClientInformationFull:
    client = OAuthClientInformationFull(
        client_id="public-client",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=SCOPE,
    )
    await provider.register_client(client)
    return client


@pytest.mark.asyncio
async def test_control_scope_survives_code_exchange_and_refresh(tmp_path: Path) -> None:
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        control_enabled=True,
    )
    scopes = (READ_SCOPE, CONTROL_SCOPE)
    client = OAuthClientInformationFull(
        client_id="control-client",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(scopes),
    )
    await provider.register_client(client)
    raw_code = provider.issue_authorization_code(
        client_id="control-client",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
        scopes=scopes,
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None

    first = await provider.exchange_authorization_code(client, code)
    access = await provider.load_access_token(first.access_token)
    refresh = await provider.load_refresh_token(client, first.refresh_token or "")
    assert access is not None and access.scopes == list(scopes)
    assert refresh is not None

    rotated = await provider.exchange_refresh_token(client, refresh, list(scopes))

    assert rotated.scope == " ".join(scopes)


def _client_info(
    client_id: str,
    *,
    grants: list[str] | None = None,
    client_name: str | None = None,
    redirect_uri: str = REDIRECT,
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_id_issued_at=1_800_000_000,
        client_name=client_name,
        redirect_uris=[AnyUrl(redirect_uri)],
        token_endpoint_auth_method="none",
        grant_types=grants or ["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=SCOPE,
    )


@pytest.mark.asyncio
async def test_explorer_client_gets_shorter_refresh_family_lifetime(tmp_path: Path) -> None:
    clock = Clock()
    provider = _provider(tmp_path, clock, explorer_origins=("https://loxberry-alias",))
    explorer = _client_info(
        "explorer-client",
        client_name=EXPLORER_CLIENT_NAME,
        redirect_uri=EXPLORER_REDIRECT,
    )
    regular = _client_info("regular-client", client_name=EXPLORER_CLIENT_NAME)
    alias_redirect = "https://loxberry-alias/admin/plugins/mcpserver/explorer_callback.cgi"
    alias = _client_info(
        "alias-explorer-client",
        client_name=EXPLORER_CLIENT_NAME,
        redirect_uri=alias_redirect,
    )
    await provider.register_client(explorer)
    await provider.register_client(regular)
    await provider.register_client(alias)

    common = {
        "code_challenge": CHALLENGE,
        "resource": RESOURCE,
        "identity_id": "identity",
        "miniserver_id": "miniserver",
    }
    provider.issue_authorization_code(
        client_id="explorer-client",
        family_id="explorer-family",
        redirect_uri=EXPLORER_REDIRECT,
        **common,
    )
    provider.issue_authorization_code(
        client_id="regular-client",
        family_id="regular-family",
        redirect_uri=REDIRECT,
        **common,
    )
    provider.issue_authorization_code(
        client_id="alias-explorer-client",
        family_id="alias-explorer-family",
        redirect_uri=alias_redirect,
        **common,
    )

    families = provider.store.snapshot()["families"]
    assert families["explorer-family"]["expires_at"] == clock.value + EXPLORER_REFRESH_FAMILY_TTL
    assert families["regular-family"]["expires_at"] == clock.value + REFRESH_FAMILY_TTL
    assert (
        families["alias-explorer-family"]["expires_at"] == clock.value + EXPLORER_REFRESH_FAMILY_TTL
    )

    def restore_legacy_lifetime(document: dict[str, Any]) -> None:
        document["families"]["explorer-family"]["expires_at"] = clock.value + REFRESH_FAMILY_TTL
        document["families"]["explorer-family"].pop("client_kind")

    provider.store.mutate(restore_legacy_lifetime)
    Phase0OAuthProvider(
        provider.store,
        issuer=ISSUER,
        resource=RESOURCE,
        clock=clock,
    )
    assert (
        provider.store.snapshot()["families"]["explorer-family"]["expires_at"]
        == clock.value + EXPLORER_REFRESH_FAMILY_TTL
    )


@pytest.mark.asyncio
async def test_limited_body_rejects_negative_and_oversized_streams() -> None:
    negative = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"content-length", b"-1")]}
    )
    assert await _limited_body(negative, 4) is None

    messages = iter(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
    )

    async def receive() -> dict[str, object]:
        return next(messages)

    streamed = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
    assert await _limited_body(streamed, 4) is None


@pytest.mark.asyncio
async def test_registration_capacity_returns_protocol_error_and_prunes_old_clients(
    tmp_path: Path,
) -> None:
    clock = Clock()
    provider = _provider(tmp_path, clock)
    template = _client_info("template").model_dump(mode="json", exclude_none=True)

    def fill(document: dict[str, object]) -> None:
        clients = document["clients"]
        assert isinstance(clients, dict)
        for index in range(256):
            clients[f"old-{index}"] = {**template, "client_id": f"old-{index}"}

    provider.store.mutate(fill)
    with pytest.raises(RegistrationError, match="capacity"):
        await provider.register_client(_client_info("overflow"))

    clock.value += 24 * 60 * 60 + 1
    await provider.register_client(_client_info("replacement"))
    assert set(provider.store.snapshot()["clients"]) == {"replacement"}


@pytest.mark.asyncio
async def test_registration_requires_authorization_code_and_refresh_grants(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(RegistrationError, match="Unsupported"):
        await provider.register_client(_client_info("refresh-only", grants=["refresh_token"]))


@pytest.mark.asyncio
async def test_stale_unused_client_is_removed_before_authorization_starts(tmp_path: Path) -> None:
    clock = Clock()
    provider = _provider(tmp_path, clock)
    client = _client_info("stale-client")
    await provider.register_client(client)

    clock.value += 24 * 60 * 60 + 1

    assert await provider.get_client("stale-client") is None
    with pytest.raises(TokenError, match="registration"):
        provider.issue_authorization_code(
            client_id="stale-client",
            redirect_uri=REDIRECT,
            code_challenge=CHALLENGE,
            resource=RESOURCE,
            identity_id="identity",
            miniserver_id="miniserver",
        )


@pytest.mark.asyncio
async def test_code_access_and_refresh_values_are_never_persisted(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    client = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity-pseudonym",
        miniserver_id="miniserver-pseudonym",
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None

    token = await provider.exchange_authorization_code(client, code)
    serialized = provider.store.path.read_text(encoding="utf-8")

    assert raw_code not in serialized
    assert token.access_token not in serialized
    assert token.refresh_token is not None
    assert token.refresh_token not in serialized
    access = await provider.load_access_token(token.access_token)
    assert access is not None
    assert access.resource == RESOURCE
    assert access.claims == {
        "iss": ISSUER,
        "identity": "identity-pseudonym",
        "miniserver": "miniserver-pseudonym",
        "audience": RESOURCE,
    }


@pytest.mark.asyncio
async def test_refresh_replay_revokes_the_entire_family(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    client = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None
    first = await provider.exchange_authorization_code(client, code)
    assert first.refresh_token is not None
    refresh = await provider.load_refresh_token(client, first.refresh_token)
    assert refresh is not None
    second = await provider.exchange_refresh_token(client, refresh, [SCOPE])

    assert await provider.load_refresh_token(client, first.refresh_token) is None
    assert await provider.load_access_token(first.access_token) is None
    assert await provider.load_access_token(second.access_token) is None
    assert second.refresh_token is not None
    assert await provider.load_refresh_token(client, second.refresh_token) is None


@pytest.mark.asyncio
async def test_expired_code_and_access_token_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    provider = _provider(tmp_path, clock)
    client = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    clock.value += 301
    assert await provider.load_authorization_code(client, raw_code) is None


def _web_app(
    provider: Phase0OAuthProvider, explorer_store: EncryptedLoxoneTokenStore | None = None
) -> Starlette:
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
        loxone_store=explorer_store,
    )
    return Starlette(
        routes=[
            Route("/register", web.register, methods=["POST"]),
            Route("/authorize", web.authorize, methods=["GET", "POST"]),
            Route("/token", web.token, methods=["POST"]),
            Route("/revoke", web.revoke, methods=["POST"]),
            Route("/explorer-session", web.explorer_session, methods=["POST"]),
            Route("/metadata", web.authorization_metadata, methods=["GET"]),
        ]
    )


def test_explorer_session_cookie_reuses_one_oauth_family_and_logout_revokes_it(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    client_info = _client_info(
        "explorer-client", client_name=EXPLORER_CLIENT_NAME, redirect_uri=EXPLORER_REDIRECT
    )
    asyncio.run(provider.register_client(client_info))
    code = provider.issue_authorization_code(
        client_id="explorer-client",
        redirect_uri=EXPLORER_REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    encrypted = EncryptedLoxoneTokenStore((tmp_path / "tokens.json").resolve(), key.resolve())
    headers = {"Origin": "https://public.example"}
    with TestClient(_web_app(provider, encrypted), base_url="https://public.example") as browser:
        complete = browser.post(
            "/explorer-session",
            headers=headers,
            json={
                "action": "complete",
                "client_id": "explorer-client",
                "code": code,
                "redirect_uri": EXPLORER_REDIRECT,
                "code_verifier": VERIFIER,
                "resource": RESOURCE,
            },
        )
        session_headers = {**headers, "Cookie": complete.headers["set-cookie"].split(";", 1)[0]}
        reused = browser.post(
            "/explorer-session", headers=session_headers, json={"action": "access"}
        )
        logout = browser.post(
            "/explorer-session", headers=session_headers, json={"action": "logout"}
        )

    assert complete.status_code == 200
    assert "Secure" in complete.headers["set-cookie"]
    assert "HttpOnly" in complete.headers["set-cookie"]
    assert "SameSite=strict" in complete.headers["set-cookie"]
    assert reused.status_code == 200
    assert reused.json()["access_token"] == complete.json()["access_token"]
    assert logout.status_code == 204
    assert next(iter(provider.store.snapshot()["families"].values()))["revoked"] is True


def test_explorer_session_rejects_cross_origin_requests(tmp_path: Path) -> None:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    encrypted = EncryptedLoxoneTokenStore((tmp_path / "tokens.json").resolve(), key.resolve())
    with TestClient(_web_app(_provider(tmp_path), encrypted)) as browser:
        response = browser.post(
            "/explorer-session",
            headers={"Origin": "https://attacker.example"},
            json={"action": "access"},
        )

    assert response.status_code == 400


def test_explorer_session_accepts_configured_origin_alias(tmp_path: Path) -> None:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    encrypted = EncryptedLoxoneTokenStore((tmp_path / "tokens.json").resolve(), key.resolve())
    provider = _provider(tmp_path, explorer_origins=("https://loxberry-alias",))
    with TestClient(_web_app(provider, encrypted), base_url="https://loxberry-alias") as browser:
        response = browser.post(
            "/explorer-session",
            headers={"Origin": "https://loxberry-alias"},
            json={"action": "access"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_session"}


def _registration_payload() -> dict[str, object]:
    return {
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "Phase zero client",
    }


def _authorize_parameters(client_id: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "scope": SCOPE,
        "resource": RESOURCE,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "client-state",
    }


def test_metadata_advertises_all_requestable_scopes(tmp_path: Path) -> None:
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.get("/metadata")

    assert response.status_code == 200
    assert response.json()["issuer"] == ISSUER
    assert response.json()["token_endpoint_auth_methods_supported"] == ["none"]
    assert response.json()["scopes_supported"] == [
        READ_SCOPE,
        HISTORY_SCOPE,
        CONTROL_SCOPE,
        LOXBERRY_READ_SCOPE,
        LOXBERRY_OPERATE_SCOPE,
    ]
    assert response.json()["code_challenge_methods_supported"] == ["S256"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "strict-origin"


def test_consent_page_uses_one_permission_dialog_for_read_and_control(tmp_path: Path) -> None:
    web = Phase0OAuthWeb(
        _provider(tmp_path),
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    transaction = LoginTransaction(
        transaction_id="transaction",
        csrf_token="csrf",
        client_id="client",
        client_name="Claude Code",
        redirect_uri=REDIRECT,
        state="state",
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        created_at=1_800_000_000,
        scopes=(READ_SCOPE, CONTROL_SCOPE),
        identity_name="user",
        miniserver_name="miniserver",
    )

    response = web._consent_page(transaction)

    assert response.status_code == 200
    assert "Choose permissions / Berechtigungen auswählen" in response.body.decode()
    assert 'type="checkbox" checked disabled' in response.body.decode()
    assert 'name="grant_control" value="true"' in response.body.decode()
    assert "Confirm permissions / Berechtigungen bestätigen" in response.body.decode()
    assert "redirected to your MCP client" in response.body.decode()


@pytest.mark.asyncio
async def test_locally_approved_operate_scope_still_requires_current_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        history_enabled=True,
        loxberry_operate_enabled=True,
        loxberry_operate_allowed=lambda *_: True,
    )
    client_info = OAuthClientInformationFull(
        client_id="operate-client",
        client_name="MCP Tool Explorer",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
    )
    await provider.register_client(client_info)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    transaction = LoginTransaction(
        transaction_id="transaction",
        csrf_token="csrf",
        client_id="operate-client",
        client_name="MCP Tool Explorer",
        redirect_uri=REDIRECT,
        state="client-state",
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        created_at=provider.now(),
        scopes=(READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE),
        identity_id="identity",
        miniserver_id="miniserver",
        loxberry_operate_locally_approved=True,
        phase="consent",
    )
    web.transactions[transaction.transaction_id] = transaction

    async def kill_token(selected: LoginTransaction) -> bool:
        selected.loxone_token = None
        return True

    monkeypatch.setattr(web, "_kill", kill_token)
    assert (
        'name="grant_loxberry_operate" value="true"' in web._consent_page(transaction).body.decode()
    )
    app = Starlette(routes=[Route("/authorize", web.authorize, methods=["POST"])])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://public.example",
        follow_redirects=False,
        headers={"Cookie": "phase0_oauth_tx=transaction"},
    ) as client:
        approved = await client.post(
            "/authorize",
            data={"csrf": "csrf", "action": "approve", "grant_history": "true"},
        )

    code_value = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
    code = await provider.load_authorization_code(client_info, code_value)
    assert approved.status_code == 302
    assert code is not None
    assert code.scopes == [READ_SCOPE, HISTORY_SCOPE]


@pytest.mark.parametrize(
    ("grant_control", "expected_scopes"),
    [
        (False, [READ_SCOPE]),
        (True, [READ_SCOPE, CONTROL_SCOPE]),
    ],
)
@pytest.mark.asyncio
async def test_consent_issues_only_the_scopes_selected_by_the_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    grant_control: bool,
    expected_scopes: list[str],
) -> None:
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        control_enabled=True,
    )
    client_info = OAuthClientInformationFull(
        client_id="control-client",
        client_name="Claude Code",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {CONTROL_SCOPE}",
    )
    await provider.register_client(client_info)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    transaction = LoginTransaction(
        transaction_id="transaction",
        csrf_token="csrf",
        client_id="control-client",
        client_name="Claude Code",
        redirect_uri=REDIRECT,
        state="client-state",
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        created_at=provider.now(),
        scopes=(READ_SCOPE, CONTROL_SCOPE),
        identity_id="identity",
        miniserver_id="miniserver",
        phase="consent",
    )
    web.transactions[transaction.transaction_id] = transaction

    async def kill_token(selected: LoginTransaction) -> bool:
        selected.loxone_token = None
        return True

    monkeypatch.setattr(web, "_kill", kill_token)
    app = Starlette(routes=[Route("/authorize", web.authorize, methods=["POST"])])
    data = {"csrf": "csrf", "action": "approve"}
    if grant_control:
        data["grant_control"] = "true"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://public.example",
        follow_redirects=False,
        headers={"Cookie": "phase0_oauth_tx=transaction"},
    ) as client:
        approved = await client.post("/authorize", data=data)

    code_value = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
    code = await provider.load_authorization_code(client_info, code_value)
    assert approved.status_code == 302
    assert code is not None
    assert code.scopes == expected_scopes


@pytest.mark.asyncio
async def test_pending_loxberry_consent_issues_scope_without_local_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        loxberry_read_enabled=True,
        loxberry_read_allowed=lambda *_: False,
    )
    client_info = OAuthClientInformationFull(
        client_id="diagnostic-client",
        client_name="MCP Tool Explorer",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
    )
    await provider.register_client(client_info)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    transaction = LoginTransaction(
        transaction_id="transaction",
        csrf_token="csrf",
        client_id="diagnostic-client",
        client_name="MCP Tool Explorer",
        redirect_uri=REDIRECT,
        state="client-state",
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        created_at=provider.now(),
        scopes=(READ_SCOPE, LOXBERRY_READ_SCOPE),
        identity_id="identity",
        miniserver_id="miniserver",
        phase="consent",
    )
    web.transactions[transaction.transaction_id] = transaction

    async def kill_token(selected: LoginTransaction) -> bool:
        selected.loxone_token = None
        return True

    monkeypatch.setattr(web, "_kill", kill_token)
    app = Starlette(routes=[Route("/authorize", web.authorize, methods=["POST"])])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://public.example",
        follow_redirects=False,
        headers={"Cookie": "phase0_oauth_tx=transaction"},
    ) as client:
        approved = await client.post(
            "/authorize",
            data={"csrf": "csrf", "action": "approve", "grant_loxberry": "true"},
        )

    code_value = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
    code = await provider.load_authorization_code(client_info, code_value)
    family = next(iter(provider.store.snapshot()["families"].values()))
    assert approved.status_code == 302
    assert code is not None
    assert code.scopes == [READ_SCOPE, LOXBERRY_READ_SCOPE]
    assert family["pending_loxberry_read"] is True


@pytest.mark.parametrize(
    "redirect",
    [
        "http://client.example/callback",
        "ftp://127.0.0.1/callback",
        "http://user@127.0.0.1/callback",
        "http://127.0.0.1/callback#fragment",
        "http://127.0.0.1/callback?state=attacker",
    ],
)
def test_registration_rejects_unsafe_redirects(tmp_path: Path, redirect: str) -> None:
    payload = {
        "redirect_uris": [redirect],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_registration_normalizes_public_client_scope(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with TestClient(_web_app(provider)) as client:
        response = client.post("/register", json=_registration_payload())

    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == "none"
    assert response.json()["scope"] == SCOPE
    assert "client_secret" not in response.json()


def test_registration_normalizes_omitted_public_auth_method(tmp_path: Path) -> None:
    payload = _registration_payload()
    payload.pop("token_endpoint_auth_method")
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in response.json()


@pytest.mark.parametrize("application_type", ["native", "web"])
def test_registration_accepts_standard_application_type(
    tmp_path: Path, application_type: str
) -> None:
    payload = {**_registration_payload(), "application_type": application_type}
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == "none"


def test_registration_rejects_unknown_application_type(tmp_path: Path) -> None:
    payload = {**_registration_payload(), "application_type": "service"}
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_registration_rejects_another_scope(tmp_path: Path) -> None:
    payload = {**_registration_payload(), "scope": "loxone:control"}
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_registration_rejects_refresh_only_metadata(tmp_path: Path) -> None:
    payload = {**_registration_payload(), "grant_types": ["refresh_token"]}
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_invalid_registration_requests_do_not_consume_valid_client_quota(tmp_path: Path) -> None:
    with TestClient(_web_app(_provider(tmp_path))) as client:
        invalid = [
            client.post("/register", content=b"invalid", headers={"Content-Type": "text/plain"})
            for _ in range(20)
        ]
        valid = client.post("/register", json=_registration_payload())

    assert all(response.status_code == 400 for response in invalid)
    assert valid.status_code == 201


def test_authorize_uses_secure_cookie_csrf_and_exact_resource(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with TestClient(_web_app(provider), follow_redirects=False) as client:
        registration = client.post("/register", json=_registration_payload())
        parameters = _authorize_parameters(registration.json()["client_id"])
        start = client.get("/authorize", params=parameters)
        wrong_resource = client.get(
            "/authorize",
            params={**parameters, "resource": "https://other.example/mcp"},
        )

    assert start.status_code == 200
    csp = start.headers["content-security-policy"]
    assert "form-action 'self' http://127.0.0.1:48765" in csp
    assert "/callback" not in csp
    cookie = start.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/plugins/mcpserver/oauth/authorize" in cookie
    assert 'name="csrf"' in start.text
    assert "client-state" not in start.text
    assert wrong_resource.status_code == 302
    assert "error=invalid_request" in wrong_resource.headers["location"]
    assert "state=client-state" in wrong_resource.headers["location"]
    assert (
        "iss=https%3A%2F%2Fpublic.example%2Fplugins%2Fmcpserver%2Foauth"
        in wrong_resource.headers["location"]
    )


def test_authorize_bounds_concurrent_login_transactions(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with TestClient(_web_app(provider), follow_redirects=False) as client:
        registration = client.post("/register", json=_registration_payload())
        parameters = _authorize_parameters(registration.json()["client_id"])
        accepted = [client.get("/authorize", params=parameters) for _ in range(16)]
        rejected = client.get("/authorize", params=parameters)

    assert all(response.status_code == 200 for response in accepted)
    assert rejected.status_code == 503


def test_login_rate_limit_survives_new_authorization_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )

    class FailingLoxoneClient:
        def __init__(self, endpoint: object, *, client_uuid: object) -> None:
            pass

        async def probe(self) -> ProbeResult:
            raise RuntimeError("unavailable")

    monkeypatch.setattr("mcpserver.auth.web.LoxoneClient", FailingLoxoneClient)
    app = Starlette(
        routes=[
            Route("/register", web.register, methods=["POST"]),
            Route("/authorize", web.authorize, methods=["GET", "POST"]),
        ]
    )
    with TestClient(app, follow_redirects=False) as client:
        results = []
        for _ in range(6):
            registration = client.post("/register", json=_registration_payload())
            parameters = _authorize_parameters(registration.json()["client_id"])
            client.cookies.clear()
            client.get("/authorize", params=parameters)
            transaction = next(reversed(web.transactions.values()))
            results.append(
                client.post(
                    "/authorize",
                    headers={"Cookie": f"phase0_oauth_tx={transaction.transaction_id}"},
                    data={
                        "csrf": transaction.csrf_token,
                        "action": "login",
                        "username": "same-user",
                        "password": "wrong-password",
                    },
                )
            )

    assert [response.status_code for response in results] == [200, 200, 200, 200, 200, 429]


@pytest.mark.asyncio
async def test_parallel_login_posts_acquire_only_one_loxone_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    acquired: list[LoxoneToken] = []

    class FakeSession:
        async def load_structure(self) -> object:
            await asyncio.sleep(0.01)
            return SimpleNamespace(identity=SimpleNamespace(username="parallel-user"))

        async def close(self) -> None:
            return None

    class FakeLoxoneClient:
        def __init__(self, endpoint: object, *, client_uuid: object) -> None:
            pass

        async def probe(self) -> ProbeResult:
            return ProbeResult("17.1.7.27", "serial", True, True)

        async def acquire_token(self, username: str, password: str) -> LoxoneToken:
            token = LoxoneToken(f"jwt-{len(acquired)}", username, "key", "SHA256", 1)
            acquired.append(token)
            return token

        async def open_session(self, token: LoxoneToken) -> FakeSession:
            return FakeSession()

        async def kill_token(self, token: LoxoneToken) -> None:
            token.destroy()

    monkeypatch.setattr("mcpserver.auth.web.LoxoneClient", FakeLoxoneClient)
    app = Starlette(
        routes=[
            Route("/register", web.register, methods=["POST"]),
            Route("/authorize", web.authorize, methods=["GET", "POST"]),
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://public.example", follow_redirects=False
    ) as client:
        registration = await client.post("/register", json=_registration_payload())
        await client.get(
            "/authorize", params=_authorize_parameters(registration.json()["client_id"])
        )
        transaction = next(iter(web.transactions.values()))
        data = {
            "csrf": transaction.csrf_token,
            "action": "login",
            "username": "parallel-user",
            "password": "password",
        }
        headers = {"Cookie": f"phase0_oauth_tx={transaction.transaction_id}"}
        responses = await asyncio.gather(
            client.post("/authorize", headers=headers, data=data),
            client.post("/authorize", headers=headers, data=data),
        )

    assert sorted(response.status_code for response in responses) == [200, 400]
    assert len(acquired) == 1
    await web._kill(transaction)


@pytest.mark.parametrize("failure_type", [LoxoneConnectionError, LoxoneProtocolError])
@pytest.mark.asyncio
async def test_expired_login_transaction_is_removed_when_remote_kill_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[Exception],
) -> None:
    provider = _provider(tmp_path)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    token = LoxoneToken("sensitive-jwt", "user", "key", "SHA256", 1)
    transaction = LoginTransaction(
        transaction_id="expired",
        client_id="client",
        client_name="Client",
        redirect_uri=REDIRECT,
        state="state",
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        csrf_token="csrf",
        created_at=0,
        loxone_token=token,
    )
    web.transactions[transaction.transaction_id] = transaction

    class FailingLoxoneClient:
        def __init__(self, endpoint: object, *, client_uuid: object) -> None:
            pass

        async def kill_token(self, value: LoxoneToken) -> None:
            raise failure_type("remote unavailable")

    monkeypatch.setattr("mcpserver.auth.web.LoxoneClient", FailingLoxoneClient)
    await web._cleanup()

    assert web.transactions == {}
    assert transaction.loxone_token is None
    assert token.value == ""


@pytest.mark.asyncio
async def test_refresh_replay_revocation_survives_token_cleanup_failure(tmp_path: Path) -> None:
    def fail_cleanup(family_id: str) -> None:
        raise RuntimeError("simulated encrypted-store failure")

    provider = Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=Clock(),
        on_family_revoked=fail_cleanup,
    )
    client = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None
    issued = await provider.exchange_authorization_code(client, code)
    refresh = await provider.load_refresh_token(client, issued.refresh_token or "")
    assert refresh is not None
    await provider.exchange_refresh_token(client, refresh, [SCOPE])

    assert await provider.load_refresh_token(client, issued.refresh_token or "") is None
    document = provider.store.snapshot()
    assert document["families"][refresh.family_id]["revoked"] is True


@pytest.mark.asyncio
async def test_expired_store_records_are_garbage_collected(tmp_path: Path) -> None:
    clock = Clock()
    provider = _provider(tmp_path, clock)
    client = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    code = await provider.load_authorization_code(client, raw_code)
    assert code is not None
    await provider.exchange_authorization_code(client, code)

    clock.value += 30 * 24 * 60 * 60 + 1
    await provider.register_client(_client_info("new-client"))
    document = provider.store.snapshot()
    assert document["codes"] == {}
    assert document["families"] == {}
    assert document["access_tokens"] == {}
    assert document["refresh_tokens"] == {}


@pytest.mark.asyncio
async def test_browser_login_consent_kills_loxone_token_and_persists_no_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path)
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    app = Starlette(
        routes=[
            Route("/register", web.register, methods=["POST"]),
            Route("/authorize", web.authorize, methods=["GET", "POST"]),
        ]
    )
    killed: list[str] = []

    class FakeSession:
        async def load_structure(self) -> object:
            return SimpleNamespace(identity=SimpleNamespace(username="private-test-user"))

        async def close(self) -> None:
            return None

    class FakeLoxoneClient:
        def __init__(self, endpoint: object, *, client_uuid: object) -> None:
            pass

        async def probe(self) -> ProbeResult:
            return ProbeResult("17.1.7.27", "private-serial", True, True)

        async def acquire_token(self, username: str, password: str) -> LoxoneToken:
            assert username == "private-test-user"
            assert password == "private-password"
            return LoxoneToken("private-jwt", username, "private-key", "SHA256", 1)

        async def open_session(self, token: LoxoneToken) -> FakeSession:
            return FakeSession()

        async def kill_token(self, token: LoxoneToken) -> None:
            killed.append(token.value)
            token.destroy()

    monkeypatch.setattr("mcpserver.auth.web.LoxoneClient", FakeLoxoneClient)
    with TestClient(app, follow_redirects=False) as client:
        registration = client.post("/register", json=_registration_payload())
        start = client.get(
            "/authorize", params=_authorize_parameters(registration.json()["client_id"])
        )
        transaction = next(iter(web.transactions.values()))
        cookie = f"phase0_oauth_tx={transaction.transaction_id}"
        login = client.post(
            "/authorize",
            headers={"Cookie": cookie},
            data={
                "csrf": transaction.csrf_token,
                "action": "login",
                "username": "private-test-user",
                "password": "private-password",
            },
        )
        approved = client.post(
            "/authorize",
            headers={"Cookie": cookie},
            data={"csrf": transaction.csrf_token, "action": "approve"},
        )

    assert start.status_code == 200
    assert login.status_code == 200
    assert "private-test-user" in login.text
    assert "private-serial" in login.text
    assert "private-password" not in login.text
    assert approved.status_code == 302
    assert "state=client-state" in approved.headers["location"]
    assert (
        "iss=https%3A%2F%2Fpublic.example%2Fplugins%2Fmcpserver%2Foauth"
        in approved.headers["location"]
    )
    assert killed == ["private-jwt"]
    persisted = provider.store.path.read_text(encoding="utf-8")
    assert "private-test-user" not in persisted
    assert "private-password" not in persisted
    assert "private-jwt" not in persisted
    assert "private-serial" not in persisted


@pytest.mark.asyncio
async def test_token_route_enforces_pkce_resource_replay_and_revoke(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    client_info = await _client(provider)
    raw_code = provider.issue_authorization_code(
        client_id=client_info.client_id or "",
        redirect_uri=REDIRECT,
        code_challenge=CHALLENGE,
        resource=RESOURCE,
        identity_id="identity",
        miniserver_id="miniserver",
    )
    form = {
        "grant_type": "authorization_code",
        "client_id": client_info.client_id,
        "code": raw_code,
        "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER,
        "resource": RESOURCE,
    }
    with TestClient(_web_app(provider)) as client:
        wrong_resource = client.post(
            "/token", data={**form, "resource": "https://other.example/mcp"}
        )
        issued = client.post("/token", data=form)
        replay = client.post("/token", data=form)
        revoked = client.post(
            "/revoke",
            data={
                "client_id": client_info.client_id,
                "token": issued.json()["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )

    assert wrong_resource.json() == {"error": "invalid_request"}
    assert issued.status_code == 200
    assert issued.json()["scope"] == SCOPE
    assert replay.json() == {"error": "invalid_grant"}
    assert revoked.status_code == 200
    assert await provider.load_access_token(issued.json()["access_token"]) is None
