"""Narrow, freshly delegated draft operations outside the event loop."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from typing import Any

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.config import PluginConfig
from mcpserver.loxone.project.query import ProjectQuery

from .catalog_runtime import CatalogRuntime
from .correction_drafts import CorrectionDraftStore
from .correction_service import CorrectionService
from .delegation import authorize_drafts, authorize_write
from .model import KnxError

LOGGER = logging.getLogger(__name__)


class CorrectionRuntime:
    def __init__(self, catalog: CatalogRuntime) -> None:
        self.catalog = catalog

    def authorized(self, access: StoredAccessToken) -> tuple[str, str]:
        return authorize_drafts(self.catalog.config_store.load(), self.catalog.auth_store, access)

    async def authorize(self, access: StoredAccessToken) -> tuple[str, str]:
        result = await self.run(access, "authorize", {})
        return result["target"], result["owner"]

    def execute(
        self,
        access: StoredAccessToken,
        action: str,
        arguments: dict[str, Any],
        query: ProjectQuery | None = None,
    ) -> dict[str, Any]:
        if action in {"authorize", "authorize_write"}:
            target, owner = (
                authorize_write(self.catalog.config_store.load(), self.catalog.auth_store, access)
                if action == "authorize_write"
                else self.authorized(access)
            )
            return {"target": target, "owner": owner}

        def operation(
            config: PluginConfig, _save: Callable[[PluginConfig], None]
        ) -> dict[str, Any]:
            def authorize() -> tuple[str, str]:
                try:
                    authorizer = (
                        authorize_write if action in {"apply", "receipt"} else authorize_drafts
                    )
                    return authorizer(config, self.catalog.auth_store, access)
                except PermissionError:
                    # Config transactions sanitize OSError, including PermissionError,
                    # as lock failures. Keep a revoked grant a domain denial.
                    raise KnxError("permission_denied") from None

            target, owner = authorize()
            self.catalog._consume_rate(access.family_id)
            target_id = hashlib.sha256(target.encode()).hexdigest()
            if arguments.get("target_id", target_id) != target_id:
                raise KnxError("knx_target_conflict")
            drafts = CorrectionDraftStore(
                self.catalog.store.path.with_name("drafts.sqlite3"), owner
            )
            service = CorrectionService(self.catalog.store, drafts)
            identifier = arguments.get("draft_id")
            if action in {"apply", "receipt"}:
                from .correction_apply import CorrectionApply

                result = CorrectionApply(service, owner).execute(
                    config,
                    target,
                    arguments,
                    reconcile=action == "receipt",
                    query=query,
                    authorize_effect=authorize,
                )
                try:
                    authorize()
                except KnxError:
                    if action == "apply":
                        raise KnxError("write_outcome_uncertain") from None
                    raise
                return {"target_id": target_id, **result}
            if action == "read":
                if arguments.get("request_id") is not None:
                    identifier = drafts.resolve_request(arguments["request_id"], target)
                if identifier is None:
                    summaries = drafts.list_corrections(target)
                    authorize()
                    return {"target_id": target_id, "drafts": summaries}
                draft = service.inspect(identifier, config, target, query=query)
                expected = arguments.get("expected_draft_revision")
                if expected is not None and expected != draft["draft_revision"]:
                    raise KnxError("knx_revision_conflict")
                draft.pop("target")
                authorize()
                return {"target_id": target_id, "draft": draft}
            if action == "prepare":
                if arguments.get("mode", "prepare") == "review":
                    authorize()
                    operation_revision = service.review(
                        identifier,
                        config,
                        target,
                        arguments["draft_revision"],
                        arguments["catalog_revision"],
                        arguments["manual_revision"],
                        arguments["decisions"],
                        request_id=arguments["request_id"],
                        query=query,
                    )
                    result = drafts.inspect_correction(identifier, target)
                    try:
                        authorize()
                    except KnxError:
                        raise KnxError("write_outcome_uncertain") from None
                    return {
                        "target_id": target_id,
                        "draft_id": result["draft_id"],
                        "draft_revision": result["draft_revision"],
                        "operation_revision": operation_revision,
                        "expires_at": result["expires_at"],
                        "applies_changes": False,
                        "exports_file": False,
                    }
                old = (
                    service.inspect(identifier, config, target, query=query) if identifier else None
                )
                if old is not None and (
                    old["catalog_stale"]
                    or old["manual_stale"]
                    or old["project_status"] not in {"not_required", "current"}
                ):
                    raise KnxError("knx_project_evidence_changed")
                plan = service.plan(
                    config,
                    target,
                    arguments["catalog_revision"],
                    arguments["manual_revision"],
                    arguments["changes"],
                    query=query,
                )
                if old is not None and (
                    plan["catalog_revision"] != old["catalog_revision"]
                    or plan["manual_revision"] != old["manual_revision"]
                    or (
                        plan["project_binding"] is not None
                        and plan["project_binding"] != old["project_binding"]
                    )
                ):
                    raise KnxError("knx_revision_conflict")
                # Admin configuration is locked throughout; OAuth revocation is
                # checked again immediately before the persistent draft operation.
                authorize()
                if old is None:
                    result = drafts.create_correction(
                        target,
                        plan["catalog_revision"],
                        plan["manual_revision"],
                        plan["changes"],
                        project_binding=plan["project_binding"],
                        request_id=arguments["request_id"],
                    )
                    operation_revision = 1
                else:
                    operation_revision = drafts.update_correction(
                        identifier,
                        target,
                        arguments["draft_revision"],
                        plan["changes"],
                        request_id=arguments["request_id"],
                    )
                    result = drafts.inspect_correction(identifier, target)
                return {
                    "target_id": target_id,
                    "draft_id": result["draft_id"],
                    "draft_revision": result["draft_revision"],
                    "operation_revision": operation_revision,
                    "expires_at": result["expires_at"],
                    "applies_changes": False,
                    "exports_file": False,
                }
            raise KnxError("knx_correction_invalid")

        return self.catalog.config_store.transaction(operation)

    async def run(
        self,
        access: StoredAccessToken,
        action: str,
        arguments: dict[str, Any],
        query: ProjectQuery | None = None,
    ) -> dict[str, Any]:
        await asyncio.wait_for(self.catalog.admission.acquire(), timeout=10)
        worker: asyncio.Task[dict[str, Any]] | None = None
        try:
            worker = asyncio.create_task(
                asyncio.to_thread(self.execute, access, action, arguments, query)
            )
            return await asyncio.wait_for(asyncio.shield(worker), timeout=10)
        finally:
            if worker is None or worker.done():
                self.catalog.admission.release()
            else:

                def finished(task: asyncio.Task[dict[str, Any]]) -> None:
                    if not task.cancelled():
                        task.exception()
                    self.catalog.admission.release()

                worker.add_done_callback(finished)

    @staticmethod
    def audit_apply(access: StoredAccessToken | None, action: str, outcome: str) -> None:
        identity = (
            hashlib.sha256(access.family_id.encode()).hexdigest()[:16] if access else "unknown"
        )
        LOGGER.info(
            "component=knx_local_apply_audit family=%s action=%s outcome=%s",
            identity,
            action,
            outcome,
            extra={"mcp_audit": True},
        )

    @staticmethod
    def audit(access: StoredAccessToken | None, outcome: str) -> None:
        identity = (
            hashlib.sha256(access.family_id.encode()).hexdigest()[:16] if access else "unknown"
        )
        LOGGER.info(
            "component=knx_draft_audit family=%s outcome=%s",
            identity,
            outcome,
            extra={"mcp_audit": True},
        )
