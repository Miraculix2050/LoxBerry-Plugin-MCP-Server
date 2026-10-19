"""Bounded KNX source-type coverage from raw and logical project nodes."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .graph import ProjectSnapshot

_KNX_MARKERS = frozenset({"EibAddr", "EibAddrPulse", "EIBType"})
_MAX_GROUPS = 50
_MAX_LABEL = 100


def source_diagnostics_projection(snapshot: ProjectSnapshot) -> dict[str, object]:
    """Share the bounded diagnostic contract across explicit analyses."""
    diagnostics = snapshot.source_diagnostics
    return {
        "entries": [
            {
                "code": item.code,
                "count": item.count,
                "source_type": item.source_type,
                "attribute_name": item.attribute_name,
                "value_shape": item.value_shape,
                "length_bucket": item.length_bucket,
                "sample_project_node_ids": list(item.sample_node_ids),
                "sample_omitted": item.sample_omitted,
            }
            for item in diagnostics.entries[:50]
        ],
        "complete": diagnostics.complete and len(diagnostics.entries) <= 50,
        "groups_omitted": diagnostics.groups_omitted + max(0, len(diagnostics.entries) - 50),
        "labels_truncated": diagnostics.labels_truncated,
    }


def _label(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_LABEL:
        return value, False
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return value[: _MAX_LABEL - 9] + "~" + suffix, True


def coverage_by_source_type(snapshot: ProjectSnapshot) -> dict[str, object]:
    """Count confirmed KNX types and retain uncertainty about marker-only candidates."""
    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "source_objects": 0,
            "modeled_endpoints": 0,
            "modeled_logic_blocks": 0,
            "modeled_lines": 0,
            "unsupported": 0,
            "invalid_or_missing_address": 0,
            "duplicate_source_occurrences": 0,
        }
    )
    ambiguous = 0
    for node in snapshot.graph.nodes:
        if node.kind != "block":
            continue
        source_type = node.block_type
        if node.knx is None and (source_type is None or not source_type.lower().startswith("eib")):
            if any(name in _KNX_MARKERS for name, _ in node.attributes):
                ambiguous += 1
            continue
        if source_type is None:
            continue
        group = groups[source_type]
        group["source_objects"] += 1
        if node.knx is None:
            group["unsupported"] += 1

    for node in snapshot.logical_nodes():
        if node.kind != "block" or node.knx is None:
            continue
        group = groups[node.knx.source_type]
        kind = node.knx.object_kind
        if kind == "endpoint":
            group["modeled_endpoints"] += 1
            if node.knx.group_address is None or node.knx.group_address.canonical is None:
                group["invalid_or_missing_address"] += 1
        elif kind == "logic_block":
            group["modeled_logic_blocks"] += 1
        elif kind == "line":
            group["modeled_lines"] += 1
        group["duplicate_source_occurrences"] += max(0, len(snapshot.source_ids_for(node.key)) - 1)

    source_types = sorted(groups)
    entries: list[dict[str, object]] = []
    for source_type in source_types[:_MAX_GROUPS]:
        label, truncated = _label(source_type)
        entries.append(
            {"source_type": label, "source_type_truncated": truncated, **groups[source_type]}
        )
    omitted = max(0, len(source_types) - len(entries))
    return {
        "entries": entries,
        "complete": omitted == 0 and ambiguous == 0,
        "groups_omitted": omitted,
        "ambiguous_source_objects": ambiguous,
    }
