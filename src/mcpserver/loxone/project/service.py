"""Identity-bound orchestration; cached content never grants permission."""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import LoxoneClient

from .graph import ProjectSnapshot
from .mapping import ProjectView, map_runtime
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .worker import process_project

if TYPE_CHECKING:
    from mcpserver.loxone.runtime import RuntimeSnapshot


class ProjectService:
    def __init__(
        self,
        client: LoxoneClient,
        tokens: EncryptedLoxoneTokenStore,
        health: LoxoneTokenHealthStore,
        validate: Callable[[StoredAccessToken], Awaitable[bool]],
        limits: ProjectLimits = DEFAULT_LIMITS,
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.health = health
        self.validate = validate
        self.limits = limits
        self._closed = False
        self._tasks: dict[asyncio.Task[object], str] = {}
        self._slot = asyncio.Semaphore(1)
        self._cache: OrderedDict[tuple[str, str, str], tuple[ProjectSnapshot, int]] = OrderedDict()

    async def _check(self, access: StoredAccessToken) -> None:
        if self._closed or READ_SCOPE not in access.scopes or not await self.validate(access):
            raise ProjectError("project_access_denied")
        if self.health.get(access.family_id).confirmation_required:
            raise ProjectError("project_token_confirmation_required")

    async def authorize(self, access: StoredAccessToken) -> None:
        """Recheck authorization before a separately bounded result is released."""
        await self._check(access)

    async def load_bundle(self, access: StoredAccessToken) -> ProjectBundle:
        result = await self._load(access, bundle_only=True)
        assert isinstance(result, ProjectBundle)
        return result

    async def load_snapshot(self, access: StoredAccessToken) -> ProjectSnapshot:
        result = await self._load(access, bundle_only=False)
        assert isinstance(result, ProjectSnapshot)
        return result

    async def view(self, access: StoredAccessToken, runtime: "RuntimeSnapshot") -> ProjectView:
        if runtime.subject != access.family_id:
            raise ProjectError("project_identity_mismatch")
        snapshot = await self.load_snapshot(access)
        mapping = map_runtime(snapshot, runtime.structure)
        await self._check(access)
        return ProjectView(snapshot, mapping)

    async def _load(
        self, access: StoredAccessToken, *, bundle_only: bool
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
                    data = await self.client.download_project(token, self.limits)
                finally:
                    token.destroy()
                await self._check(access)
                bundle, _ = await process_project(data, self.limits, bundle_only=True)
                assert isinstance(bundle, ProjectBundle)
                await self._check(access)
                if bundle_only:
                    return bundle
                cached = self._cache.get(cache_key)
                if cached is not None and cached[0].fingerprint == bundle.fingerprint:
                    self._cache.move_to_end(cache_key)
                    return cached[0]
                snapshot, serialized_size = await process_project(data, self.limits)
                assert isinstance(snapshot, ProjectSnapshot)
                await self._check(access)
                # Conservative object overhead allowance in addition to serialized content.
                size = (
                    serialized_size * 4
                    + sum(project.element_count * 128 for project in snapshot.projects)
                    + (len(snapshot.graph.nodes) + len(snapshot.graph.edges)) * 512
                )
                if size <= 128 * 1024 * 1024:
                    self._cache[cache_key] = (snapshot, size)
                    self._cache.move_to_end(cache_key)
                    while (
                        len(self._cache) > 8
                        or sum(v[1] for v in self._cache.values()) > 128 * 1024 * 1024
                    ):
                        self._cache.popitem(last=False)
                return snapshot
        except BaseException:
            self._cache.pop(cache_key, None)
            raise
        finally:
            self._tasks.pop(task, None)

    async def revoke(self, family_id: str) -> None:
        for key in tuple(self._cache):
            if key[2] == family_id:
                self._cache.pop(key)
        tasks = [task for task, family in self._tasks.items() if family == family_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        self._cache.clear()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
