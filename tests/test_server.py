from __future__ import annotations

from starlette.testclient import TestClient

from mcpserver.server import create_server
from mcpserver.settings import ServerSettings


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


def test_unknown_host_is_rejected() -> None:
    app = create_server(_settings()).streamable_http_app()
    with TestClient(app, base_url="http://untrusted.example") as client:
        response = client.get("/mcp")

    assert response.status_code == 421


def test_unknown_origin_is_rejected() -> None:
    app = create_server(_settings()).streamable_http_app()
    headers = {"Origin": "https://untrusted.example"}
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/mcp", headers=headers)

    assert response.status_code == 403


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
