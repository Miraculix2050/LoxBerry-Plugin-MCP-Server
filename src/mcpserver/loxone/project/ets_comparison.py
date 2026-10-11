"""Explicit imported-address comparison using the existing authorized query index."""

from __future__ import annotations

import asyncio
import hashlib
from time import monotonic
from typing import Any

from mcpserver.knx.model import KnxError
from mcpserver.knx.project_comparison import ProjectComparison, unpack_observation
from mcpserver.knx.project_metadata import ProjectMetadata

from .analysis import ANALYSIS_VERSION
from .coverage import source_diagnostics_projection
from .models import ProjectError
from .query import ProjectQuery

ETS_COMPARISON = "ets_project_comparison"
_MAX_OBJECTS = 20


def _primary_name(query: ProjectQuery, key: str) -> tuple[str | None, bool]:
    node = query._nodes[key]
    mappings = query._mapped_nodes.get(query.view.snapshot.canonical_node_key(key), ())
    exact = [item for item in mappings if item.status == "exact"]
    runtime_name = query.control_names.get(exact[0].control_uuid) if len(exact) == 1 else None
    primary = runtime_name or (node.knx.title if node.knx else None)
    complete = bool(
        primary and (runtime_name or not node.knx or "title" not in node.knx.truncated_fields)
    )
    return primary, complete


def _object(query: ProjectQuery, key: str) -> dict[str, Any]:
    node = query._nodes[key]
    knx = node.knx
    primary, complete = _primary_name(query, key)
    return {
        "project_node_id": key,
        "loxone_name": primary,
        "name_complete": complete,
        "project_title": knx.title if knx else None,
        "project_description": knx.description if knx else None,
        "internal_name": knx.internal_name if knx else None,
        "original_address": knx.group_address.original if knx and knx.group_address else None,
        "address_variant": knx.group_address.variant.value
        if knx and knx.group_address and knx.group_address.variant
        else None,
        "address_format": knx.group_address.format if knx and knx.group_address else None,
        "truncated_fields": list(knx.truncated_fields) if knx else [],
    }


