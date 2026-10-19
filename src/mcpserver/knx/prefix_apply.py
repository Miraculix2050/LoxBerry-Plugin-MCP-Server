"""Selected prefix effects and their receipts in one atomic configuration save."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from mcpserver.config import PluginConfig
from mcpserver.loxone.project.taxonomy import parse_taxonomy

from .catalog import labels_revision, manual_labels, prefix_projection
from .model import KnxError
from .prefix_receipts import LIMIT, TTL, PrefixReceipt, receipt_key
from .store import KnxStore


def receipt(
    config: PluginConfig, owner: str, target: str, request: str, digest: str, now: int
) -> dict[str, Any] | None:
    key = receipt_key(owner, target, request)
    previous = next((row for row in config.knx_prefix_apply_receipts if row.key == key), None)
    if previous is None:
        return None
    if previous.digest != digest:
        raise KnxError("knx_correction_request_conflict")
    if previous.expires_at <= now:
        raise KnxError("knx_correction_receipt_expired")
    return previous.result()


def apply_prefixes(
    store: KnxStore,
    config: PluginConfig,
    owner: str,
    target: str,
    request: str,
    digest: str,
    expected: int,
    expected_manual: str,
    changes: list[dict[str, Any]],
    *,
    expires_at: float,
    save: Callable[[PluginConfig], None],
    authorize_effect: Callable[[], object],
) -> dict[str, Any]:
    # Caller holds the configuration lock. Hold the catalog write lock through
    # the config save so imports cannot change selected labels during validation.
    # SQLite has no effects here; this is not a cross-store atomic commit.
    if (
        not isinstance(owner, str)
        or not re.fullmatch(r"[0-9a-f]{64}", owner)
        or not isinstance(request, str)
        or not re.fullmatch(r"[0-9a-f]{32}", request)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or type(expires_at) not in {int, float}
        or not math.isfinite(expires_at)
        or not isinstance(changes, list)
        or not 1 <= len(changes) <= 50
    ):
        raise KnxError("knx_correction_invalid")
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for change in changes:
        if not isinstance(change, dict):
            raise KnxError("knx_correction_invalid")
        if (
            change.get("kind") != "prefix"
            or change.get("destination") != "local_metadata"
            or change.get("field") != "label"
        ):
            raise KnxError("knx_correction_storage_mixed")
        if (
            change.get("decision") != "accepted"
            or change.get("operation") not in {"set", "remove_override"}
            or (change["operation"] == "set") != ("value" in change)
            or not isinstance(change.get("address_format"), str)
            or not isinstance(change.get("prefix"), str)
        ):
            raise KnxError("knx_correction_invalid")
        identity = (change["address_format"], change["prefix"])
        if identity in selected:
            raise KnxError("knx_correction_invalid")
        try:
            parse_taxonomy(
                [
                    {
                        "address_format": identity[0],
                        "prefix": identity[1],
                        "label": change.get("value", "validation"),
                    }
                ]
            )
        except ValueError:
            raise KnxError("knx_correction_invalid") from None
        selected[identity] = change
    if not 1 <= len(selected) <= 50:
        raise KnxError("knx_correction_invalid")
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        store.check(db, target, expected)
        if labels_revision(config, target) != expected_manual:
            raise KnxError("knx_revision_conflict")
        try:
            imported = [
                {"address_format": fmt, "prefix": prefix, "label": json.loads(fields)["name"]}
                for fmt, prefix, fields in db.execute(
                    "SELECT format,prefix,fields FROM import_groups WHERE target=? AND selected=1 "
                    "ORDER BY format,prefix",
                    (target,),
                )
            ]
        except (ValueError, TypeError, KeyError):
            raise KnxError("knx_storage_failed") from None
        old = {
            (row["address_format"], row["prefix"]): row["label"]
            for row in manual_labels(config, target)
        }
        labels = dict(old)
        for identity, change in selected.items():
            if change["operation"] == "set":
                labels[identity] = change["value"]
            else:
                labels.pop(identity, None)
        rows = [
            {"address_format": fmt, "prefix": prefix, "label": value}
            for (fmt, prefix), value in labels.items()
        ]
        try:
            entries = parse_taxonomy(rows)
        except ValueError:
            raise KnxError("knx_label_limit") from None
        prefix_projection(imported, rows)
        retained = tuple(
            row for row in config.knx_prefix_apply_receipts if row.expires_at > int(time.time())
        )
        if len(retained) >= LIMIT:
            raise KnxError("knx_correction_receipt_limit")
        banks = dict(config.knx_taxonomy_targets)
        if config.knx_address_taxonomy_endpoint:
            banks[config.knx_address_taxonomy_endpoint] = config.knx_address_taxonomy
        banks[target] = entries
        updated = replace(
            config,
            knx_address_taxonomy_endpoint=target,
            knx_address_taxonomy=entries,
            knx_taxonomy_targets=tuple(sorted(banks.items())),
        )
        current = time.time()
        if current >= expires_at:
            raise KnxError("knx_draft_unavailable")
        authorize_effect()
        current = time.time()
        if current >= expires_at:
            raise KnxError("knx_draft_unavailable")
        now = int(current)
        record = PrefixReceipt(
            receipt_key(owner, target, request),
            digest,
            labels_revision(updated, target),
            expected,
            len(changes),
            sum(old.get(key) != labels.get(key) for key in selected),
            now + TTL,
        )
        updated = replace(updated, knx_prefix_apply_receipts=(*retained, record))
        # Revalidate the serialized bound and active target bank before saving.
        updated = PluginConfig.from_document(updated.to_document())
        save(updated)
        return record.result()
