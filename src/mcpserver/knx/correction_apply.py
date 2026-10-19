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
    storage = arguments.get("storage", "addresses")
    if storage not in {"addresses", "prefix_labels"}:
        raise KnxError("knx_correction_invalid")
    fields = [
        arguments.get(key)
        for key in ("draft_id", "draft_revision", "catalog_revision", "manual_revision")
    ]
    return hashlib.sha256(
        json.dumps(
            [
                "local-address-apply-v1" if storage == "addresses" else "local-prefix-apply-v1",
                target,
                *fields,
                sorted(selected),
            ],
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
        save_config: Callable[[PluginConfig], None] | None = None,
    ) -> dict[str, Any]:
        request = arguments.get("request_id")
        if not isinstance(request, str) or not re.fullmatch(r"[0-9a-f]{32}", request):
            raise KnxError("knx_correction_invalid")
        digest = operation_digest(arguments, target)
        now = int(time.time())
        storage = arguments.get("storage", "addresses")
        if storage == "prefix_labels":
            from .prefix_apply import receipt as prefix_receipt

            previous = prefix_receipt(config, self.owner, target, request, digest, now)
        else:
            with self.service.store.connection() as db:
                previous = receipt(db, self.owner, target, request, digest, now)
        if previous is not None:
            return {"outcome": "applied", **previous}
        if reconcile:
            # An absent observation is not permission to retry an uncertain write.
            return {"outcome": "not_observed", "automatic_retry_allowed": False, "storage": storage}
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
        if storage == "prefix_labels":
            from .prefix_apply import apply_prefixes

            if save_config is None:
                raise KnxError("knx_correction_invalid")
            result = apply_prefixes(
                self.service.store,
                config,
                self.owner,
                target,
                request,
                digest,
                arguments["catalog_revision"],
                arguments["manual_revision"],
                selected,
                expires_at=draft["expires_at"],
                save=save_config,
                authorize_effect=authorize_effect,
            )
            return {"outcome": "applied", **result}
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
