"""User-isolated Loxone connection, cache, and bounded control lifecycle."""

from __future__ import annotations

import asyncio
import json
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
from mcpserver.loxone.control import (
    SUPPORTED_CONTROL_TYPES,
    prepare_control_command,
    visible_mood_ids,
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
    control_type: str
    action: str
    accepted: bool
    confirmed: bool
    observed_state: str
    observed_values: tuple[tuple[str, object], ...] = ()


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

    @staticmethod
    def _state_matches(value: object, target: float | str) -> bool:
        if target == "__positive__":
            return isinstance(value, int | float) and not isinstance(value, bool) and value > 0
        if isinstance(target, float):
            return (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and abs(float(value) - target) <= 0.001
            )
        if target == "0" and isinstance(value, str) and value in {"[]", "[0]", '["0"]'}:
            return True
        if isinstance(value, str):
            with suppress(json.JSONDecodeError):
                value = json.loads(value)
        if isinstance(value, list | tuple):
            return target in {str(item) for item in value}
        return str(value) == target

    async def operate_control(
        self,
        access: StoredAccessToken,
        control_uuid: str,
        action: str,
        *,
        level: float | None = None,
        mood_id: str | None = None,
        position: float | None = None,
        slat_position: float | None = None,
    ) -> ControlOperation:
        """Execute one bounded documented operation for the immutable OAuth identity."""
        if READ_SCOPE not in access.scopes or CONTROL_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:control is required")
        if not control_uuid or len(control_uuid) > 128 or not action or len(action) > 64:
            raise ControlOperationError("invalid_input", "invalid control operation")

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
                if control.action_uuid is None or control.read_only:
                    raise ControlOperationError(
                        "permission_denied", "control is not operable for this identity"
                    )
                if not 1 <= len(control.action_uuid) <= 128:
                    raise ControlOperationError(
                        "unsupported_control", "control has an invalid action target"
                    )
                if control.control_type not in SUPPORTED_CONTROL_TYPES:
                    raise ControlOperationError(
                        "unsupported_control", "control type is not supported"
                    )
                try:
                    prepared = prepare_control_command(
                        control,
                        action,
                        level=level,
                        mood_id=mood_id,
                        position=position,
                        slat_position=slat_position,
                    )
                except ValueError as exc:
                    raise ControlOperationError("invalid_input", str(exc)) from exc
                state_uuids = dict(control.state_uuids)
                if (
                    control.control_type == "LightControllerV2"
                    and action == "set_mood"
                    and mood_id != "0"
                ):
                    mood_list_uuid = state_uuids.get("moodList")
                    if mood_list_uuid is None:
                        raise ControlOperationError(
                            "unsupported_control", "control has no visible moodList state"
                        )
                    mood_list = self.cache.get(snapshot.subject, mood_list_uuid)
                    if mood_list.freshness is not Freshness.CURRENT:
                        raise ControlOperationError(
                            "temporarily_unavailable", "visible moodList is not current"
                        )
                    available_moods = visible_mood_ids(mood_list.value)
                    if available_moods is None:
                        raise ControlOperationError(
                            "unsupported_control", "visible moodList has an invalid format"
                        )
                    if mood_id not in available_moods:
                        raise ControlOperationError(
                            "invalid_input", "mood_id is not present in the visible moodList"
                        )
                missing = [
                    name for name, _target in prepared.expected_states if name not in state_uuids
                ]
                if missing:
                    raise ControlOperationError(
                        "unsupported_control", "control lacks a state required for confirmation"
                    )
                before = {
                    name: self.cache.get(snapshot.subject, state_uuids[name]).observed_at
                    for name, _target in prepared.expected_states
                }
                await command_session.operate_control(control.action_uuid, prepared.command)
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

            if not prepared.expected_states:
                return ControlOperation(
                    control_uuid, control.control_type, action, True, False, "unknown"
                )
            deadline = time.monotonic() + self._control_confirmation_seconds
            observed_values: dict[str, object] = {}
            while time.monotonic() < deadline:
                confirmed = True
                for name, target in prepared.expected_states:
                    observed = self.cache.get(snapshot.subject, state_uuids[name])
                    previous_observed_at = before[name]
                    if observed.value is not None:
                        observed_values[name] = observed.value
                    if not (
                        observed.freshness is Freshness.CURRENT
                        and observed.observed_at is not None
                        and (
                            previous_observed_at is None
                            or observed.observed_at > previous_observed_at
                        )
                        and self._state_matches(observed.value, target)
                    ):
                        confirmed = False
                if confirmed:
                    state = action if control.control_type == "Switch" else "confirmed"
                    return ControlOperation(
                        control_uuid,
                        control.control_type,
                        action,
                        True,
                        True,
                        state,
                        tuple(observed_values.items()),
                    )
                await asyncio.sleep(0.05)
            state = "unknown"
            if control.control_type == "Switch" and observed_values.get("active") in {0.0, 1.0}:
                state = "on" if observed_values["active"] == 1.0 else "off"
            return ControlOperation(
                control_uuid,
                control.control_type,
                action,
                True,
                False,
                state,
                tuple(observed_values.items()),
            )

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
