from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from mcpserver.auth.provider import SCOPE, Phase0OAuthProvider
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.auth.web import Phase0OAuthWeb
from mcpserver.loxone.client import LoxoneToken, MiniserverEndpoint, ProbeResult

ISSUER = "https://public.example/plugins/mcpserver/oauth"
RESOURCE = "https://public.example/plugins/mcpserver/mcp"
REDIRECT = "http://127.0.0.1:48765/callback"
VERIFIER = "v" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


class Clock:
    def __init__(self) -> None:
        self.value = 1_800_000_000

    def __call__(self) -> float:
        return float(self.value)


def _provider(tmp_path: Path, clock: Clock | None = None) -> Phase0OAuthProvider:
    return Phase0OAuthProvider(
        AtomicJsonAuthStore(tmp_path / "auth" / "sessions.json"),
        issuer=ISSUER,
        resource=RESOURCE,
        clock=clock or Clock(),
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


def _web_app(provider: Phase0OAuthProvider) -> Starlette:
    web = Phase0OAuthWeb(
        provider,
        endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        issuer=ISSUER,
        resource=RESOURCE,
    )
    return Starlette(
        routes=[
            Route("/register", web.register, methods=["POST"]),
            Route("/authorize", web.authorize, methods=["GET", "POST"]),
            Route("/token", web.token, methods=["POST"]),
            Route("/revoke", web.revoke, methods=["POST"]),
            Route("/metadata", web.authorization_metadata, methods=["GET"]),
        ]
    )


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


def test_metadata_advertises_only_the_public_contract(tmp_path: Path) -> None:
    with TestClient(_web_app(_provider(tmp_path))) as client:
        response = client.get("/metadata")

    assert response.status_code == 200
    assert response.json()["issuer"] == ISSUER
    assert response.json()["token_endpoint_auth_methods_supported"] == ["none"]
    assert response.json()["scopes_supported"] == [SCOPE]
    assert response.json()["code_challenge_methods_supported"] == ["S256"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "strict-origin"


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
