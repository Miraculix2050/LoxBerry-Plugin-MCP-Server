"""Caller-authorized native PVPF read, separate from planning and MCP transport."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from mcpserver.auth.loxone_store import LoxoneTokenStoreError
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneResponseEnvelopeError,
    LoxoneSourceIpBlocked,
    LoxoneTokenAuthenticationRejected,
    LoxoneWebSocketClosed,
    LoxoneWebSocketConnectionFailed,
)
from mcpserver.loxone.events import LoxonePayloadTooLarge, LoxoneProtocolError
from mcpserver.loxone.models import Control, Freshness, LoxoneStructure
from mcpserver.loxone.pv_forecast_hours import PvForecastError, PvForecastResult, decode_forecast
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime, RuntimeUnavailable
from mcpserver.loxone.uuid import normalize_loxone_uuid

if TYPE_CHECKING:
    from mcpserver.loxone.client import LoxoneWebSocketSession


# Reuse the existing runtime diagnostic component and bounded service-event fields.
_LOGGER = logging.getLogger("mcpserver.loxone.runtime")


def _read_failure(
    trace_id: str, phase: str, reason: str, code: str, message: str
) -> ControlOperationError:
    """Log only fixed caller-independent labels; never exception or response text."""
    _LOGGER.debug(
        "trace_id=%s outcome=error code=pv_forecast_%s error_type=%s",
        trace_id,
        phase,
        reason,
    )
    return ControlOperationError(code, message, trace_id=trace_id)


def visible_pvpf(structure: LoxoneStructure, uuid: str) -> Control:
    control = next((c for c in structure.controls if c.uuid == uuid and not c.is_hidden), None)
    if control is None:
        raise ControlOperationError("not_found", "PV forecast target is not accessible")
    if control.control_type.casefold() != "pvproductionforecast":
        raise ControlOperationError("unsupported_source", "A native PVPF source is required")
    return control


async def read_pv_forecast(
    runtime: LoxoneRuntime, access: StoredAccessToken, uuid: str
) -> tuple[Control, LoxoneStructure, PvForecastResult]:
    """Read one forecast through the shared bounded transport."""
    return (await read_pv_forecasts(runtime, access, [uuid]))[0]


async def read_pv_forecasts(
    runtime: LoxoneRuntime, access: StoredAccessToken, uuids: list[str]
) -> list[tuple[Control, LoxoneStructure, PvForecastResult]]:
    """One session, one command per distinct PVPF, one publication structure read."""
    if READ_SCOPE not in access.scopes:
        raise PermissionError("loxone:read scope is required")
    try:
        uuids = [normalize_loxone_uuid(uuid) for uuid in uuids]
        if not 1 <= len(uuids) <= 4 or len(set(uuids)) != len(uuids):
            raise ValueError("invalid forecast selection")
    except ValueError:
        raise ControlOperationError("invalid_input", "Invalid PV forecast target") from None
    session: LoxoneWebSocketSession | None = None
    token = None
    trace_id = str(uuid4())
    phase = "snapshot"
    try:
        async with asyncio.timeout(30), runtime.snapshot_context(access) as snapshot:
            controls = [visible_pvpf(snapshot.structure, uuid) for uuid in uuids]
            try:
                actions = [normalize_loxone_uuid(control.action_uuid) for control in controls]
                if len(set(actions)) != len(actions):
                    raise ValueError("duplicate forecast action identity")
            except ValueError:
                raise ControlOperationError(
                    "unsupported_source", "Invalid PVPF action identity"
                ) from None
            phase = "token_lookup"
            token = runtime.token_store.get(
                access.family_id, access.miniserver_id, access.identity_id
            )
            if token is None:
                raise RuntimeUnavailable("Loxone authorization is unavailable")
            phase = "session_establishment"
            session = await runtime._open_session(
                token,
                owner="tool_request",
                phase="session_establishment",
                access=access,
                require_token_confirmation=True,
            )
            if runtime.token_health is not None:
                runtime.token_health.record_successful_authentication(access.family_id)
            payloads = []
            for control, action in zip(controls, actions, strict=True):
                ready_records = [
                    runtime.cache.get(snapshot.subject, state_uuid)
                    for name, state_uuid in control.state_uuids
                    if name == "ready"
                ]
                not_ready = any(
                    record.freshness is Freshness.CURRENT
                    and type(record.value) in {int, float}
                    and record.value == 0
                    for record in ready_records
                )
                phase = "forecast_command"
                payloads.append("{}" if not_ready else await session.pv_forecast(action))
            phase = "structure_recheck"
            refreshed = await session.load_structure()
            results = []
            for control, raw in zip(controls, payloads, strict=True):
                after = visible_pvpf(refreshed, control.uuid)
                if (
                    after.action_uuid != control.action_uuid
                    or refreshed.identity != snapshot.structure.identity
                    or after.state_uuids != control.state_uuids
                ):
                    raise ControlOperationError(
                        "temporarily_unavailable", "PV forecast source changed"
                    )
                states: dict[str, object] = {}
                for name, state_uuid in control.state_uuids:
                    record = runtime.cache.get(snapshot.subject, state_uuid)
                    if record.freshness is Freshness.CURRENT:
                        states[name] = record.value
                phase = "forecast_decode"
                result = decode_forecast(
                    raw,
                    states,
                    control_uuid=control.uuid,
                    retrieved_at=datetime.now(UTC).isoformat(),
                    now=datetime.now(UTC).timestamp(),
                )
                results.append((after, refreshed, result))
        return results
    except LoxonePayloadTooLarge:
        raise _read_failure(
            trace_id,
            phase,
            "payload_too_large",
            "response_too_large",
            "PV forecast response exceeds bounds",
        ) from None
    except PvForecastError:
        raise _read_failure(
            trace_id,
            phase,
            "forecast_invalid",
            "unsupported_source",
            "PV forecast response is invalid",
        ) from None
    except LoxoneTokenAuthenticationRejected:
        if runtime.token_health is not None:
            runtime.token_health.record_rejected_authentication(access.family_id)
        raise _read_failure(
            trace_id,
            phase,
            "authentication_rejected",
            "permission_denied",
            "Loxone authentication rejected",
        ) from None
    except TimeoutError:
        raise _read_failure(
            trace_id, phase, "timeout", "temporarily_unavailable", "PV forecast read timed out"
        ) from None
    except LoxoneProtocolError as exc:
        raise _read_failure(
            trace_id,
            phase,
            "response_envelope_invalid"
            if isinstance(exc, LoxoneResponseEnvelopeError)
            else "protocol_error",
            "temporarily_unavailable",
            "PV forecast read failed due to a protocol error",
        ) from None
    except LoxoneCommandRejected:
        raise _read_failure(
            trace_id,
            phase,
            "request_rejected",
            "temporarily_unavailable",
            "Miniserver rejected the PV forecast request",
        ) from None
    except LoxoneConnectionError as exc:
        reason = "connection_error"
        if isinstance(exc, LoxoneWebSocketClosed):
            reason = "websocket_closed"
        elif isinstance(exc, LoxoneWebSocketConnectionFailed):
            reason = "websocket_connection_failed"
        elif isinstance(exc, LoxoneSourceIpBlocked):
            reason = "source_ip_blocked"
        raise _read_failure(
            trace_id,
            phase,
            reason,
            "temporarily_unavailable",
            "PV forecast read failed due to a connection error",
        ) from None
    except LoxoneTokenStoreError:
        raise _read_failure(
            trace_id,
            phase,
            "authorization_storage_unavailable",
            "temporarily_unavailable",
            "PV forecast authorization storage is unavailable",
        ) from None
    finally:
        if session is not None:
            with suppress(Exception):
                await asyncio.wait_for(session.close(), 1)
        if token is not None:
            token.destroy()
