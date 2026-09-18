"""Identity-bound orchestration; cached content never grants permission."""

import asyncio
from collections.abc import Awaitable, Callable

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import LoxoneClient

from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .source import unpack_project


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

    async def _check(self, access: StoredAccessToken) -> None:
        if self._closed or READ_SCOPE not in access.scopes or not await self.validate(access):
            raise ProjectError("project_access_denied")
        if self.health.get(access.family_id).confirmation_required:
            raise ProjectError("project_token_confirmation_required")

    async def load_bundle(self, access: StoredAccessToken) -> ProjectBundle:
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
                bundle = await asyncio.to_thread(unpack_project, data, self.limits)
                await self._check(access)
                return bundle
        finally:
            self._tasks.pop(task, None)

    async def revoke(self, family_id: str) -> None:
        tasks = [task for task, family in self._tasks.items() if family == family_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
