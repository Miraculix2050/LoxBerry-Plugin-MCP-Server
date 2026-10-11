"""Bounded local catalog projection shared by MCP and the KNX administration."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mcpserver.config import PluginConfig
from mcpserver.loxone.project.taxonomy import parse_taxonomy

from .model import KnxError, address, metadata
from .read_model import query_filters
from .store import KnxStore


def manual_labels(config: PluginConfig, target: str) -> list[dict[str, str]]:
    entries = config.knx_address_taxonomy if config.knx_address_taxonomy_endpoint == target else ()
    return [
        {"address_format": entry.address_format, "prefix": entry.prefix, "label": entry.label}
        for entry in entries
    ]


def labels_revision(config: PluginConfig, target: str) -> str:
    return hashlib.sha256(
        json.dumps(manual_labels(config, target), sort_keys=True).encode()
    ).hexdigest()


def prefix_projection(
    imported: list[dict[str, str]], manual: list[dict[str, str]]
) -> dict[str, Any]:
    # Validate the same style-bound identities as existing active labels. A
    # prefix provides hierarchy context only, never an inferred signal link.
    result: dict[str, Any] = {}
    for source, rows in (("imported", imported), ("manual", manual)):
        for entry in parse_taxonomy(rows):
            identifier = f"{entry.address_format}:{entry.prefix}"
            item = result.setdefault(
                identifier,
                {
                    "prefix_id": identifier,
                    "address_format": entry.address_format,
                    "prefix": entry.prefix,
                    "sources": {},
                },
            )
            item["sources"][source] = entry.label
            item["local_label_source"] = "manual" if "manual" in item["sources"] else "imported"
    if len(result) > 128:
        raise KnxError("knx_label_limit")
    return result


def catalog_page(
    store: KnxStore,
    config: PluginConfig,
    target: str,
    *,
    offset: int = 0,
    limit: int = 50,
    filters: object = None,
    expected: object = None,
    address_id: int | None = None,
    count_only: bool = False,
) -> dict[str, Any]:
    """Read addresses and selected ETS labels in one SQLite snapshot, without a project graph."""
    page = store.page(
        target,
        offset,
        limit,
        filters=filters,
        expected=expected,
        address_id=address_id,
        count_only=count_only,
        include_labels=True,
    )
    prefixes = prefix_projection(page.pop("imported_labels"), manual_labels(config, target))
    records = []
    used_prefixes: set[str] = set()
    for row in page["items"]:
        number, canonical = address(row["address"], row["address_format"])
        if number != row["address_id"]:
            raise KnxError("knx_storage_failed")
        sources = {"imported": metadata(row["imported"]), "manual": metadata(row["overrides"])}
        parts = canonical.split("/")
        applicable = [
            f"{row['address_format']}:{'/'.join(parts[:length])}"
            for length in range(1, len(parts) + 1)
        ]
        applicable = [identifier for identifier in applicable if identifier in prefixes]
        used_prefixes.update(applicable)
        records.append(
            {
                "address_id": number,
                "address": row["address"],
                "address_format": row["address_format"],
                "sources": sources,
                "local_resolution": {
                    field: "manual"
                    if field in sources["manual"]
                    else "imported"
                    if field in sources["imported"]
                    else "unknown"
                    for field in ("name", "description", "dpts")
                },
                "dpt_details": row["dpt_details"],
                "deviations": row["deviations"],
                "prefix_ids": applicable,
                "import_format": row["import_info"].get("file_format"),
            }
        )
    return {
        "revision": page["revision"],
        "labels_revision": labels_revision(config, target),
        "total_matching": page["total"],
        "records": records,
        "prefix_context": [prefixes[key] for key in sorted(used_prefixes)],
        "active_prefix_count": len(prefixes),
        "offset": offset,
        "returned": len(records),
        "filters": page["filters"],
        "count_scope": "matching_local_records",
        "source_scope": "local_knx_metadata",
        "loxone_names_included": False,
    }


def catalog_prefix_page(
    store: KnxStore,
    config: PluginConfig,
    target: str,
    *,
    offset: int = 0,
    limit: int = 50,
    filters: object = None,
    expected: object = None,
    count_only: bool = False,
) -> dict[str, Any]:
    """Selected imported and manual labels remain readable without any single-address record."""
    selection = query_filters(filters)
    snapshot = store.page(
        target, offset, limit, expected=expected, count_only=True, include_labels=True
    )
    prefixes = prefix_projection(snapshot["imported_labels"], manual_labels(config, target))
    selected = []
    for identifier in sorted(prefixes):
        row = prefixes[identifier]
        sources = row["sources"]
        if selection["source"] != "all" and (
            (selection["source"] in {"imported", "both"} and "imported" not in sources)
            or (selection["source"] in {"manual", "both"} and "manual" not in sources)
        ):
            continue
        if selection["deviations_only"] and not (
            "imported" in sources
            and "manual" in sources
            and sources["imported"] != sources["manual"]
        ):
            continue
        if selection["query"] and not any(
            selection["query"].casefold() in value.casefold()
            for value in (row["prefix"], *sources.values())
        ):
            continue
        selected.append(row)
    rows = [] if count_only else selected[offset : offset + limit]
    return {
        "revision": snapshot["revision"],
        "labels_revision": labels_revision(config, target),
        "total_matching": len(selected),
        "records": [],
        "prefix_labels": rows,
        "prefix_context": [],
        "active_prefix_count": len(prefixes),
        "offset": offset,
        "returned": len(rows),
        "filters": selection,
        "count_scope": "matching_active_prefixes",
        "source_scope": "local_knx_metadata",
        "loxone_names_included": False,
    }
