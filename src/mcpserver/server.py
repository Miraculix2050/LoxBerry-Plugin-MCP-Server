"""Loopback MCP transport with the Phase 1 read-only tool surface."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import create_protected_resource_routes
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
from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
    Phase0OAuthProvider,
)
from mcpserver.auth.remote_revocation import run_remote_revocation_worker
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.auth.web import Phase0OAuthWeb
from mcpserver.config import DEFAULT_LOG_LEVEL, AtomicConfigStore
from mcpserver.loxberry.diagnostics import LoxBerryDiagnostics
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.loxone.runtime import LoxoneRuntime
from mcpserver.loxone.statistics import StatisticsCache
from mcpserver.settings import ServerSettings
from mcpserver.skill_delivery import SERVER_INSTRUCTIONS, register_skill_resource
from mcpserver.tools import (
    LoxBerryOperateRuntime,
    LoxBerryReadRuntime,
    register_control_tool,
    register_history_tools,
    register_loxberry_operate_tool,
    register_loxberry_read_tools,
    register_read_tools,
    register_skill_tool,
)

SERVER_NAME: Final = "LoxBerry MCP Server"
LOG_MAX_BYTES: Final = 512 * 1024
LOG_BACKUP_COUNT: Final = 2
LOG_MAX_RECORD_BYTES: Final = 8 * 1024
LOG_TRUNCATION_SUFFIX: Final = " ... [truncated]"
_LOG_LEVELS: Final = {
    "off": None,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}
_TRANSPORT_LOGGER_NAME: Final = "mcp.server.transport_security"
_SENSITIVE_REJECTION_PREFIXES: Final = (
    "Invalid Host header:",
    "Invalid Origin header:",
    "Invalid Content-Type header:",
)


class ServiceLevelFilter(logging.Filter):
    """Apply the persistent service level while always retaining control audits."""

    def __init__(self, level: str = DEFAULT_LOG_LEVEL) -> None:
        super().__init__()
        self._level = _LOG_LEVELS[level]

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "mcp_audit", False):
            return True
        return self._level is not None and record.levelno >= self._level


class BoundedLogFormatter(logging.Formatter):
    """Keep one rendered record within the configured UTF-8 byte budget."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        encoded = rendered.encode("utf-8")
        if len(encoded) <= LOG_MAX_RECORD_BYTES:
            return rendered
        suffix = LOG_TRUNCATION_SUFFIX.encode("utf-8")
        prefix = encoded[: LOG_MAX_RECORD_BYTES - len(suffix)].decode("utf-8", "ignore")
        return prefix + LOG_TRUNCATION_SUFFIX


def _remove_stale_log_backups(log_file: str) -> None:
    path = Path(log_file)
    for candidate in path.parent.glob(f"{path.name}.*"):
        suffix = candidate.name.removeprefix(f"{path.name}.")
        try:
            oversized = candidate.stat().st_size > LOG_MAX_BYTES
        except OSError:
            continue
        if suffix.isdecimal() and (int(suffix) > LOG_BACKUP_COUNT or oversized):
            with suppress(OSError):
                candidate.unlink()


