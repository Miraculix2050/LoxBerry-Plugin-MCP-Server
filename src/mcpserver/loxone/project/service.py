"""Identity-bound orchestration; cached content never grants permission."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneToken,
    LoxoneTokenAuthenticationRejected,
)
from mcpserver.loxone.events import LoxoneProtocolError
from mcpserver.loxone.models import LoxoneStructure

from .graph import ProjectSnapshot
from .mapping import ProjectView, map_runtime
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .query import ProjectQuery
from .worker import process_project

if TYPE_CHECKING:
    from mcpserver.loxone.runtime import RuntimeSnapshot

_LOGGER = logging.getLogger(__name__)
_MAX_CACHE_BYTES = 128 * 1024 * 1024
_MAX_CACHE_ENTRIES = 8
_MAX_VIEW_CACHE_BYTES = 64 * 1024 * 1024


class ProjectService:
    def __init__(
        self,
        client: LoxoneClient,
        tokens: EncryptedLoxoneTokenStore,
        health: LoxoneTokenHealthStore,
        validate: Callable[[StoredAccessToken], Awaitable[bool]],
        limits: ProjectLimits = DEFAULT_LIMITS,
        marker_reader: Callable[[LoxoneToken], Awaitable[str]] | None = None,
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.health = health
        self.validate = validate
        self.marker_reader = marker_reader
        self.limits = limits
        self._closed = False
        self._tasks: dict[asyncio.Task[object], str] = {}
        self._slot = asyncio.Semaphore(1)
        self._cache: OrderedDict[tuple[str, str, str], tuple[str, ProjectSnapshot, int]] = (
            OrderedDict()
        )
        self._markers: dict[tuple[str, str, str], str] = {}
        self._views: OrderedDict[
            tuple[str, str, str, str],
            tuple[LoxoneStructure, ProjectView, ProjectQuery | None, int],
        ] = OrderedDict()
        self.cache_counts = {"hit": 0, "miss": 0, "invalidate": 0, "evict": 0}

    def _record_cache(self, outcome: str) -> None:
        self.cache_counts[outcome] += 1
        _LOGGER.debug(
            "component=project_cache outcome=%s count=%d",
            outcome,
            self.cache_counts[outcome],
        )

    async def _check(self, access: StoredAccessToken) -> None:
        if self._closed or READ_SCOPE not in access.scopes or not await self.validate(access):
            raise ProjectError("project_access_denied")
        if self.health.get(access.family_id).confirmation_required:
            raise ProjectError("project_token_confirmation_required")

    async def authorize(self, access: StoredAccessToken) -> None:
        """Recheck authorization before a separately bounded result is released."""
        await self._check(access)

    async def _marker(self, token: LoxoneToken) -> str:
        try:
            reader = self.marker_reader or self.client.project_marker
            marker = await reader(token)
            if not isinstance(marker, str) or not marker or len(marker) > 128:
                raise ProjectError("project_marker_invalid")
            return marker
        except LoxoneTokenAuthenticationRejected:
            raise ProjectError("project_permission_denied") from None
        except (LoxoneConnectionError, LoxoneProtocolError, TimeoutError):
            raise ProjectError("project_transport_error") from None

    async def load_bundle(self, access: StoredAccessToken) -> ProjectBundle:
        result = await self._load(access, bundle_only=True, verified_marker=None)
        assert isinstance(result, ProjectBundle)
        return result

    async def load_snapshot(
        self, access: StoredAccessToken, *, verified_marker: str | None = None
    ) -> ProjectSnapshot:
        result = await self._load(access, bundle_only=False, verified_marker=verified_marker)
        assert isinstance(result, ProjectSnapshot)
        return result

    async def view(self, access: StoredAccessToken, runtime: "RuntimeSnapshot") -> ProjectView:
        if runtime.subject != access.family_id:
            raise ProjectError("project_identity_mismatch")
        snapshot = await self.load_snapshot(access, verified_marker=runtime.structure.last_modified)
        cache_key = (access.miniserver_id, access.identity_id, access.family_id)
        marker = self._markers.get(cache_key)
        if marker is None:
            raise ProjectError("project_changed_during_load")
        view_key = (*cache_key, marker)
        cached = self._views.get(view_key)
        if cached is not None and cached[0] == runtime.structure:
            self._views.move_to_end(view_key)
            return cached[1]
        mapping = map_runtime(snapshot, runtime.structure)
        view = ProjectView(snapshot, mapping, marker)
        if cache_key in self._cache:
            size = len(mapping.entries) * 512
            if size <= _MAX_VIEW_CACHE_BYTES:
                self._views[view_key] = (runtime.structure, view, None, size)
                self._views.move_to_end(view_key)
                self._prune_views()
        return view

    async def query(self, access: StoredAccessToken, runtime: "RuntimeSnapshot") -> ProjectQuery:
        view = await self.view(access, runtime)
        cache_key = (access.miniserver_id, access.identity_id, access.family_id)
        view_key = (*cache_key, view.marker)
        cached = self._views.get(view_key)
        if cached is not None and cached[0] == runtime.structure and cached[2] is not None:
            return cached[2]
        names: dict[str, str] = {}
        pending = list(runtime.structure.controls)
        while pending:
            control = pending.pop()
            names[control.uuid] = control.name
            pending.extend(control.subcontrols)
        query = ProjectQuery(view, names)
        if cached is not None:
            size = cached[3] + len(view.snapshot.graph.nodes) * 256
            if size <= _MAX_VIEW_CACHE_BYTES:
                self._views[view_key] = (runtime.structure, view, query, size)
                self._views.move_to_end(view_key)
                self._prune_views()
        return query

    def _prune_views(self) -> None:
        while (
            len(self._views) > _MAX_CACHE_ENTRIES
            or sum(value[3] for value in self._views.values()) > _MAX_VIEW_CACHE_BYTES
        ):
            self._views.popitem(last=False)

    def _invalidate_views(self, cache_key: tuple[str, str, str]) -> None:
        for key in tuple(self._views):
            if key[:3] == cache_key:
                self._views.pop(key)

    async def _load(
        self, access: StoredAccessToken, *, bundle_only: bool, verified_marker: str | None
    ) -> ProjectBundle | ProjectSnapshot:
        cache_key = (access.miniserver_id, access.identity_id, access.family_id)
        task = asyncio.current_task()
        if task is None:
            raise ProjectError("project_task_unavailable")
        self._tasks[task] = access.family_id
        try:
            async with self._slot:
                await self._check(access)
                token = self.tokens.get(access.family_id, access.miniserver_id, access.identity_id)
                if token is None:
                    raise ProjectError("project_token_unavailable")
                try:
                    if bundle_only:
                        data = await self.client.download_project(token, self.limits)
                        await self._check(access)
                        bundle, _ = await process_project(data, self.limits, bundle_only=True)
                        assert isinstance(bundle, ProjectBundle)
                        await self._check(access)
                        return bundle
                    marker = (
                        verified_marker
                        if verified_marker is not None
                        else await self._marker(token)
                    )
                    if not marker or len(marker) > 128:
                        raise ProjectError("project_marker_invalid")
                    # A supplied runtime marker needs no network await; the
                    # initial authorization check still covers a cache hit.
                    if verified_marker is None:
                        await self._check(access)
                    cached = self._cache.get(cache_key)
                    if cached is not None and cached[0] == marker:
                        self._cache.move_to_end(cache_key)
                        self._markers[cache_key] = marker
                        self._record_cache("hit")
                        return cached[1]
                    if cached is not None:
                        self._cache.pop(cache_key)
                        self._invalidate_views(cache_key)
                        self._record_cache("invalidate")
                    self._record_cache("miss")
                    data = await self.client.download_project(token, self.limits)
                    await self._check(access)
                    snapshot, serialized_size = await process_project(data, self.limits)
                    assert isinstance(snapshot, ProjectSnapshot)
                    await self._check(access)
                    if await self._marker(token) != marker:
                        raise ProjectError("project_changed_during_load")
                    await self._check(access)
                    self._markers[cache_key] = marker
                finally:
                    token.destroy()
                # Conservative object overhead allowance in addition to serialized content.
                size = (
                    serialized_size * 4
                    + sum(project.element_count * 128 for project in snapshot.projects)
                    + (len(snapshot.graph.nodes) + len(snapshot.graph.edges)) * 512
                )
                if size <= _MAX_CACHE_BYTES:
                    self._cache[cache_key] = (marker, snapshot, size)
                    self._cache.move_to_end(cache_key)
                    while (
                        len(self._cache) > _MAX_CACHE_ENTRIES
                        or sum(v[2] for v in self._cache.values()) > _MAX_CACHE_BYTES
                    ):
                        evicted_key, _ = self._cache.popitem(last=False)
                        self._markers.pop(evicted_key, None)
                        self._invalidate_views(evicted_key)
                        self._record_cache("evict")
                return snapshot
        except BaseException:
            self._markers.pop(cache_key, None)
            self._invalidate_views(cache_key)
            if self._cache.pop(cache_key, None) is not None:
                self._record_cache("invalidate")
            raise
        finally:
            self._tasks.pop(task, None)

    def invalidate(self, family_id: str) -> None:
        """Discard unverified project generations without cancelling callers."""
        for key in tuple(self._cache):
            if key[2] == family_id:
                self._cache.pop(key)
                self._markers.pop(key, None)
                self._invalidate_views(key)
                self._record_cache("invalidate")
        for key in tuple(self._markers):
            if key[2] == family_id:
                self._markers.pop(key)
                self._invalidate_views(key)

    async def revoke(self, family_id: str) -> None:
        self.invalidate(family_id)
        tasks = [task for task, family in self._tasks.items() if family == family_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        self._cache.clear()
        self._markers.clear()
        self._views.clear()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
