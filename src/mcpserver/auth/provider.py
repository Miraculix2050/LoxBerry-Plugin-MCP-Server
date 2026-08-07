"""OAuth 2.1 provider with opaque, hashed, family-bound credentials."""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from mcpserver.auth.store import AtomicJsonAuthStore, token_digest

READ_SCOPE: Final = "loxone:read"
CONTROL_SCOPE: Final = "loxone:control"
LOXBERRY_READ_SCOPE: Final = "loxberry:read"
# Retained as the Phase 1 source-level alias used by existing integrations.
SCOPE: Final = READ_SCOPE
SUPPORTED_SCOPES: Final = (READ_SCOPE, CONTROL_SCOPE, LOXBERRY_READ_SCOPE)
_LOGGER = logging.getLogger("mcpserver.auth.provider")
AUTHORIZATION_CODE_TTL: Final = 5 * 60
ACCESS_TOKEN_TTL: Final = 10 * 60
REFRESH_FAMILY_TTL: Final = 30 * 24 * 60 * 60
EXPLORER_CLIENT_NAME: Final = "LoxBerry MCP Tool Explorer"
EXPLORER_REFRESH_FAMILY_TTL: Final = 8 * 60 * 60
_EXPLORER_CALLBACK_PATH: Final = "/admin/plugins/mcpserver/explorer_callback.cgi"
_MAX_REGISTERED_CLIENTS: Final = 256
_MAX_ACTIVE_FAMILIES: Final = 256
_MAX_FAMILIES_PER_CLIENT: Final = 16
_UNUSED_CLIENT_TTL: Final = 24 * 60 * 60


class StoredAuthorizationCode(AuthorizationCode):
    family_id: str
    identity_id: str
    miniserver_id: str


class StoredRefreshToken(RefreshToken):
    family_id: str
    resource: str
    identity_id: str
    miniserver_id: str


class StoredAccessToken(AccessToken):
    family_id: str
    identity_id: str
    miniserver_id: str


def _opaque_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_scopes(
    value: str | None, *, control_enabled: bool, loxberry_read_enabled: bool = False
) -> tuple[str, ...]:
    """Return the canonical supported scope set without allowing control alone."""
    requested = value.split() if value else [READ_SCOPE]
    if len(requested) != len(set(requested)) or set(requested) - set(SUPPORTED_SCOPES):
        raise ValueError("unsupported scope")
    if (
        READ_SCOPE not in requested
        or (CONTROL_SCOPE in requested and not control_enabled)
        or (LOXBERRY_READ_SCOPE in requested and not loxberry_read_enabled)
    ):
        raise ValueError("unsupported scope")
    return tuple(scope for scope in SUPPORTED_SCOPES if scope in requested)


def scope_text(scopes: tuple[str, ...] | list[str]) -> str:
    return " ".join(scopes)


def redirect_uri_is_allowed(value: str) -> bool:
    """Allow HTTPS callbacks and registered HTTP loopback callbacks only."""
    parsed = urlsplit(value)
    if (
        parsed.hostname is None
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in parsed.netloc
        or set(parse_qs(parsed.query, keep_blank_values=True)) & {"code", "error", "iss", "state"}
    ):
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    try:
        host = parsed.hostname.lower()
        return host == "localhost" or host == "127.0.0.1" or host == "::1"
    except ValueError:
        return False


