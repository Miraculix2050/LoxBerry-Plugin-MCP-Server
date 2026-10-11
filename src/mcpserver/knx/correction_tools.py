"""Typed, bounded MCP preparation and inspection; no metadata apply or export."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mcpserver.config import ConfigError
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable
from mcpserver.tools import ErrorData, ToolEnvelope, _access, _error, _project_query, _result

from .catalog_runtime import CatalogRuntime, CatalogUnavailable
from .correction_projection import project_draft
from .correction_runtime import CorrectionRuntime
from .model import KnxError


class ChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: Literal["local_metadata", "ets_export"]
    kind: Literal["address", "prefix"]
    address_format: Literal["two_level", "three_level"]
    address: Annotated[str | None, Field(max_length=32)] = None
    prefix: Annotated[str | None, Field(max_length=32)] = None
    field: Literal["name", "description", "label"]
    operation: Literal["set", "remove_override"]
    value: Annotated[str | None, Field(max_length=4096)] = None
    project_object_id: Annotated[str | None, Field(max_length=128)] = None
    evidence_note: Annotated[str | None, Field(max_length=512)] = None


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    change_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]
    decision: Literal["proposed", "accepted", "rejected"]


class ValueData(BaseModel):
    state: Literal["missing", "value"]
    value: str | None
    truncated: bool


class ChangeData(BaseModel):
    change_id: str
    destination: Literal["local_metadata", "ets_export"]
    kind: Literal["address", "prefix"]
    address_format: Literal["two_level", "three_level"]
    identity: str
    field: Literal["name", "description", "label"]
    operation: Literal["set", "remove_override"]
    proposed: ValueData
    imported: ValueData
    manual: ValueData
    project_object_id: str | None
    evidence_note: ValueData
    decision: Literal["proposed", "accepted", "rejected"]


class DraftSummary(BaseModel):
    draft_id: str
    catalog_revision: int
    manual_revision: str
    draft_revision: int
    expires_at: int
    created_at: int
    change_count: int
    project_binding_digest: str | None


class DraftReadData(BaseModel):
    target_id: str
    drafts: Annotated[list[DraftSummary], Field(max_length=8)]
    draft: DraftSummary | None
    catalog_stale: bool | None
    manual_stale: bool | None
    project_status: Literal["not_required", "not_checked", "current", "changed"] | None
    changes: Annotated[list[ChangeData], Field(max_length=20)]
    next_offset: int | None
    applies_changes: Literal[False] = False
    exports_file: Literal[False] = False


class DraftReadEnvelope(ToolEnvelope):
    data: DraftReadData | ErrorData


class DraftPreparationData(BaseModel):
    target_id: str
    draft_id: str
    draft_revision: int
    operation_revision: int
    expires_at: int
    applies_changes: Literal[False]
    exports_file: Literal[False]


class DraftPreparationEnvelope(ToolEnvelope):
    data: DraftPreparationData | ErrorData


def register_correction_tools(
    server: FastMCP, catalog: CatalogRuntime | None, project_runtime: LoxoneRuntime | None
) -> None:
    runtime = CorrectionRuntime(catalog) if catalog is not None else None
    scopes = ["loxone:read", "loxberry:knx:read", "loxberry:knx:drafts"]

    async def execute(action: str, arguments: dict[str, Any], use_project: bool) -> ToolEnvelope:
        envelope = DraftReadEnvelope if action == "read" else DraftPreparationEnvelope
        access = None
        outcome = "failed"
        preparation_started = False
        try:
            access = _access()
            if runtime is None:
                raise RuntimeUnavailable("KNX drafts are not configured")
            target, _ = await runtime.authorize(access)
            query = None
            if use_project:
                if project_runtime is None or project_runtime.endpoint.origin != target:
                    raise KnxError("knx_project_evidence_required")
                query, _ = await _project_query(project_runtime)
            preparation_started = action == "prepare"
            result = await runtime.run(access, action, arguments, query)
            if use_project:
                assert project_runtime is not None and project_runtime.projects is not None
                try:
                    await project_runtime.projects.authorize(access)
                except (ProjectError, PermissionError):
                    if action == "prepare":
                        outcome = "write_outcome_uncertain"
                        return _error(
                            envelope, outcome, "Draft may be persisted; reconcile without retrying"
                        )
                    raise KnxError("project_access_denied") from None
            if action == "read":
                result = project_draft(
                    result, arguments["offset"], arguments["limit"], arguments["detail"]
                )
            value = _result(envelope, result)
            if len(value.model_dump_json().encode()) > 65536:
                raise CatalogUnavailable("Draft response exceeds limit")
            outcome = "completed"
            return value
        except PermissionError:
            outcome = "permission_denied"
            return _error(envelope, outcome, "KNX drafts require independent Admin approval")
        except (KnxError, ValidationError) as exc:
            outcome = exc.code if isinstance(exc, KnxError) else "invalid_input"
            return _error(envelope, outcome, "KNX draft selection, source or revision rejected")
        except TimeoutError:
            outcome = (
                "write_outcome_uncertain" if preparation_started else "temporarily_unavailable"
            )
            return _error(
                envelope, outcome, "Read persisted drafts to reconcile; never automatically retry"
            )
        except asyncio.CancelledError:
            outcome = "write_outcome_uncertain" if preparation_started else "cancelled"
            raise
        except (
            ConfigError,
            RuntimeUnavailable,
            CatalogUnavailable,
            ProjectError,
            OSError,
            ValueError,
        ):
            outcome = "temporarily_unavailable"
            return _error(envelope, outcome, "KNX draft service unavailable")
        finally:
            if action == "prepare" and runtime is not None:
                runtime.audit(access, outcome)

    @server.tool(
        name="loxberry_get_knx_correction_drafts",
        description=(
            "Inspect own 24-hour KNX proposals, including stale drafts. Independent Admin "
            "draft/read approval required. No apply/export; project evidence is unchecked "
            "unless explicitly requested. Use request_id to reconcile uncertain creation; "
            "absence does not prove failure while a worker is still running. Continue with "
            "the returned draft revision."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        meta={"requiredScopes": scopes},
        structured_output=True,
    )
    async def get_drafts(
        draft_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{48}$")] = None,
        request_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{32}$")] = None,
        expected_draft_revision: Annotated[int | None, Field(strict=True, ge=1)] = None,
        offset: Annotated[int, Field(strict=True, ge=0, le=50)] = 0,
        limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10,
        detail: bool = False,
        verify_project: bool = False,
    ) -> DraftReadEnvelope:
        if (
            (draft_id is not None and request_id is not None)
            or (
                draft_id is None
                and request_id is None
                and (offset != 0 or expected_draft_revision is not None or verify_project)
            )
            or (offset > 0 and expected_draft_revision is None)
            or (detail and ((draft_id is None and request_id is None) or limit != 1))
        ):
            return _error(
                DraftReadEnvelope,
                "invalid_input",
                "Select one draft; continuation requires its revision",
            )
        return cast(
            DraftReadEnvelope,
            await execute(
                "read",
                dict(
                    draft_id=draft_id,
                    request_id=request_id,
                    expected_draft_revision=expected_draft_revision,
                    offset=offset,
                    limit=limit,
                    detail=detail,
                ),
                verify_project,
            ),
        )

    @server.tool(
        name="loxberry_prepare_knx_corrections",
        description=(
            "Prepare/update own bounded KNX proposals after user discussion. Does not apply "
            "metadata, export XML or write Loxone. Requires separate default-off Admin draft "
            "approval. Stable request_id reconciles uncertainty; never automatically retry."
            " Use mode=review with explicit per-change user decisions instead of changes. "
            "Acceptance records a draft decision only; it grants no metadata write or download."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        meta={"requiredScopes": scopes},
        structured_output=True,
    )
    async def prepare(
        target_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
        catalog_revision: Annotated[int, Field(strict=True, ge=0)],
        manual_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
        request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")],
        changes: Annotated[
            Any,
            Field(
                json_schema_extra={
                    "type": ["array", "null"],
                    "minItems": 1,
                    "maxItems": 50,
                    "items": ChangeInput.model_json_schema(),
                }
            ),
        ] = None,
        draft_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{48}$")] = None,
        draft_revision: Annotated[int | None, Field(strict=True, ge=1)] = None,
        use_project_evidence: bool = False,
        mode: Literal["prepare", "review"] = "prepare",
        decisions: Annotated[
            Any,
            Field(
                json_schema_extra={
                    "type": ["array", "null"],
                    "minItems": 1,
                    "maxItems": 50,
                    "items": DecisionInput.model_json_schema(),
                }
            ),
        ] = None,
    ) -> DraftPreparationEnvelope:
        # Validate private change values here, returning only fixed diagnostics;
        # SDK validation errors must not echo proposed descriptions or names.
        try:
            if (draft_id is None) != (draft_revision is None):
                raise KnxError("knx_correction_invalid")
            parsed: list[dict[str, Any]] = []
            parsed_decisions: list[dict[str, Any]] = []
            if mode == "prepare":
                if (
                    decisions is not None
                    or not isinstance(changes, list)
                    or not 1 <= len(changes) <= 50
                ):
                    raise KnxError("knx_correction_invalid")
                parsed = [
                    ChangeInput.model_validate(row).model_dump(exclude_unset=True)
                    for row in changes
                ]
            else:
                if (
                    changes is not None
                    or draft_id is None
                    or not isinstance(decisions, list)
                    or not 1 <= len(decisions) <= 50
                ):
                    raise KnxError("knx_correction_invalid")
                parsed_decisions = [
                    DecisionInput.model_validate(row).model_dump() for row in decisions
                ]
        except (KnxError, ValidationError):
            if runtime is not None:
                runtime.audit(None, "invalid_input")
            return _error(DraftPreparationEnvelope, "invalid_input", "KNX proposal fields rejected")
        return cast(
            DraftPreparationEnvelope,
            await execute(
                "prepare",
                dict(
                    target_id=target_id,
                    catalog_revision=catalog_revision,
                    manual_revision=manual_revision,
                    request_id=request_id,
                    changes=parsed,
                    draft_id=draft_id,
                    draft_revision=draft_revision,
                    mode=mode,
                    decisions=parsed_decisions,
                ),
                use_project_evidence or any("project_object_id" in row for row in parsed),
            ),
        )
