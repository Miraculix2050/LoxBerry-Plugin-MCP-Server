"""User-isolated Loxone connection and cache lifecycle for read-only tools."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneConnectionError,
    LoxoneToken,
    LoxoneWebSocketSession,
)
from mcpserver.loxone.models import Control, LoxoneStructure, StateRecord

_LOXONE_EPOCH_UNIX = 1_230_768_000
_REFRESH_BEFORE_SECONDS = 24 * 60 * 60


class RuntimeUnavailable(RuntimeError):
    """The identity-bound Loxone runtime is not currently available."""


def _state_uuids(controls: tuple[Control, ...]) -> frozenset[str]:
    result: set[str] = set()
    for control in controls:
        result.update(uuid for _name, uuid in control.state_uuids)
        result.update(_state_uuids(control.subcontrols))
    return frozenset(result)


@dataclass(slots=True)
class RuntimeSnapshot:
    subject: str
    structure: LoxoneStructure
    connected: bool


@dataclass(slots=True)
class _ConnectionRecord:
    structure: LoxoneStructure
    allowed_states: frozenset[str]
    session: LoxoneWebSocketSession
    task: asyncio.Task[None]
    connected: bool = True


class LoxoneRuntime:
    """Create one bounded live read session per immutable OAuth family."""

    def __init__(
        self,
        endpoint: object,
        token_store: EncryptedLoxoneTokenStore,
        *,
        timeout_seconds: float = 10.0,
        requests_per_minute: int = 60,
        max_parallel_calls: int = 4,
    ) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        if not isinstance(endpoint, MiniserverEndpoint):
            raise TypeError("endpoint must be a MiniserverEndpoint")
        self.endpoint = endpoint
        self.token_store = token_store
        self.client = LoxoneClient(
            endpoint,
            client_uuid=uuid5(NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver"),
            timeout_seconds=timeout_seconds,
        )
        self.cache = UserStateCache()
        self._records: dict[str, _ConnectionRecord] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._rate_limit = requests_per_minute
        self._parallel = asyncio.Semaphore(max_parallel_calls)

    @asynccontextmanager
    async def call_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        if "loxone:read" not in access.scopes:
            raise PermissionError("loxone:read scope is required")
        now = time.monotonic()
        values = self._rate[access.family_id]
        while values and values[0] <= now - 60:
            values.popleft()
        if len(values) >= self._rate_limit:
            raise RuntimeUnavailable("request rate limit exceeded")
        values.append(now)
        async with self._parallel:
            yield

    async def snapshot(self, access: StoredAccessToken) -> RuntimeSnapshot:
        subject = access.family_id
        record = self._records.get(subject)
        if record is None or record.task.done():
            async with self._locks[subject]:
                record = self._records.get(subject)
                if record is None or record.task.done():
                    record = await self._connect(access)
                    self._records[subject] = record
        return RuntimeSnapshot(
            subject, record.structure, record.connected and not record.task.done()
        )

    async def _connect(self, access: StoredAccessToken) -> _ConnectionRecord:
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
        except LoxoneTokenStoreError as exc:
            raise RuntimeUnavailable("Loxone authorization is unavailable") from exc
        if token is None:
            raise RuntimeUnavailable("Loxone authorization is unavailable")
        try:
            session = await self.client.open_session(token)
            structure = await session.load_structure()
        except LoxoneConnectionError as exc:
            raise RuntimeUnavailable("Miniserver connection failed") from exc
        allowed = _state_uuids(structure.controls)
        self.cache.begin_connection(access.family_id)
        placeholder = asyncio.create_task(asyncio.sleep(0))
        record = _ConnectionRecord(structure, allowed, session, placeholder)
        record.task = asyncio.create_task(self._maintain(access, token, record))
        return record

    async def _maintain(
        self,
        access: StoredAccessToken,
        token: LoxoneToken,
        record: _ConnectionRecord,
    ) -> None:
        events = asyncio.create_task(self._pump_events(access.family_id, record))
        try:
            while not events.done():
                refresh_at = token.valid_until + _LOXONE_EPOCH_UNIX - _REFRESH_BEFORE_SECONDS
                timeout = max(1.0, min(3600.0, refresh_at - time.time()))
                done, _pending = await asyncio.wait({events}, timeout=timeout)
                if done:
                    await events
                    break
                if refresh_at <= time.time():
                    await record.session.refresh_token()
                    self.token_store.put(
                        access.family_id,
                        access.miniserver_id,
                        access.identity_id,
                        token,
                    )
        except Exception:
            record.connected = False
            self.cache.disconnect(access.family_id)
        finally:
            events.cancel()
            with suppress(asyncio.CancelledError):
                await events
            await record.session.close()

    async def _pump_events(self, subject: str, record: _ConnectionRecord) -> None:
        async for event_batch in record.session.state_events():
            self.cache.apply(subject, event_batch, allowed_uuids=record.allowed_states)

    def state(self, snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
        return self.cache.get(snapshot.subject, uuid)

    async def revoke(self, family_id: str) -> None:
        record = self._records.pop(family_id, None)
        if record is not None:
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task
        self.cache.clear(family_id)
        self.token_store.delete(family_id)

    async def close(self) -> None:
        for family_id in tuple(self._records):
            await self.revoke(family_id)
