"""Strict public OAuth and browser-consent endpoints for Phase 0."""

# Embedded responsive HTML is kept close to this temporary browser flow.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlencode, urlsplit
from uuid import NAMESPACE_URL, uuid5

from mcp.server.auth.provider import RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from mcpserver.auth.loxone_store import (
    EncryptedLoxoneTokenStore,
    ExplorerSession,
    LoxoneTokenStoreError,
)
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    EXPLORER_CLIENT_NAME,
    EXPLORER_REFRESH_FAMILY_TTL,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
    Phase0OAuthProvider,
    normalize_scopes,
    scope_text,
)
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneToken,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import LoxoneProtocolError

_MAX_FORM_BYTES: Final = 16 * 1024
_MAX_JSON_BYTES: Final = 32 * 1024
_TRANSACTION_TTL: Final = 5 * 60
_MAX_LOGIN_ATTEMPTS: Final = 5
_MAX_LOGIN_TRANSACTIONS: Final = 16
_LOGIN_RATE_WINDOW: Final = 5 * 60
_MAX_CLIENT_LOGIN_FAILURES: Final = 10
_MAX_GLOBAL_LOGIN_FAILURES: Final = 20
_MAX_RATE_KEYS: Final = 512
_REGISTRATION_RATE_WINDOW: Final = 5 * 60
_MAX_REGISTRATIONS_PER_WINDOW: Final = 16
_COOKIE_NAME: Final = "phase0_oauth_tx"
_EXPLORER_COOKIE_NAME: Final = "mcp_explorer_session"
_PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


@dataclass(slots=True)
class LoginTransaction:
    transaction_id: str
    csrf_token: str
    client_id: str
    client_name: str
    redirect_uri: str
    state: str
    code_challenge: str
    resource: str
    created_at: int
    scopes: tuple[str, ...] = (READ_SCOPE,)
    attempts: int = 0
    loxone_token: LoxoneToken | None = None
    identity_name: str | None = None
    identity_id: str | None = None
    miniserver_id: str | None = None
    miniserver_name: str | None = None
    loxberry_read_locally_approved: bool = False
    loxberry_operate_locally_approved: bool = False
    phase: str = "login"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def _callback_csp_source(uri: str) -> str:
    parsed = urlsplit(uri)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    authority = host if parsed.port is None else f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{authority}"


def _security_headers(
    *, callback_uri: str | None = None, script_nonce: str | None = None
) -> dict[str, str]:
    form_action = "'self'"
    if callback_uri is not None:
        form_action = f"{form_action} {_callback_csp_source(callback_uri)}"
    script_policy = "" if script_nonce is None else f" script-src 'nonce-{script_nonce}';"
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'unsafe-inline'; form-action {form_action}; "
            f"{script_policy} frame-ancestors 'none'; base-uri 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin",
    }


def _json(payload: Mapping[str, object], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=_security_headers())


def _oauth_error(error: str, *, status: int = 400) -> JSONResponse:
    return _json({"error": error}, status)


def _redirect(uri: str, parameters: Mapping[str, str]) -> RedirectResponse:
    separator = "&" if "?" in uri else "?"
    return RedirectResponse(
        f"{uri}{separator}{urlencode(parameters)}",
        status_code=302,
        headers=_security_headers(callback_uri=uri),
    )


