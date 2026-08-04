"""Stable read-only MCP tool contracts for the Phase 1 alpha."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import uuid4

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, JsonValue

from mcpserver.auth.provider import CONTROL_SCOPE, StoredAccessToken
from mcpserver.loxone.models import Control, Freshness, NamedGroup
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeSnapshot,
    RuntimeUnavailable,
)

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100
MAX_STATE_UUIDS: Final = 100
_LOGGER = logging.getLogger("mcpserver.tools")
_AUDIT_SUPPRESSION_SECONDS: Final = 60.0
_MAX_AUDIT_SUPPRESSION_KEYS: Final = 512
_AUDIT_LAST: OrderedDict[tuple[str, str], float] = OrderedDict()


class ErrorData(BaseModel):
    error: str
    message: str


class NamedGroupData(BaseModel):
    uuid: str
    name: str


class NamedGroupPageData(BaseModel):
    items: list[NamedGroupData]
    next_cursor: str | None


class ControlSummaryData(BaseModel):
    uuid: str
    name: str
    type: str
    room: NamedGroupData | None
    category: NamedGroupData | None


class ControlPageData(BaseModel):
    items: list[ControlSummaryData]
    next_cursor: str | None


class StateReferenceData(BaseModel):
    name: str
    uuid: str


class CapabilitiesData(BaseModel):
    readable: bool
    allowed_actions: list[str]


class ControlDescriptionData(ControlSummaryData):
    states: list[StateReferenceData]
    capabilities: CapabilitiesData


class StateData(BaseModel):
    uuid: str
    value: JsonValue
    freshness: str
    observed_at: str | None


class StatesData(BaseModel):
    states: list[StateData]


class SystemStatusData(BaseModel):
    reachable: bool
    miniserver_serial: str
    structure_last_modified: str
    cache_freshness: str


class ToolEnvelope(BaseModel):
    ok: bool
    data: object
    warnings: list[str] = Field(default_factory=list)
    observed_at: str
    stale: bool
    trace_id: str


class SystemStatusEnvelope(ToolEnvelope):
    data: SystemStatusData | ErrorData


class NamedGroupPageEnvelope(ToolEnvelope):
    data: NamedGroupPageData | ErrorData


class ControlPageEnvelope(ToolEnvelope):
    data: ControlPageData | ErrorData


class ControlDescriptionEnvelope(ToolEnvelope):
    data: ControlDescriptionData | ErrorData


class StatesEnvelope(ToolEnvelope):
    data: StatesData | ErrorData


class ControlOperationData(BaseModel):
    control_uuid: str
    action: Literal["on", "off"]
    accepted: bool
    confirmed: bool
    observed_state: Literal["on", "off", "unknown"]


class ControlOperationEnvelope(ToolEnvelope):
    data: ControlOperationData | ErrorData


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _result[EnvelopeT: ToolEnvelope](
    envelope_type: type[EnvelopeT],
    data: Any,
    *,
    stale: bool = False,
    warnings: list[str] | None = None,
) -> EnvelopeT:
    trace_id = str(uuid4())
    _LOGGER.info("component=tools severity=INFO trace_id=%s outcome=ok", trace_id)
    return envelope_type(
        ok=True,
        data=data,
        warnings=warnings or [],
        observed_at=_now(),
        stale=stale,
        trace_id=trace_id,
    )


def _error[EnvelopeT: ToolEnvelope](
    envelope_type: type[EnvelopeT], code: str, message: str
) -> EnvelopeT:
    trace_id = str(uuid4())
    _LOGGER.warning(
        "component=tools severity=WARNING trace_id=%s outcome=error code=%s",
        trace_id,
        code,
    )
    return envelope_type(
        ok=False,
        data={"error": code, "message": message},
        observed_at=_now(),
        stale=False,
        trace_id=trace_id,
    )


def _audit_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _control_envelope(
    access: StoredAccessToken | None,
    control_uuid: str,
    action: str,
    *,
    result: dict[str, Any] | None = None,
    error: tuple[str, str] | None = None,
    warnings: list[str] | None = None,
) -> ControlOperationEnvelope:
    trace_id = str(uuid4())
    outcome = (
        ("accepted_confirmed" if result and result.get("confirmed") else "accepted_unconfirmed")
        if error is None
        else error[0]
    )
    should_log = True
    if error is not None:
        identity = access.identity_id if access is not None else "unauthenticated"
        key = (_audit_identity(identity), outcome)
        now = time.monotonic()
        previous = _AUDIT_LAST.get(key)
        if previous is not None and previous > now - _AUDIT_SUPPRESSION_SECONDS:
            should_log = False
        else:
            _AUDIT_LAST[key] = now
            _AUDIT_LAST.move_to_end(key)
            while len(_AUDIT_LAST) > _MAX_AUDIT_SUPPRESSION_KEYS:
                _AUDIT_LAST.popitem(last=False)
    if should_log:
        log = _LOGGER.info if error is None else _LOGGER.warning
        log(
            "component=control_audit trace_id=%s client=%s identity=%s "
            "target=%s action=%s outcome=%s",
            trace_id,
            _audit_identity(str(access.client_id)) if access is not None else "unknown",
            _audit_identity(access.identity_id) if access is not None else "unknown",
            json.dumps(control_uuid[:128]),
            action if action in {"on", "off"} else "invalid",
            outcome,
        )
    data = (
        ControlOperationData.model_validate(result)
        if error is None
        else ErrorData(error=error[0], message=error[1])
    )
    return ControlOperationEnvelope(
        ok=error is None,
        data=data,
        warnings=warnings or [],
        observed_at=_now(),
        stale=False,
        trace_id=trace_id,
    )


class _CursorCodec:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def encode(self, scope: str, offset: int) -> str:
        body = json.dumps({"scope": scope, "offset": offset}, separators=(",", ":")).encode()
        signature = hmac.new(self._key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")

    def decode(self, scope: str, value: str | None) -> int:
        if value is None:
            return 0
        if len(value) > 512:
            raise ValueError("cursor is invalid")
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                signature, hmac.new(self._key, body, hashlib.sha256).digest()
            ):
                raise ValueError
            document = json.loads(body)
            offset = document.get("offset")
            if document.get("scope") != scope or not isinstance(offset, int) or offset < 0:
                raise ValueError
            return offset
        except (UnicodeError, ValueError, json.JSONDecodeError):
            raise ValueError("cursor is invalid") from None


def _access() -> StoredAccessToken:
    access = get_access_token()
    if not isinstance(access, StoredAccessToken):
        raise PermissionError("authentication is required")
    return access


def _groups(items: tuple[NamedGroup, ...]) -> list[dict[str, str]]:
    return [{"uuid": item.uuid, "name": item.name} for item in items]


def _flatten(controls: tuple[Control, ...]) -> list[Control]:
    result: list[Control] = []
    for control in controls:
        result.append(control)
        result.extend(_flatten(control.subcontrols))
    return result


def _control_summary(control: Control, snapshot: RuntimeSnapshot) -> dict[str, Any]:
    rooms = {item.uuid: item.name for item in snapshot.structure.rooms}
    categories = {item.uuid: item.name for item in snapshot.structure.categories}
    return {
        "uuid": control.uuid,
        "name": control.name,
        "type": control.control_type,
        "room": (
            {"uuid": control.room_uuid, "name": rooms.get(control.room_uuid, "")}
            if control.room_uuid
            else None
        ),
        "category": (
            {"uuid": control.category_uuid, "name": categories.get(control.category_uuid, "")}
            if control.category_uuid
            else None
        ),
    }


def _page(
    codec: _CursorCodec, scope: str, items: list[Any], cursor: str | None, limit: int
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError("limit must be between 1 and 100")
    offset = codec.decode(scope, cursor)
    selected = items[offset : offset + limit]
    next_offset = offset + len(selected)
    return {
        "items": selected,
        "next_cursor": codec.encode(scope, next_offset) if next_offset < len(items) else None,
    }


async def _snapshot(runtime: LoxoneRuntime | None) -> tuple[StoredAccessToken, RuntimeSnapshot]:
    if runtime is None:
        raise RuntimeUnavailable("the service is not configured")
    access = _access()
    async with runtime.call_slot(access):
        return access, await runtime.snapshot(access)


def register_read_tools(
    server: FastMCP, runtime: LoxoneRuntime | None, *, control_enabled: bool = False
) -> None:
    """Publish exactly the six stable Phase 1 read-only tools."""
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    cursors = _CursorCodec()

    @server.tool(
        name="loxone_get_system_status",
        description=(
            "Get sanitized Miniserver connection and cache status for this Loxone identity."
        ),
        annotations=annotations,
        structured_output=True,
    )
    async def get_system_status() -> SystemStatusEnvelope:
        try:
            _access_token, snapshot = await _snapshot(runtime)
            return _result(
                SystemStatusEnvelope,
                {
                    "reachable": snapshot.connected,
                    "miniserver_serial": snapshot.structure.identity.miniserver_serial,
                    "structure_last_modified": snapshot.structure.last_modified,
                    "cache_freshness": "current" if snapshot.connected else "stale",
                },
                stale=not snapshot.connected,
            )
        except PermissionError:
            return _error(
                SystemStatusEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(SystemStatusEnvelope, "temporarily_unavailable", str(exc))

    @server.tool(
        name="loxone_list_rooms",
        description="List visible Loxone rooms.",
        annotations=annotations,
        structured_output=True,
    )
    async def list_rooms(
        cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> NamedGroupPageEnvelope:
        try:
            _access_token, snapshot = await _snapshot(runtime)
            return _result(
                NamedGroupPageEnvelope,
                _page(cursors, "rooms", _groups(snapshot.structure.rooms), cursor, limit),
            )
        except ValueError as exc:
            return _error(NamedGroupPageEnvelope, "invalid_input", str(exc))
        except PermissionError:
            return _error(
                NamedGroupPageEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(NamedGroupPageEnvelope, "temporarily_unavailable", str(exc))

    @server.tool(
        name="loxone_list_categories",
        description="List visible Loxone categories.",
        annotations=annotations,
        structured_output=True,
    )
    async def list_categories(
        cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> NamedGroupPageEnvelope:
        try:
            _access_token, snapshot = await _snapshot(runtime)
            return _result(
                NamedGroupPageEnvelope,
                _page(cursors, "categories", _groups(snapshot.structure.categories), cursor, limit),
            )
        except ValueError as exc:
            return _error(NamedGroupPageEnvelope, "invalid_input", str(exc))
        except PermissionError:
            return _error(
                NamedGroupPageEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(NamedGroupPageEnvelope, "temporarily_unavailable", str(exc))

    @server.tool(
        name="loxone_find_controls",
        description="Search visible Loxone controls by text, room, category, and type.",
        annotations=annotations,
        structured_output=True,
    )
    async def find_controls(
        query: str | None = None,
        room_uuid: str | None = None,
        category_uuid: str | None = None,
        control_type: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ControlPageEnvelope:
        if query is not None and len(query) > 200:
            return _error(ControlPageEnvelope, "invalid_input", "query is too long")
        try:
            _access_token, snapshot = await _snapshot(runtime)
            controls = _flatten(snapshot.structure.controls)
            normalized = query.casefold().strip() if query else None
            matches = [
                item
                for item in controls
                if (normalized is None or normalized in item.name.casefold())
                and (room_uuid is None or item.room_uuid == room_uuid)
                and (category_uuid is None or item.category_uuid == category_uuid)
                and (control_type is None or item.control_type == control_type)
            ]
            scope = hashlib.sha256(
                json.dumps([normalized, room_uuid, category_uuid, control_type]).encode()
            ).hexdigest()
            values = [_control_summary(item, snapshot) for item in matches]
            return _result(
                ControlPageEnvelope,
                _page(cursors, f"controls:{scope}", values, cursor, limit),
            )
        except ValueError as exc:
            return _error(ControlPageEnvelope, "invalid_input", str(exc))
        except PermissionError:
            return _error(
                ControlPageEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(ControlPageEnvelope, "temporarily_unavailable", str(exc))

    @server.tool(
        name="loxone_describe_control",
        description="Describe one visible Loxone control and its read-only states.",
        annotations=annotations,
        structured_output=True,
    )
    async def describe_control(control_uuid: str) -> ControlDescriptionEnvelope:
        try:
            access_token, snapshot = await _snapshot(runtime)
            control = next(
                (
                    item
                    for item in _flatten(snapshot.structure.controls)
                    if item.uuid == control_uuid
                ),
                None,
            )
            if control is None:
                return _error(ControlDescriptionEnvelope, "not_found", "control is not visible")
            value = _control_summary(control, snapshot)
            value["states"] = [{"name": name, "uuid": uuid} for name, uuid in control.state_uuids]
            value["capabilities"] = {
                "readable": True,
                "allowed_actions": (
                    ["on", "off"]
                    if control_enabled
                    and CONTROL_SCOPE in access_token.scopes
                    and control.control_type == "Switch"
                    and control.action_uuid is not None
                    else []
                ),
            }
            return _result(ControlDescriptionEnvelope, value)
        except PermissionError:
            return _error(
                ControlDescriptionEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(ControlDescriptionEnvelope, "temporarily_unavailable", str(exc))

    @server.tool(
        name="loxone_get_states",
        description="Get current cached values for up to 100 visible state UUIDs.",
        annotations=annotations,
        structured_output=True,
    )
    async def get_states(state_uuids: list[str]) -> StatesEnvelope:
        if (
            not state_uuids
            or len(state_uuids) > MAX_STATE_UUIDS
            or len(set(state_uuids)) != len(state_uuids)
        ):
            return _error(
                StatesEnvelope,
                "invalid_input",
                "state_uuids must contain 1 to 100 unique values",
            )
        try:
            _access_token, snapshot = await _snapshot(runtime)
            allowed = {
                uuid
                for control in _flatten(snapshot.structure.controls)
                for _name, uuid in control.state_uuids
            }
            if any(uuid not in allowed for uuid in state_uuids):
                return _error(StatesEnvelope, "not_found", "one or more states are not visible")
            records = [runtime.state(snapshot, uuid) for uuid in state_uuids] if runtime else []
            stale = any(record.freshness is not Freshness.CURRENT for record in records)
            values = [
                {
                    "uuid": record.uuid,
                    "value": record.value,
                    "freshness": record.freshness.value,
                    "observed_at": (
                        datetime.fromtimestamp(record.observed_at, UTC)
                        .isoformat()
                        .replace("+00:00", "Z")
                        if record.observed_at is not None
                        else None
                    ),
                }
                for record in records
            ]
            return _result(StatesEnvelope, {"states": values}, stale=stale)
        except PermissionError:
            return _error(
                StatesEnvelope,
                "unauthenticated",
                "Authentication with loxone:read is required",
            )
        except RuntimeUnavailable as exc:
            return _error(StatesEnvelope, "temporarily_unavailable", str(exc))


def register_control_tool(server: FastMCP, runtime: LoxoneRuntime | None) -> None:
    """Publish the single explicitly enabled Phase 2 Switch operation."""
    annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="loxone_operate_control",
        description=(
            "Switch one visible and operable Loxone Switch control explicitly on or off. "
            "Requires loxone:control. Never retries an uncertain command."
        ),
        annotations=annotations,
        structured_output=True,
    )
    async def operate_control(
        control_uuid: str, action: Literal["on", "off"]
    ) -> ControlOperationEnvelope:
        access: StoredAccessToken | None = None
        try:
            access = _access()
            if runtime is None:
                raise ControlOperationError(
                    "temporarily_unavailable", "the service is not configured"
                )
            operation = await runtime.operate_switch(access, control_uuid, action)
            warnings = (
                []
                if operation.confirmed
                else ["The command was accepted but the resulting state was not confirmed."]
            )
            return _control_envelope(
                access,
                control_uuid,
                action,
                result={
                    "control_uuid": operation.control_uuid,
                    "action": operation.action,
                    "accepted": operation.accepted,
                    "confirmed": operation.confirmed,
                    "observed_state": operation.observed_state,
                },
                warnings=warnings,
            )
        except PermissionError:
            return _control_envelope(
                access,
                control_uuid,
                action,
                error=("unauthenticated", "Authentication is required"),
            )
        except ControlOperationError as exc:
            return _control_envelope(access, control_uuid, action, error=(exc.code, str(exc)))