def configure_service_logging(
    *,
    level: str,
    log_file: str | None,
) -> logging.Handler:
    """Configure one bounded handler and return it for deterministic verification."""
    if log_file:
        _remove_stale_log_backups(log_file)
        handler: logging.Handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    else:
        handler = logging.StreamHandler()
    handler.addFilter(ServiceLevelFilter(level))
    handler.setFormatter(
        BoundedLogFormatter(
            "%(asctime)s component=%(name)s severity=%(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    assert handler.formatter is not None
    handler.formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[handler],
        force=True,
    )
    return handler


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


class _DisabledServiceMiddleware(BaseHTTPMiddleware):
    """Keep health available while failing closed for all public protocol routes."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path != "/healthz":
            return JSONResponse(
                {"ok": False, "error": "service_disabled"},
                status_code=503,
            )
        return await call_next(request)


class _ForwardedHostFastMCP(FastMCP):
    """FastMCP application that also validates Apache's original Host header."""

    async def run_streamable_http_async(self) -> None:  # pragma: no cover - process boundary
        """Run Uvicorn through the bounded root logger without request access logs."""
        import uvicorn

        config = uvicorn.Config(
            self.streamable_http_app(),
            host=self.settings.host,
            port=self.settings.port,
            log_config=None,
            log_level="debug",
            access_log=False,
        )
        await uvicorn.Server(config).serve()

    forwarded_allowed_hosts: tuple[str, ...] = ()
    transport_guard: TransportSecurityMiddleware | None = None
    service_enabled: bool = True
    advertised_scopes: tuple[str, ...] = ()

    def streamable_http_app(self) -> Starlette:
        app = super().streamable_http_app()
        auth = self.settings.auth
        if self.advertised_scopes and auth and auth.resource_server_url:
            metadata_route = create_protected_resource_routes(
                resource_url=auth.resource_server_url,
                authorization_servers=[auth.issuer_url],
                scopes_supported=list(self.advertised_scopes),
            )[0]
            for index, route in enumerate(app.routes):
                if getattr(route, "path", None) == metadata_route.path:
                    app.routes[index] = metadata_route
                    break
            else:  # pragma: no cover - pinned SDK always creates this route
                raise RuntimeError("OAuth protected resource metadata route is missing")
        app.router.redirect_slashes = False
        if not self.service_enabled:
            app.add_middleware(_DisabledServiceMiddleware)
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


@asynccontextmanager
async def _runtime_lifespan(
    runtime: LoxoneRuntime | None,
    remote_revocation: tuple[MiniserverEndpoint, EncryptedLoxoneTokenStore, float] | None = None,
) -> AsyncIterator[None]:
    """Close all live Miniserver sessions when the HTTP application stops."""
    worker = (
        asyncio.create_task(run_remote_revocation_worker(*remote_revocation))
        if remote_revocation is not None
        else None
    )
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        if runtime is not None:
            await runtime.close()


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
    runtime: LoxoneRuntime | None = None
    loxberry_runtime: LoxBerryReadRuntime | None = None
    loxberry_operate_runtime: LoxBerryOperateRuntime | None = None
    statistics_cache: StatisticsCache | None = None
    if settings.phase0_auth is not None:
        auth_store = AtomicJsonAuthStore(settings.phase0_auth.store_path)
        loxone_store: EncryptedLoxoneTokenStore | None = None
        if (
            settings.phase0_auth.loxone_store_path is not None
            and settings.phase0_auth.install_key_path is not None
        ):
            loxone_store = EncryptedLoxoneTokenStore(
                settings.phase0_auth.loxone_store_path,
                settings.phase0_auth.install_key_path,
            )
        config = settings.phase0_auth.plugin_config

        def loxberry_binding_allowed(client_id: str, identity_id: str, miniserver_id: str) -> bool:
            if settings.phase0_auth is None or settings.phase0_auth.config_path is None:
                return False
            try:
                current = AtomicConfigStore(settings.phase0_auth.config_path).load()
                binding = auth_store.pseudonym(
                    "loxberry-read-binding-v1", client_id, identity_id, miniserver_id
                )
                return current.loxberry_read_enabled and binding in current.loxberry_read_bindings
            except Exception:
                return False

        def loxberry_operate_binding_allowed(
            client_id: str, identity_id: str, miniserver_id: str
        ) -> bool:
            if settings.phase0_auth is None or settings.phase0_auth.config_path is None:
                return False
            try:
                current = AtomicConfigStore(settings.phase0_auth.config_path).load()
                binding = auth_store.pseudonym(
                    "loxberry-operate-binding-v1", client_id, identity_id, miniserver_id
                )
                return (
                    current.loxone_history_enabled
                    and current.loxberry_operate_enabled
                    and binding in current.loxberry_operate_bindings
                )
            except Exception:
                return False

        runtime_ref: dict[str, LoxoneRuntime] = {}

        def on_family_revoked(family_id: str) -> None:
            if loxone_store is not None:
                loxone_store.schedule_remote_revoke(family_id)
                loxone_store.delete_explorer_family(family_id)
            runtime_value = runtime_ref.get("runtime")
            if runtime_value is None:
                return
            try:
                asyncio.get_running_loop().create_task(runtime_value.revoke(family_id))
            except RuntimeError:
                # Startup cleanup has no running event loop; the token was still removed.
                return

        provider = Phase0OAuthProvider(
            auth_store,
            issuer=settings.phase0_auth.issuer_url,
            resource=settings.phase0_auth.resource_url,
            on_family_revoked=on_family_revoked,
            control_enabled=bool(config and config.loxone_control_enabled),
            loxberry_read_enabled=bool(config and config.loxberry_read_enabled),
            loxberry_read_allowed=loxberry_binding_allowed,
            history_enabled=bool(config and config.loxone_history_enabled),
            loxberry_operate_enabled=bool(config and config.loxberry_operate_enabled),
            loxberry_operate_allowed=loxberry_operate_binding_allowed,
            explorer_origins=settings.allowed_origins,
        )
        oauth_web = Phase0OAuthWeb(
            provider,
            endpoint=settings.phase0_auth.loxone_endpoint,
            issuer=settings.phase0_auth.issuer_url,
            resource=settings.phase0_auth.resource_url,
            loxone_store=loxone_store,
        )
        oauth_auth = AuthSettings(
            issuer_url=AnyHttpUrl(settings.phase0_auth.issuer_url),
            resource_server_url=AnyHttpUrl(settings.phase0_auth.resource_url),
            required_scopes=[READ_SCOPE],
        )
        token_verifier = _Phase0TokenVerifier(provider)
        if loxone_store is not None:
            statistics_cache = StatisticsCache(
                maximum_bytes=(
                    config.statistics_memory_max_mib * 1024 * 1024
                    if config is not None
                    else 128 * 1024 * 1024
                ),
            )
            runtime = LoxoneRuntime(
                settings.phase0_auth.loxone_endpoint,
                loxone_store,
                token_health=LoxoneTokenHealthStore(auth_store),
                timeout_seconds=config.connection_timeout if config is not None else 10.0,
                requests_per_minute=config.requests_per_minute if config is not None else 60,
                max_parallel_calls=config.max_parallel_calls if config is not None else 4,
                control_requests_per_minute=(
                    config.control_requests_per_minute if config is not None else 10
                ),
                history_requests_per_minute=(
                    config.history_requests_per_minute if config is not None else 12
                ),
                statistics_cache=statistics_cache,
                control_enabled=bool(config and config.loxone_control_enabled),
                history_enabled=bool(config and config.loxone_history_enabled),
                structure_refresh_seconds=(
                    config.structure_refresh_seconds if config is not None else 300
                ),
                max_active_sessions=(
                    config.max_active_runtime_sessions if config is not None else 16
                ),
                session_idle_seconds=(
                    config.runtime_session_idle_seconds if config is not None else 900
                ),
                max_states_per_identity=(
                    config.max_states_per_identity if config is not None else 20_000
                ),
                max_structure_controls=(
                    config.max_structure_controls if config is not None else 20_000
                ),
                max_structure_state_references=(
                    config.max_structure_state_references if config is not None else 100_000
                ),
                max_structure_depth=(config.max_structure_depth if config is not None else 32),
            )
            runtime_ref["runtime"] = runtime
        if config and settings.phase0_auth.config_path is not None:
            home = Path(os.getenv("LBHOMEDIR", "/opt/loxberry"))
            if home.is_absolute():
                loxberry_runtime = LoxBerryReadRuntime(
                    LoxBerryDiagnostics(home),
                    AtomicConfigStore(settings.phase0_auth.config_path),
                    auth_store,
                )
        if config and settings.phase0_auth.config_path is not None and statistics_cache is not None:
            loxberry_operate_runtime = LoxBerryOperateRuntime(
                statistics_cache,
                AtomicConfigStore(settings.phase0_auth.config_path),
                auth_store,
            )

    server = _ForwardedHostFastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        token_verifier=token_verifier,
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        auth=oauth_auth,
        transport_security=transport_security,
        lifespan=lambda _server: _runtime_lifespan(
            runtime,
            (
                settings.phase0_auth.loxone_endpoint,
                loxone_store,
                config.connection_timeout if config is not None else 10.0,
            )
            if settings.phase0_auth is not None and loxone_store is not None
            else None,
        ),
    )
    server.forwarded_allowed_hosts = settings.allowed_hosts
    server.transport_guard = transport_guard
    server.service_enabled = settings.service_enabled
    control_enabled = bool(
        settings.phase0_auth
        and settings.phase0_auth.plugin_config
        and settings.phase0_auth.plugin_config.loxone_control_enabled
    )
    server.advertised_scopes = (
        READ_SCOPE,
        HISTORY_SCOPE,
        CONTROL_SCOPE,
        LOXBERRY_READ_SCOPE,
        LOXBERRY_OPERATE_SCOPE,
    )
    register_skill_resource(server)
    register_skill_tool(server)
    register_read_tools(server, runtime, control_enabled=control_enabled)
    if runtime is not None:
        register_control_tool(server, runtime)
    if loxberry_runtime is not None:
        register_loxberry_read_tools(server, loxberry_runtime)
    if runtime is not None:
        register_history_tools(server, runtime)
    if loxberry_operate_runtime is not None:
        register_loxberry_operate_tool(server, loxberry_operate_runtime)

    if oauth_web is not None:
        server.custom_route("/authorize", methods=["GET", "POST"], include_in_schema=False)(
            oauth_web.authorize
        )
        server.custom_route("/token", methods=["POST"], include_in_schema=False)(oauth_web.token)
        server.custom_route("/register", methods=["POST"], include_in_schema=False)(
            oauth_web.register
        )
        server.custom_route("/revoke", methods=["POST"], include_in_schema=False)(oauth_web.revoke)
        server.custom_route("/explorer-session", methods=["POST"], include_in_schema=False)(
            oauth_web.explorer_session
        )
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
    configure_service_logging(
        level=settings.log_level,
        log_file=os.environ.get("MCPSERVER_LOG_FILE"),
    )
    logging.getLogger("mcpserver.service").info(
        "event=service_start version=%s configured_level=%s",
        __version__,
        settings.log_level,
    )
    create_server(settings).run(transport="streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
