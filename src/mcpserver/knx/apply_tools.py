"""One explicit, separately delegated local apply/reconciliation surface."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcpserver.config import ConfigError
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable
from mcpserver.tools import ErrorData, ToolEnvelope, _access, _error, _project_query, _result

from .catalog_runtime import CatalogRuntime, CatalogUnavailable
from .correction_runtime import CorrectionRuntime
from .model import KnxError


class ApplyData(BaseModel):
    outcome: Literal["applied", "not_observed"]
    target_id: str
    catalog_revision: int | None = None
    selected_changes: int | None = None
    changed_addresses: int | None = None
    destination: Literal["local_metadata"] = "local_metadata"
    storage: Literal["addresses", "prefix_labels"] = "addresses"
    manual_revision: str | None = None
    changed_prefixes: int | None = None
    automatic_retry_allowed: Literal[False] = False
    loxone_written: Literal[False] = False
    import_written: Literal[False] = False
    exports_file: Literal[False] = False


class ApplyEnvelope(ToolEnvelope):
    data: ApplyData | ErrorData


def register_apply_tools(
    server: FastMCP, catalog: CatalogRuntime | None, project_runtime: LoxoneRuntime | None
) -> None:
    runtime = CorrectionRuntime(catalog) if catalog is not None else None

    @server.tool(
        name="loxberry_apply_knx_corrections",
        description=(
            "Apply explicitly user-approved accepted IDs from an owned KNX draft. "
            "Separate default-off Admin write, draft and read grants required. Existing "
            "address name/description overrides or style-bound prefix labels; choose one storage "
            "per call. Prefix labels additionally require explicit Admin prefix activation. "
            "No new addresses, ETS/import or Loxone writes. "
            "Project-bound drafts require use_project_evidence=true. Exact revisions and "
            "request_id required. After uncertainty use action=reconcile with the same "
            "selection/revisions/request_id; never automatically retry. A receipt describes "
            "the original operation, so reread current catalog to verify."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
        ),
        meta={
            "requiredScopes": [
                "loxone:read",
                "loxberry:knx:read",
                "loxberry:knx:drafts",
                "loxberry:knx:write",
            ]
        },
        structured_output=True,
    )
    async def apply(
        action: Literal["apply", "reconcile"],
        target_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
        draft_id: Annotated[str, Field(pattern=r"^[0-9a-f]{48}$")],
        draft_revision: Annotated[int, Field(strict=True, ge=1)],
        catalog_revision: Annotated[int, Field(strict=True, ge=0)],
        manual_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
        request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")],
        approved_change_ids: Annotated[
            list[Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]],
            Field(min_length=1, max_length=50),
        ],
        use_project_evidence: Annotated[bool, Field(strict=True)] = False,
        storage: Literal["addresses", "prefix_labels"] = "addresses",
    ) -> ApplyEnvelope:
        access = None
        started = False
        outcome = "failed"
        try:
            access = _access()
            if runtime is None:
                raise RuntimeUnavailable("KNX local writes are not configured")
            authorized = await runtime.run(access, "authorize_write", {"storage": storage})
            query = None
            if use_project_evidence and action == "apply":
                if (
                    project_runtime is None
                    or project_runtime.endpoint.origin != authorized["target"]
                ):
                    raise KnxError("knx_project_evidence_required")
                query, _ = await _project_query(project_runtime)
            arguments = dict(
                target_id=target_id,
                draft_id=draft_id,
                draft_revision=draft_revision,
                catalog_revision=catalog_revision,
                manual_revision=manual_revision,
                request_id=request_id,
                approved_change_ids=approved_change_ids,
                storage=storage,
            )
            started = action == "apply"
            result = await runtime.run(access, "apply" if started else "receipt", arguments, query)
            if query is not None:
                assert project_runtime is not None and project_runtime.projects is not None
                try:
                    await project_runtime.projects.authorize(access)
                except (ProjectError, PermissionError):
                    raise KnxError("write_outcome_uncertain") from None
            value = _result(ApplyEnvelope, result)
            outcome = "completed"
            return value
        except PermissionError:
            outcome = "permission_denied"
            return _error(
                ApplyEnvelope, outcome, "KNX local writes require independent Admin approval"
            )
        except KnxError as exc:
            outcome = (
                "write_outcome_uncertain"
                if started and exc.code == "knx_storage_failed"
                else exc.code
            )
            message = (
                "Reconcile the exact request; never automatically retry"
                if outcome == "write_outcome_uncertain"
                else "KNX selected decision, source, revision or receipt rejected"
            )
            return _error(ApplyEnvelope, outcome, message)
        except TimeoutError:
            outcome = "write_outcome_uncertain" if started else "temporarily_unavailable"
            return _error(
                ApplyEnvelope, outcome, "Reconcile the exact request; never automatically retry"
            )
        except asyncio.CancelledError:
            outcome = "write_outcome_uncertain" if started else "cancelled"
            raise
        except (
            ConfigError,
            ProjectError,
            RuntimeUnavailable,
            CatalogUnavailable,
            OSError,
            ValueError,
        ):
            outcome = "write_outcome_uncertain" if started else "temporarily_unavailable"
            return _error(ApplyEnvelope, outcome, "Local operation outcome requires reconciliation")
        finally:
            if runtime is not None:
                runtime.audit_apply(access, action, outcome)
