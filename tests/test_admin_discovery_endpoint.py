"""Local-only fixed projections do not become MCP/OAuth capabilities."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import PluginConfig
from mcpserver.server import create_server
from mcpserver.service_discovery import PATH, admin_key
from mcpserver.settings import ServerSettings


def fixture(tmp_path, monkeypatch, peer="127.0.0.1"):
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(store.path))
    settings = ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("127.0.0.1:*",),
        allowed_origins=("http://127.0.0.1:*",),
        plugin_config=PluginConfig(enabled=True),
    )
    server = create_server(settings)
    owner = SimpleNamespace(
        project=AsyncMock(return_value={"projection": {"controls": []}, "timing": {}}),
        close=AsyncMock(),
        retry_not_before=lambda: 1234567890,
    )
    server.admin_discovery = owner
    app = server.streamable_http_app()
    return (
        TestClient(app, base_url="http://127.0.0.1:8765", client=(peer, 12345)),
        owner,
        admin_key(store),
    )


def body():
    return {
        "projection": "event_history",
        "binding": "a" * 64,
        "manual_retry": False,
        "early_probe": False,
    }


@pytest.mark.parametrize(
    "peer,key",
    [("127.0.0.1", ""), ("127.0.0.1", "foreign"), ("127.0.0.1", "ü"), ("192.168.1.10", None)],
)
def test_unauthorized_or_nonloopback_request_cannot_discover(tmp_path, monkeypatch, peer, key):
    client, owner, secret = fixture(tmp_path, monkeypatch, peer)
    # HTTP header values must be ASCII; use an ASCII malformed value here.
    supplied = secret if key is None else key.replace("ü", "invalid")
    with client:
        response = client.post(PATH, json=body(), headers={"X-LoxBerry-Admin-Discovery": supplied})
    assert response.status_code == 403
    owner.project.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("projection", []),
        ("projection", "structure"),
        ("binding", "bad"),
        ("manual_retry", 1),
        ("early_probe", True),
    ],
)
def test_malformed_or_generic_projection_is_rejected(tmp_path, monkeypatch, field, value):
    client, owner, secret = fixture(tmp_path, monkeypatch)
    payload = body()
    payload[field] = value
    with client:
        response = client.post(PATH, json=payload, headers={"X-LoxBerry-Admin-Discovery": secret})
    assert response.status_code == 400
    owner.project.assert_not_awaited()


def test_local_helper_and_lifecycle_use_fixed_projection(tmp_path, monkeypatch):
    client, owner, secret = fixture(tmp_path, monkeypatch)
    with client:
        response = client.post(PATH, json=body(), headers={"X-LoxBerry-Admin-Discovery": secret})
        assert response.status_code == 200 and response.json()["projection"] == {"controls": []}
    owner.project.assert_awaited_once_with(
        "event_history", "a" * 64, manual_retry=False, early_probe=False
    )
    owner.close.assert_awaited_once()


def test_oversize_local_request_never_reaches_discovery(tmp_path, monkeypatch):
    client, owner, secret = fixture(tmp_path, monkeypatch)
    with client:
        response = client.post(
            PATH, content=b"x" * 1025, headers={"X-LoxBerry-Admin-Discovery": secret}
        )
    assert response.status_code == 413
    owner.project.assert_not_awaited()


def test_cooldown_response_preserves_sanitized_retry_time(tmp_path, monkeypatch):
    from mcpserver.loxone.auth_diagnostics import MiniserverAuthenticationCooldown

    client, owner, secret = fixture(tmp_path, monkeypatch)
    owner.project.side_effect = MiniserverAuthenticationCooldown("synthetic")
    with client:
        response = client.post(PATH, json=body(), headers={"X-LoxBerry-Admin-Discovery": secret})
    assert response.json() == {
        "ok": False,
        "error": "authentication_cooldown",
        "retry_not_before": 1234567890,
    }


@pytest.mark.asyncio
async def test_actual_asgi_disconnect_cancels_active_discovery(tmp_path, monkeypatch):
    client, owner, secret = fixture(tmp_path, monkeypatch)
    endpoint = next(
        route.endpoint for route in client.app.routes if getattr(route, "path", None) == PATH
    )
    entered, disconnect, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def pending(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    owner.project.side_effect = pending
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": json.dumps(body()).encode(), "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": PATH,
            "headers": [(b"x-loxberry-admin-discovery", secret.encode())],
            "client": ("127.0.0.1", 1),
        },
        receive,
    )
    task = asyncio.create_task(endpoint(request))
    await entered.wait()
    disconnect.set()
    response = await asyncio.wait_for(task, 1)
    assert response.status_code == 499 and cancelled.is_set()
