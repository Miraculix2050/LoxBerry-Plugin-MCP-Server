"""Narrow, independently approved MCP mutations of installation metadata."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from pathlib import Path
from typing import Any

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.installation_profile import (
    ProfileBindingInput,
    ProfileError,
    ProfileSources,
    ProfileStore,
    installation_identity,
)
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.runtime import LoxoneRuntime
from mcpserver.tools import _loxberry_binding_allowed, _snapshot

PROFILE_CAPABILITY = "installation-profile-write-binding-v1"
WRITE_TIMEOUT_SECONDS = 30.0
_LOGGER = logging.getLogger(__name__)


def profile_binding(auth: AtomicJsonAuthStore, access: StoredAccessToken) -> str:
    return auth.pseudonym(
        PROFILE_CAPABILITY, access.client_id, access.identity_id, access.miniserver_id
    )


class ProfileWriteRuntime:
    def __init__(
        self,
        runtime: LoxoneRuntime,
        path: Path,
        config: AtomicConfigStore,
        auth: AtomicJsonAuthStore,
    ) -> None:
        self.runtime = runtime
        self.path = path
        self.config = config
        self.auth = auth
        self._requests: dict[str, list[float]] = {}
        self._pending: asyncio.Task[dict[str, Any]] | None = None

    def _allowed(self, access: StoredAccessToken, config: PluginConfig) -> None:
        family = self.auth.snapshot().get("families", {}).get(access.family_id, {})
        expires = family.get("expires_at") if isinstance(family, dict) else None
        if (
            not isinstance(expires, int | float)
            or not math.isfinite(expires)
            or expires <= time.time()
        ):
            raise PermissionError("Profile mutation is not authorized")
        if (
            not {"loxone:read", "loxone:history", "loxberry:operate"}.issubset(access.scopes)
            or not {"loxone:read", "loxone:history", "loxberry:operate"}.issubset(
                str(family.get("scope", "")).split()
            )
            or not config.loxone_read_enabled
            or not config.loxberry_operate_enabled
            or not config.installation_profile_write_enabled
            or not isinstance(family, dict)
            or family.get("revoked")
            or family.get("client_id") != access.client_id
            or family.get("identity_id") != access.identity_id
            or family.get("miniserver_id") != access.miniserver_id
            or not _loxberry_binding_allowed(config, self.auth, access, "loxberry:operate")
            or profile_binding(self.auth, access) not in config.installation_profile_write_bindings
        ):
            raise PermissionError("Profile mutation is not authorized")

    def _admit(self, key: str, config: PluginConfig) -> None:
        now = time.monotonic()
        self._requests = {
            key: [stamp for stamp in values if stamp > now - 60]
            for key, values in self._requests.items()
            if values and values[-1] > now - 60
        }
        entries = self._requests.get(key, [])
        if len(entries) >= config.loxberry_operate_requests_per_minute:
            raise ProfileError("profile_rate_limited")
        if key not in self._requests and len(self._requests) >= 64:
            raise ProfileError("profile_busy")
        self._requests[key] = [*entries, now]

    async def change(
        self,
        access: StoredAccessToken,
        revision: int,
        *,
        binding: ProfileBindingInput | None = None,
        binding_id: str | None = None,
    ) -> dict[str, Any]:
        if self._pending is not None and not self._pending.done():
            raise ProfileError("profile_busy")
        task = asyncio.create_task(
            self._change(
                access, revision, binding, binding_id, time.monotonic() + WRITE_TIMEOUT_SECONDS
            )
        )
        self._pending = task

        def finished(done: asyncio.Task[dict[str, Any]]) -> None:
            # Consume and audit late completion without retrying an uncertain mutation.
            if not done.cancelled():
                self.audit(access, "profile_worker", "failed" if done.exception() else "completed")
            if self._pending is done:
                self._pending = None

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=WRITE_TIMEOUT_SECONDS)
        except ProfileError as exc:
            if exc.code == "permission_denied":
                raise PermissionError("Profile mutation is not authorized") from None
            if exc.code == "profile_deadline_expired":
                raise TimeoutError from None
            raise

    async def _change(
        self,
        access: StoredAccessToken,
        revision: int,
        binding: ProfileBindingInput | None,
        binding_id: str | None,
        deadline: float,
    ) -> dict[str, Any]:
        def policy() -> tuple[PluginConfig, str]:
            config = self.config.load()
            self._allowed(access, config)
            if (
                MiniserverEndpoint.parse(config.loxone_endpoint).origin
                != self.runtime.endpoint.origin
            ):
                raise ProfileError("profile_installation_changed")
            return config, profile_binding(self.auth, access)

        config, key = await asyncio.to_thread(policy)
        self._admit(key, config)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        fresh_access, snapshot = await asyncio.wait_for(
            _snapshot(self.runtime, fresh_visibility=True),
            timeout=remaining,
        )
        if fresh_access != access:
            raise PermissionError("Profile mutation is not authorized")
        installation = installation_identity(self.runtime.endpoint.origin, snapshot.structure)
        sources = ProfileSources.from_structure(installation, snapshot.structure)

        def mutate(current: PluginConfig, _save: object) -> dict[str, Any]:
            # PermissionError/TimeoutError inherit OSError, which the configuration
            # transaction classifies as a lock failure. Preserve policy outcomes.
            try:
                self._allowed(access, current)
            except PermissionError:
                raise ProfileError("permission_denied") from None
            if current.loxone_endpoint != config.loxone_endpoint:
                raise ProfileError("profile_installation_changed")
            store = ProfileStore(self.path)
            document = store.read(installation)
            if document.installation != installation:
                raise ProfileError("permission_denied")
            affected = (
                [item for item in document.bindings if item.binding_id == binding.binding_id]
                if binding is not None
                else [
                    item
                    for item in document.bindings
                    if binding_id is None or item.binding_id == binding_id
                ]
            )
            if any(not sources.authorized(item) for item in affected):
                raise ProfileError("permission_denied")
            if binding is not None:
                if not sources.authorized(binding):
                    raise ProfileError("permission_denied")
                if time.monotonic() >= deadline:
                    raise ProfileError("profile_deadline_expired")
                updated = store.put(
                    installation,
                    revision,
                    binding,
                    sources,
                    origin="mcp_user_confirmed",
                    actor_ref=profile_binding(self.auth, access),
                    deadline=deadline,
                )
            else:
                if time.monotonic() >= deadline:
                    raise ProfileError("profile_deadline_expired")
                updated = store.delete(installation, revision, binding_id, deadline=deadline)
            return {
                "revision": updated.revision,
                "binding_id": binding.binding_id if binding else binding_id,
            }

        return await asyncio.to_thread(self.config.transaction, mutate)

    def audit(self, access: StoredAccessToken | None, tool: str, outcome: str) -> None:
        actor = (
            hashlib.sha256(access.family_id.encode()).hexdigest()[:16]
            if access is not None
            else "unknown"
        )
        _LOGGER.warning(
            "event=installation_profile_operation tool=%s outcome=%s actor=%s",
            tool,
            outcome,
            actor,
            extra={"mcp_audit": True},
        )
