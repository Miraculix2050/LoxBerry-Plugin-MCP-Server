"""Single-use, identity-bound approval for version-bound Message Center actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, PrivateAttr

from mcpserver.auth.provider import MESSAGE_CONFIRM_SCOPE, StoredAccessToken
from mcpserver.loxone.client import LoxoneCommandRejected
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.loxone.system_messages import (
    MessageSource,
    SystemMessage,
    decode_messages,
    identifier,
)

_LOGGER = logging.getLogger("mcpserver.message_confirmation")
TTL_SECONDS = 120
MAX_PREVIEWS = 3000
MAX_PREVIEWS_PER_BINDING = 10


class MessageConfirmationPreview(BaseModel):
    preview_id: str
    expires_in_seconds: Literal[120] = 120
    entry_uuid: str
    message: SystemMessage
    action_id: int
    effect: Literal["acknowledge", "historize"]
    effect_description: str
    user_approval_required: Literal[True] = True
    repairs_underlying_problem: Literal[False] = False


class MessageConfirmationResult(BaseModel):
    _trace_id: str = PrivateAttr(default="")
    entry_uuid: str
    action_id: int
    effect: Literal["acknowledge", "historize"]
    dispatched: bool
    accepted: bool
    effect_observed: bool
    outcome: Literal["observed", "accepted_unverified", "rejected", "uncertain"]
    retry_allowed: Literal[False] = False
    historic: bool | None = None
    confirmed_at: int | None = None
    set_historic_at: int | None = None


@dataclass(frozen=True)
class _Ticket:
    binding: tuple[str, str, str]
    expires: float
    fingerprint: str
    entry_uuid: str
    action_id: int
    effect: Literal["acknowledge", "historize"]


def _binding(access: StoredAccessToken) -> tuple[str, str, str]:
    return access.family_id, access.identity_id, access.miniserver_id


def _target(source: MessageSource, entry_uuid: str) -> SystemMessage:
    record = next((item for item in source.records if item.entry_uuid == entry_uuid), None)
    if (
        record is None
        or record.historic
        or record.confirmed_at is not None
        or record.visu_locked
        or record.confirmation_action_id is None
        or record.confirmation_effect is None
    ):
        raise ControlOperationError("not_confirmable", "No verified current confirmation action")
    return record


def _fingerprint(source: MessageSource, record: SystemMessage) -> str:
    # Opening the native detail UI marks a message read; that does not change approval.
    value = [
        source.firmware,
        source.miniserver_serial,
        source.message_center_uuid,
        record.model_dump(exclude={"read_at"}),
        record._confirmation_revision,
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class MessageConfirmations:
    def __init__(self) -> None:
        self.tickets: dict[str, _Ticket] = {}
        self.rates: dict[tuple[str, str, str], deque[float]] = {}
        self.inflight: set[tuple[str, str]] = set()

    def _prune(self, now: float) -> None:
        self.tickets = {key: value for key, value in self.tickets.items() if value.expires > now}
        self.rates = {
            key: deque(t for t in values if t > now - 60)
            for key, values in self.rates.items()
            if values and values[-1] > now - 60
        }

    async def preview(
        self, runtime: LoxoneRuntime, access: StoredAccessToken, entry_uuid: str
    ) -> MessageConfirmationPreview:
        if identifier(entry_uuid) is None:
            raise ControlOperationError("invalid_input", "Invalid message identifier")
        source = await runtime.get_system_messages(access)
        record = _target(source, entry_uuid)
        assert record.confirmation_action_id is not None and record.confirmation_effect is not None
        now = time.monotonic()
        self._prune(now)
        binding = _binding(access)
        if (access.miniserver_id, entry_uuid) in self.inflight:
            raise ControlOperationError(
                "confirmation_in_progress", "Message confirmation is in progress"
            )
        # One current preview per entry/caller. A fresh preview supersedes its older sibling.
        self.tickets = {
            key: value
            for key, value in self.tickets.items()
            if value.binding != binding or value.entry_uuid != entry_uuid
        }
        if (
            sum(value.binding == binding for value in self.tickets.values())
            >= MAX_PREVIEWS_PER_BINDING
        ):
            raise ControlOperationError(
                "rate_limited", "Too many pending previews for this identity"
            )
        if len(self.tickets) >= MAX_PREVIEWS:
            raise ControlOperationError("rate_limited", "Too many pending previews")
        preview_id = secrets.token_urlsafe(32)
        self.tickets[preview_id] = _Ticket(
            binding,
            now + TTL_SECONDS,
            _fingerprint(source, record),
            entry_uuid,
            record.confirmation_action_id,
            record.confirmation_effect,
        )
        return MessageConfirmationPreview(
            preview_id=preview_id,
            entry_uuid=entry_uuid,
            message=record,
            action_id=record.confirmation_action_id,
            effect=record.confirmation_effect,
            effect_description=(
                "Historize this message using its native Okay action; confirmed_at is not set."
                if record.confirmation_effect == "historize"
                else "Acknowledge this message using its native acknowledgement action."
            ),
        )

    async def confirm(
        self,
        runtime: LoxoneRuntime,
        access: StoredAccessToken,
        preview_id: str,
        user_approved: bool,
    ) -> MessageConfirmationResult:
        # Invalid/foreign previews and denied approval share normal bounded admission too.
        admitted = False
        try:
            async with runtime.call_slot(access):
                admitted = True
                return await self._confirm(runtime, access, preview_id, user_approved)
        except BaseException as exc:
            if not admitted:
                ticket = self.tickets.get(preview_id)
                if ticket is not None and ticket.binding == _binding(access):
                    del self.tickets[preview_id]
                self._audit(
                    access,
                    None,
                    None,
                    "admission_cancelled"
                    if isinstance(exc, asyncio.CancelledError)
                    else "admission_rejected",
                    str(uuid4()),
                )
            raise

    async def _confirm(
        self,
        runtime: LoxoneRuntime,
        access: StoredAccessToken,
        preview_id: str,
        user_approved: bool,
    ) -> MessageConfirmationResult:
        ticket = self.tickets.get(preview_id)
        if ticket is None or ticket.binding != _binding(access):
            self._audit(access, None, None, "invalid_preview", str(uuid4()))
            raise ControlOperationError(
                "invalid_preview", "Preview is unavailable for this identity"
            )
        if user_approved is not True:
            self._audit(
                access, ticket.entry_uuid, ticket.action_id, "approval_required", str(uuid4())
            )
            raise ControlOperationError(
                "approval_required", "Explicit approval of this preview is required"
            )
        # Consume before any await: concurrent calls, failures and uncertain writes cannot replay.
        del self.tickets[preview_id]
        now = time.monotonic()
        self._prune(now)
        result: MessageConfirmationResult | None = None
        dispatched = False
        outcome = "not_dispatched"
        trace_id = str(uuid4())
        target = (access.miniserver_id, ticket.entry_uuid)
        active = False
        try:
            if ticket.expires <= now:
                raise ControlOperationError("expired_preview", "Create and approve a new preview")
            if target in self.inflight:
                raise ControlOperationError(
                    "confirmation_in_progress", "Message confirmation is in progress"
                )
            self.inflight.add(target)
            active = True
            self.tickets = {
                key: value
                for key, value in self.tickets.items()
                if value.binding[2] != access.miniserver_id or value.entry_uuid != ticket.entry_uuid
            }
            await self._authorize(runtime, access)
            rate = self.rates.setdefault(_binding(access), deque())
            if len(rate) >= 3:
                raise ControlOperationError("rate_limited", "Message confirmation budget exceeded")
            rate.append(now)
            async with runtime.message_source_session(access) as (session, source, rights):
                record = _target(source, ticket.entry_uuid)
                if _fingerprint(source, record) != ticket.fingerprint:
                    raise ControlOperationError(
                        "changed_preview", "Message changed; create a new preview"
                    )
                await self._authorize(runtime, access)
                dispatched = True
                result = MessageConfirmationResult(
                    entry_uuid=ticket.entry_uuid,
                    action_id=ticket.action_id,
                    effect=ticket.effect,
                    dispatched=True,
                    accepted=False,
                    effect_observed=False,
                    outcome="uncertain",
                )
                result._trace_id = trace_id
                try:
                    await session.confirm_system_message(
                        source.message_center_uuid, ticket.entry_uuid, ticket.action_id
                    )
                except LoxoneCommandRejected:
                    result.outcome = "rejected"
                except Exception:
                    # The transport may have sent before it failed. Never retry.
                    pass
                else:
                    result.accepted = True
                    result.outcome = "accepted_unverified"
                    try:
                        raw = await session.system_messages(source.message_center_uuid)
                        after = decode_messages(
                            raw,
                            firmware=source.firmware,
                            serial=source.miniserver_serial,
                            center=source.message_center_uuid,
                            rights=rights,
                        )
                        await self._authorize(runtime, access)
                        observed = next(
                            (r for r in after.records if r.entry_uuid == ticket.entry_uuid),
                            None,
                        )
                        if observed is not None:
                            result.historic = observed.historic
                            result.confirmed_at = observed.confirmed_at
                            result.set_historic_at = observed.set_historic_at
                            result.effect_observed = (
                                observed.historic and observed.set_historic_at is not None
                                if ticket.effect == "historize"
                                else observed.confirmed_at is not None
                            )
                            if result.effect_observed:
                                result.outcome = "observed"
                    except Exception:
                        pass
            return result
        except Exception:
            if result is not None:
                # Cleanup errors must not turn a known dispatch into a retryable failure.
                return result
            raise
        finally:
            if active:
                self.inflight.discard(target)
            if result is not None:
                outcome = result.outcome
            elif dispatched:
                outcome = "uncertain"
            self._audit(access, ticket.entry_uuid, ticket.action_id, outcome, trace_id)

    @staticmethod
    def _audit(
        access: StoredAccessToken,
        entry_uuid: str | None,
        action_id: int | None,
        outcome: str,
        trace_id: str,
    ) -> None:
        _LOGGER.info(
            "component=message_confirmation_audit severity=INFO trace_id=%s "
            "identity=%s entry=%s action=%s outcome=%s",
            trace_id,
            hashlib.sha256(json.dumps(_binding(access)).encode()).hexdigest()[:16],
            hashlib.sha256(entry_uuid.encode()).hexdigest()[:16] if entry_uuid else "unknown",
            action_id,
            outcome,
            extra={"mcp_audit": True},
        )

    @staticmethod
    async def _authorize(runtime: LoxoneRuntime, access: StoredAccessToken) -> None:
        validator = getattr(runtime, "validate_message_confirmation", None)
        if (
            MESSAGE_CONFIRM_SCOPE not in access.scopes
            or validator is None
            or not await validator(access)
        ):
            raise ControlOperationError(
                "permission_denied", "Message confirmation is not authorized or enabled"
            )
        await runtime._require_access(access)
