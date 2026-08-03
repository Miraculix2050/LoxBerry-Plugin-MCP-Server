"""MCP transport foundation with no released domain tools."""

from __future__ import annotations

import logging
from typing import Final

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcpserver import __version__
from mcpserver.auth.provider import SCOPE, Phase0OAuthProvider
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.auth.web import Phase0OAuthWeb
from mcpserver.settings import ServerSettings

SERVER_NAME: Final = "LoxBerry MCP Server"
_TRANSPORT_LOGGER_NAME: Final = "mcp.server.transport_security"
_SENSITIVE_REJECTION_PREFIXES: Final = (
    "Invalid Host header:",
    "Invalid Origin header:",
    "Invalid Content-Type header:",
)


class _RedactRejectedTransportHeader(logging.Filter):
    """Prevent rejected attacker-controlled headers from reaching service logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for prefix in _SENSITIVE_REJECTION_PREFIXES:
            if message.startswith(prefix):
                record.msg = f"{prefix} [redacted]"
                record.args = ()
                break
        return True


_transport_logger = logging.getLogger(_TRANSPORT_LOGGER_NAME)
if not any(isinstance(item, _RedactRejectedTransportHeader) for item in _transport_logger.filters):
    _transport_logger.addFilter(_RedactRejectedTransportHeader())


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    if "," in host:
        return False
    if host in allowed_hosts:
        return True
    return any(
        allowed.endswith(":*") and host.startswith(f"{allowed[:-2]}:") for allowed in allowed_hosts
    )


class _ForwardedHostValidationMiddleware(BaseHTTPMiddleware):
    """Validate the original Host supplied by the trusted loopback proxy."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: tuple[str, ...]) -> None:
        super().__init__(app)
        self._allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host is not None and not _host_is_allowed(forwarded_host, self._allowed_hosts):
            logging.getLogger(_TRANSPORT_LOGGER_NAME).warning(
                "Invalid forwarded Host header: [redacted]"
            )
            return Response("Invalid forwarded Host header", status_code=421)
        return await call_next(request)


class _TransportValidationMiddleware(BaseHTTPMiddleware):
    """Apply Host and Origin validation to OAuth and metadata routes too."""

    def __init__(self, app: ASGIApp, *, guard: TransportSecurityMiddleware) -> None:
        super().__init__(app)
        self._guard = guard

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rejection = await self._guard.validate_request(request)
        if rejection is not None:
            return rejection
        return await call_next(request)


class _ForwardedHostFastMCP(FastMCP):
    """FastMCP application that also validates Apache's original Host header."""

    forwarded_allowed_hosts: tuple[str, ...] = ()
    transport_guard: TransportSecurityMiddleware | None = None

    def streamable_http_app(self) -> Starlette:
        app = super().streamable_http_app()
        app.router.redirect_slashes = False
        app.add_middleware(
            _ForwardedHostValidationMiddleware,
            allowed_hosts=self.forwarded_allowed_hosts,
        )
        if self.transport_guard is not None:
            app.add_middleware(_TransportValidationMiddleware, guard=self.transport_guard)
        return app


class _Phase0TokenVerifier(TokenVerifier):
    """Expose the concrete provider through the SDK verifier contract."""

    def __init__(self, provider: Phase0OAuthProvider) -> None:
        self._provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self._provider.load_access_token(token)


def create_server(settings: ServerSettings) -> FastMCP:
    """Create the MCP server from already validated settings."""
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=list(settings.allowed_origins),
    )
    transport_guard = TransportSecurityMiddleware(transport_security)
    oauth_web: Phase0OAuthWeb | None = None
    oauth_auth: AuthSettings | None = None
    token_verifier: _Phase0TokenVerifier | None = None
    if settings.phase0_auth is not None:
        auth_store = AtomicJsonAuthStore(settings.phase0_auth.store_path)
        provider = Phase0OAuthProvider(
            auth_store,
            issuer=settings.phase0_auth.issuer_url,
            resource=settings.phase0_auth.resource_url,
        )
        oauth_web = Phase0OAuthWeb(
            provider,
            endpoint=settings.phase0_auth.loxone_endpoint,
            issuer=settings.phase0_auth.issuer_url,
            resource=settings.phase0_auth.resource_url,
        )
        oauth_auth = AuthSettings(
            issuer_url=AnyHttpUrl(settings.phase0_auth.issuer_url),
            resource_server_url=AnyHttpUrl(settings.phase0_auth.resource_url),
            required_scopes=[SCOPE],
        )
        token_verifier = _Phase0TokenVerifier(provider)

    server = _ForwardedHostFastMCP(
        SERVER_NAME,
        token_verifier=token_verifier,
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        auth=oauth_auth,
        transport_security=transport_security,
    )
    server.forwarded_allowed_hosts = settings.allowed_hosts
    server.transport_guard = transport_guard

    if oauth_web is not None:
        server.custom_route("/authorize", methods=["GET", "POST"], include_in_schema=False)(
            oauth_web.authorize
        )
        server.custom_route("/token", methods=["POST"], include_in_schema=False)(oauth_web.token)
        server.custom_route("/register", methods=["POST"], include_in_schema=False)(
            oauth_web.register
        )
        server.custom_route("/revoke", methods=["POST"], include_in_schema=False)(oauth_web.revoke)
        server.custom_route(
            "/.well-known/oauth-authorization-server/plugins/mcpserver/oauth",
            methods=["GET"],
            include_in_schema=False,
        )(oauth_web.authorization_metadata)

    @server.custom_route(  # type: ignore[misc]
        "/healthz", methods=["GET"], include_in_schema=False
    )
    async def health(request: Request) -> Response:
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
