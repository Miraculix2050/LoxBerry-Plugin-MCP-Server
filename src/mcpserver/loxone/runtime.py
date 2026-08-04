"""User-isolated Loxone connection, cache, and bounded control lifecycle."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.provider import CONTROL_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneToken,
    LoxoneWebSocketSession,
)
from mcpserver.loxone.events import LoxoneProtocolError
from mcpserver.loxone.models import Control, Freshness, LoxoneStructure, StateRecord

_LOXONE_EPOCH_UNIX = 1_230_768_000
_REFRESH_BEFORE_SECONDS = 24 * 60 * 60


class RuntimeUnavailable(RuntimeError):
    """The identity-bound Loxone runtime is not currently available."""


class ControlOperationError(RuntimeError):
    """A stable control failure that can be returned through the MCP contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ControlOperation:
    control_uuid: str
    action: str
    accepted: bool
    confirmed: bool
    observed_state: str


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
        control_requests_per_minute: int = 10,
        control_confirmation_seconds: float = 3.0,
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
        self._control_rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._control_rate_limit = control_requests_per_minute
        self._control_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._control_confirmation_seconds = control_confirmation_seconds
        self._parallel = asyncio.Semaphore(max_parallel_calls)

    @asynccontextmanager
    async def call_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        if READ_SCOPE not in access.scopes:
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

    @staticmethod
    def _consume_rate(values: deque[float], limit: int, now: float) -> bool:
        while values and values[0] <= now - 60:
            values.popleft()
        if len(values) >= limit:
            return False
        values.append(now)
        return True

    @staticmethod
    def _control(structure: LoxoneStructure, uuid: str) -> Control | None:
        pending = list(structure.controls)
        while pending:
            control = pending.pop()
            if control.uuid == uuid:
                return control
            pending.extend(control.subcontrols)
        return None

    async def operate_switch(
        self, access: StoredAccessToken, control_uuid: str, action: str
    ) -> ControlOperation:
        """Execute a bounded Switch operation for the immutable OAuth identity."""
        if READ_SCOPE not in access.scopes or CONTROL_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:control is required")
        if not control_uuid or len(control_uuid) > 128 or action not in {"on", "off"}:
            raise ControlOperationError("invalid_input", "invalid Switch operation")

        now = time.monotonic()
        if not self._consume_rate(self._rate[access.family_id], self._rate_limit, now):
            raise ControlOperationError("rate_limited", "request rate limit exceeded")
        if not self._consume_rate(
            self._control_rate[access.family_id], self._control_rate_limit, now
        ):
            raise ControlOperationError("rate_limited", "control rate limit exceeded")

        async with self._parallel, self._control_locks[access.family_id]:
            try:
                snapshot = await self.snapshot(access)
            except RuntimeUnavailable as exc:
                raise ControlOperationError("temporarily_unavailable", str(exc)) from exc
            try:
                token = self.token_store.get(
                    access.family_id, access.miniserver_id, access.identity_id
                )
            except LoxoneTokenStoreError as exc:
                raise ControlOperationError(
                    "temporarily_unavailable", "Loxone authorization is unavailable"
                ) from exc
            if token is None:
                raise ControlOperationError(
                    "temporarily_unavailable", "Loxone authorization is unavailable"
                )
            try:
                command_session = await self.client.open_session(token)
            except LoxoneConnectionError as exc:
                raise ControlOperationError(
                    "loxone_unreachable", "Miniserver connection failed"
                ) from exc
            try:
                try:
                    structure = await command_session.load_structure()
                except (LoxoneConnectionError, LoxoneProtocolError) as exc:
                    raise ControlOperationError(
                        "temporarily_unavailable",
                        "Current Loxone permissions could not be verified",
                    ) from exc
                control = self._control(structure, control_uuid)
                if control is None:
                    raise ControlOperationError("not_found", "control is not visible")
                if control.control_type != "Switch":
                    raise ControlOperationError(
                        "unsupported_control", "only Switch controls are supported"
                    )
                if control.action_uuid is None:
                    raise ControlOperationError(
                        "permission_denied", "control is not operable for this identity"
                    )
                if not 1 <= len(control.action_uuid) <= 128:
                    raise ControlOperationError(
                        "unsupported_control", "Switch control has an invalid action target"
                    )
                active_uuid = dict(control.state_uuids).get("active")
                if active_uuid is None:
                    raise ControlOperationError(
                        "unsupported_control", "Switch control has no active state"
                    )
                before = self.cache.get(snapshot.subject, active_uuid).observed_at
                await command_session.operate_switch(control.action_uuid, action)
            except ControlOperationError:
                raise
            except LoxoneCommandRejected as exc:
                raise ControlOperationError(
                    "permission_denied", "Miniserver rejected the control action"
                ) from exc
            except Exception as exc:
                raise ControlOperationError(
                    "outcome_unknown",
                    "Control outcome is unknown; read the state before retrying",
                ) from exc
            finally:
                await command_session.close()

            target = 1.0 if action == "on" else 0.0
            deadline = time.monotonic() + self._control_confirmation_seconds
            observed = self.cache.get(snapshot.subject, active_uuid)
            while time.monotonic() < deadline:
                observed = self.cache.get(snapshot.subject, active_uuid)
                if (
                    observed.freshness is Freshness.CURRENT
                    and observed.observed_at is not None
                    and (before is None or observed.observed_at > before)
                    and observed.value == target
                ):
                    return ControlOperation(control_uuid, action, True, True, action)
                await asyncio.sleep(0.05)
            state = "unknown"
            if observed.freshness is Freshness.CURRENT and observed.value in {0.0, 1.0}:
                state = "on" if observed.value == 1.0 else "off"
            return ControlOperation(control_uuid, action, True, False, state)

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
