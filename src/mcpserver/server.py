"""Minimal Phase-0 MCP transport with no released domain tools."""

from __future__ import annotations

from typing import Final

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcpserver import __version__
from mcpserver.settings import ServerSettings

SERVER_NAME: Final = "LoxBerry MCP Server"


def create_server(settings: ServerSettings) -> FastMCP:
    """Create the MCP server from already validated settings."""
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=list(settings.allowed_origins),
    )
    server = FastMCP(
        SERVER_NAME,
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security,
    )

    @server.custom_route(  # type: ignore[misc]
        "/healthz", methods=["GET"], include_in_schema=False
    )
    async def health(_: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "service": "mcpserver",
                "version": __version__,
            }
        )

    return server


def main() -> None:
    """Run Streamable HTTP on the configured loopback port."""
    settings = ServerSettings.from_environment()
    create_server(settings).run(transport="streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
