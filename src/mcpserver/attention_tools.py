"""Additive overview retaining each source's independent evidence contract."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcpserver import tools
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable
from mcpserver.message_tools import (
    NotificationsData,
    NotificationsEnvelope,
    SystemMessagesData,
    SystemMessagesEnvelope,
)
from mcpserver.tools import ActiveAlertsData, ActiveAlertsEnvelope, ErrorData, ToolEnvelope

type SourceStatus = Literal["available", "partial", "unavailable"]


class OverviewCoverage(BaseModel):
    active_alerts: SourceStatus
    system_messages: SourceStatus
    notifications: SourceStatus


class AttentionOverviewData(BaseModel):
    scope: Literal["authorized_visible_sources"] = "authorized_visible_sources"
    simultaneous: Literal[False] = False
    coverage_complete: Literal[False] = False
    system_message_mode: Literal["current", "all"]
    coverage: OverviewCoverage
    active_alerts: ActiveAlertsEnvelope
    system_messages: SystemMessagesEnvelope
    notifications: NotificationsEnvelope


class AttentionOverviewEnvelope(ToolEnvelope):
    data: AttentionOverviewData | ErrorData


def _bounded[E: ToolEnvelope](envelope: E) -> E:
    # Three independently bounded source envelopes leave room for wrapper metadata.
    if len(envelope.model_dump_json().encode("utf-8")) > 20_480:
        return tools._error(
            type(envelope), "response_too_large", "Use the dedicated source tool for details"
        )
    return envelope


def register_attention_tools(server: FastMCP, runtime: LoxoneRuntime | None) -> None:
    @server.tool(
        name="loxone_get_attention_overview",
        description=(
            "Read one bounded source-separated overview of current control alerts, System "
            "Messages and the latest observed notification. Existing source contracts, "
            "errors, coverage and times remain independent; observations are sequential. "
            "No global absence, causal, delivery or severity inference. Follow dedicated "
            "source tools and cursors for detail; derive evidence-linked repair tasks. "
            "Read-only; no acknowledgement, read markers, sending, writes or polling."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        structured_output=True,
    )
    async def get_attention_overview(
        limit: Annotated[
            int, Field(strict=True, ge=1, le=10, description="Maximum records per source, 1 to 10.")
        ] = 5,
        include_history: Annotated[
            bool,
            Field(strict=True, description="System Messages history requires History approval."),
        ] = False,
    ) -> AttentionOverviewEnvelope:
        if type(limit) is not int or not 1 <= limit <= 10 or type(include_history) is not bool:
            return tools._error(
                AttentionOverviewEnvelope, "invalid_input", "Invalid overview selection"
            )
        try:
            access = tools._access()
            if runtime is None:
                raise RuntimeUnavailable("the service is not configured")
            # Fixed existing readers retain their own authorization and rate admission.
            alerts_tool = server._tool_manager.get_tool("loxone_get_active_alerts")
            messages_tool = server._tool_manager.get_tool("loxone_get_system_messages")
            notifications_tool = server._tool_manager.get_tool("loxone_get_notifications")
            assert (
                alerts_tool is not None
                and messages_tool is not None
                and notifications_tool is not None
            )
            alerts = _bounded(
                ActiveAlertsEnvelope.model_validate(await alerts_tool.fn(limit=limit))
            )
            mode: Literal["current", "all"] = "all" if include_history else "current"
            messages = _bounded(
                SystemMessagesEnvelope.model_validate(
                    await messages_tool.fn(mode=mode, limit=limit)
                )
            )
            notifications = _bounded(
                NotificationsEnvelope.model_validate(await notifications_tool.fn())
            )
            await runtime._require_access(access)
            coverage = OverviewCoverage(
                active_alerts=(
                    "available"
                    if alerts.ok
                    and not alerts.stale
                    and isinstance(alerts.data, ActiveAlertsData)
                    and alerts.data.complete
                    else "partial"
                    if alerts.ok
                    else "unavailable"
                ),
                system_messages=(
                    "available"
                    if messages.ok
                    and not messages.stale
                    and isinstance(messages.data, SystemMessagesData)
                    and not messages.data.truncated
                    else "partial"
                    if messages.ok
                    else "unavailable"
                ),
                notifications=(
                    "available"
                    if notifications.ok
                    and not notifications.stale
                    and isinstance(notifications.data, NotificationsData)
                    and notifications.data.availability == "latest_event"
                    else "unavailable"
                ),
            )
            return tools._result(
                AttentionOverviewEnvelope,
                AttentionOverviewData(
                    system_message_mode=mode,
                    coverage=coverage,
                    active_alerts=alerts,
                    system_messages=messages,
                    notifications=notifications,
                ),
                stale=any(status != "available" for status in coverage.model_dump().values()),
                warnings=[
                    "Sources are sequential observations, not simultaneous measurements.",
                    "No exhaustive notification history or global alarm-absence claim.",
                    "Use dedicated source tools for bounded-out details and every non-null cursor.",
                ],
            )
        except PermissionError:
            return tools._error(
                AttentionOverviewEnvelope, "permission_denied", "Authorized read access is required"
            )
        except RuntimeUnavailable as exc:
            return tools._availability_error(AttentionOverviewEnvelope, exc)
