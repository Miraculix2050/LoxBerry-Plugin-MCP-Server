from __future__ import annotations

import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.server import create_server
from mcpserver.settings import Phase0AuthSettings, ServerSettings


def _settings() -> ServerSettings:
    return ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_origins=("https://client.example",),
    )


def test_health_is_small_and_contains_no_configuration() -> None:
    app = create_server(_settings()).streamable_http_app()
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "mcpserver"
    assert set(response.json()) == {"ok", "service", "version"}


def test_health_rejects_unknown_host() -> None:
    app = create_server(_settings()).streamable_http_app()
    with TestClient(app, base_url="http://untrusted.example") as client:
        response = client.get("/healthz")

    assert response.status_code == 421


def test_health_rejects_unknown_origin() -> None:
    app = create_server(_settings()).streamable_http_app()
    headers = {"Origin": "https://untrusted.example"}
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/healthz", headers=headers)

    assert response.status_code == 403


def test_unknown_host_is_rejected() -> None:
    app = create_server(_settings()).streamable_http_app()
    with TestClient(app, base_url="http://untrusted.example") as client:
        response = client.get("/mcp")

    assert response.status_code == 421


def test_unknown_forwarded_host_is_rejected_and_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_server(_settings()).streamable_http_app()
    secret = "host-value-that-must-not-be-logged"
    headers = {"X-Forwarded-Host": secret}
    caplog.set_level(logging.WARNING, logger="mcp.server.transport_security")

    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/mcp", headers=headers)

    assert response.status_code == 421
    assert secret not in caplog.text
    assert "Invalid forwarded Host header: [redacted]" in caplog.text


def test_concatenated_forwarded_host_does_not_match_wildcard() -> None:
    settings = ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver:*",),
        allowed_origins=(),
    )
    app = create_server(settings).streamable_http_app()
    headers = {"X-Forwarded-Host": "testserver:123, untrusted.example"}

    with TestClient(app, base_url="http://testserver:8765") as client:
        response = client.get("/mcp", headers=headers)

    assert response.status_code == 421


def test_unknown_origin_is_rejected() -> None:
    app = create_server(_settings()).streamable_http_app()
    headers = {"Origin": "https://untrusted.example"}
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/mcp", headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/healthz", "/mcp"])
def test_rejected_origin_is_redacted_from_logs(caplog: pytest.LogCaptureFixture, path: str) -> None:
    app = create_server(_settings()).streamable_http_app()
    secret = "token-that-must-not-be-logged"
    headers = {"Origin": f"https://user:{secret}@untrusted.example"}
    caplog.set_level(logging.WARNING, logger="mcp.server.transport_security")

    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(path, headers=headers)

    assert response.status_code == 403
    assert secret not in caplog.text
    assert "Invalid Origin header: [redacted]" in caplog.text


def test_mcp_initialize_uses_expected_protocol() -> None:
    app = create_server(_settings()).streamable_http_app()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "phase-zero-test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://client.example",
    }
    with TestClient(app, base_url="http://testserver") as client:
        response = client.post("/mcp", json=request, headers=headers)

    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == "2025-11-25"
    assert response.json()["result"]["serverInfo"]["name"] == "LoxBerry MCP Server"


def test_oauth_routes_and_protected_resource_metadata_are_exact(tmp_path: Path) -> None:
    settings = ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_origins=(),
        phase0_auth=Phase0AuthSettings(
            public_origin="https://public.example",
            store_path=tmp_path / "sessions.json",
            loxone_endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
        ),
    )
    app = create_server(settings).streamable_http_app()
    with TestClient(app, base_url="http://testserver") as client:
        authorization = client.get(
            "/.well-known/oauth-authorization-server/plugins/mcpserver/oauth"
        )
        resource = client.get("/.well-known/oauth-protected-resource/plugins/mcpserver/mcp")
        unauthenticated = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        aliases = [
            client.get("/.well-known/oauth-authorization-server"),
            client.get("/plugins/mcpserver/oauth/authorize"),
            client.get("/authorize/"),
        ]

    assert authorization.status_code == 200
    assert authorization.json()["issuer"] == "https://public.example/plugins/mcpserver/oauth"
    assert resource.status_code == 200
    assert resource.json()["resource"] == "https://public.example/plugins/mcpserver/mcp"
    assert resource.json()["authorization_servers"] == [
        "https://public.example/plugins/mcpserver/oauth"
    ]
    assert unauthenticated.status_code == 401
    assert all(response.status_code == 404 for response in aliases)
