"""Explicit local effects; export and project writes are separate destinations."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from typing import Any

from mcpserver.config import PluginConfig
from mcpserver.loxone.project.query import ProjectQuery

from .address_apply import apply_addresses, receipt
from .correction_service import CorrectionService
from .model import KnxError


def operation_digest(arguments: dict[str, Any], target: str) -> str:
    """Bind a receipt to exact IDs/revisions without retaining private values."""
    selected = arguments.get("approved_change_ids")
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= 50
        or any(
            not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{24}", item)
            for item in selected
        )
        or len(set(selected)) != len(selected)
    ):
        raise KnxError("knx_correction_invalid")
    fields = [
        arguments.get(key)
        for key in ("draft_id", "draft_revision", "catalog_revision", "manual_revision")
    ]
    return hashlib.sha256(
        json.dumps(
            ["local-address-apply-v1", target, *fields, sorted(selected)],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class CorrectionApply:
    def __init__(self, service: CorrectionService, owner: str) -> None:
        self.service, self.owner = service, owner

    def execute(
        self,
        config: PluginConfig,
        target: str,
        arguments: dict[str, Any],
        *,
        reconcile: bool = False,
        query: ProjectQuery | None = None,
        authorize_effect: Callable[[], object],
    ) -> dict[str, Any]:
        request = arguments.get("request_id")
        if not isinstance(request, str) or not re.fullmatch(r"[0-9a-f]{32}", request):
            raise KnxError("knx_correction_invalid")
        digest = operation_digest(arguments, target)
        now = int(time.time())
        with self.service.store.connection() as db:
            previous = receipt(db, self.owner, target, request, digest, now)
        if previous is not None:
            return {"outcome": "applied", **previous}
        if reconcile:
            # An absent observation is not permission to retry an uncertain write.
            return {"outcome": "not_observed", "automatic_retry_allowed": False}
        draft, selected = self.service.approved_selection(
            arguments.get("draft_id"),
            config,
            target,
            arguments.get("draft_revision"),
            arguments.get("catalog_revision"),
            arguments.get("manual_revision"),
            arguments.get("approved_change_ids"),
            query=query,
        )
        result = apply_addresses(
            self.service.store,
            self.owner,
            target,
            request,
            digest,
            arguments["catalog_revision"],
            selected,
            now=now,
            expires_at=draft["expires_at"],
            authorize_effect=authorize_effect,
        )
        return {"outcome": "applied", **result}