def observe_project(
    query: ProjectQuery,
    metadata: ProjectMetadata,
    target: str,
    revision: int,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Return compact findings; source values are projected only for delivered pages."""
    if deadline is not None and monotonic() >= deadline:
        raise ProjectError("project_worker_limit")
    index = query.graph_index
    assert index is not None
    names = {}
    for number, keys in index.knx_by_address.items():
        values = []
        for key in keys:
            if deadline is not None and monotonic() >= deadline:
                raise ProjectError("project_worker_limit")
            name, complete = _primary_name(query, key)
            if name and complete:
                values.append(name)
        names[number] = tuple(values)
    try:
        observed = ProjectComparison(metadata).observe(target, revision, names, deadline=deadline)
    except KnxError:
        if deadline is not None and monotonic() >= deadline:
            raise ProjectError("project_worker_limit") from None
        raise
    if deadline is not None and monotonic() >= deadline:
        raise ProjectError("project_worker_limit")
    status: Any = query.status()
    endpoints = [
        node for node in index.nodes.values() if node.knx and node.knx.object_kind == "endpoint"
    ]
    coverage = status["coverage_by_source_type"]
    diagnostics = source_diagnostics_projection(query.view.snapshot)
    findings = observed["rows"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "project_fingerprint": query.view.snapshot.fingerprint,
        "model_version": query.view.snapshot.model_version,
        "scope": "knx",
        "analyses": [ETS_COMPARISON],
        "coverage": {
            "endpoints": len(endpoints),
            "endpoint_source_occurrences": sum(
                len(query.view.snapshot.source_ids_for(node.key)) or 1 for node in endpoints
            ),
            "canonical_group_addresses": sum(node.key in index.knx_addresses for node in endpoints),
            "raw_datatypes": sum(
                node.knx is not None and node.knx.datatype is not None for node in endpoints
            ),
            "reviewed_signal_usage": 0,
            "unresolved_relationships": status["unresolved_relationships"],
            "exact_runtime_mappings": sum(
                query._summary(node).get("runtime_control") is not None for node in endpoints
            ),
            "named_endpoints": sum(bool(node.knx and node.knx.title) for node in endpoints),
        },
        "coverage_by_source_type": coverage,
        "source_diagnostics": diagnostics,
        "summaries": {
            ETS_COMPARISON: {
                "comparison_version": 1,
                "knx_revision": revision,
                "target_binding": hashlib.sha256(target.encode()).hexdigest(),
                "import_info": observed["import_info"],
                "import_scope": "latest_document_declaration",
                "catalog_scope": "may_combine_imports",
                "counts": observed["counts"],
                "project_addressed_objects": len(index.knx_addresses),
                "project_distinct_addresses": len(index.knx_by_address),
                "project_model_sources": status["model_sources"],
                "source_coverage_complete": coverage["complete"],
                "source_diagnostics_complete": diagnostics["complete"],
                "source_limits": {
                    "unsupported_source_objects": sum(
                        item["unsupported"] for item in coverage["entries"]
                    ),
                    "invalid_or_missing_address": sum(
                        item["invalid_or_missing_address"] for item in coverage["entries"]
                    ),
                    "ambiguous_source_objects": coverage["ambiguous_source_objects"],
                    "source_groups_omitted": coverage["groups_omitted"],
                    "diagnostic_groups_omitted": diagnostics["groups_omitted"],
                    "incomplete_project_names": sum(
                        len(keys) - len(names[number])
                        for number, keys in index.knx_by_address.items()
                    ),
                    "counts_scope": "reported_source_groups",
                },
                "observation_scope": "authorized_parsed_project_addresses",
                "installation_coverage": "not_assessable",
                "bus_usage_assessed": False,
                "configuration_error_assessed": False,
                "name_based_address_assignment": False,
                "manual_values_change_source_names": False,
            }
        },
        "limitations": [],
        "findings": findings,
        "analysis_truncated": observed["truncated"],
        "truncation_reasons": ["max_findings"] if observed["truncated"] else [],
    }


async def observe_project_bounded(
    query: ProjectQuery,
    metadata: ProjectMetadata,
    target: str,
    revision: int,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Retain the caller's worker lease until real threaded work finishes."""
    task = asyncio.create_task(
        asyncio.to_thread(
            observe_project,
            query,
            metadata,
            target,
            revision,
            monotonic() + 45 if deadline is None else deadline,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise


def project_page(
    query: ProjectQuery,
    metadata: ProjectMetadata,
    target: str,
    revision: int,
    findings: list[dict[str, Any] | int],
) -> list[dict[str, Any]]:
    """Hydrate copies of one output page; never mutate reusable cached findings."""
    index = query.graph_index
    assert index is not None
    numbers = {item & 65535 for item in findings if isinstance(item, int)}
    values = metadata.lookup(target, revision, numbers)
    result = []
    for item in findings:
        if not isinstance(item, int):
            result.append(item)
            continue
        row = unpack_observation(item)
        number = row["address_id"]
        keys = index.knx_by_address.get(number, ())
        result.append(
            {
                "finding_id": "ets-"
                + hashlib.sha256(f"1:{number}:{row['relation']}".encode()).hexdigest()[:24],
                "analysis": ETS_COMPARISON,
                "finding_type": "imported_project_address_observation",
                "classification": "fact",
                "evidence_category": "address_structure",
                "group_address": f"{number >> 11}/{(number >> 8) & 7}/{number & 255}",
                "affected_project_node_ids": list(keys[:_MAX_OBJECTS]),
                "affected_omitted": max(0, len(keys) - _MAX_OBJECTS),
                "comparison": {
                    **row,
                    "project_names_complete": all(
                        complete and bool(name)
                        for name, complete in (_primary_name(query, key) for key in keys)
                    ),
                    "local_metadata": values.get(number),
                    "project_objects": [_object(query, key) for key in keys[:_MAX_OBJECTS]],
                    "project_objects_omitted": max(0, len(keys) - _MAX_OBJECTS),
                },
            }
        )
    return result