def _html_page(
    title: str,
    body: str,
    *,
    status: int = 200,
    callback_uri: str | None = None,
    script: str | None = None,
) -> HTMLResponse:
    script_nonce = secrets.token_urlsafe(16) if script is not None else None
    script_markup = "" if script is None else f'<script nonce="{script_nonce}">{script}</script>'
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{font-family:system-ui,sans-serif;color-scheme:light dark}}body{{margin:0;padding:1rem;background:#18222d}}
main{{box-sizing:border-box;max-width:34rem;margin:4vh auto;padding:1.4rem;border-radius:.8rem;background:#fff;color:#17202a}}
label{{display:block;margin:.9rem 0 .25rem}}input{{box-sizing:border-box;width:100%;padding:.75rem;font:inherit}}
.actions{{display:flex;gap:.7rem;flex-wrap:wrap;margin-top:1.2rem}}button{{padding:.7rem 1rem;font:inherit}}
.error{{color:#a00000}}.notice{{padding:.8rem;border-left:.3rem solid #476d91;background:#edf4fa}}
.scope-list{{margin:1rem 0;padding:0;border:0}}.scope-list legend{{font-weight:700;margin-bottom:.35rem}}
.scope-select-all{{display:flex;align-items:center;gap:.45rem;margin:.2rem 0 .55rem;font-size:.9rem;font-weight:600}}
.scope-select-all input{{width:auto;margin:0;padding:0;flex:none}}
.scope-option{{display:flex;align-items:flex-start;gap:.7rem;margin:.65rem 0;padding:.8rem;border:1px solid #b6c2cc;border-radius:.5rem}}
.scope-option input{{width:auto;margin:.2rem 0 0;padding:0;flex:none}}.scope-option span{{display:block}}.scope-option small{{display:block;margin-top:.2rem}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:.4rem .8rem}}dt{{font-weight:700}}
@media(max-width:430px){{main{{margin:0 auto;padding:1rem}}dl{{display:block}}dd{{margin:0 0 .7rem}}button{{flex:1}}}}
</style></head><body><main>{body}</main>{script_markup}</body></html>"""
    return HTMLResponse(
        document,
        status_code=status,
        headers=_security_headers(callback_uri=callback_uri, script_nonce=script_nonce),
    )


def _message_page(
    title: str,
    heading: str,
    message: str,
    *,
    status: int,
    callback_uri: str | None = None,
) -> HTMLResponse:
    body = f'<h1>{html.escape(heading)}</h1><p class="notice">{html.escape(message)}</p>'
    return _html_page(title, body, status=status, callback_uri=callback_uri)


async def _limited_body(request: Request, limit: int) -> bytes | None:
    length_header = request.headers.get("content-length")
    if length_header is not None:
        try:
            length = int(length_header)
        except ValueError:
            return None
        if length < 0 or length > limit:
            return None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            return None
        body.extend(chunk)
    return bytes(body)


async def _form(request: Request, *, allowed: set[str]) -> dict[str, str] | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        return None
    body = await _limited_body(request, _MAX_FORM_BYTES)
    if body is None:
        return None
    from urllib.parse import parse_qsl

    try:
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, ValueError):
        return None
    if any(key not in allowed for key, _ in pairs) or len({key for key, _ in pairs}) != len(pairs):
        return None
    return dict(pairs)


class Phase0OAuthWeb:
    """Own exact endpoint behavior while using MCP SDK data interfaces."""

    def __init__(
        self,
        provider: Phase0OAuthProvider,
        *,
        endpoint: MiniserverEndpoint,
        issuer: str,
        resource: str,
        loxone_store: EncryptedLoxoneTokenStore | None = None,
    ) -> None:
        self.provider = provider
        self.endpoint = endpoint
        self.issuer = issuer
        self.resource = resource
        self.loxone_store = loxone_store
        self.explorer_origin = issuer.rsplit("/plugins/mcpserver/oauth", 1)[0]
        self._explorer_locks: dict[str, asyncio.Lock] = {}
        self.transactions: dict[str, LoginTransaction] = {}
        self._client_uuid = uuid5(NAMESPACE_URL, issuer)
        self._login_slots = asyncio.Semaphore(2)
        self._login_failures: dict[str, deque[int]] = {}
        self._global_login_failures: deque[int] = deque()
        self._registration_attempts: dict[str, deque[int]] = {}

    async def _kill(self, transaction: LoginTransaction) -> bool:
        token = transaction.loxone_token
        if token is None:
            return True
        try:
            await LoxoneClient(self.endpoint, client_uuid=self._client_uuid).kill_token(token)
        except (LoxoneConnectionError, LoxoneProtocolError):
            token.destroy()
        transaction.loxone_token = None
        return True

    async def _cleanup(self) -> None:
        now = int(time.time())
        expired = [
            key
            for key, value in self.transactions.items()
            if value.created_at + _TRANSACTION_TTL <= now
        ]
        for key in expired:
            transaction = self.transactions.get(key)
            if transaction is None:
                continue
            async with transaction.lock:
                if self.transactions.get(key) is transaction and await self._kill(transaction):
                    self.transactions.pop(key, None)

    def _explorer_response(self, token: OAuthToken, expires_at: int) -> JSONResponse:
        return _json(
            {
                "access_token": token.access_token,
                "expires_in": token.expires_in,
                "scope": token.scope,
                "expires_at": expires_at,
            }
        )

    def _explorer_cookie(self, response: Response, session_id: str) -> None:
        response.set_cookie(
            _EXPLORER_COOKIE_NAME,
            session_id,
            max_age=EXPLORER_REFRESH_FAMILY_TTL,
            path="/plugins/mcpserver/oauth",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    def _delete_explorer_cookie(self, response: Response) -> None:
        response.delete_cookie(
            _EXPLORER_COOKIE_NAME,
            path="/plugins/mcpserver/oauth",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    async def _explorer_payload(self, request: Request) -> dict[str, str] | None:
        if request.headers.get("origin") not in self.provider.explorer_origins:
            return None
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return None
        raw = await _limited_body(request, _MAX_JSON_BYTES)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in payload.items()
        ):
            return None
        return payload

    async def explorer_session(self, request: Request) -> Response:
        """Broker a short-lived Explorer OAuth family through an HttpOnly browser cookie."""
        payload = await self._explorer_payload(request)
        if payload is None or self.loxone_store is None:
            return _json({"error": "invalid_request"}, status=400)
        action = payload.get("action")
        if action == "complete":
            allowed = {"action", "client_id", "code", "redirect_uri", "code_verifier", "resource"}
            if set(payload) != allowed or payload["resource"] != self.resource:
                return _json({"error": "invalid_request"}, status=400)
            client = await self.provider.get_client(payload["client_id"])
            if (
                client is None
                or client.client_name != EXPLORER_CLIENT_NAME
                or not self.provider.is_explorer_client(client)
            ):
                return _json({"error": "invalid_client"}, status=401)
            code = await self.provider.load_authorization_code(client, payload["code"])
            verifier = payload["code_verifier"]
            if (
                code is None
                or str(code.redirect_uri) != payload["redirect_uri"]
                or code.resource != self.resource
                or not _PKCE_VERIFIER.fullmatch(verifier)
            ):
                return _json({"error": "invalid_grant"}, status=400)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            if not hmac.compare_digest(challenge, code.code_challenge):
                return _json({"error": "invalid_grant"}, status=400)
            token = await self.provider.exchange_authorization_code(client, code)
            session_id = secrets.token_urlsafe(32)
            now = self.provider.now()
            expires_at = now + EXPLORER_REFRESH_FAMILY_TTL
            self.loxone_store.put_explorer_session(
                ExplorerSession(
                    session_id,
                    code.family_id,
                    client.client_id or "",
                    self.resource,
                    token.scope or scope_text(list(code.scopes)),
                    token.access_token or "",
                    now + int(token.expires_in or 0),
                    token.refresh_token or "",
                    expires_at,
                )
            )
            response = self._explorer_response(token, expires_at)
            self._explorer_cookie(response, session_id)
            return response
        session_id = request.cookies.get(_EXPLORER_COOKIE_NAME, "")
        try:
            session = self.loxone_store.get_explorer_session(session_id)
        except LoxoneTokenStoreError:
            session = None
        if session is None or session.expires_at <= self.provider.now():
            response = _json({"error": "invalid_session"}, status=401)
            self._delete_explorer_cookie(response)
            if session_id:
                self.loxone_store.delete_explorer_session(session_id)
            return response
        if action == "logout" and set(payload) == {"action"}:
            await self.provider.revoke_raw_token(session.refresh_token, session.client_id)
            self.loxone_store.delete_explorer_session(session.session_id)
            logout_response = Response(status_code=204, headers=_security_headers())
            self._delete_explorer_cookie(logout_response)
            return logout_response
        if action != "access" or set(payload) != {"action"}:
            return _json({"error": "invalid_request"}, status=400)
        lock = self._explorer_locks.setdefault(session.session_id, asyncio.Lock())
        async with lock:
            current = self.loxone_store.get_explorer_session(session.session_id)
            if current is None or current.expires_at <= self.provider.now():
                return _json({"error": "invalid_session"}, status=401)
            if current.access_expires_at <= self.provider.now() + 15:
                client = await self.provider.get_client(current.client_id)
                refresh = (
                    None
                    if client is None
                    else await self.provider.load_refresh_token(client, current.refresh_token)
                )
                if client is None or refresh is None:
                    self.loxone_store.delete_explorer_session(current.session_id)
                    return _json({"error": "invalid_session"}, status=401)
                token = await self.provider.exchange_refresh_token(
                    client, refresh, current.scope.split()
                )
                current = ExplorerSession(
                    current.session_id,
                    current.family_id,
                    current.client_id,
                    current.resource,
                    token.scope or current.scope,
                    token.access_token or "",
                    self.provider.now() + int(token.expires_in or 0),
                    token.refresh_token or "",
                    current.expires_at,
                )
                self.loxone_store.put_explorer_session(current)
            token = OAuthToken(
                access_token=current.access_token,
                token_type="Bearer",
                expires_in=max(0, current.access_expires_at - self.provider.now()),
                scope=current.scope,
            )
            return self._explorer_response(token, current.expires_at)

    @staticmethod
    def _prune_times(values: deque[int], *, now: int, window: int) -> None:
        while values and values[0] + window <= now:
            values.popleft()

    def _login_rate_keys(self, transaction: LoginTransaction, username: str) -> tuple[str, str]:
        normalized = username.casefold()
        identity_key = self.provider.store.pseudonym(
            "login-identity", self.endpoint.origin, normalized
        )
        return f"identity:{identity_key}", f"client:{transaction.client_id}"

    def _login_is_limited(self, keys: tuple[str, str], now: int) -> bool:
        self._prune_times(self._global_login_failures, now=now, window=_LOGIN_RATE_WINDOW)
        if len(self._global_login_failures) >= _MAX_GLOBAL_LOGIN_FAILURES:
            return True
        limits = (_MAX_LOGIN_ATTEMPTS, _MAX_CLIENT_LOGIN_FAILURES)
        for key, limit in zip(keys, limits, strict=True):
            values = self._login_failures.setdefault(key, deque())
            self._prune_times(values, now=now, window=_LOGIN_RATE_WINDOW)
            if len(values) >= limit:
                return True
        return False

    def _record_login_failure(self, keys: tuple[str, str], now: int) -> None:
        self._global_login_failures.append(now)
        for key in keys:
            self._login_failures.setdefault(key, deque()).append(now)
        empty = [key for key, values in self._login_failures.items() if not values]
        for key in empty:
            self._login_failures.pop(key, None)
        if len(self._login_failures) > _MAX_RATE_KEYS:
            oldest = sorted(
                self._login_failures,
                key=lambda key: self._login_failures[key][-1],
            )
            for key in oldest[: len(self._login_failures) - _MAX_RATE_KEYS]:
                self._login_failures.pop(key, None)

    def _clear_identity_failures(self, keys: tuple[str, str]) -> None:
        self._login_failures.pop(keys[0], None)

    def _registration_key(self, request: Request) -> str:
        source = request.client.host if request.client is not None else "unknown"
        return self.provider.store.pseudonym("registration-source", source)

    def _registration_is_limited(self, key: str) -> bool:
        now = int(time.time())
        values = self._registration_attempts.setdefault(key, deque())
        self._prune_times(values, now=now, window=_REGISTRATION_RATE_WINDOW)
        return len(values) >= _MAX_REGISTRATIONS_PER_WINDOW

    def _record_registration(self, key: str) -> None:
        self._registration_attempts.setdefault(key, deque()).append(int(time.time()))
        self._bound_rate_map(self._registration_attempts)

    @staticmethod
    def _bound_rate_map(values: dict[str, deque[int]]) -> None:
        if len(values) <= _MAX_RATE_KEYS:
            return
        oldest = sorted(values, key=lambda key: values[key][-1] if values[key] else 0)
        for key in oldest[: len(values) - _MAX_RATE_KEYS]:
            values.pop(key, None)

    @staticmethod
    def _single_query(request: Request) -> dict[str, str] | None:
        if len(request.url.query.encode("utf-8")) > _MAX_FORM_BYTES:
            return None
        pairs = request.query_params.multi_items()
        allowed = {
            "response_type",
            "client_id",
            "redirect_uri",
            "scope",
            "resource",
            "code_challenge",
            "code_challenge_method",
            "state",
        }
        if any(key not in allowed for key, _ in pairs) or len({key for key, _ in pairs}) != len(
            pairs
        ):
            return None
        return dict(pairs)

    async def authorize(self, request: Request) -> Response:
        await self._cleanup()
        if request.method == "GET":
            return await self._authorize_start(request)
        return await self._authorize_post(request)

    async def _authorize_start(self, request: Request) -> Response:
        query = self._single_query(request)
        if query is None:
            return _message_page(
                "Invalid authorization request",
                "Invalid authorization request / Ungültige Autorisierungsanfrage",
                "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
                status=400,
            )
        client_id = query.get("client_id", "")
        client = await self.provider.get_client(client_id)
        redirect_uri = query.get("redirect_uri", "")
        if (
            client is None
            or client.redirect_uris is None
            or redirect_uri not in {str(value) for value in client.redirect_uris}
        ):
            return _message_page(
                "Invalid authorization request",
                "Invalid authorization request / Ungültige Autorisierungsanfrage",
                "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
                status=400,
            )
        try:
            scopes = normalize_scopes(
                query.get("scope"),
                control_enabled=self.provider.control_enabled,
                loxberry_read_enabled=self.provider.loxberry_read_enabled,
                history_enabled=self.provider.history_enabled,
                loxberry_operate_enabled=self.provider.loxberry_operate_enabled,
            )
        except ValueError:
            return _redirect(
                redirect_uri,
                {"error": "invalid_scope", "state": query.get("state", ""), "iss": self.issuer},
            )
        if (
            query.get("response_type") != "code"
            or query.get("resource") != self.resource
            or query.get("code_challenge_method") != "S256"
            or not _PKCE_CHALLENGE.fullmatch(query.get("code_challenge", ""))
            or not query.get("state")
        ):
            return _redirect(
                redirect_uri,
                {"error": "invalid_request", "state": query.get("state", ""), "iss": self.issuer},
            )
        if len(self.transactions) >= _MAX_LOGIN_TRANSACTIONS:
            return _message_page(
                "Authorization unavailable",
                "Authorization unavailable / Autorisierung nicht verfügbar",
                "Try again later. / Versuchen Sie es später erneut.",
                status=503,
            )
        transaction = LoginTransaction(
            transaction_id=_opaque(),
            csrf_token=_opaque(),
            client_id=client_id,
            client_name=client.client_name or client_id,
            redirect_uri=redirect_uri,
            state=query["state"],
            code_challenge=query["code_challenge"],
            resource=query["resource"],
            scopes=scopes,
            created_at=int(time.time()),
        )
        self.transactions[transaction.transaction_id] = transaction
        response = self._login_page(transaction)
        response.set_cookie(
            _COOKIE_NAME,
            transaction.transaction_id,
            max_age=_TRANSACTION_TTL,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/plugins/mcpserver/oauth/authorize",
        )
        return response

    def _hidden(self, transaction: LoginTransaction, action: str) -> str:
        return (
            f'<input type="hidden" name="csrf" value="{html.escape(transaction.csrf_token)}">'
            f'<input type="hidden" name="action" value="{action}">'
        )

    def _login_page(self, transaction: LoginTransaction, error: str = "") -> HTMLResponse:
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        body = f"""<h1>Connect Loxone / Loxone verbinden</h1><p>Sign in with the dedicated Loxone user for <strong>{html.escape(transaction.client_name)}</strong>. / Melden Sie sich mit dem dedizierten Loxone-Benutzer an.</p>
{error_html}<form method="post" action="/plugins/mcpserver/oauth/authorize">{self._hidden(transaction, "login")}
<label for="username">Loxone user / Loxone-Benutzer</label><input id="username" name="username" autocomplete="username" maxlength="128" required>
<label for="password">Password / Passwort</label><input id="password" type="password" name="password" autocomplete="current-password" maxlength="1024" required>
<div class="actions"><button type="submit">Continue / Weiter</button></div></form>"""
        return _html_page("Connect Loxone", body, callback_uri=transaction.redirect_uri)

    def _consent_page(self, transaction: LoginTransaction) -> HTMLResponse:
        history_option = (
            """<label class="scope-option" for="grant_history"><input id="grant_history" type="checkbox" name="grant_history" value="true" data-optional-scope>
<span><strong>Loxone history / Loxone-Historie</strong><small>Optional: read bounded statistics and control history. / Optional: Begrenzte Statistiken und Control-Historie lesen.</small></span></label>"""
            if HISTORY_SCOPE in transaction.scopes
            else ""
        )
        control_requested = CONTROL_SCOPE in transaction.scopes
        control_option = (
            """<label class="scope-option" for="grant_control"><input id="grant_control" type="checkbox" name="grant_control" value="true" data-optional-scope>
<span><strong>Loxone control / Loxone-Steuerung</strong><small>Optional: execute narrowly documented actions on permitted controls. / Optional: Eng dokumentierte Aktionen auf freigegebenen Controls ausführen.</small></span></label>"""
            if control_requested
            else ""
        )
        loxberry_requested = LOXBERRY_READ_SCOPE in transaction.scopes
        loxberry_approval = (
            " Locally approved for this client, identity and Miniserver. / Lokal für diesen Client, diese Identität und diesen Miniserver freigegeben."
            if transaction.loxberry_read_locally_approved
            else " Local approval is requested after consent. / Die lokale Freigabe wird nach der Zustimmung angefordert."
        )
        loxberry_option = (
            """<label class="scope-option" for="grant_loxberry"><input id="grant_loxberry" type="checkbox" name="grant_loxberry" value="true" data-optional-scope>
<span><strong>LoxBerry diagnostics / LoxBerry-Diagnose</strong><small>Optional: read the approved LoxBerry system, plugin and service status."""
            + loxberry_approval
            + """</small></span></label>"""
            if loxberry_requested
            else ""
        )
        operate_requested = LOXBERRY_OPERATE_SCOPE in transaction.scopes
        operate_approval = (
            " Locally approved for this client, identity and Miniserver. / Lokal für diesen Client, diese Identität und diesen Miniserver freigegeben."
            if transaction.loxberry_operate_locally_approved
            else " Local approval is requested after consent. / Die lokale Freigabe wird nach der Zustimmung angefordert."
        )
        operate_option = (
            """<label class="scope-option" for="grant_loxberry_operate"><input id="grant_loxberry_operate" type="checkbox" name="grant_loxberry_operate" value="true" data-optional-scope>
<span><strong>LoxBerry cache operation / LoxBerry-Cache-Operation</strong><small>Optional: clear only the plugin statistic cache."""
            + operate_approval
            + """</small></span></label>"""
            if operate_requested
            else ""
        )
        select_all_option = (
            """<label class="scope-select-all" for="grant_all"><input id="grant_all" type="checkbox">
<span id="grant_all_label" data-select-label="Select all / Alle auswählen" data-deselect-label="Deselect all / Alle abwählen">Select all / Alle auswählen</span></label>"""
            if any((history_option, control_option, loxberry_option, operate_option))
            else ""
        )
        select_all_script = (
            """(() => {
const selectAll = document.getElementById("grant_all");
const label = document.getElementById("grant_all_label");
const options = [...document.querySelectorAll("input[data-optional-scope]")];
if (!selectAll || !label || !options.length) return;
const sync = () => {
  const selected = options.filter((option) => option.checked).length;
  selectAll.checked = selected === options.length;
  selectAll.indeterminate = selected > 0 && selected < options.length;
  label.textContent = selectAll.checked ? label.dataset.deselectLabel : label.dataset.selectLabel;
};
selectAll.addEventListener("change", () => {
  options.forEach((option) => { option.checked = selectAll.checked; });
  sync();
});
options.forEach((option) => option.addEventListener("change", sync));
sync();
})();"""
            if select_all_option
            else ""
        )
        body = f"""<h1>Choose permissions / Berechtigungen auswählen</h1><dl>
<dt>Client</dt><dd>{html.escape(transaction.client_name)}</dd>
<dt>Miniserver</dt><dd>{html.escape(transaction.miniserver_name or "")}</dd>
<dt>Loxone identity / Loxone-Identität</dt><dd>{html.escape(transaction.identity_name or "")}</dd></dl>
<form method="post" action="/plugins/mcpserver/oauth/authorize">{self._hidden(transaction, "approve")}
<fieldset class="scope-list"><legend>Permissions / Berechtigungen</legend>
{select_all_option}
<label class="scope-option"><input type="checkbox" checked disabled><span><strong>Read access / Lesezugriff</strong><small>Required: read permitted Loxone structure and states. / Erforderlich: Freigegebene Loxone-Struktur und Zustände lesen.</small></span></label>
{history_option}{control_option}{loxberry_option}{operate_option}</fieldset>
<p class="notice">After confirmation, you will be redirected to your MCP client. / Nach der Bestätigung werden Sie zu Ihrem MCP-Client weitergeleitet.</p>
<div class="actions"><button type="submit">Confirm permissions / Berechtigungen bestätigen</button></div></form>
<form method="post" action="/plugins/mcpserver/oauth/authorize">{self._hidden(transaction, "deny")}
<div class="actions"><button type="submit">Deny / Ablehnen</button></div></form>"""
        return _html_page(
            "Authorize client",
            body,
            callback_uri=transaction.redirect_uri,
            script=select_all_script or None,
        )

    async def _authorize_post(self, request: Request) -> Response:
        form = await _form(
            request,
            allowed={
                "csrf",
                "action",
                "username",
                "password",
                "grant_control",
                "grant_history",
                "grant_loxberry",
                "grant_loxberry_operate",
            },
        )
        transaction_id = request.cookies.get(_COOKIE_NAME, "")
        transaction = self.transactions.get(transaction_id)
        if (
            form is None
            or transaction is None
            or not hmac.compare_digest(form.get("csrf", ""), transaction.csrf_token)
            or transaction.created_at + _TRANSACTION_TTL <= int(time.time())
        ):
            return _message_page(
                "Authorization expired",
                "Authorization expired / Autorisierung abgelaufen",
                "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
                status=400,
            )
        action = form.get("action")
        async with transaction.lock:
            if self.transactions.get(transaction_id) is not transaction:
                return _message_page(
                    "Authorization expired",
                    "Authorization expired / Autorisierung abgelaufen",
                    "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
                    status=400,
                )
            if action == "login" and transaction.phase == "login":
                transaction.phase = "login_pending"
                return await self._login(transaction, form)
            if (
                action == "approve"
                and transaction.phase == "consent"
                and transaction.identity_id
                and transaction.miniserver_id
            ):
                grant_control = form.get("grant_control")
                grant_history = form.get("grant_history")
                grant_loxberry = form.get("grant_loxberry")
                grant_loxberry_operate = form.get("grant_loxberry_operate")
                if (
                    grant_control not in {None, "true"}
                    or (grant_control is not None and CONTROL_SCOPE not in transaction.scopes)
                    or grant_loxberry not in {None, "true"}
                    or (
                        grant_loxberry is not None and LOXBERRY_READ_SCOPE not in transaction.scopes
                    )
                    or grant_history not in {None, "true"}
                    or (grant_history is not None and HISTORY_SCOPE not in transaction.scopes)
                    or grant_loxberry_operate not in {None, "true"}
                    or (
                        grant_loxberry_operate is not None
                        and LOXBERRY_OPERATE_SCOPE not in transaction.scopes
                    )
                ):
                    return _message_page(
                        "Invalid authorization request",
                        "Invalid authorization request / Ungültige Autorisierungsanfrage",
                        "Review the requested permissions and try again. / Prüfen Sie die angeforderten Berechtigungen und versuchen Sie es erneut.",
                        status=400,
                    )
                approved_scopes: tuple[str, ...] = (READ_SCOPE,)
                if grant_history == "true":
                    approved_scopes = (*approved_scopes, HISTORY_SCOPE)
                if grant_control == "true":
                    approved_scopes = (*approved_scopes, CONTROL_SCOPE)
                pending_loxberry_read = (
                    grant_loxberry == "true" and not transaction.loxberry_read_locally_approved
                )
                if grant_loxberry == "true":
                    approved_scopes = (*approved_scopes, LOXBERRY_READ_SCOPE)
                pending_loxberry_operate = (
                    grant_loxberry_operate == "true"
                    and not transaction.loxberry_operate_locally_approved
                )
                if grant_loxberry_operate == "true":
                    if HISTORY_SCOPE not in approved_scopes:
                        return _message_page(
                            "Invalid authorization request",
                            "Invalid authorization request / Ungültige Autorisierungsanfrage",
                            "LoxBerry cache operation requires Loxone history. / Die LoxBerry-Cache-Operation benötigt Loxone-Historie.",
                            status=400,
                        )
                    approved_scopes = (*approved_scopes, LOXBERRY_OPERATE_SCOPE)
                transaction.phase = "approving"
                family_id: str | None = None
                if self.loxone_store is None:
                    if not await self._kill(transaction):
                        transaction.phase = "consent"
                        return _message_page(
                            "Authorization unavailable",
                            "Authorization unavailable / Autorisierung nicht verfügbar",
                            "The authorization could not be completed. Try again. / Die Autorisierung konnte nicht abgeschlossen werden. Versuchen Sie es erneut.",
                            status=503,
                            callback_uri=transaction.redirect_uri,
                        )
                else:
                    family_id = secrets.token_hex(16)
                    token = transaction.loxone_token
                    if token is None:
                        transaction.phase = "consent"
                        return _message_page(
                            "Authorization unavailable",
                            "Authorization unavailable / Autorisierung nicht verfügbar",
                            "The authorization could not be completed. Try again. / Die Autorisierung konnte nicht abgeschlossen werden. Versuchen Sie es erneut.",
                            status=503,
                            callback_uri=transaction.redirect_uri,
                        )
                    try:
                        self.loxone_store.put(
                            family_id,
                            transaction.miniserver_id,
                            transaction.identity_id,
                            token,
                        )
                    except Exception:
                        transaction.phase = "consent"
                        return _message_page(
                            "Authorization unavailable",
                            "Authorization unavailable / Autorisierung nicht verfügbar",
                            "The authorization could not be completed. Try again. / Die Autorisierung konnte nicht abgeschlossen werden. Versuchen Sie es erneut.",
                            status=503,
                            callback_uri=transaction.redirect_uri,
                        )
                try:
                    code = self.provider.issue_authorization_code(
                        client_id=transaction.client_id,
                        redirect_uri=transaction.redirect_uri,
                        code_challenge=transaction.code_challenge,
                        resource=transaction.resource,
                        identity_id=transaction.identity_id,
                        miniserver_id=transaction.miniserver_id,
                        scopes=approved_scopes,
                        family_id=family_id,
                        pending_loxberry_read=pending_loxberry_read,
                        pending_loxberry_operate=pending_loxberry_operate,
                    )
                except TokenError:
                    if family_id is not None and self.loxone_store is not None:
                        self.loxone_store.delete(family_id)
                    transaction.phase = "consent"
                    return _message_page(
                        "Authorization unavailable",
                        "Authorization unavailable / Autorisierung nicht verfügbar",
                        "The authorization could not be completed. Try again. / Die Autorisierung konnte nicht abgeschlossen werden. Versuchen Sie es erneut.",
                        status=503,
                        callback_uri=transaction.redirect_uri,
                    )
                transaction.loxone_token = None
                transaction.phase = "finished"
                self.transactions.pop(transaction_id, None)
                response = _redirect(
                    transaction.redirect_uri,
                    {"code": code, "state": transaction.state, "iss": self.issuer},
                )
                response.delete_cookie(_COOKIE_NAME, path="/plugins/mcpserver/oauth/authorize")
                return response
            if action == "deny" and transaction.phase in {"login", "consent"}:
                transaction.phase = "denying"
                if not await self._kill(transaction):
                    transaction.phase = "consent" if transaction.identity_id else "login"
                    return _message_page(
                        "Authorization unavailable",
                        "Authorization unavailable / Autorisierung nicht verfügbar",
                        "The authorization could not be completed. Try again. / Die Autorisierung konnte nicht abgeschlossen werden. Versuchen Sie es erneut.",
                        status=503,
                        callback_uri=transaction.redirect_uri,
                    )
                transaction.phase = "finished"
                self.transactions.pop(transaction_id, None)
                response = _redirect(
                    transaction.redirect_uri,
                    {"error": "access_denied", "state": transaction.state, "iss": self.issuer},
                )
                response.delete_cookie(_COOKIE_NAME, path="/plugins/mcpserver/oauth/authorize")
                return response
        return _message_page(
            "Invalid authorization request",
            "Invalid authorization request / Ungültige Autorisierungsanfrage",
            "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
            status=400,
        )

    async def _login(self, transaction: LoginTransaction, form: Mapping[str, str]) -> Response:
        transaction.attempts += 1
        if transaction.attempts > _MAX_LOGIN_ATTEMPTS:
            self.transactions.pop(transaction.transaction_id, None)
            transaction.phase = "finished"
            return _message_page(
                "Authorization expired",
                "Authorization expired / Autorisierung abgelaufen",
                "Restart the connection from your MCP client. / Starten Sie die Verbindung in Ihrem MCP-Client neu.",
                status=429,
            )
        username = form.get("username", "")
        password = form.get("password", "")
        now = int(time.time())
        rate_keys = self._login_rate_keys(transaction, username)
        if self._login_is_limited(rate_keys, now):
            transaction.phase = "login"
            return _message_page(
                "Sign-in temporarily unavailable",
                "Sign-in temporarily unavailable / Anmeldung vorübergehend nicht verfügbar",
                "Try again later. / Versuchen Sie es später erneut.",
                status=429,
            )
        if not username or len(username) > 128 or not password or len(password) > 1024:
            self._record_login_failure(rate_keys, now)
            transaction.phase = "login"
            return self._login_page(transaction, "Sign-in failed. / Anmeldung fehlgeschlagen.")
        client = LoxoneClient(self.endpoint, client_uuid=self._client_uuid)
        token: LoxoneToken | None = None
        try:
            async with self._login_slots:
                probe = await client.probe()
                token = await client.acquire_token(username, password)
                session = await client.open_session(token)
                try:
                    structure = await session.load_structure()
                finally:
                    await session.close()
        except Exception:
            if token is not None:
                with suppress(LoxoneConnectionError):
                    await client.kill_token(token)
            self._record_login_failure(rate_keys, now)
            transaction.phase = "login"
            return self._login_page(transaction, "Sign-in failed. / Anmeldung fehlgeschlagen.")
        miniserver_id = self.provider.store.pseudonym(self.endpoint.origin, probe.serial)
        identity_id = self.provider.store.pseudonym(
            self.endpoint.origin,
            probe.serial,
            structure.identity.username,
        )
        transaction.loxone_token = token
        transaction.identity_name = structure.identity.username
        transaction.miniserver_name = probe.serial
        transaction.miniserver_id = miniserver_id
        transaction.identity_id = identity_id
        self._clear_identity_failures(rate_keys)
        transaction.loxberry_read_locally_approved = (
            LOXBERRY_READ_SCOPE in transaction.scopes
            and self.provider.loxberry_read_allowed(
                transaction.client_id, identity_id, miniserver_id
            )
        )
        transaction.loxberry_operate_locally_approved = (
            LOXBERRY_OPERATE_SCOPE in transaction.scopes
            and self.provider.loxberry_operate_allowed(
                transaction.client_id, identity_id, miniserver_id
            )
        )
        transaction.phase = "consent"
        return self._consent_page(transaction)

    async def token(self, request: Request) -> Response:
        if request.headers.get("authorization"):
            return _oauth_error("invalid_client", status=401)
        form = await _form(
            request,
            allowed={
                "grant_type",
                "client_id",
                "code",
                "redirect_uri",
                "code_verifier",
                "refresh_token",
                "scope",
                "resource",
            },
        )
        if form is None or form.get("resource") != self.resource:
            return _oauth_error("invalid_request")
        client = await self.provider.get_client(form.get("client_id", ""))
        if client is None or client.token_endpoint_auth_method != "none":
            return _oauth_error("invalid_client", status=401)
        try:
            if form.get("grant_type") == "authorization_code":
                return await self._authorization_code_token(client, form)
            if form.get("grant_type") == "refresh_token":
                return await self._refresh_token(client, form)
            return _oauth_error("unsupported_grant_type")
        except TokenError as exc:
            return _oauth_error(exc.error)

    async def _authorization_code_token(
        self, client: OAuthClientInformationFull, form: Mapping[str, str]
    ) -> Response:
        raw_code = form.get("code", "")
        verifier = form.get("code_verifier", "")
        code = await self.provider.load_authorization_code(client, raw_code)
        if (
            code is None
            or form.get("redirect_uri") != str(code.redirect_uri)
            or form.get("resource") != code.resource
            or not _PKCE_VERIFIER.fullmatch(verifier)
        ):
            return _oauth_error("invalid_grant")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        if not hmac.compare_digest(challenge, code.code_challenge):
            return _oauth_error("invalid_grant")
        token = await self.provider.exchange_authorization_code(client, code)
        return _json(token.model_dump(mode="json", exclude_none=True))

    async def _refresh_token(
        self, client: OAuthClientInformationFull, form: Mapping[str, str]
    ) -> Response:
        refresh = await self.provider.load_refresh_token(client, form.get("refresh_token", ""))
        if refresh is None or refresh.resource != form.get("resource"):
            return _oauth_error("invalid_grant")
        requested = form.get("scope")
        try:
            scopes = (
                normalize_scopes(
                    requested,
                    control_enabled=self.provider.control_enabled,
                    loxberry_read_enabled=self.provider.loxberry_read_enabled,
                    history_enabled=self.provider.history_enabled,
                    loxberry_operate_enabled=self.provider.loxberry_operate_enabled,
                )
                if requested is not None
                else tuple(refresh.scopes)
            )
        except ValueError:
            return _oauth_error("invalid_scope")
        token = await self.provider.exchange_refresh_token(client, refresh, list(scopes))
        return _json(token.model_dump(mode="json", exclude_none=True))

    async def register(self, request: Request) -> Response:
        if request.headers.get("authorization"):
            return _oauth_error("invalid_client_metadata")
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return _oauth_error("invalid_client_metadata")
        raw = await _limited_body(request, _MAX_JSON_BYTES)
        if raw is None:
            return _oauth_error("invalid_client_metadata")
        reason = "Malformed client metadata"
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
            allowed = set(OAuthClientMetadata.model_fields) | {"application_type"}
            unsupported = sorted(key for key in payload if key not in allowed)
            reason = f"Unsupported client metadata field: {', '.join(unsupported)}"
            if unsupported:
                raise ValueError
            reason = "Unsupported application type"
            if payload.get("application_type") not in {None, "native", "web"}:
                raise ValueError
            reason = "Only public clients are supported"
            if payload.get("token_endpoint_auth_method") not in {None, "none"}:
                raise ValueError
            reason = "Unsupported scope"
            try:
                scopes = normalize_scopes(
                    payload.get("scope"),
                    control_enabled=self.provider.control_enabled,
                    loxberry_read_enabled=self.provider.loxberry_read_enabled,
                    history_enabled=self.provider.history_enabled,
                    loxberry_operate_enabled=self.provider.loxberry_operate_enabled,
                )
            except (AttributeError, ValueError):
                raise ValueError from None
            reason = "Client metadata schema is invalid"
            sdk_payload = {
                key: value for key, value in payload.items() if key != "application_type"
            }
            metadata = OAuthClientMetadata.model_validate(sdk_payload)
            normalized = metadata.model_dump()
            normalized["scope"] = scope_text(list(scopes))
            normalized["token_endpoint_auth_method"] = "none"
            normalized["client_id"] = _opaque()
            normalized["client_id_issued_at"] = self.provider.now()
            full = OAuthClientInformationFull.model_validate(normalized)
            registration_key = self._registration_key(request)
            if self._registration_is_limited(registration_key):
                response = _oauth_error("temporarily_unavailable", status=429)
                response.headers["Retry-After"] = str(_REGISTRATION_RATE_WINDOW)
                return response
            reason = "Client registration was rejected"
            await self.provider.register_client(full)
            self._record_registration(registration_key)
        except (ValueError, ValidationError, TypeError, RegistrationError):
            return _json(
                {"error": "invalid_client_metadata", "error_description": reason}, status=400
            )
        return _json(full.model_dump(mode="json", exclude_none=True), status=201)

    async def revoke(self, request: Request) -> Response:
        if request.headers.get("authorization"):
            return _oauth_error("invalid_client", status=401)
        form = await _form(request, allowed={"token", "token_type_hint", "client_id"})
        if form is None:
            return _oauth_error("invalid_request")
        client = await self.provider.get_client(form.get("client_id", ""))
        if client is None or client.token_endpoint_auth_method != "none":
            return _oauth_error("invalid_client", status=401)
        await self.provider.revoke_raw_token(form.get("token", ""), client.client_id or "")
        return Response(status_code=200, headers=_security_headers())

    async def authorization_metadata(self, request: Request) -> Response:
        return _json(
            {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "registration_endpoint": f"{self.issuer}/register",
                "revocation_endpoint": f"{self.issuer}/revoke",
                "scopes_supported": [
                    READ_SCOPE,
                    HISTORY_SCOPE,
                    CONTROL_SCOPE,
                    LOXBERRY_READ_SCOPE,
                    LOXBERRY_OPERATE_SCOPE,
                ],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
            }
        )


def _opaque() -> str:
    return secrets.token_urlsafe(32)
