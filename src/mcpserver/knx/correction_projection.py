"""Bounded source projection shared by MCP and authenticated Admin adapters."""

from typing import Any

from .model import KnxError


def _value(value: dict[str, Any], key: str, maximum: int) -> dict[str, Any]:
    raw = value.get(key)
    if key not in value:
        return {"state": "missing", "value": None, "truncated": False}
    if not isinstance(raw, str):
        raise KnxError("knx_draft_storage_failed")
    return {"state": "value", "value": raw[:maximum], "truncated": len(raw) > maximum}


def project_draft(raw: dict[str, Any], offset: int, limit: int, detail: bool) -> dict[str, Any]:
    if "drafts" in raw:
        return {
            "target_id": raw["target_id"],
            "drafts": raw["drafts"],
            "draft": None,
            "catalog_stale": None,
            "manual_stale": None,
            "project_status": None,
            "changes": [],
            "next_offset": None,
            "applies_changes": False,
            "exports_file": False,
        }
    draft = raw["draft"]
    changes = draft["changes"]
    maximum = 4096 if detail else 128
    rows = []
    for row in changes[offset : offset + limit]:
        rows.append(
            {
                "change_id": row["change_id"],
                "destination": row["destination"],
                "kind": row["kind"],
                "address_format": row["address_format"],
                "identity": row.get("address", row.get("prefix")),
                "field": row["field"],
                "operation": row["operation"],
                "proposed": _value(row, "value", maximum),
                "imported": _value(row["sources"]["imported"], row["field"], maximum),
                "manual": _value(row["sources"]["manual"], row["field"], maximum),
                "project_object_id": row.get("project_object_id"),
                "evidence_note": _value(row, "evidence_note", maximum),
                "decision": row["decision"],
            }
        )
    import hashlib

    summary = {
        key: draft[key]
        for key in (
            "draft_id",
            "catalog_revision",
            "manual_revision",
            "draft_revision",
            "expires_at",
            "created_at",
        )
    }
    summary.update(
        change_count=len(changes),
        project_binding_digest=hashlib.sha256(draft["project_binding"].encode()).hexdigest()
        if draft["project_binding"]
        else None,
    )
    return {
        "target_id": raw["target_id"],
        "drafts": [],
        "draft": summary,
        "catalog_stale": draft["catalog_stale"],
        "manual_stale": draft["manual_stale"],
        "project_status": draft["project_status"],
        "changes": rows,
        "next_offset": offset + len(rows) if offset + len(rows) < len(changes) else None,
        "applies_changes": False,
        "exports_file": False,
    }
