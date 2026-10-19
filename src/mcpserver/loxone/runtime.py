"""User-isolated Loxone connection, cache, and bounded control lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager, nullcontext, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.provider import CONTROL_SCOPE, HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.auth.store import lifecycle_event
from mcpserver.availability import AvailabilityPhase, AvailabilityReason
from mcpserver.bounded_worker import run_admitted_worker
from mcpserver.loxone.auth_diagnostics import (
    AttemptProvenance,
    MiniserverAuthCoordinator,
    MiniserverAuthenticationBusy,
    MiniserverAuthenticationCooldown,
    MiniserverAuthenticationSuppressed,
    MiniserverSourceIpSuppressed,
)
from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    LoxoneToken,
    LoxoneTokenAuthenticationRejected,
    LoxoneWebSocketSession,
)
from mcpserver.loxone.control import (
    SUPPORTED_CONTROL_TYPES,
    prepare_control_command,
    visible_mood_ids,
)
from mcpserver.loxone.events import LoxonePayloadTooLarge, LoxoneProtocolError
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneStructure,
    StateRecord,
    StatisticSeries,
)
from mcpserver.loxone.native_efm import (
    FIRMWARE as NATIVE_EFM_FIRMWARE,
)
from mcpserver.loxone.native_efm import (
    VIEWS as NATIVE_EFM_VIEWS,
)
from mcpserver.loxone.native_efm import (
    NativeEfmError,
    NativeEfmResult,
    NativeResultView,
    decode_native_efm,
)
from mcpserver.loxone.project.service import ProjectService
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.statistics import (
    StatisticPoint,
    StatisticsCache,
    parse_statistic_points,
)
from mcpserver.loxone.system_messages import (
    SUPPORTED_FIRMWARE,
    SYSTEM_MESSAGES_PERMISSION,
    MessageSource,
    MessageSourceError,
    canonical_serial,
    decode_messages,
    identifier,
)
from mcpserver.message_approval import MessageApprovalStore

_LOXONE_EPOCH_UNIX = 1_230_768_000
_REFRESH_BEFORE_SECONDS = 24 * 60 * 60
_MAX_LEGACY_STATISTIC_BYTES = 64 * 1024 * 1024
_MAX_HISTORY_TIMESTAMP = 4_102_444_800
_LOGGER = logging.getLogger(__name__)
_HISTORY_TRACE_ID: ContextVar[str | None] = ContextVar("history_trace_id", default=None)


class _SessionEstablishmentTimeout(LoxoneConnectionError, TimeoutError):
    """The existing connection budget expired during session establishment."""


@dataclass
class _FamilyLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class _FamilyLocks(dict[str, _FamilyLock]):
    """Retain one lock until its last holder or waiter has left."""

    @asynccontextmanager
    async def hold(self, family_id: str) -> AsyncIterator[None]:
        entry = self.setdefault(family_id, _FamilyLock())
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0:
                del self[family_id]


@contextmanager
def history_trace(trace_id: str) -> Iterator[None]:
    """Associate sanitized History phase timings with one MCP tool result."""
    token = _HISTORY_TRACE_ID.set(trace_id)
    try:
        yield
    finally:
        _HISTORY_TRACE_ID.reset(token)


def _history_phase(trace_id: str, phase: str, started: float) -> None:
    _history_duration(trace_id, phase, time.perf_counter() - started)


def _history_duration(trace_id: str, phase: str, seconds: float) -> None:
    _LOGGER.debug(
        "component=history_timing trace_id=%s phase=%s duration_ms=%.1f",
        trace_id,
        phase,
        seconds * 1000,
    )


def _token_auth_rejection_message(response_code: str) -> str:
    messages = {
        "401": "Miniserver rejected token authentication as unauthorized",
        "403": "Miniserver rejected token authentication due to insufficient rights",
        "423": "Miniserver rejected token authentication because the user is disabled",
        "429": "Miniserver rate-limited token authentication after failed logins",
    }
    return messages.get(response_code, "Miniserver token authentication was rejected")


def _legacy_statistic_dates(start: int, end: int) -> tuple[str, ...]:
    """Return the at-most-two monthly legacy files covering a bounded raw query."""
    first = datetime.fromtimestamp(start, UTC).date().replace(day=1)
    last = datetime.fromtimestamp(end, UTC).date().replace(day=1)
    result: list[str] = []
    current = first
    while current <= last:
        result.append(current.strftime("%Y%m"))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    if len(result) > 2:
        raise ControlOperationError("invalid_input", "legacy raw statistics exceed the file limit")
    return tuple(result)


def _parse_legacy_statistic_points(
    payload: bytes,
    *,
    output_index: int,
    output_count: int,
    maximum_points: int = 100_000,
) -> tuple[StatisticPoint, ...]:
    """Decode one output from a bounded documented legacy statistic stream."""
    if not 1 <= output_count <= 16 or not 0 <= output_index < output_count:
        raise ValueError("legacy statistic output selection is invalid")
    if len(payload) > _MAX_LEGACY_STATISTIC_BYTES:
        raise LoxoneProtocolError("Statistic response exceeds the configured limit")
    record = struct.Struct(f"<I{output_count}d")
    if len(payload) % record.size:
        raise LoxoneProtocolError("Statistic response has a truncated entry")
    if len(payload) // record.size > maximum_points:
        raise LoxoneProtocolError("Statistic response contains too many points")
    result: list[StatisticPoint] = []
    previous = -1
    for values in record.iter_unpack(payload):
        timestamp = values[0]
        outputs = values[1:]
        if timestamp < previous:
            raise LoxoneProtocolError("Statistic response is not ordered")
        if timestamp > 4_102_444_800 or any(not math.isfinite(value) for value in outputs):
            raise LoxoneProtocolError("Statistic response contains an invalid point")
        previous = timestamp
        result.append(StatisticPoint(timestamp=timestamp, value=outputs[output_index]))
    return tuple(result)


def _points_in_range(
    payload: bytes, start: int, end: int, maximum_points: int
) -> tuple[StatisticPoint, ...]:
    return tuple(
        p
        for p in parse_statistic_points(payload, maximum_points=maximum_points)
        if start <= p.timestamp <= end
    )


def _legacy_points_in_range(
    payload: bytes,
    output_index: int,
    output_count: int,
    start: int,
    end: int,
    maximum_points: int,
) -> tuple[StatisticPoint, ...]:
    return tuple(
        StatisticPoint(_LOXONE_EPOCH_UNIX + p.timestamp, p.value)
        for p in _parse_legacy_statistic_points(
            payload,
            output_index=output_index,
            output_count=output_count,
            maximum_points=maximum_points,
        )
        if start <= _LOXONE_EPOCH_UNIX + p.timestamp <= end
    )


class RuntimeAuthorizationError(PermissionError):
    """OAuth authorization has ended independently of Miniserver availability."""


class RuntimeUnavailable(RuntimeError):
    """The identity-bound Loxone runtime is not currently available."""

    def __init__(
        self,
        message: str,
        *,
        reason: AvailabilityReason = AvailabilityReason.UNKNOWN,
        phase: AvailabilityPhase = AvailabilityPhase.UNKNOWN,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = AvailabilityReason(reason)
        self.phase = AvailabilityPhase(phase)
        self.retry_after_seconds = (
            retry_after_seconds
            if self.reason == AvailabilityReason.LOCAL_RATE_LIMIT
            and type(retry_after_seconds) is int
            and 1 <= retry_after_seconds <= 60
            else None
        )


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


@dataclass(frozen=True, slots=True)
class ControlHistoryEntry:
    timestamp: int
    what: str
    trigger: str
    trigger_type: str
    impacts: tuple[str, ...]


def normalize_control_history_entries(
    raw: list[Mapping[str, Any]],
) -> tuple[ControlHistoryEntry, ...]:
    """Validate and bound decoded native History entries for a caller."""
    entries: list[ControlHistoryEntry] = []
    for item in raw[:1000]:
        timestamp = item.get("ts")
        what = item.get("what", "")
        trigger = item.get("trigger", "")
        trigger_type = item.get("triggerType", "")
        impacts_value = item.get("impacts", [])
        if (
            not isinstance(timestamp, int)
            or isinstance(timestamp, bool)
            or not 0 <= timestamp <= _MAX_HISTORY_TIMESTAMP
            or not isinstance(what, str)
            or not isinstance(trigger, str)
            or not isinstance(trigger_type, str)
            or not isinstance(impacts_value, list)
        ):
            continue
        impacts = tuple(value[:500] for value in impacts_value[:20] if isinstance(value, str))
        entries.append(
            ControlHistoryEntry(timestamp, what[:500], trigger[:500], trigger_type[:64], impacts)
        )
    return tuple(entries)


def _state_uuids(controls: tuple[Control, ...]) -> frozenset[str]:
    result: set[str] = set()
    for control in controls:
        result.update(uuid for _name, uuid in control.state_uuids)
        result.update(_state_uuids(control.subcontrols))
    return frozenset(result)


def _structure_state_uuids(structure: LoxoneStructure) -> frozenset[str]:
    """Return visible control plus explicitly normalized global-state UUIDs."""
    return _state_uuids(structure.controls + structure.hidden_controls) | frozenset(
        item.state_uuid for item in structure.global_metadata if item.state_uuid is not None
    )


@dataclass(slots=True)
class RuntimeSnapshot:
    subject: str
    structure: LoxoneStructure
    connected: bool
    structure_generation: int = 1


@dataclass(slots=True)
class _ConnectionRecord:
    structure: LoxoneStructure
    allowed_states: frozenset[str]
    session: LoxoneWebSocketSession
    task: asyncio.Task[None]
    connected: bool = True
    close_reason: str = "local_disconnect"
    generation: int = 1
    last_structure_check: float = 0.0
    last_used: float = 0.0
    state_stream_diagnostics_logged: bool = False
    initial_state_batch: asyncio.Event = field(default_factory=asyncio.Event)
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class LoxoneRuntime:
    """Create one bounded live read session per immutable OAuth family."""

    def __init__(
        self,
        endpoint: object,
        token_store: EncryptedLoxoneTokenStore,
        *,
        token_health: LoxoneTokenHealthStore | None = None,
        timeout_seconds: float = 10.0,
        requests_per_minute: int = 60,
        max_parallel_calls: int = 4,
        call_admission: asyncio.Semaphore | None = None,
        control_requests_per_minute: int = 10,
        control_confirmation_seconds: float = 3.0,
        history_requests_per_minute: int = 12,
        statistics_cache: StatisticsCache | None = None,
        control_enabled: bool = False,
        history_enabled: bool = False,
        structure_refresh_seconds: int = 300,
        max_active_sessions: int = 16,
        session_idle_seconds: int = 900,
        max_states_per_identity: int = 20_000,
        max_structure_controls: int = 20_000,
        max_structure_state_references: int = 100_000,
        max_structure_depth: int = 32,
        auth_coordinator: MiniserverAuthCoordinator | None = None,
        auth_binding: Callable[[StoredAccessToken], str] | None = None,
        validate_access: Callable[[StoredAccessToken], Awaitable[bool]] | None = None,
    ) -> None:
        from mcpserver.loxone.client import MiniserverEndpoint

        if not isinstance(endpoint, MiniserverEndpoint):
            raise TypeError("endpoint must be a MiniserverEndpoint")
        self.endpoint = endpoint
        self.projects: ProjectService | None = None
        self.token_store = token_store
        self.token_health = token_health
        self.client = LoxoneClient(
            endpoint,
            client_uuid=uuid5(NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver"),
            timeout_seconds=timeout_seconds,
            max_structure_controls=max_structure_controls,
            max_structure_state_references=max_structure_state_references,
            max_structure_depth=max_structure_depth,
            structure_lookup=self,
        )
        self.auth_coordinator = auth_coordinator
        self.auth_binding = auth_binding
        self.message_approval_store: MessageApprovalStore | None = None
        self._validate_access = validate_access
        self.validate_authentication_diagnostics_access: (
            Callable[[StoredAccessToken], Awaitable[bool]] | None
        ) = None
        self.validate_message_confirmation: (
            Callable[[StoredAccessToken], Awaitable[bool]] | None
        ) = None
        self._initial_state_timeout_seconds = min(timeout_seconds, 2.0)
        self.cache = UserStateCache(max_states_per_user=max_states_per_identity)
        self._records: dict[str, _ConnectionRecord] = {}
        self._admission_lock = asyncio.Lock()
        self._closed = False
        self._locks = _FamilyLocks()
        self._rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._rate_limit = requests_per_minute
        self._control_rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._control_rate_limit = control_requests_per_minute
        self._control_locks = _FamilyLocks()
        self._control_confirmation_seconds = control_confirmation_seconds
        self._parallel = (
            call_admission if call_admission is not None else asyncio.Semaphore(max_parallel_calls)
        )
        self._project_admission = asyncio.Semaphore(1)
        self._project_rate: deque[float] = deque()
        self._history_rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._history_rate_limit = history_requests_per_minute
        self._rate_prune_at = 0.0
        self.statistics_cache = statistics_cache or StatisticsCache()
        self.control_enabled = control_enabled
        self.history_enabled = history_enabled
        self.structure_refresh_seconds = structure_refresh_seconds
        self.max_active_sessions = max_active_sessions
        self.session_idle_seconds = session_idle_seconds

    async def _require_access(self, access: StoredAccessToken) -> None:
        validator = getattr(self, "_validate_access", None)
        if validator is not None and not await validator(access):
            raise RuntimeAuthorizationError("Loxone authorization is unavailable")

    async def authentication_diagnostics(self, access: StoredAccessToken) -> dict[str, Any]:
        """Read only local retained events under fresh, mutation-free authorization."""
        validator = self.validate_authentication_diagnostics_access
        if validator is None or not await validator(access):
            raise PermissionError("Authentication diagnostics require current loxone:read")
        if self._closed or self.auth_coordinator is None or self.auth_binding is None:
            raise RuntimeUnavailable("Authentication diagnostics unavailable")
        result = self.auth_coordinator.diagnostic_snapshot(self.auth_binding(access))
        if not await validator(access):
            raise PermissionError("Authentication diagnostics require current loxone:read")
        return result

    def _prune_rate_state(self, now: float) -> None:
        """Keep live rate windows across disconnects; discard expired family keys."""
        if now < self._rate_prune_at:
            return
        next_prune = now + 60
        for rates in (self._rate, self._control_rate, self._history_rate):
            for family_id, values in tuple(rates.items()):
                if not values or values[-1] <= now - 60:
                    del rates[family_id]
                else:
                    next_prune = min(next_prune, values[-1] + 60)
        self._rate_prune_at = next_prune

    @asynccontextmanager
    async def call_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        if READ_SCOPE not in access.scopes:
            raise PermissionError("loxone:read scope is required")
        now = time.monotonic()
        self._prune_rate_state(now)
        values = self._rate[access.family_id]
        while values and values[0] <= now - 60:
            values.popleft()
        if len(values) >= self._rate_limit:
            raise RuntimeUnavailable(
                "request rate limit exceeded",
                reason=AvailabilityReason.LOCAL_RATE_LIMIT,
                phase=AvailabilityPhase.LOCAL_BUDGET,
                retry_after_seconds=max(1, min(60, math.ceil(values[-self._rate_limit] + 60 - now)))
                if self._rate_limit > 0
                else None,
            )
        values.append(now)
        async with self._parallel:
            await self._require_access(access)
            yield

    @asynccontextmanager
    async def _project_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        """Reject excess project work before it can occupy shared read slots."""
        if READ_SCOPE not in access.scopes:
            raise PermissionError("loxone:read scope is required")
        await self._require_access(access)
        if self._closed:
            raise RuntimeUnavailable("the service is closed")
        # No await between the availability check and acquisition: there are no waiters.
        if self._project_admission.locked():
            raise RuntimeUnavailable(
                "project request already active",
                reason=AvailabilityReason.LOCAL_RATE_LIMIT,
                phase=AvailabilityPhase.LOCAL_BUDGET,
                retry_after_seconds=1,
            )
        async with self._project_admission:
            now = time.monotonic()
            while self._project_rate and self._project_rate[0] <= now - 60:
                self._project_rate.popleft()
            if len(self._project_rate) >= 12:
                raise RuntimeUnavailable(
                    "project request rate limit exceeded",
                    reason=AvailabilityReason.LOCAL_RATE_LIMIT,
                    phase=AvailabilityPhase.LOCAL_BUDGET,
                    retry_after_seconds=max(
                        1, min(60, math.ceil(self._project_rate[0] + 60 - now))
                    ),
                )
            yield

    @asynccontextmanager
    async def project_call_slot(
        self, access: StoredAccessToken, *, worker_admitted: bool = False
    ) -> AsyncIterator[None]:
        # Internal callers with a retained global worker lease must not acquire
        # that same lease again. All project identity/rate gates still apply.
        async with (
            self._project_slot(access),
            nullcontext() if worker_admitted else self.call_slot(access),
        ):
            # Charge only work admitted by the family and current-access gates.
            self._project_rate.append(time.monotonic())
            yield

    @asynccontextmanager
    async def history_project_call_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        if READ_SCOPE not in access.scopes or HISTORY_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:history is required")
        if not self.history_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone history requires administrator activation"
            )
        async with self._project_slot(access), self.history_call_slot(access):
            self._project_rate.append(time.monotonic())
            yield

    @asynccontextmanager
    async def worker_slot(self) -> AsyncIterator[None]:
        """Bound local project workers by the configured global call concurrency."""

        async with self._parallel:
            yield

    @asynccontextmanager
    async def history_call_slot(self, access: StoredAccessToken) -> AsyncIterator[None]:
        """Apply the normal and history-specific limits to a local history read."""

        if READ_SCOPE not in access.scopes or HISTORY_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:history is required")
        if not self.history_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone history requires administrator activation"
            )
        now = time.monotonic()
        self._prune_rate_state(now)
        if not self._consume_rate(
            self._rate[access.family_id], self._rate_limit, now
        ) or not self._consume_rate(
            self._history_rate[access.family_id], self._history_rate_limit, now
        ):
            raise ControlOperationError("rate_limited", "history rate limit exceeded")
        async with self._parallel:
            try:
                await self._require_access(access)
            except RuntimeAuthorizationError as exc:
                raise ControlOperationError("permission_denied", str(exc)) from exc
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
    def _control(
        structure: LoxoneStructure, uuid: str, *, include_hidden: bool = False
    ) -> Control | None:
        pending = list(structure.controls)
        if include_hidden:
            pending.extend(structure.hidden_controls)
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
        scene_id: str | None = None,
        output_id: str | None = None,
        hue: float | None = None,
        saturation: float | None = None,
        brightness: float | None = None,
        kelvin: int | None = None,
        value: float | None = None,
        duration_seconds: int | None = None,
    ) -> ControlOperation:
        """Execute one bounded documented operation for the immutable OAuth identity."""
        if READ_SCOPE not in access.scopes or CONTROL_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:control is required")
        if not self.control_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone control requires administrator activation"
            )
        if not control_uuid or len(control_uuid) > 128 or not action or len(action) > 64:
            raise ControlOperationError("invalid_input", "invalid control operation")

        now = time.monotonic()
        self._prune_rate_state(now)
        if not self._consume_rate(self._rate[access.family_id], self._rate_limit, now):
            raise ControlOperationError("rate_limited", "request rate limit exceeded")
        if not self._consume_rate(
            self._control_rate[access.family_id], self._control_rate_limit, now
        ):
            raise ControlOperationError("rate_limited", "control rate limit exceeded")

        async with self._parallel, self._control_locks.hold(access.family_id):
            try:
                snapshot = await self.snapshot(access)
            except RuntimeAuthorizationError as exc:
                raise ControlOperationError("permission_denied", str(exc)) from exc
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
                command_session = await self._open_session(
                    token, owner="tool_request", phase="session_establishment", access=access
                )
            except RuntimeAuthorizationError as exc:
                raise ControlOperationError("permission_denied", str(exc)) from exc
            except RuntimeUnavailable as exc:
                raise ControlOperationError("temporarily_unavailable", str(exc)) from exc
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
                if (
                    control.action_uuid is None
                    or control.read_only
                    or control.is_monitor_referenced
                ):
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
                        scene_id=scene_id,
                        output_id=output_id,
                        hue=hue,
                        saturation=saturation,
                        brightness=brightness,
                        kelvin=kelvin,
                        value=value,
                        duration_seconds=duration_seconds,
                        now_seconds_since_2009=int(time.time()) - _LOXONE_EPOCH_UNIX,
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
                before_records = {
                    name: self.cache.get(snapshot.subject, state_uuids[name])
                    for name, _target in prepared.expected_states
                }
                if any(
                    record.freshness is not Freshness.CURRENT for record in before_records.values()
                ):
                    raise ControlOperationError(
                        "temporarily_unavailable",
                        "control confirmation state is not current",
                    )
                before = {name: record.observed_at for name, record in before_records.items()}
                try:
                    await command_session.operate_control(control.action_uuid, prepared.command)
                except ValueError as exc:
                    _LOGGER.warning(
                        "component=control outcome=transport_validation_failed "
                        "control_type=%s action=%s error_type=%s",
                        control.control_type,
                        action,
                        type(exc).__name__,
                    )
                    raise ControlOperationError(
                        "unsupported_control",
                        "control command is not supported by the transport",
                    ) from exc
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

    @asynccontextmanager
    async def history_context(
        self,
        access: StoredAccessToken,
    ) -> AsyncIterator[tuple[LoxoneStructure, LoxoneWebSocketSession]]:
        trace_id = _HISTORY_TRACE_ID.get() or uuid4().hex
        started = time.perf_counter()
        if READ_SCOPE not in access.scopes or HISTORY_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:history is required")
        if not self.history_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone history requires administrator activation"
            )
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
        except LoxoneTokenStoreError as exc:
            raise ControlOperationError(
                "temporarily_unavailable", "Loxone authorization is unavailable"
            ) from exc
        if token is None:
            raise ControlOperationError(
                "temporarily_unavailable", "Loxone authorization is unavailable"
            )
        _history_phase(trace_id, "authorization", started)
        started = time.perf_counter()
        async with self.history_call_slot(access):
            _history_phase(trace_id, "rate_wait", started)
            session: LoxoneWebSocketSession | None = None
            try:
                started = time.perf_counter()
                session = await self._open_session(
                    token, owner="tool_request", phase="session_establishment", access=access
                )
                _history_phase(trace_id, "connection", started)
                structure = await self._history_visible_structure(session, trace_id)
                trace_context = _HISTORY_TRACE_ID.set(trace_id)
                try:
                    yield structure, session
                finally:
                    _HISTORY_TRACE_ID.reset(trace_context)
            except RuntimeAuthorizationError as exc:
                raise ControlOperationError("permission_denied", str(exc)) from exc
            except RuntimeUnavailable as exc:
                raise ControlOperationError("temporarily_unavailable", str(exc)) from exc
            except ControlOperationError:
                raise
            except (LoxoneConnectionError, LoxoneProtocolError, TimeoutError) as exc:
                raise ControlOperationError(
                    "loxone_unreachable", "Miniserver connection failed"
                ) from exc
            finally:
                if session is not None:
                    await session.close()

    @asynccontextmanager
    async def _history_session(
        self,
        access: StoredAccessToken,
        control_uuid: str,
        *,
        include_hidden: bool = False,
    ) -> AsyncIterator[tuple[Control, LoxoneWebSocketSession]]:
        if not control_uuid or len(control_uuid) > 128:
            raise ControlOperationError("invalid_input", "invalid control identifier")
        async with self.history_context(access) as (structure, session):
            started = time.perf_counter()
            control = self._control(structure, control_uuid, include_hidden=include_hidden)
            _history_phase(_HISTORY_TRACE_ID.get() or uuid4().hex, "visibility", started)
            if control is None:
                raise ControlOperationError("not_found", "control is not visible")
            yield control, session

    async def _history_visible_structure(
        self,
        session: LoxoneWebSocketSession,
        trace_id: str,
    ) -> LoxoneStructure:
        """Load the caller-filtered structure before releasing native History data."""
        started = time.perf_counter()
        structure = await session.load_structure()
        _history_phase(trace_id, "structure", started)
        _LOGGER.debug("component=history_visibility trace_id=%s outcome=fresh", trace_id)
        return structure

    async def read_native_efm(
        self, access: StoredAccessToken, control_uuid: str, view: NativeResultView
    ) -> tuple[Control, LoxoneStructure, NativeEfmResult]:
        """Admin-first native reads; fresh caller checks before reading and release."""
        from mcpserver.loxone.uuid import normalize_loxone_uuid

        try:
            control_uuid = normalize_loxone_uuid(control_uuid)
        except ValueError:
            raise ControlOperationError("invalid_input", "Invalid native EFM target") from None
        if view not in NATIVE_EFM_VIEWS:
            raise ControlOperationError("invalid_input", "Invalid native EFM view")
        if READ_SCOPE not in access.scopes:
            raise PermissionError("loxone:read scope is required")
        if view != "actual" and (HISTORY_SCOPE not in access.scopes or not self.history_enabled):
            raise ControlOperationError("permission_denied", "Activated loxone:history is required")
        if (
            self.token_health is not None
            and self.token_health.get(access.family_id).confirmation_required
        ):
            raise ControlOperationError("permission_denied", "Token use requires confirmation")
        session: LoxoneWebSocketSession | None = None
        token: LoxoneToken | None = None
        timeout = min(self.client.timeout_seconds, 10.0)
        deadline = time.monotonic() + 30

        def visible_admin(structure: LoxoneStructure) -> Control:
            control = next(
                (c for c in structure.controls if c.uuid == control_uuid and not c.is_hidden), None
            )
            if control is None:
                raise ControlOperationError("not_found", "Native EFM target is not accessible")
            if structure.caller_is_admin is not True:
                raise ControlOperationError("permission_denied", "Loxone administrator required")
            if control.control_type != "EFM":
                raise ControlOperationError("unsupported_source", "Native EFM source unsupported")
            return control

        try:
            async with asyncio.timeout(30):
                slot = (
                    self.call_slot(access) if view == "actual" else self.history_call_slot(access)
                )
                async with slot:
                    try:
                        await self._require_access(access)
                        if (
                            self.token_health is not None
                            and self.token_health.get(access.family_id).confirmation_required
                        ):
                            raise ControlOperationError(
                                "permission_denied", "Token use requires confirmation"
                            )
                        token = self.token_store.get(
                            access.family_id, access.miniserver_id, access.identity_id
                        )
                        if token is None:
                            raise RuntimeUnavailable("Loxone authorization is unavailable")
                        try:
                            session = await asyncio.wait_for(
                                self._open_session(
                                    token,
                                    owner="tool_request",
                                    phase="native_efm",
                                    access=access,
                                    require_token_confirmation=True,
                                ),
                                timeout,
                            )
                        except LoxoneTokenAuthenticationRejected:
                            if self.token_health is not None:
                                self.token_health.record_rejected_authentication(access.family_id)
                            raise ControlOperationError(
                                "permission_denied", "Loxone authentication rejected"
                            ) from None
                        if self.token_health is not None:
                            self.token_health.record_successful_authentication(access.family_id)
                        structure = await asyncio.wait_for(session.load_structure(), timeout)
                        control = visible_admin(structure)
                        try:
                            action_uuid = normalize_loxone_uuid(control.action_uuid)
                        except ValueError:
                            raise ControlOperationError(
                                "unsupported_source", "Native EFM action identity invalid"
                            ) from None
                        probe = await asyncio.wait_for(self.client.probe(), timeout)
                        serial = canonical_serial(structure.identity.miniserver_serial)
                        if (
                            probe.firmware != NATIVE_EFM_FIRMWARE
                            or canonical_serial(probe.serial) != serial
                        ):
                            raise ControlOperationError(
                                "unsupported_source", "Native EFM firmware or identity unsupported"
                            )
                        await self._require_access(access)
                        native_control = control
                        value = await asyncio.wait_for(
                            session.native_efm_result(action_uuid, view), timeout
                        )
                        result = decode_native_efm(
                            value, view, retrieved_at=datetime.now(UTC).isoformat()
                        )
                        await self._require_access(access)
                        refreshed = await asyncio.wait_for(session.load_structure(), timeout)
                        control = visible_admin(refreshed)
                        try:
                            refreshed_action = normalize_loxone_uuid(control.action_uuid)
                        except ValueError:
                            raise ControlOperationError(
                                "unsupported_source", "Native EFM action identity invalid"
                            ) from None
                        if refreshed_action != action_uuid:
                            raise ControlOperationError(
                                "unsupported_source", "Native EFM action identity changed"
                            )
                        if canonical_serial(refreshed.identity.miniserver_serial) != serial:
                            raise ControlOperationError(
                                "unsupported_source", "Native EFM source identity changed"
                            )
                        await self._require_access(access)
                        result = StateSemanticsResolver().resolve_native_efm(
                            result, native_control, control
                        )
                        return control, refreshed, result
                    finally:
                        if session is not None:
                            with suppress(TimeoutError, LoxoneConnectionError, LoxoneProtocolError):
                                await asyncio.wait_for(
                                    session.close(),
                                    max(0.001, min(timeout, deadline - time.monotonic())),
                                )
        except RuntimeAuthorizationError:
            raise ControlOperationError(
                "permission_denied", "Loxone authorization unavailable"
            ) from None
        except MessageSourceError:
            raise ControlOperationError(
                "unsupported_source", "Native EFM identity invalid"
            ) from None
        except LoxonePayloadTooLarge:
            raise ControlOperationError(
                "response_too_large", "Native EFM response too large"
            ) from None
        except NativeEfmError as exc:
            code = (
                "response_too_large"
                if str(exc) == "native_efm_response_too_large"
                else "temporarily_unavailable"
            )
            raise ControlOperationError(code, "Native EFM response invalid") from None
        except (LoxoneTokenStoreError, LoxoneConnectionError, LoxoneProtocolError, TimeoutError):
            raise ControlOperationError(
                "temporarily_unavailable", "Native EFM source unavailable"
            ) from None
        finally:
            if token is not None:
                token.destroy()

    async def get_statistics(
        self,
        access: StoredAccessToken,
        control_uuid: str,
        series_id: str,
        start: int,
        end: int,
        granularity: str,
        *,
        include_hidden: bool = False,
    ) -> tuple[Control, StatisticSeries, tuple[StatisticPoint, ...]]:
        """Read one visible documented statistic series without exposing raw commands."""
        if granularity not in {"raw", "hour", "day", "month", "year"}:
            raise ControlOperationError("invalid_input", "unsupported statistic granularity")
        if not 0 <= start <= end <= 4_102_444_800:
            raise ControlOperationError("invalid_input", "invalid statistic time range")
        if granularity == "raw" and end - start > 7 * 24 * 60 * 60:
            raise ControlOperationError("invalid_input", "raw statistics are limited to seven days")
        if granularity != "raw" and end - start > 10 * 366 * 24 * 60 * 60:
            raise ControlOperationError(
                "invalid_input", "aggregated statistics are limited to ten years"
            )
        history_session = (
            self._history_session(access, control_uuid, include_hidden=True)
            if include_hidden
            else self._history_session(access, control_uuid)
        )
        async with (
            history_session as (
                control,
                session,
            )
        ):
            return await self.authorized_statistics(
                access, control, session, series_id, start, end, granularity
            )

    async def authorized_statistics(
        self,
        access: StoredAccessToken,
        control: Control,
        session: LoxoneWebSocketSession,
        series_id: str,
        start: int,
        end: int,
        granularity: str,
        *,
        maximum_points: int | None = None,
    ) -> tuple[Control, StatisticSeries, tuple[StatisticPoint, ...]]:
        """Reuse the native adapter only inside a freshly authorized history context."""
        if granularity not in {"raw", "hour", "day", "month", "year"}:
            raise ControlOperationError("invalid_input", "unsupported statistic granularity")
        selected_limit = 100_000 if maximum_points is None else maximum_points
        if not 0 <= start <= end <= 4_102_444_800 or not 0 <= selected_limit <= 100_000:
            raise ControlOperationError(
                "invalid_input", "invalid statistic time range or point budget"
            )
        if granularity == "raw" and end - start > 7 * 24 * 60 * 60:
            raise ControlOperationError("invalid_input", "raw statistics are limited to seven days")
        control_uuid = control.uuid
        trace_id = _HISTORY_TRACE_ID.get() or uuid4().hex
        series = next(
            (item for item in control.statistic_series if item.series_id == series_id), None
        )
        if series is None:
            raise ControlOperationError("not_found", "statistic series is not visible")
        # Select only after fresh authorization. Technical source changes must
        # never reinterpret an old raw/diff payload under new semantic metadata.
        cache_key = StatisticsCache.source_key(
            access.family_id,
            control_uuid,
            series_id,
            str(start),
            str(end),
            granularity,
            series.source,
            series.group_id,
            series.output,
            str(series.accumulated),
            str(series.accumulated_metadata_valid),
            str(series.recording_mode),
            series.format,
            str(series.legacy_output_index),
            str(series.legacy_output_count),
        )
        cached = self.statistics_cache.get(cache_key)
        if cached is not None:
            if len(cached) > selected_limit:
                raise ControlOperationError("invalid_input", "analysis input point limit exceeded")
            _LOGGER.debug("component=statistics trace_id=%s outcome=cache_hit", trace_id)
            return control, series, cached
        _LOGGER.debug("component=statistics trace_id=%s outcome=cache_miss", trace_id)
        fetch_seconds = 0.0
        parse_seconds = 0.0
        try:
            if series.source == "legacy":
                if (
                    granularity != "raw"
                    or series.legacy_output_index is None
                    or series.legacy_output_count is None
                ):
                    raise ControlOperationError(
                        "invalid_input", "legacy statistics support raw granularity only"
                    )
                collected: list[StatisticPoint] = []
                for date in _legacy_statistic_dates(start, end):
                    phase_started = time.perf_counter()
                    payload = await session.legacy_statistic_data(control.uuid, date)
                    fetch_seconds += time.perf_counter() - phase_started
                    phase_started = time.perf_counter()
                    decoded = await run_admitted_worker(
                        _legacy_points_in_range,
                        payload,
                        series.legacy_output_index,
                        series.legacy_output_count,
                        start,
                        end,
                        # Released reads retain independent per-file and selected-total
                        # bounds. Analysis explicitly supplies a remaining parse budget.
                        100_000 if maximum_points is None else maximum_points - len(collected),
                    )
                    collected.extend(decoded)
                    if len(collected) > selected_limit:
                        raise ControlOperationError(
                            "temporarily_unavailable",
                            "legacy statistic response contains too many points",
                        )
                    parse_seconds += time.perf_counter() - phase_started
                points = tuple(collected)
            else:
                phase_started = time.perf_counter()
                info = await session.statistic_info(control.uuid)
                fetch_seconds += time.perf_counter() - phase_started
                available = {
                    str(item.get("id"))
                    for item in info
                    if isinstance(item.get("id"), int | str)
                    and not isinstance(item.get("id"), bool)
                }
                if series.group_id not in available:
                    raise ControlOperationError("not_found", "statistic data is not available")
                phase_started = time.perf_counter()
                payload = await session.statistic_data(
                    control.uuid,
                    mode="diff" if series.accumulated and granularity != "raw" else "raw",
                    start=start,
                    end=end,
                    unit="all" if granularity == "raw" else granularity,
                    group_id=series.group_id,
                    output=series.output,
                )
                fetch_seconds += time.perf_counter() - phase_started
                phase_started = time.perf_counter()
                points = await run_admitted_worker(
                    _points_in_range, payload, start, end, selected_limit
                )
                parse_seconds += time.perf_counter() - phase_started
        except ControlOperationError:
            raise
        except LoxoneCommandRejected as exc:
            raise ControlOperationError(
                "temporarily_unavailable", "Miniserver rejected the statistic request"
            ) from exc
        except LoxoneProtocolError as exc:
            raise ControlOperationError(
                "temporarily_unavailable",
                f"Miniserver returned invalid statistic data: {exc}",
            ) from exc
        except (LoxoneConnectionError, TimeoutError, ValueError) as exc:
            raise ControlOperationError(
                "temporarily_unavailable", "Statistic data could not be read"
            ) from exc
        _history_duration(trace_id, "statistics_fetch", fetch_seconds)
        _history_duration(trace_id, "statistics_parse", parse_seconds)
        self.statistics_cache.put(cache_key, points)
        return control, series, points

    async def get_control_history(
        self, access: StoredAccessToken, control_uuid: str, *, include_hidden: bool = False
    ) -> tuple[Control, tuple[ControlHistoryEntry, ...]]:
        history_session = (
            self._history_session(access, control_uuid, include_hidden=True)
            if include_hidden
            else self._history_session(access, control_uuid)
        )
        async with (
            history_session as (
                control,
                session,
            )
        ):
            trace_id = _HISTORY_TRACE_ID.get() or uuid4().hex
            if not control.has_history or control.action_uuid is None:
                raise ControlOperationError("not_found", "control history is not available")
            try:
                fetch_started = time.perf_counter()
                raw = await session.control_history(control.action_uuid)
                _history_phase(trace_id, "history_fetch", fetch_started)
            except (LoxoneConnectionError, LoxoneProtocolError, TimeoutError, ValueError) as exc:
                raise ControlOperationError(
                    "temporarily_unavailable", "Control history could not be read"
                ) from exc
        parse_started = time.perf_counter()
        entries = normalize_control_history_entries(raw)
        _history_phase(trace_id, "history_parse", parse_started)
        return control, entries

    async def get_notification_state(
        self, access: StoredAccessToken
    ) -> tuple[RuntimeSnapshot, str, StateRecord, str]:
        """Use the existing caller-owned state cache, without a history collector."""
        async with self.call_slot(access):
            snapshot = await self.snapshot(access, fresh_visibility=True)
            states = [
                item.state_uuid
                for item in snapshot.structure.global_metadata
                if item.kind == "global_state" and item.identifier == "notifications"
            ]
            uuid = identifier(states[0]) if len(states) == 1 else None
            if uuid is None:
                raise ControlOperationError(
                    "unsupported_source", "Notification state is not advertised"
                )
            probe = await self.client.probe()
            if probe.firmware not in SUPPORTED_FIRMWARE:
                raise ControlOperationError(
                    "unsupported_source", "Notification firmware contract is not verified"
                )
            if canonical_serial(probe.serial) != canonical_serial(
                snapshot.structure.identity.miniserver_serial
            ):
                raise ControlOperationError(
                    "unsupported_source", "Notification source identity does not match"
                )
            record = self.state(snapshot, uuid)
            await self._require_access(access)
            return snapshot, uuid, record, probe.firmware

    async def get_system_messages(
        self, access: StoredAccessToken, *, include_history: bool = False
    ) -> MessageSource:
        """Read through a fresh caller session, with independent source permission."""
        slot = self.history_call_slot(access) if include_history else self.call_slot(access)
        async with slot, self.message_source_session(access) as (_session, result, _rights):
            if not include_history:
                result.records = [record for record in result.records if not record.historic]
            return result

    @asynccontextmanager
    async def message_source_session(
        self, access: StoredAccessToken
    ) -> AsyncIterator[tuple[LoxoneWebSocketSession, MessageSource, int]]:
        """Fresh source authorization and the same authenticated dispatch session."""
        if (
            self.token_health is not None
            and self.token_health.get(access.family_id).confirmation_required
        ):
            raise ControlOperationError(
                "permission_denied", "Token use requires administrator confirmation"
            )
        session: LoxoneWebSocketSession | None = None
        token: LoxoneToken | None = None
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
            if token is None:
                raise ControlOperationError(
                    "permission_denied", "Loxone authorization is unavailable"
                )
            session = await self._open_session(
                token, owner="tool_request", phase="session_establishment", access=access
            )
            if self.token_health is not None:
                self.token_health.record_successful_authentication(access.family_id)
            structure = await session.load_structure()
            rights = structure.user_rights
            if rights is None or not rights & SYSTEM_MESSAGES_PERMISSION:
                raise ControlOperationError(
                    "permission_denied", "System Messages permission is required"
                )
            center = structure.message_center_uuid
            if center is None:
                raise ControlOperationError(
                    "unsupported_source", "Exactly one valid Message Center is required"
                )
            probe = await self.client.probe()
            if probe.firmware not in SUPPORTED_FIRMWARE:
                raise ControlOperationError(
                    "unsupported_source", "Message Center firmware contract is not verified"
                )
            if canonical_serial(probe.serial) != canonical_serial(
                structure.identity.miniserver_serial
            ):
                raise ControlOperationError(
                    "unsupported_source", "Message Center source identity does not match"
                )
            await self._require_access(access)
            raw = await session.system_messages(center)
            result = decode_messages(
                raw,
                firmware=probe.firmware,
                serial=structure.identity.miniserver_serial,
                center=center,
                rights=rights,
            )
            await self._require_access(access)
            yield session, result, rights
        except LoxoneCommandRejected as exc:
            if session is None and self.token_health is not None:
                self.token_health.record_rejected_authentication(access.family_id)
            raise ControlOperationError(
                "permission_denied", "Miniserver rejected message access"
            ) from exc
        except RuntimeAuthorizationError as exc:
            raise ControlOperationError(
                "permission_denied", "Loxone authorization is unavailable"
            ) from exc
        except MessageSourceError as exc:
            raise ControlOperationError("unsupported_source", str(exc)) from exc
        except (
            LoxoneTokenStoreError,
            LoxoneConnectionError,
            LoxoneProtocolError,
            TimeoutError,
        ) as exc:
            raise ControlOperationError(
                "temporarily_unavailable", "System Messages source could not be read"
            ) from exc
        finally:
            try:
                if session is not None:
                    await session.close()
            finally:
                if token is not None:
                    token.destroy()

    async def get_control_notes(
        self, access: StoredAccessToken, control_uuid: str, *, include_hidden: bool = False
    ) -> tuple[Control, str]:
        """Read bounded user-authored notes for one currently visible control."""
        trace_id = _HISTORY_TRACE_ID.get() or uuid4().hex
        started = time.perf_counter()
        if not control_uuid or len(control_uuid) > 128:
            raise ControlOperationError("invalid_input", "invalid control identifier")
        try:
            async with self.call_slot(access):
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
                _history_phase(trace_id, "authorization", started)
                session: LoxoneWebSocketSession | None = None
                try:
                    started = time.perf_counter()
                    session = await self._open_session(
                        token, owner="tool_request", phase="session_establishment", access=access
                    )
                    _history_phase(trace_id, "connection", started)
                    started = time.perf_counter()
                    structure = await session.load_structure()
                    _history_phase(trace_id, "structure", started)
                    started = time.perf_counter()
                    control = self._control(structure, control_uuid, include_hidden=include_hidden)
                    _history_phase(trace_id, "visibility", started)
                    if control is None:
                        raise ControlOperationError("not_found", "control is not visible")
                    if not control.has_notes or control.action_uuid is None:
                        raise ControlOperationError("not_found", "control notes are not available")
                    started = time.perf_counter()
                    notes = await session.control_notes(control.action_uuid)
                    _history_phase(trace_id, "notes_fetch", started)
                    return control, notes
                except RuntimeAuthorizationError as exc:
                    raise ControlOperationError("permission_denied", str(exc)) from exc
                except RuntimeUnavailable as exc:
                    raise ControlOperationError("temporarily_unavailable", str(exc)) from exc
                except ControlOperationError:
                    raise
                except (
                    LoxoneConnectionError,
                    LoxoneProtocolError,
                    TimeoutError,
                    ValueError,
                ) as exc:
                    raise ControlOperationError(
                        "temporarily_unavailable", "Control notes could not be read"
                    ) from exc
                finally:
                    if session is not None:
                        await session.close()
        except RuntimeUnavailable as exc:
            raise ControlOperationError("rate_limited", str(exc)) from exc

    async def snapshot(
        self, access: StoredAccessToken, *, fresh_visibility: bool = False
    ) -> RuntimeSnapshot:
        await self._require_access(access)
        return await self._snapshot_admitted(access, fresh_visibility=fresh_visibility)

    @asynccontextmanager
    async def snapshot_context(
        self, access: StoredAccessToken, *, fresh_visibility: bool = True
    ) -> AsyncIterator[RuntimeSnapshot]:
        """Hold read admission through local work and authorize before publication.

        Callers must leave this context successfully before returning derived
        data. Admission already checks access after waiting, so the private
        snapshot path does not repeat that same pre-admission entry check.
        """
        async with self.call_slot(access):
            snapshot = await self._snapshot_admitted(access, fresh_visibility=fresh_visibility)
            yield snapshot
            await self._require_access(access)

    async def _snapshot_admitted(
        self, access: StoredAccessToken, *, fresh_visibility: bool
    ) -> RuntimeSnapshot:
        """Only enter through snapshot's access gate or snapshot_context's slot."""
        subject = access.family_id
        # Admission precedes family locks. Disconnect never takes admission, so
        # pruning cannot reverse the order while waiting for a family holder.
        async with self._admission_lock:
            await self._require_access(access)
            if self._closed:
                raise RuntimeUnavailable("Loxone runtime is closed")
            await self._prune_sessions(subject)
            record = self._records.get(subject)
            connected_now = False
            if record is None or record.task.done():
                async with self._locks.hold(subject):
                    await self._require_access(access)
                    record = self._records.get(subject)
                    if record is None or record.task.done():
                        record = await self._connect(access)
                        try:
                            await self._require_access(access)
                            if self._closed:
                                raise RuntimeUnavailable("Loxone runtime is closed")
                        except BaseException:
                            record.task.cancel()
                            with suppress(asyncio.CancelledError, Exception):
                                await record.task
                            self.cache.clear(subject)
                            raise
                        self._records[subject] = record
                        connected_now = True
        record.last_used = time.monotonic()
        if (fresh_visibility and not connected_now) or (
            record.last_structure_check + self.structure_refresh_seconds <= record.last_used
        ):
            async with record.refresh_lock:
                record.last_used = time.monotonic()
                if (fresh_visibility and not connected_now) or (
                    record.last_structure_check + self.structure_refresh_seconds <= record.last_used
                ):
                    await self._refresh_structure(access, record, fresh_visibility=fresh_visibility)
        await self._require_access(access)
        return RuntimeSnapshot(
            subject,
            record.structure,
            record.connected and not record.task.done(),
            record.generation,
        )

    async def _connect(self, access: StoredAccessToken) -> _ConnectionRecord:
        if (
            self.token_health is not None
            and self.token_health.get(access.family_id).confirmation_required
        ):
            raise RuntimeUnavailable(
                "Loxone token use requires local administrator confirmation before another login"
            )
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
        except LoxoneTokenStoreError as exc:
            raise RuntimeUnavailable("Loxone authorization is unavailable") from exc
        if token is None:
            raise RuntimeUnavailable("Loxone authorization is unavailable")
        try:
            session = await self._open_session(
                token, owner="runtime_event_stream", phase="session_establishment", access=access
            )
        except MiniserverAuthenticationSuppressed as exc:
            raise RuntimeUnavailable(
                "Miniserver authentication is temporarily unavailable"
            ) from exc
        except LoxoneSourceIpBlocked as exc:
            raise RuntimeUnavailable(
                "Miniserver temporarily blocked this source IP after failed login attempts"
            ) from exc
        except LoxoneCommandRejected as exc:
            if exc.response_code == "4003":
                raise RuntimeUnavailable(
                    "Miniserver temporarily blocked this source IP after failed login attempts"
                ) from exc
            health = (
                self.token_health.record_rejected_authentication(access.family_id)
                if self.token_health is not None
                else None
            )
            if health is not None and health.confirmation_required:
                _LOGGER.warning("component=auth outcome=token_confirmation_required")
                raise RuntimeUnavailable(
                    "Loxone token use requires local administrator confirmation "
                    "before another login"
                ) from exc
            raise RuntimeUnavailable(_token_auth_rejection_message(exc.response_code)) from exc
        except LoxoneConnectionError as exc:
            raise RuntimeUnavailable("Miniserver connection failed") from exc
        try:
            structure = await session.load_structure()
        except LoxoneConnectionError as exc:
            await session.close()
            raise RuntimeUnavailable("Miniserver structure access failed") from exc
        if self.token_health is not None:
            self.token_health.record_successful_authentication(access.family_id)
        allowed = _structure_state_uuids(structure)
        self.cache.begin_connection(access.family_id)
        placeholder = asyncio.create_task(asyncio.sleep(0))
        now = time.monotonic()
        record = _ConnectionRecord(
            structure,
            allowed,
            session,
            placeholder,
            last_structure_check=now,
            last_used=now,
        )
        lifecycle_event(
            "connection_opened", family_id=access.family_id, source="runtime", outcome="opened"
        )
        record.task = asyncio.create_task(self._maintain(access, token, record))
        initial_state_wait = asyncio.create_task(record.initial_state_batch.wait())
        try:
            done, _pending = await asyncio.wait(
                {initial_state_wait, record.task},
                timeout=self._initial_state_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if record.task in done and not record.initial_state_batch.is_set():
                await record.task
                raise RuntimeUnavailable("Miniserver state subscription failed")
            if not record.initial_state_batch.is_set():
                record.close_reason = "initial_state_timeout"
                raise RuntimeUnavailable("Miniserver initial state timed out")
        except BaseException as exc:
            if not record.task.done():
                if (
                    not isinstance(exc, asyncio.CancelledError)
                    and record.close_reason == "local_disconnect"
                ):
                    record.close_reason = "transport_failed"
                record.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await record.task
            await record.session.close()
            self.cache.disconnect(access.family_id)
            raise
        finally:
            if not initial_state_wait.done():
                initial_state_wait.cancel()
                with suppress(asyncio.CancelledError):
                    await initial_state_wait
        return record

    async def _prune_sessions(self, keep_subject: str) -> None:
        now = time.monotonic()
        for subject, record in tuple(self._records.items()):
            if subject != keep_subject and now - record.last_used >= self.session_idle_seconds:
                await self.disconnect(subject, reason="idle_eviction")
        active = [
            (subject, record)
            for subject, record in self._records.items()
            if subject != keep_subject and not record.task.done()
        ]
        while len(active) >= self.max_active_sessions:
            subject, _record = min(active, key=lambda item: item[1].last_used)
            await self.disconnect(subject, reason="capacity_eviction")
            active = [item for item in active if item[0] != subject]

    def _find_received_structure(self, parse_identity: str) -> LoxoneStructure | None:
        # Existing bounded connection records own immutable values, never access.
        if not parse_identity:
            return None
        for record in self._records.values():
            if record.structure.parse_identity == parse_identity:
                return record.structure
        return None

    def _has_received_structure(self, username: str) -> bool:
        return any(
            record.structure.parse_identity and record.structure.identity.username == username
            for record in self._records.values()
        )

    async def _refresh_structure(
        self,
        access: StoredAccessToken,
        record: _ConnectionRecord,
        *,
        fresh_visibility: bool = False,
    ) -> None:
        if (
            self._records.get(access.family_id) is not record
            or not record.connected
            or record.task.done()
        ):
            await self._require_access(access)
            raise RuntimeUnavailable("Loxone runtime connection changed during structure refresh")
        phase = AvailabilityPhase.TOKEN
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
            if token is None:
                raise LoxoneTokenStoreError("Loxone token is unavailable")
            phase = AvailabilityPhase.SESSION
            session_started = time.monotonic()
            session = await self._open_session(
                token, owner="tool_request", phase="session_establishment", access=access
            )
            if fresh_visibility:
                _LOGGER.info(
                    "component=project_load phase=visibility_open duration_ms=%.1f",
                    (time.monotonic() - session_started) * 1000,
                )
            try:
                if not fresh_visibility:
                    phase = AvailabilityPhase.VERSION
                    version = await session.structure_version()
                    if version == record.structure.last_modified:
                        record.last_structure_check = time.monotonic()
                        _LOGGER.debug("component=structure outcome=unchanged")
                        return
                phase = AvailabilityPhase.LOAD
                command_started = time.monotonic()
                structure = await session.load_structure()
                if fresh_visibility:
                    _LOGGER.info(
                        "component=project_load phase=visibility_command duration_ms=%.1f",
                        (time.monotonic() - command_started) * 1000,
                    )
            finally:
                operation_phase = phase
                phase = AvailabilityPhase.CLOSE
                close_started = time.monotonic()
                await session.close()
                if fresh_visibility:
                    _LOGGER.info(
                        "component=project_load phase=visibility_close duration_ms=%.1f",
                        (time.monotonic() - close_started) * 1000,
                    )
                phase = operation_phase
        except RuntimeAuthorizationError:
            raise
        except Exception as exc:
            reason = (
                AvailabilityReason.REFRESH_AUTH_BUSY
                if isinstance(exc, MiniserverAuthenticationBusy)
                else AvailabilityReason.REFRESH_AUTH_COOLDOWN
                if isinstance(exc, MiniserverAuthenticationCooldown)
                else AvailabilityReason.REFRESH_SOURCE_IP
                if isinstance(exc, MiniserverSourceIpSuppressed | LoxoneSourceIpBlocked)
                or (isinstance(exc, LoxoneCommandRejected) and exc.response_code == "4003")
                else AvailabilityReason.REFRESH_TIMEOUT
                if isinstance(exc, TimeoutError)
                else AvailabilityReason.REFRESH_CONNECTION
                if isinstance(exc, LoxoneConnectionError)
                else AvailabilityReason.REFRESH_PROTOCOL
                if isinstance(exc, LoxoneProtocolError)
                else AvailabilityReason.REFRESH_TOKEN
                if isinstance(exc, LoxoneTokenStoreError)
                else AvailabilityReason.REFRESH_TIMEOUT
                if isinstance(exc, TimeoutError)
                else AvailabilityReason.REFRESH_UNKNOWN
            )
            _LOGGER.warning(
                "component=structure outcome=refresh_failed diagnostic_code=%s "
                "availability_phase=%s",
                reason.value,
                phase.value,
            )
            raise RuntimeUnavailable(
                "Miniserver structure refresh failed", reason=reason, phase=phase
            ) from exc
        # Cleanup can finish while this independently owned request is awaiting
        # network I/O. Only the current live owner may publish into family cache.
        # Do not take the family lock while holding refresh_lock.
        if (
            self._records.get(access.family_id) is not record
            or not record.connected
            or record.task.done()
        ):
            await self._require_access(access)
            raise RuntimeUnavailable("Loxone runtime connection changed during structure refresh")
        record.last_structure_check = time.monotonic()
        if structure == record.structure:
            # Equal normalized data can originate from different exact bytes.
            record.structure = structure
            _LOGGER.debug("component=structure outcome=unchanged")
            return
        if not fresh_visibility and structure.last_modified == record.structure.last_modified:
            _LOGGER.warning("component=structure outcome=version_mismatch_without_change")
            return
        record.structure = structure
        record.allowed_states = _structure_state_uuids(structure)
        record.generation += 1
        self.cache.apply(access.family_id, (), allowed_uuids=record.allowed_states)
        _LOGGER.info("component=structure outcome=changed")

    async def _maintain(
        self,
        access: StoredAccessToken,
        token: LoxoneToken,
        record: _ConnectionRecord,
    ) -> None:
        events = asyncio.create_task(self._pump_events(access.family_id, record))
        close_reason = "stream_ended"
        try:
            while not events.done():
                refresh_at = token.valid_until + _LOXONE_EPOCH_UNIX - _REFRESH_BEFORE_SECONDS
                timeout = max(1.0, min(3600.0, refresh_at - time.time()))
                done, _pending = await asyncio.wait({events}, timeout=timeout)
                if done:
                    await events
                    break
                if refresh_at <= time.time():
                    events.cancel()
                    with suppress(asyncio.CancelledError):
                        await events
                    await record.session.close()
                    refreshed = await self._open_session(
                        token, owner="runtime_event_stream", phase="token_refresh", access=access
                    )
                    try:
                        await refreshed.refresh_token()
                        self.token_store.put(
                            access.family_id,
                            access.miniserver_id,
                            access.identity_id,
                            token,
                        )
                    finally:
                        await refreshed.close()
                    close_reason = "token_refresh"
                    record.connected = False
                    self.cache.disconnect(access.family_id)
                    break
        except asyncio.CancelledError:
            close_reason = record.close_reason
            raise
        except Exception as exc:
            close_reason = "transport_failed"
            _LOGGER.warning(
                "component=state_cache outcome=event_stream_failed error_type=%s",
                type(exc).__name__,
            )
            record.connected = False
            self.cache.disconnect(access.family_id)
        finally:
            events.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await events
            # Normal iterator exhaustion and cancellation are terminal too.
            # Invalidate freshness before awaiting websocket teardown.
            record.connected = False
            self.cache.disconnect(access.family_id)
            try:
                await record.session.close()
            except BaseException:
                lifecycle_event(
                    "connection_closed",
                    family_id=access.family_id,
                    source="runtime",
                    reason="teardown_failed",
                    outcome="failed",
                )
                raise
            else:
                lifecycle_event(
                    "connection_closed",
                    family_id=access.family_id,
                    source="runtime",
                    reason=close_reason,
                    outcome="closed",
                )

    async def _open_session(
        self,
        token: LoxoneToken,
        *,
        owner: str,
        phase: str,
        access: StoredAccessToken | None = None,
        require_token_confirmation: bool = False,
    ) -> LoxoneWebSocketSession:
        """Open a session through the shared source-IP breaker when configured."""
        coordinator = getattr(self, "auth_coordinator", None)
        coordinated = False

        async def authorize() -> None:
            nonlocal coordinated
            coordinated = True
            if access is not None:
                await self._require_access(access)
                if (
                    require_token_confirmation
                    and self.token_health is not None
                    and self.token_health.get(access.family_id).confirmation_required
                ):
                    raise ControlOperationError(
                        "permission_denied", "Token use requires confirmation"
                    )
            if getattr(self, "_closed", False):
                raise RuntimeUnavailable("Loxone runtime is closed")

        if not isinstance(coordinator, MiniserverAuthCoordinator):
            await authorize()
            return await self.client.open_session(token)

        # Coordination and login consume one existing connection budget. Outer
        # caller cancellation remains effective, including while queued locally.
        budget = self.client.timeout_seconds
        provenance = None
        if owner == "tool_request" and access is not None and self.auth_binding is not None:
            provenance = AttemptProvenance(
                binding_id=self.auth_binding(access), trace_id=_HISTORY_TRACE_ID.get()
            )
        try:
            async with asyncio.timeout(budget):
                return await coordinator.attempt(
                    lambda: self.client.open_session(token),
                    owner=owner,
                    phase=phase,
                    provenance=provenance,
                    busy_wait_seconds=min(30.0, budget),
                    before_attempt=authorize,
                )
        except TimeoutError as exc:
            if not coordinated:
                raise MiniserverAuthenticationBusy(
                    "Miniserver authentication coordination timed out"
                ) from exc
            raise _SessionEstablishmentTimeout(
                "Miniserver session establishment timed out"
            ) from exc

    async def project_marker(self, token: LoxoneToken) -> str:
        """Read the project marker through the shared authentication coordinator."""
        started = time.monotonic()
        session = await self._open_session(token, owner="tool_request", phase="project_marker")
        _LOGGER.info(
            "component=project_load phase=marker_open duration_ms=%.1f",
            (time.monotonic() - started) * 1000,
        )
        try:
            started = time.monotonic()
            marker = await session.structure_version()
            _LOGGER.info(
                "component=project_load phase=marker_command duration_ms=%.1f",
                (time.monotonic() - started) * 1000,
            )
            return marker
        finally:
            started = time.monotonic()
            await session.close()
            _LOGGER.info(
                "component=project_load phase=marker_close duration_ms=%.1f",
                (time.monotonic() - started) * 1000,
            )

    async def _pump_events(self, subject: str, record: _ConnectionRecord) -> None:
        async for event_batch in record.session.state_events():
            if not record.state_stream_diagnostics_logged:
                matching = sum(event.uuid in record.allowed_states for event in event_batch)
                _LOGGER.debug(
                    "component=loxone.runtime severity=DEBUG outcome=state_event_batch "
                    "code=received_%d_matched_%d",
                    len(event_batch),
                    matching,
                )
                record.state_stream_diagnostics_logged = True
            self.cache.apply(subject, event_batch, allowed_uuids=record.allowed_states)
            record.initial_state_batch.set()

    def state(self, snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
        return self.cache.get(snapshot.subject, uuid)

    async def disconnect(self, family_id: str, *, reason: str = "local_disconnect") -> None:
        # Wait for an in-flight connection before removing its eventual record.
        # Never acquire the control lock here: control calls acquire connection
        # locks through snapshot(), and cleanup must not reverse that order.
        async with self._locks.hold(family_id):
            record = self._records.pop(family_id, None)
            if record is not None:
                record.close_reason = reason
                lifecycle_event(
                    "connection_close_requested",
                    family_id=family_id,
                    source="runtime",
                    reason=reason,
                    outcome="pending",
                    debug=True,
                )
                record.task.cancel()
                with suppress(asyncio.CancelledError):
                    await record.task
            self.cache.clear(family_id)
        self._prune_rate_state(time.monotonic())

    async def revoke(self, family_id: str, *, reason: str = "oauth_revocation") -> None:
        projects = getattr(self, "projects", None)
        if projects is not None:
            await projects.revoke(family_id)
        await self.disconnect(family_id, reason=reason)

    async def close(self) -> None:
        # Stop queued admission before waiting for a connection already opening.
        self._closed = True
        projects = getattr(self, "projects", None)
        if projects is not None:
            await projects.close()
        async with self._admission_lock:
            for family_id in tuple(self._records):
                await self.disconnect(family_id, reason="shutdown")
        lifecycle_event("runtime_closed", source="runtime", reason="shutdown", outcome="closed")
