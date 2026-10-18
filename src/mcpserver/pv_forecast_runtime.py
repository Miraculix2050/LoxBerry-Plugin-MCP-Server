"""Caller-authorized native PVPF read, separate from planning and MCP transport."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from mcpserver.auth.loxone_store import LoxoneTokenStoreError
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import (
    LoxoneConnectionError,
    LoxoneTokenAuthenticationRejected,
)
from mcpserver.loxone.events import LoxonePayloadTooLarge, LoxoneProtocolError
from mcpserver.loxone.models import Control, Freshness, LoxoneStructure
from mcpserver.loxone.pv_forecast import PvForecastError, PvForecastResult, decode_forecast
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime, RuntimeUnavailable
from mcpserver.loxone.uuid import normalize_loxone_uuid

if TYPE_CHECKING:
    from mcpserver.loxone.client import LoxoneWebSocketSession


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
    """One forecast request; visibility and identity checked before publication."""
    if READ_SCOPE not in access.scopes:
        raise PermissionError("loxone:read scope is required")
    try:
        uuid = normalize_loxone_uuid(uuid)
    except ValueError:
        raise ControlOperationError("invalid_input", "Invalid PV forecast target") from None
    session: LoxoneWebSocketSession | None = None
    token = None
    try:
        async with asyncio.timeout(30), runtime.snapshot_context(access) as snapshot:
            control = visible_pvpf(snapshot.structure, uuid)
            try:
                action = normalize_loxone_uuid(control.action_uuid)
            except ValueError:
                raise ControlOperationError(
                    "unsupported_source", "Invalid PVPF action identity"
                ) from None
            token = runtime.token_store.get(
                access.family_id, access.miniserver_id, access.identity_id
            )
            if token is None:
                raise RuntimeUnavailable("Loxone authorization is unavailable")
            session = await runtime._open_session(
                token,
                owner="tool_request",
                phase="session_establishment",
                access=access,
                require_token_confirmation=True,
            )
            if runtime.token_health is not None:
                runtime.token_health.record_successful_authentication(access.family_id)
            raw = await session.pv_forecast(action)
            refreshed = await session.load_structure()
            after = visible_pvpf(refreshed, uuid)
            if (
                after.action_uuid != control.action_uuid
                or refreshed.identity != snapshot.structure.identity
                or after.state_uuids != control.state_uuids
            ):
                raise ControlOperationError("temporarily_unavailable", "PV forecast source changed")
            states: dict[str, object] = {}
            for name, state_uuid in control.state_uuids:
                record = runtime.cache.get(snapshot.subject, state_uuid)
                if record.freshness is Freshness.CURRENT:
                    states[name] = record.value
            result = decode_forecast(
                raw,
                states,
                control_uuid=uuid,
                retrieved_at=datetime.now(UTC).isoformat(),
                now=datetime.now(UTC).timestamp(),
            )
        return after, refreshed, result
    except LoxonePayloadTooLarge:
        raise ControlOperationError(
            "response_too_large", "PV forecast response exceeds bounds"
        ) from None
    except PvForecastError:
        raise ControlOperationError(
            "unsupported_source", "PV forecast response is invalid"
        ) from None
    except LoxoneTokenAuthenticationRejected:
        if runtime.token_health is not None:
            runtime.token_health.record_rejected_authentication(access.family_id)
        raise ControlOperationError("permission_denied", "Loxone authentication rejected") from None
    except (TimeoutError, LoxoneConnectionError, LoxoneProtocolError, LoxoneTokenStoreError):
        raise ControlOperationError(
            "temporarily_unavailable", "PV forecast read timed out"
        ) from None
    finally:
        if session is not None:
            with suppress(Exception):
                await asyncio.wait_for(session.close(), 1)
        if token is not None:
            token.destroy()
