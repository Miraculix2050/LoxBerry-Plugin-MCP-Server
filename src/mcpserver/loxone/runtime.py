"""User-isolated Loxone connection, cache, and bounded control lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.provider import CONTROL_SCOPE, HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
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
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneStructure,
    StateRecord,
    StatisticSeries,
)
from mcpserver.loxone.statistics import (
    StatisticPoint,
    StatisticsCache,
    parse_statistic_points,
)

_LOXONE_EPOCH_UNIX = 1_230_768_000
_REFRESH_BEFORE_SECONDS = 24 * 60 * 60
_MAX_LEGACY_STATISTIC_BYTES = 64 * 1024 * 1024
_MAX_HISTORY_TIMESTAMP = 4_102_444_800
_LOGGER = logging.getLogger(__name__)


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
    payload: bytes, *, output_index: int, output_count: int
) -> tuple[StatisticPoint, ...]:
    """Decode one output from a bounded documented legacy statistic stream."""
    if not 1 <= output_count <= 16 or not 0 <= output_index < output_count:
        raise ValueError("legacy statistic output selection is invalid")
    if len(payload) > _MAX_LEGACY_STATISTIC_BYTES:
        raise LoxoneProtocolError("Statistic response exceeds the configured limit")
    record = struct.Struct(f"<I{output_count}d")
    if len(payload) % record.size:
        raise LoxoneProtocolError("Statistic response has a truncated entry")
    if len(payload) // record.size > 100_000:
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


@dataclass(frozen=True, slots=True)
class ControlHistoryEntry:
    timestamp: int
    what: str
    trigger: str
    trigger_type: str
    impacts: tuple[str, ...]


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
    generation: int = 1
    last_structure_check: float = 0.0
    last_used: float = 0.0
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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
            max_structure_controls=max_structure_controls,
            max_structure_state_references=max_structure_state_references,
            max_structure_depth=max_structure_depth,
        )
        self.cache = UserStateCache(max_states_per_user=max_states_per_identity)
        self._records: dict[str, _ConnectionRecord] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._rate_limit = requests_per_minute
        self._control_rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._control_rate_limit = control_requests_per_minute
        self._control_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._control_confirmation_seconds = control_confirmation_seconds
        self._parallel = asyncio.Semaphore(max_parallel_calls)
        self._history_rate: defaultdict[str, deque[float]] = defaultdict(deque)
        self._history_rate_limit = history_requests_per_minute
        self.statistics_cache = statistics_cache or StatisticsCache()
        self.control_enabled = control_enabled
        self.history_enabled = history_enabled
        self.structure_refresh_seconds = structure_refresh_seconds
        self.max_active_sessions = max_active_sessions
        self.session_idle_seconds = session_idle_seconds

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

    @asynccontextmanager
    async def _history_session(
        self,
        access: StoredAccessToken,
        control_uuid: str,
        *,
        include_hidden: bool = False,
    ) -> AsyncIterator[tuple[Control, LoxoneWebSocketSession]]:
        if READ_SCOPE not in access.scopes or HISTORY_SCOPE not in access.scopes:
            raise ControlOperationError("permission_denied", "loxone:history is required")
        if not self.history_enabled:
            raise ControlOperationError(
                "permission_denied", "Loxone history requires administrator activation"
            )
        if not control_uuid or len(control_uuid) > 128:
            raise ControlOperationError("invalid_input", "invalid control identifier")
        now = time.monotonic()
        if not self._consume_rate(
            self._rate[access.family_id], self._rate_limit, now
        ) or not self._consume_rate(
            self._history_rate[access.family_id], self._history_rate_limit, now
        ):
            raise ControlOperationError("rate_limited", "history rate limit exceeded")
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
        async with self._parallel:
            session: LoxoneWebSocketSession | None = None
            try:
                session = await self.client.open_session(token)
                structure = await session.load_structure()
                control = self._control(structure, control_uuid, include_hidden=include_hidden)
                if control is None:
                    raise ControlOperationError("not_found", "control is not visible")
                yield control, session
            except ControlOperationError:
                raise
            except (LoxoneConnectionError, LoxoneProtocolError, TimeoutError) as exc:
                raise ControlOperationError(
                    "loxone_unreachable", "Miniserver connection failed"
                ) from exc
            finally:
                if session is not None:
                    await session.close()

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
        cache_key = StatisticsCache.source_key(
            access.family_id, control_uuid, series_id, str(start), str(end), granularity
        )
        cached = self.statistics_cache.get(cache_key)
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
            series = next(
                (item for item in control.statistic_series if item.series_id == series_id), None
            )
            if series is None:
                raise ControlOperationError("not_found", "statistic series is not visible")
            if cached is not None:
                _LOGGER.debug("component=statistics outcome=cache_hit")
                return control, series, cached
            _LOGGER.debug("component=statistics outcome=cache_miss")
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
                        payload = await session.legacy_statistic_data(control.uuid, date)
                        for item in _parse_legacy_statistic_points(
                            payload,
                            output_index=series.legacy_output_index,
                            output_count=series.legacy_output_count,
                        ):
                            point = StatisticPoint(_LOXONE_EPOCH_UNIX + item.timestamp, item.value)
                            if start <= point.timestamp <= end:
                                collected.append(point)
                                if len(collected) > 100_000:
                                    raise ControlOperationError(
                                        "temporarily_unavailable",
                                        "legacy statistic response contains too many points",
                                    )
                    points = tuple(collected)
                else:
                    info = await session.statistic_info(control.uuid)
                    available = {
                        str(item.get("id"))
                        for item in info
                        if isinstance(item.get("id"), int | str)
                        and not isinstance(item.get("id"), bool)
                    }
                    if series.group_id not in available:
                        raise ControlOperationError("not_found", "statistic data is not available")
                    payload = await session.statistic_data(
                        control.uuid,
                        mode="diff" if series.accumulated and granularity != "raw" else "raw",
                        start=start,
                        end=end,
                        unit="all" if granularity == "raw" else granularity,
                        group_id=series.group_id,
                        output=series.output,
                    )
                    points = tuple(
                        point
                        for point in parse_statistic_points(payload)
                        if start <= point.timestamp <= end
                    )
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
            if not control.has_history or control.action_uuid is None:
                raise ControlOperationError("not_found", "control history is not available")
            try:
                raw = await session.control_history(control.action_uuid)
            except (LoxoneConnectionError, LoxoneProtocolError, TimeoutError, ValueError) as exc:
                raise ControlOperationError(
                    "temporarily_unavailable", "Control history could not be read"
                ) from exc
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
                ControlHistoryEntry(
                    timestamp, what[:500], trigger[:500], trigger_type[:64], impacts
                )
            )
        return control, tuple(entries)

    async def get_control_notes(
        self, access: StoredAccessToken, control_uuid: str, *, include_hidden: bool = False
    ) -> tuple[Control, str]:
        """Read bounded user-authored notes for one currently visible control."""
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
                session: LoxoneWebSocketSession | None = None
                try:
                    session = await self.client.open_session(token)
                    structure = await session.load_structure()
                    control = self._control(structure, control_uuid, include_hidden=include_hidden)
                    if control is None:
                        raise ControlOperationError("not_found", "control is not visible")
                    if not control.has_notes or control.action_uuid is None:
                        raise ControlOperationError("not_found", "control notes are not available")
                    notes = await session.control_notes(control.action_uuid)
                    return control, notes
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

    async def snapshot(self, access: StoredAccessToken) -> RuntimeSnapshot:
        subject = access.family_id
        await self._prune_sessions(subject)
        record = self._records.get(subject)
        if record is None or record.task.done():
            async with self._locks[subject]:
                record = self._records.get(subject)
                if record is None or record.task.done():
                    record = await self._connect(access)
                    self._records[subject] = record
        record.last_used = time.monotonic()
        if record.last_structure_check + self.structure_refresh_seconds <= record.last_used:
            async with record.refresh_lock:
                record.last_used = time.monotonic()
                if record.last_structure_check + self.structure_refresh_seconds <= record.last_used:
                    await self._refresh_structure(access, record)
        return RuntimeSnapshot(
            subject,
            record.structure,
            record.connected and not record.task.done(),
            record.generation,
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
        record.task = asyncio.create_task(self._maintain(access, token, record))
        return record

    async def _prune_sessions(self, keep_subject: str) -> None:
        now = time.monotonic()
        for subject, record in tuple(self._records.items()):
            if subject != keep_subject and now - record.last_used >= self.session_idle_seconds:
                await self.disconnect(subject)
        active = [
            (subject, record)
            for subject, record in self._records.items()
            if subject != keep_subject and not record.task.done()
        ]
        while len(active) >= self.max_active_sessions:
            subject, _record = min(active, key=lambda item: item[1].last_used)
            await self.disconnect(subject)
            active = [item for item in active if item[0] != subject]

    async def _refresh_structure(
        self, access: StoredAccessToken, record: _ConnectionRecord
    ) -> None:
        try:
            token = self.token_store.get(access.family_id, access.miniserver_id, access.identity_id)
            if token is None:
                raise LoxoneTokenStoreError("Loxone token is unavailable")
            session = await self.client.open_session(token)
            try:
                version = await session.structure_version()
                if version == record.structure.last_modified:
                    record.last_structure_check = time.monotonic()
                    _LOGGER.debug("component=structure outcome=unchanged")
                    return
                structure = await session.load_structure()
            finally:
                await session.close()
        except (LoxoneConnectionError, LoxoneProtocolError, LoxoneTokenStoreError) as exc:
            _LOGGER.warning(
                "component=structure outcome=refresh_failed error_type=%s",
                type(exc).__name__,
            )
            raise RuntimeUnavailable("Miniserver structure refresh failed") from exc
        record.last_structure_check = time.monotonic()
        if structure.last_modified == record.structure.last_modified:
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
                    refreshed = await self.client.open_session(token)
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
                    record.connected = False
                    self.cache.disconnect(access.family_id)
                    break
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

    async def disconnect(self, family_id: str) -> None:
        record = self._records.pop(family_id, None)
        if record is not None:
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task
        self.cache.clear(family_id)

    async def revoke(self, family_id: str) -> None:
        await self.disconnect(family_id)
        self.token_store.delete(family_id)

    async def close(self) -> None:
        for family_id in tuple(self._records):
            await self.disconnect(family_id)
