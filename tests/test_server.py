from __future__ import annotations

import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
)
from mcpserver.config import PluginConfig
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.server import _runtime_lifespan, create_server, main
from mcpserver.settings import Phase0AuthSettings, ServerSettings


def _settings() -> ServerSettings:
    return ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_origins=("https://client.example",),
    )


def test_main_opens_the_configured_log_as_the_service_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "service.log"
    logging_options: dict[str, object] = {}
    run_options: dict[str, object] = {}

    class Server:
        def run(self, **kwargs: object) -> None:
            run_options.update(kwargs)

    monkeypatch.setenv("MCPSERVER_LOG_FILE", str(log_file))
    monkeypatch.setattr(
        "mcpserver.server.configure_service_logging",
        lambda **kwargs: logging_options.update(kwargs),
    )
    monkeypatch.setattr(ServerSettings, "from_environment", staticmethod(_settings))
    monkeypatch.setattr("mcpserver.server.create_server", lambda settings: Server())

    main()

    assert logging_options == {
        "level": "warning",
        "log_file": str(log_file),
    }
    assert run_options == {"transport": "streamable-http"}


@pytest.mark.asyncio
async def test_runtime_lifespan_closes_live_miniserver_sessions() -> None:
    class Runtime:
        closed = False

        async def close(self) -> None:
            self.closed = True

    runtime = Runtime()
    async with _runtime_lifespan(runtime):  # type: ignore[arg-type]
        assert runtime.closed is False

    assert runtime.closed is True


@pytest.mark.asyncio
async def test_http_runtime_uses_root_logging_without_access_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = create_server(_settings())
    options: dict[str, object] = {}
    served: list[object] = []

    def config(app: object, **kwargs: object) -> object:
        options.update(kwargs)
        return app

    class UvicornServer:
        def __init__(self, config: object) -> None:
            self.config = config

        async def serve(self) -> None:
            served.append(self.config)

    monkeypatch.setattr("uvicorn.Config", config)
    monkeypatch.setattr("uvicorn.Server", UvicornServer)

    await server.run_streamable_http_async()

    assert options["log_config"] is None
    assert options["log_level"] == "debug"
    assert options["access_log"] is False
    assert len(served) == 1


@pytest.mark.asyncio
async def test_http_runtime_starts_mqtt_for_the_service_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Publisher:
        started = False
        closed = False

        async def start(self) -> None:
            self.started = True

        async def close(self) -> None:
            self.closed = True

    publisher = Publisher()
    server = create_server(_settings())
    server.mqtt_health = publisher  # type: ignore[assignment]

    monkeypatch.setattr("uvicorn.Config", lambda app, **kwargs: app)

    class UvicornServer:
        def __init__(self, _config: object) -> None:
            pass

        async def serve(self) -> None:
            assert publisher.started is True

    monkeypatch.setattr("uvicorn.Server", UvicornServer)

    await server.run_streamable_http_async()

    assert publisher.closed is True


def test_health_is_small_and_contains_no_configuration() -> None:
    app = create_server(_settings()).streamable_http_app()
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "mcpserver"
    assert set(response.json()) == {"ok", "service", "version"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/mcp"),
        ("get", "/.well-known/oauth-protected-resource/plugins/mcpserver/mcp"),
        ("get", "/authorize"),
    ],
)
def test_disabled_service_exposes_only_health(method: str, path: str) -> None:
    settings = ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_origins=(),
        service_enabled=False,
    )
    app = create_server(settings).streamable_http_app()
    with TestClient(app, base_url="http://testserver") as client:
        health = client.get("/healthz")
        response = client.request(method, path)

    assert health.status_code == 200
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "service_disabled"}


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
    instructions = response.json()["result"]["instructions"]
    assert "skill://using-loxberry-mcp/SKILL.md" in instructions
    assert "loxone_get_skill_guide" in instructions


def test_exact_default_read_only_tools_are_published() -> None:
    app = create_server(_settings()).streamable_http_app()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://client.example",
    }
    with TestClient(app, base_url="http://testserver") as client:
        response = client.post("/mcp", json=request, headers=headers)

    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "loxone_get_skill_guide",
        "loxone_get_system_status",
        "loxone_list_rooms",
        "loxone_get_room_snapshot",
        "loxone_list_categories",
        "loxone_list_global_metadata",
        "loxone_get_weather",
        "loxone_find_controls",
        "loxone_describe_control",
        "loxone_get_control_notes",
        "loxone_get_states",
    ]
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools)
    assert all(tool["annotations"]["destructiveHint"] is False for tool in tools)
    assert all(tool["outputSchema"]["properties"]["data"].get("anyOf") for tool in tools)
    assert all(tool["outputSchema"].get("$defs") for tool in tools)


@pytest.mark.asyncio
async def test_bundled_skill_is_published_as_an_mcp_resource() -> None:
    server = create_server(_settings())

    resources = await server.list_resources()
    assert [(str(item.uri), item.mimeType) for item in resources] == [
        ("skill://using-loxberry-mcp/SKILL.md", "text/markdown")
    ]

    contents = await server.read_resource("skill://using-loxberry-mcp/SKILL.md")
    assert len(contents) == 1
    assert contents[0].mime_type == "text/markdown"
    assert contents[0].content.startswith("---\nname: using-loxberry-mcp\n")
    assert "canonical `loxone_*` and `loxberry_*`" in contents[0].content
    assert "including tool-specific limits" in contents[0].content
    assert "schema-defined bounds from the current tool schema" in contents[0].content
    assert "such as a visible `moodList`" in contents[0].content
    assert "only when the current MCP results expose the required `scene_id`" in contents[0].content
    assert "do not guess or probe" in contents[0].content
    assert "### Inspect one known room" in contents[0].content
    assert "### Find and read a control" in contents[0].content
    assert "### Interpret controller-specific states" in contents[0].content
    assert "### Read weather" in contents[0].content
    assert "Never automatically retry an uncertain or failed write" in contents[0].content
    assert "It requires `loxone:history`," in contents[0].content
    assert "Treat a timeout as an unknown outcome" in contents[0].content
    assert "failed or uncertain cache clear" in contents[0].content


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
    assert resource.json()["scopes_supported"] == [
        READ_SCOPE,
        HISTORY_SCOPE,
        CONTROL_SCOPE,
        LOXBERRY_READ_SCOPE,
        LOXBERRY_OPERATE_SCOPE,
    ]
    assert unauthenticated.status_code == 401
    assert all(response.status_code == 404 for response in aliases)


def test_protected_resource_metadata_advertises_optional_control_scope(tmp_path: Path) -> None:
    settings = ServerSettings(
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_origins=(),
        phase0_auth=Phase0AuthSettings(
            public_origin="https://public.example",
            store_path=tmp_path / "sessions.json",
            loxone_endpoint=MiniserverEndpoint.parse_gen1("http://192.168.255.254"),
            plugin_config=PluginConfig(loxone_control_enabled=True),
        ),
    )
    app = create_server(settings).streamable_http_app()
    with TestClient(app, base_url="http://testserver") as client:
        resource = client.get("/.well-known/oauth-protected-resource/plugins/mcpserver/mcp")
        unauthenticated = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert resource.status_code == 200
    assert resource.json()["scopes_supported"] == [
        READ_SCOPE,
        HISTORY_SCOPE,
        CONTROL_SCOPE,
        LOXBERRY_READ_SCOPE,
        LOXBERRY_OPERATE_SCOPE,
    ]
    assert unauthenticated.status_code == 401
    assert "scope=" not in unauthenticated.headers["www-authenticate"]
