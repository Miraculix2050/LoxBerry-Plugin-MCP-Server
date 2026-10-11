"""Narrow proposal fields; source validation and approval belong to the service."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mcpserver.loxone.project.taxonomy import parse_taxonomy

from .correction_drafts import MAX_CORRECTION_CHANGES
from .model import KnxError, address, text

_COMMON = frozenset({"destination", "kind", "address_format", "field", "operation"})
_OPTIONAL = frozenset({"value", "project_object_id", "evidence_note"})


def parse_correction_changes(value: object) -> list[dict[str, Any]]:
    """Validate proposed values without accepting source claims or applying writes."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CORRECTION_CHANGES:
        raise KnxError("knx_draft_limit")
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise KnxError("knx_correction_invalid")
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in {"address", "prefix"}:
            raise KnxError("knx_correction_invalid")
        key = "address" if kind == "address" else "prefix"
        required = _COMMON | {key}
        if not required <= item.keys() or not item.keys() <= required | _OPTIONAL:
            raise KnxError("knx_correction_invalid")
        destination = item["destination"]
        if not isinstance(destination, str) or destination not in {"local_metadata", "ets_export"}:
            raise KnxError("knx_correction_invalid")
        operation = item["operation"]
        if (
            not isinstance(operation, str)
            or operation not in {"set", "remove_override"}
            or (destination == "ets_export" and operation != "set")
        ):
            raise KnxError("knx_correction_invalid")
        if (operation == "set") != ("value" in item):
            raise KnxError("knx_correction_invalid")
        field = item["field"]
        if not isinstance(field, str):
            raise KnxError("knx_correction_invalid")
        entry: dict[str, Any] = {name: item[name] for name in required}
        identity: tuple[Any, ...]
        if kind == "prefix":
            if destination != "local_metadata" or field != "label" or "project_object_id" in item:
                raise KnxError("knx_correction_invalid")
            try:
                parse_taxonomy(
                    [
                        {
                            "address_format": item["address_format"],
                            "prefix": item["prefix"],
                            "label": item.get("value", "validation"),
                        }
                    ]
                )
            except ValueError:
                raise KnxError("knx_correction_invalid") from None
            identity = (destination, kind, item["address_format"], item["prefix"], field)
            if operation == "set":
                entry["value"] = text(item["value"], 80, empty=False)
        else:
            if field not in {"name", "description"}:
                raise KnxError("knx_correction_invalid")
            number, original = address(item["address"], item["address_format"])
            entry.update(address=original, address_id=number)
            identity = (destination, kind, number, field)
            if operation == "set":
                entry["value"] = text(
                    item["value"],
                    255 if field == "name" else 4096,
                    empty=field == "description" and destination == "local_metadata",
                )
        if identity in seen:
            raise KnxError("knx_correction_duplicate")
        seen.add(identity)
        if "project_object_id" in item:
            entry["project_object_id"] = text(item["project_object_id"], 128, empty=False)
        if "evidence_note" in item:
            entry["evidence_note"] = text(item["evidence_note"], 512)
        entry["change_id"] = hashlib.sha256(
            json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        # Updating a proposal never carries an earlier approval forward.
        entry["decision"] = "proposed"
        result.append(entry)
    return result