class Phase0OAuthProvider(
    OAuthAuthorizationServerProvider[
        StoredAuthorizationCode,
        StoredRefreshToken,
        StoredAccessToken,
    ]
):
    """MCP SDK provider with exact audience and refresh-family semantics."""

    def __init__(
        self,
        store: AtomicJsonAuthStore,
        *,
        issuer: str,
        resource: str,
        clock: Callable[[], float] = time.time,
        on_family_revoked: Callable[[str], None] | None = None,
        control_enabled: bool = False,
        loxberry_read_enabled: bool = False,
        loxberry_read_allowed: Callable[[str, str, str], bool] | None = None,
        explorer_origins: tuple[str, ...] = (),
    ) -> None:
        self.store = store
        self.issuer = issuer
        self.resource = resource
        self._clock = clock
        self._on_family_revoked = on_family_revoked
        self.control_enabled = control_enabled
        self.loxberry_read_enabled = loxberry_read_enabled
        self._loxberry_read_allowed = loxberry_read_allowed
        canonical_origin = issuer.rsplit("/plugins/mcpserver/oauth", 1)[0]
        self.explorer_origins = frozenset((canonical_origin, *explorer_origins))
        self.store.mutate(self._garbage_collect)

    def now(self) -> int:
        return int(self._clock())

    def loxberry_read_allowed(self, client_id: str, identity_id: str, miniserver_id: str) -> bool:
        """Evaluate the locally administered Phase 3 binding live."""
        return bool(
            self.loxberry_read_enabled
            and self._loxberry_read_allowed is not None
            and self._loxberry_read_allowed(client_id, identity_id, miniserver_id)
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        record: dict[str, Any] | None = None

        def load(document: dict[str, Any]) -> None:
            nonlocal record
            self._garbage_collect(document)
            record = document["clients"].get(client_id)

        self.store.mutate(load)
        return OAuthClientInformationFull.model_validate(record) if record is not None else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        try:
            scopes = normalize_scopes(
                client_info.scope,
                control_enabled=self.control_enabled,
                loxberry_read_enabled=self.loxberry_read_enabled,
            )
        except ValueError:
            scopes = ()
        if (
            not client_info.client_id
            or client_info.client_secret is not None
            or client_info.token_endpoint_auth_method != "none"
            or client_info.redirect_uris is None
            or not client_info.redirect_uris
            or any(not redirect_uri_is_allowed(str(uri)) for uri in client_info.redirect_uris)
            or set(client_info.grant_types) != {"authorization_code", "refresh_token"}
            or len(client_info.grant_types) != 2
            or client_info.response_types != ["code"]
            or not scopes
        ):
            raise RegistrationError("invalid_client_metadata", "Unsupported public client metadata")

        record = client_info.model_dump(mode="json", exclude_none=True)
        record["scope"] = scope_text(list(scopes))

        def insert(document: dict[str, Any]) -> None:
            self._garbage_collect(document)
            if client_info.client_id in document["clients"]:
                raise RegistrationError(
                    "invalid_client_metadata", "Client identifier already exists"
                )
            if len(document["clients"]) >= _MAX_REGISTERED_CLIENTS:
                raise RegistrationError(
                    "invalid_client_metadata", "Client registration capacity reached"
                )
            document["clients"][client_info.client_id] = record

        self.store.mutate(insert)

    def _garbage_collect(self, document: dict[str, Any]) -> None:
        now = self.now()
        for family in document["families"].values():
            client = document["clients"].get(family.get("client_id"), {})
            if family.get("client_kind") == "tool_explorer" or self._is_explorer_client(client):
                family["client_kind"] = "tool_explorer"
                family["expires_at"] = min(
                    int(family.get("expires_at", 0)), now + EXPLORER_REFRESH_FAMILY_TTL
                )
        expired_families = {
            family_id
            for family_id, record in document["families"].items()
            if record.get("expires_at", 0) <= now
        }
        for family_id in expired_families:
            document["families"].pop(family_id, None)
            if self._on_family_revoked is not None:
                self._on_family_revoked(family_id)
        document["codes"] = {
            digest: record
            for digest, record in document["codes"].items()
            if record.get("expires_at", 0) > now and record.get("family_id") not in expired_families
        }
        document["access_tokens"] = {
            digest: record
            for digest, record in document["access_tokens"].items()
            if record.get("expires_at", 0) > now and record.get("family_id") not in expired_families
        }
        document["refresh_tokens"] = {
            digest: record
            for digest, record in document["refresh_tokens"].items()
            if record.get("family_id") not in expired_families
        }
        referenced_clients = {
            str(record.get("client_id"))
            for collection in ("codes", "families", "access_tokens", "refresh_tokens")
            for record in document[collection].values()
            if record.get("client_id")
        }
        document["clients"] = {
            client_id: record
            for client_id, record in document["clients"].items()
            if client_id in referenced_clients
            or int(record.get("client_id_issued_at", now)) + _UNUSED_CLIENT_TTL > now
        }

    def _is_explorer_client(self, client: dict[str, Any]) -> bool:
        redirects = client.get("redirect_uris")
        if client.get("client_name") != EXPLORER_CLIENT_NAME or not isinstance(redirects, list):
            return False
        if len(redirects) != 1 or not isinstance(redirects[0], str):
            return False
        redirect = urlsplit(redirects[0])
        origin = f"{redirect.scheme}://{redirect.netloc}"
        return (
            redirect.path == _EXPLORER_CALLBACK_PATH
            and not redirect.query
            and not redirect.fragment
            and origin in self.explorer_origins
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        raise NotImplementedError("The browser authorization route owns this flow")

    def issue_authorization_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        resource: str,
        identity_id: str,
        miniserver_id: str,
        scopes: tuple[str, ...] = (READ_SCOPE,),
        family_id: str | None = None,
    ) -> str:
        if resource != self.resource:
            raise TokenError("invalid_grant", "Resource mismatch")
        try:
            validated_scopes = normalize_scopes(
                scope_text(list(scopes)),
                control_enabled=self.control_enabled,
                loxberry_read_enabled=self.loxberry_read_enabled,
            )
        except ValueError as exc:
            raise TokenError("invalid_scope", "Unsupported authorization scope") from exc
        if validated_scopes != scopes:
            raise TokenError("invalid_scope", "Authorization scopes must be canonical")
        if LOXBERRY_READ_SCOPE in scopes and not self.loxberry_read_allowed(
            client_id, identity_id, miniserver_id
        ):
            raise TokenError("invalid_scope", "LoxBerry diagnostics require local approval")
        raw_code = _opaque_token()
        digest = token_digest(raw_code)
        now = self.now()
        family_id = family_id or secrets.token_hex(16)
        record = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "resource": resource,
            "scopes": list(validated_scopes),
            "expires_at": now + AUTHORIZATION_CODE_TTL,
            "family_id": family_id,
            "identity_id": identity_id,
            "miniserver_id": miniserver_id,
            "status": "active",
        }

        def insert(document: dict[str, Any]) -> None:
            self._garbage_collect(document)
            client_record = document["clients"].get(client_id)
            if client_record is None:
                raise TokenError("invalid_client", "Client registration is unavailable")
            active_families = [
                item for item in document["families"].values() if not item.get("revoked", False)
            ]
            if len(active_families) >= _MAX_ACTIVE_FAMILIES:
                raise TokenError("invalid_request", "Session capacity reached")
            if (
                sum(item.get("client_id") == client_id for item in active_families)
                >= _MAX_FAMILIES_PER_CLIENT
            ):
                raise TokenError("invalid_request", "Client session capacity reached")
            document["codes"][digest] = record
            is_explorer = self._is_explorer_client(client_record)
            family_ttl = EXPLORER_REFRESH_FAMILY_TTL if is_explorer else REFRESH_FAMILY_TTL
            document["families"][family_id] = {
                "client_id": client_id,
                "identity_id": identity_id,
                "miniserver_id": miniserver_id,
                "scope": scope_text(list(validated_scopes)),
                "resource": resource,
                "expires_at": now + family_ttl,
                "revoked": False,
                **({"client_kind": "tool_explorer"} if is_explorer else {}),
            }

        self.store.mutate(insert)
        return raw_code

    @staticmethod
    def _code_model(raw_code: str, record: dict[str, Any]) -> StoredAuthorizationCode:
        return StoredAuthorizationCode(
            code=raw_code,
            scopes=record["scopes"],
            expires_at=record["expires_at"],
            client_id=record["client_id"],
            code_challenge=record["code_challenge"],
            redirect_uri=AnyUrl(record["redirect_uri"]),
            redirect_uri_provided_explicitly=True,
            resource=record["resource"],
            family_id=record["family_id"],
            identity_id=record["identity_id"],
            miniserver_id=record["miniserver_id"],
            subject=record["identity_id"],
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> StoredAuthorizationCode | None:
        record = self.store.snapshot()["codes"].get(token_digest(authorization_code))
        if (
            record is None
            or record.get("status") != "active"
            or record.get("client_id") != client.client_id
            or record.get("expires_at", 0) <= self.now()
        ):
            return None
        return self._code_model(authorization_code, record)

    def _new_token_records(
        self,
        *,
        family_id: str,
        client_id: str,
        identity_id: str,
        miniserver_id: str,
        resource: str,
        family_expires_at: int,
        scopes: list[str],
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        now = self.now()
        raw_access = _opaque_token()
        raw_refresh = _opaque_token()
        access_record = {
            "client_id": client_id,
            "scopes": scopes,
            "expires_at": min(now + ACCESS_TOKEN_TTL, family_expires_at),
            "resource": resource,
            "family_id": family_id,
            "identity_id": identity_id,
            "miniserver_id": miniserver_id,
            "status": "active",
        }
        refresh_record = {
            "client_id": client_id,
            "scopes": scopes,
            "expires_at": family_expires_at,
            "resource": resource,
            "family_id": family_id,
            "identity_id": identity_id,
            "miniserver_id": miniserver_id,
            "status": "active",
        }
        return raw_access, raw_refresh, access_record, refresh_record

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: StoredAuthorizationCode,
    ) -> OAuthToken:
        raw_access = ""
        raw_refresh = ""
        access_expires_at = 0

        def exchange(document: dict[str, Any]) -> None:
            nonlocal access_expires_at, raw_access, raw_refresh
            self._garbage_collect(document)
            digest = token_digest(authorization_code.code)
            record = document["codes"].get(digest)
            if (
                record is None
                or record.get("status") != "active"
                or record.get("client_id") != client.client_id
                or record.get("expires_at", 0) <= self.now()
            ):
                raise TokenError("invalid_grant", "Authorization code is invalid")
            family = document["families"].get(record["family_id"])
            if family is None or family["revoked"] or family["expires_at"] <= self.now():
                raise TokenError("invalid_grant", "Authorization session is invalid")
            record["status"] = "consumed"
            raw_access, raw_refresh, access, refresh = self._new_token_records(
                family_id=record["family_id"],
                client_id=record["client_id"],
                identity_id=record["identity_id"],
                miniserver_id=record["miniserver_id"],
                resource=record["resource"],
                family_expires_at=family["expires_at"],
                scopes=list(record["scopes"]),
            )
            document["access_tokens"][token_digest(raw_access)] = access
            document["refresh_tokens"][token_digest(raw_refresh)] = refresh
            access_expires_at = access["expires_at"]

        self.store.mutate(exchange)
        return OAuthToken(
            access_token=raw_access,
            token_type="Bearer",
            expires_in=max(0, access_expires_at - self.now()),
            scope=scope_text(list(authorization_code.scopes)),
            refresh_token=raw_refresh,
        )

    def _revoke_family(self, document: dict[str, Any], family_id: str) -> None:
        family = document["families"].get(family_id)
        if family is not None:
            family["revoked"] = True
        for collection in ("access_tokens", "refresh_tokens"):
            for record in document[collection].values():
                if record.get("family_id") == family_id:
                    record["status"] = "revoked"
        if self._on_family_revoked is not None:
            try:
                self._on_family_revoked(family_id)
            except Exception as exc:
                _LOGGER.warning(
                    "component=oauth severity=WARNING outcome=token_cleanup_failed error_type=%s",
                    type(exc).__name__,
                )

    @staticmethod
    def _refresh_model(raw_token: str, record: dict[str, Any]) -> StoredRefreshToken:
        return StoredRefreshToken(
            token=raw_token,
            client_id=record["client_id"],
            scopes=record["scopes"],
            expires_at=record["expires_at"],
            subject=record["identity_id"],
            family_id=record["family_id"],
            resource=record["resource"],
            identity_id=record["identity_id"],
            miniserver_id=record["miniserver_id"],
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> StoredRefreshToken | None:
        result: StoredRefreshToken | None = None

        def load(document: dict[str, Any]) -> None:
            nonlocal result
            self._garbage_collect(document)
            record = document["refresh_tokens"].get(token_digest(refresh_token))
            if record is None or record.get("client_id") != client.client_id:
                return
            family = document["families"].get(record["family_id"])
            if record.get("status") == "consumed":
                self._revoke_family(document, record["family_id"])
                return
            if (
                record.get("status") != "active"
                or family is None
                or family["revoked"]
                or record["expires_at"] <= self.now()
                or family["expires_at"] <= self.now()
            ):
                return
            result = self._refresh_model(refresh_token, record)

        self.store.mutate(load)
        return result

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if scopes != list(refresh_token.scopes):
            raise TokenError("invalid_scope", "Refresh cannot change the authorized scopes")
        raw_access = ""
        raw_refresh = ""
        access_expires_at = 0
        failure: str | None = None

        def exchange(document: dict[str, Any]) -> None:
            nonlocal access_expires_at, failure, raw_access, raw_refresh
            self._garbage_collect(document)
            record = document["refresh_tokens"].get(token_digest(refresh_token.token))
            if record is None or record.get("client_id") != client.client_id:
                failure = "Refresh token is invalid"
                return
            family = document["families"].get(record["family_id"])
            if record.get("status") != "active":
                self._revoke_family(document, record["family_id"])
                failure = "Refresh token is invalid"
                return
            if family is None or family["revoked"] or family["expires_at"] <= self.now():
                failure = "Refresh session is invalid"
                return
            record["status"] = "consumed"
            raw_access, raw_refresh, access, refresh = self._new_token_records(
                family_id=record["family_id"],
                client_id=record["client_id"],
                identity_id=record["identity_id"],
                miniserver_id=record["miniserver_id"],
                resource=record["resource"],
                family_expires_at=family["expires_at"],
                scopes=list(record["scopes"]),
            )
            document["access_tokens"][token_digest(raw_access)] = access
            document["refresh_tokens"][token_digest(raw_refresh)] = refresh
            access_expires_at = access["expires_at"]

        self.store.mutate(exchange)
        if failure is not None:
            raise TokenError("invalid_grant", failure)
        return OAuthToken(
            access_token=raw_access,
            token_type="Bearer",
            expires_in=max(0, access_expires_at - self.now()),
            scope=scope_text(scopes),
            refresh_token=raw_refresh,
        )

    async def load_access_token(self, token: str) -> StoredAccessToken | None:
        document: dict[str, Any] = {}

        def load(current: dict[str, Any]) -> None:
            nonlocal document
            self._garbage_collect(current)
            document = current

        self.store.mutate(load)
        record = document["access_tokens"].get(token_digest(token))
        if record is None or record.get("status") != "active" or record["expires_at"] <= self.now():
            return None
        family = document["families"].get(record["family_id"])
        if (
            family is None
            or family["revoked"]
            or family["expires_at"] <= self.now()
            or record["resource"] != self.resource
        ):
            return None
        return StoredAccessToken(
            token=token,
            client_id=record["client_id"],
            scopes=record["scopes"],
            expires_at=record["expires_at"],
            resource=record["resource"],
            subject=record["identity_id"],
            claims={
                "iss": self.issuer,
                "identity": record["identity_id"],
                "miniserver": record["miniserver_id"],
                "audience": record["resource"],
            },
            family_id=record["family_id"],
            identity_id=record["identity_id"],
            miniserver_id=record["miniserver_id"],
        )

    async def revoke_token(self, token: StoredAccessToken | StoredRefreshToken) -> None:
        self.store.mutate(lambda document: self._revoke_family(document, token.family_id))

    async def revoke_raw_token(self, raw_token: str, client_id: str) -> None:
        digest = token_digest(raw_token)

        def revoke(document: dict[str, Any]) -> None:
            for collection in ("access_tokens", "refresh_tokens"):
                record = document[collection].get(digest)
                if record is not None and record.get("client_id") == client_id:
                    self._revoke_family(document, record["family_id"])
                    return

        self.store.mutate(revoke)

    def revoke_scope_locally(self, scope: str) -> int:
        """Fail closed for a disabled scope without discarding remote token material."""
        revoked: list[str] = []

        def revoke(document: dict[str, Any]) -> None:
            for family_id, family in document["families"].items():
                if (
                    family.get("revoked", False)
                    or scope not in str(family.get("scope", "")).split()
                ):
                    continue
                family["revoked"] = True
                revoked.append(family_id)
                for collection in ("codes", "access_tokens", "refresh_tokens"):
                    for record in document[collection].values():
                        if record.get("family_id") == family_id:
                            record["status"] = "revoked"

        self.store.mutate(revoke)
        return len(revoked)
