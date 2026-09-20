"""Deterministic, bounded KNX evidence derived from an authorized project view."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

from .graph import GraphEdge, GraphNode, SemanticEdge
from .mapping import ProjectView

ANALYSIS_VERSION = 1
ANALYSES = frozenset(
    {
        "address_patterns",
        "raw_datatype_reuse",
        "signal_usage",
        "technology_paths",
        "project_connectivity",
    }
)
_MAX_FINDINGS = 10_000
_MAX_EVIDENCE = 20
_MAX_PATHS = 5_000
_MAX_VISITED_PER_START = 2_000
_AddressGroupKey = tuple[str, str, str, tuple[tuple[str, str | None], ...]]
_DirectionalAdjacency = dict[str, list[GraphEdge | SemanticEdge]]


@dataclass(frozen=True, slots=True)
class _Endpoint:
    node: GraphNode
    block: GraphNode
    direction: str
    address: str | None
    address_format: str | None
    segments: tuple[int, ...] | None
    datatype: str | None
    usage: tuple[tuple[str, str | None], ...]


def _finding_id(kind: str, basis: object, nodes: list[str]) -> str:
    material = json.dumps(
        [ANALYSIS_VERSION, kind, basis, sorted(nodes)], separators=(",", ":"), sort_keys=True
    ).encode()
    return "knx:" + hashlib.sha256(material).hexdigest()[:20]


def _bounded_nodes(values: list[str]) -> tuple[list[str], int]:
    ordered = sorted(set(values))
    return ordered[:_MAX_EVIDENCE], max(0, len(ordered) - _MAX_EVIDENCE)


def _children(graph_edges: tuple[GraphEdge, ...]) -> tuple[dict[str, list[str]], dict[str, str]]:
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, str] = {}
    for edge in graph_edges:
        if edge.kind == "contains":
            children[edge.source].append(edge.target)
            parents[edge.target] = edge.source
    return children, parents


def _block(node: GraphNode, nodes: dict[str, GraphNode], parents: dict[str, str]) -> GraphNode:
    return node if node.kind == "block" else nodes[parents[node.key]]


def _descendants(key: str, children: dict[str, list[str]]) -> list[str]:
    result, pending = [key], deque([key])
    while pending:
        current = pending.popleft()
        for child in children[current]:
            result.append(child)
            pending.append(child)
    return result


def _directional_adjacencies(
    graph_edges: tuple[GraphEdge, ...], semantic_edges: tuple[SemanticEdge, ...]
) -> tuple[_DirectionalAdjacency, _DirectionalAdjacency]:
    downstream: _DirectionalAdjacency = defaultdict(list)
    upstream: _DirectionalAdjacency = defaultdict(list)
    for edge in graph_edges:
        if edge.kind in {"signal", "reference"}:
            downstream[edge.source].append(edge)
            upstream[edge.target].append(edge)
    for semantic_edge in semantic_edges:
        downstream[semantic_edge.source].append(semantic_edge)
        upstream[semantic_edge.target].append(semantic_edge)
    return downstream, upstream


def _usage(
    node: GraphNode,
    children: dict[str, list[str]],
    adjacency: _DirectionalAdjacency,
) -> tuple[tuple[str, str | None], ...]:
    assert node.knx is not None and node.knx.flow_direction is not None
    seeds = _descendants(node.key, children)
    upstream = node.knx.flow_direction == "loxone_to_bus"
    seen, pending, result = set(seeds), deque(seeds), set[tuple[str, str | None]]()
    while pending:
        current = pending.popleft()
        for relationship in adjacency[current]:
            other = relationship.source if upstream else relationship.target
            if isinstance(relationship, SemanticEdge):
                result.add((relationship.interpretation, relationship.effect))
            if other not in seen:
                seen.add(other)
                pending.append(other)
    return tuple(sorted(result))


def analyze_knx(view: ProjectView, analyses: frozenset[str]) -> dict[str, object]:
    """Return facts and review candidates, never a configuration verdict."""
    if not analyses or not analyses <= ANALYSES:
        raise ValueError("project_analysis_invalid")
    graph = view.snapshot.graph
    nodes = {node.key: node for node in graph.nodes}
    children, parents = _children(graph.edges)
    needs_usage = bool({"address_patterns", "signal_usage"} & analyses)
    needs_directional_adjacency = needs_usage or "technology_paths" in analyses
    downstream: _DirectionalAdjacency = {}
    upstream: _DirectionalAdjacency = {}
    if needs_directional_adjacency:
        downstream, upstream = _directional_adjacencies(graph.edges, graph.semantic_edges)
    endpoints: list[_Endpoint] = []
    for node in graph.nodes:
        knx = node.knx
        if knx is None or knx.object_kind != "endpoint" or knx.flow_direction is None:
            continue
        address = knx.group_address
        usage_adjacency = upstream if knx.flow_direction == "loxone_to_bus" else downstream
        endpoints.append(
            _Endpoint(
                node,
                _block(node, nodes, parents),
                knx.flow_direction,
                address.canonical if address else None,
                address.format if address else None,
                address.segments if address else None,
                knx.datatype.source_value if knx.datatype else None,
                _usage(node, children, usage_adjacency) if needs_usage else (),
            )
        )
    findings: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    truncated_reasons: list[str] = []

    if "address_patterns" in analyses:
        groups: dict[_AddressGroupKey, list[_Endpoint]] = defaultdict(list)
        for item in endpoints:
            if item.address and item.address_format and item.datatype and item.usage:
                group_key = (item.direction, item.address_format, item.datatype, item.usage)
                groups[group_key].append(item)
        pattern_count = 0
        for basis, members in sorted(groups.items(), key=lambda pair: repr(pair[0])):
            if len(members) < 5:
                continue
            levels = (1,) if basis[1] == "two_level" else (1, 2)
            for level in levels:
                prefixes: dict[tuple[int, ...], list[_Endpoint]] = defaultdict(list)
                for item in members:
                    assert item.segments is not None
                    prefixes[item.segments[:level]].append(item)
                dominant, dominant_members = max(
                    prefixes.items(), key=lambda pair: (len(pair[1]), pair[0])
                )
                ratio = len(dominant_members) / len(members)
                if ratio < 0.8 or len(prefixes) == 1:
                    continue
                for prefix, minority in sorted(prefixes.items()):
                    if prefix == dominant:
                        continue
                    ids, omitted = _bounded_nodes([item.node.key for item in minority])
                    findings.append(
                        {
                            "finding_id": _finding_id(
                                "address_pattern_deviation", [basis, level, prefix], ids
                            ),
                            "analysis": "address_patterns",
                            "finding_type": "address_pattern_deviation",
                            "flow_direction": basis[0],
                            "address_format": basis[1],
                            "raw_datatype": basis[2],
                            "usage": [{"interpretation": x, "effect": y} for x, y in basis[3]],
                            "prefix_level": level,
                            "dominant_prefix": list(dominant),
                            "dominant_count": len(dominant_members),
                            "peer_count": len(members),
                            "deviation_prefix": list(prefix),
                            "affected_project_node_ids": ids,
                            "affected_omitted": omitted,
                        }
                    )
                    pattern_count += 1
        summaries["address_patterns"] = {
            "comparison_groups": len(groups),
            "deviations": pattern_count,
        }

    if "raw_datatype_reuse" in analyses:
        by_address: dict[str, list[_Endpoint]] = defaultdict(list)
        for item in endpoints:
            if item.address and item.datatype:
                by_address[item.address].append(item)
        conflicts = 0
        for group_address, members in sorted(by_address.items()):
            values = sorted({item.datatype for item in members if item.datatype is not None})
            if len(values) < 2:
                continue
            ids, omitted = _bounded_nodes([item.node.key for item in members])
            findings.append(
                {
                    "finding_id": _finding_id(
                        "raw_datatype_conflict", [group_address, values], ids
                    ),
                    "analysis": "raw_datatype_reuse",
                    "finding_type": "raw_datatype_conflict",
                    "group_address": group_address,
                    "raw_datatypes": values,
                    "affected_project_node_ids": ids,
                    "affected_omitted": omitted,
                }
            )
            conflicts += 1
        summaries["raw_datatype_reuse"] = {"conflicts": conflicts}

    if "signal_usage" in analyses:
        by_address = defaultdict(list)
        for item in endpoints:
            if item.address and item.usage:
                by_address[item.address].append(item)
        mixed = 0
        for group_address, members in sorted(by_address.items()):
            signatures = sorted({item.usage for item in members})
            if len(signatures) < 2:
                continue
            ids, omitted = _bounded_nodes([item.node.key for item in members])
            findings.append(
                {
                    "finding_id": _finding_id(
                        "mixed_signal_usage", [group_address, signatures], ids
                    ),
                    "analysis": "signal_usage",
                    "finding_type": "mixed_signal_usage",
                    "group_address": group_address,
                    "usage_signatures": [
                        [{"interpretation": x, "effect": y} for x, y in signature]
                        for signature in signatures
                    ],
                    "affected_project_node_ids": ids,
                    "affected_omitted": omitted,
                }
            )
            mixed += 1
        summaries["signal_usage"] = {"mixed_group_addresses": mixed}

    if "project_connectivity" in analyses:
        adjacency: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            if edge.kind in {"signal", "reference"}:
                adjacency[edge.source].append(edge)
                adjacency[edge.target].append(edge)
        unresolved = {key for key, _ in graph.unresolved}
        disconnected = ambiguous = 0
        for item in endpoints:
            seed = _descendants(item.block.key, children)
            has_relation = any(adjacency[key] for key in seed)
            if has_relation:
                continue
            ids, omitted = _bounded_nodes(seed)
            finding_type = (
                "project_connectivity_ambiguous"
                if any(key in unresolved for key in seed)
                else "no_project_signal_relationship"
            )
            findings.append(
                {
                    "finding_id": _finding_id(finding_type, [item.direction, item.address], ids),
                    "analysis": "project_connectivity",
                    "finding_type": finding_type,
                    "flow_direction": item.direction,
                    "group_address": item.address,
                    "affected_project_node_ids": ids,
                    "affected_omitted": omitted,
                }
            )
            disconnected += finding_type == "no_project_signal_relationship"
            ambiguous += finding_type == "project_connectivity_ambiguous"
        summaries["project_connectivity"] = {"unconnected": disconnected, "ambiguous": ambiguous}

    if "technology_paths" in analyses:
        counts: Counter[str] = Counter()
        samples: dict[str, list[dict[str, object]]] = defaultdict(list)
        mapped = {
            key
            for entry in view.mapping.entries
            if entry.status == "exact"
            for key in entry.node_keys
        }
        seen_paths: set[tuple[str, str, str]] = set()
        for start in endpoints:
            is_downstream = start.direction == "bus_to_loxone"
            path_adjacency = downstream if is_downstream else upstream
            pending = deque((key, [key], 0) for key in _descendants(start.block.key, children))
            visited = {key for key, _, _ in pending}
            while pending:
                current, path, depth = pending.popleft()
                if len(visited) > _MAX_VISITED_PER_START:
                    truncated_reasons.append("max_path_nodes")
                    break
                if depth >= 16:
                    continue
                for traversal_edge in path_adjacency[current]:
                    other = traversal_edge.target if is_downstream else traversal_edge.source
                    if other in visited:
                        continue
                    visited.add(other)
                    next_path = [*path, other]
                    target = nodes[other]
                    target_block = _block(target, nodes, parents)
                    target_kind = None
                    if target_block.knx and target_block.knx.object_kind == "endpoint":
                        target_kind = target_block.knx.flow_direction
                    elif target_block.key in mapped:
                        target_kind = "loxone"
                    kind = None
                    if start.direction == "bus_to_loxone" and target_kind == "loxone":
                        kind = "knx_to_loxone"
                    elif start.direction == "bus_to_loxone" and target_kind == "loxone_to_bus":
                        kind = "knx_to_knx"
                    elif start.direction == "loxone_to_bus" and target_kind == "loxone":
                        kind = "loxone_to_knx"
                    elif start.direction == "loxone_to_bus" and target_kind == "bus_to_loxone":
                        kind = "knx_to_knx"
                    if kind:
                        source_block, destination_block = (
                            (start.block, target_block)
                            if is_downstream
                            else (target_block, start.block)
                        )
                        identity = (kind, source_block.key, destination_block.key)
                        if identity not in seen_paths:
                            if len(seen_paths) >= _MAX_PATHS:
                                truncated_reasons.append("max_paths")
                                pending.clear()
                                break
                            seen_paths.add(identity)
                            counts[kind] += 1
                            if len(samples[kind]) < 3:
                                samples[kind].append(
                                    {
                                        "source_project_node_id": source_block.key,
                                        "target_project_node_id": destination_block.key,
                                        "evidence_project_node_ids": (
                                            next_path
                                            if is_downstream
                                            else list(reversed(next_path))
                                        ),
                                    }
                                )
                    pending.append((other, next_path, depth + 1))
        summaries["technology_paths"] = {
            "counts": dict(sorted(counts.items())),
            "samples": dict(sorted(samples.items())),
        }

    if len(findings) > _MAX_FINDINGS:
        findings = findings[:_MAX_FINDINGS]
        truncated_reasons.append("max_findings")
    findings.sort(
        key=lambda item: (str(item["analysis"]), str(item["finding_type"]), str(item["finding_id"]))
    )
    return {
        "analysis_version": ANALYSIS_VERSION,
        "project_fingerprint": view.snapshot.fingerprint,
        "model_version": view.snapshot.model_version,
        "scope": "knx",
        "analyses": sorted(analyses),
        "coverage": {
            "endpoints": len(endpoints),
            "canonical_group_addresses": sum(item.address is not None for item in endpoints),
            "raw_datatypes": sum(item.datatype is not None for item in endpoints),
            "reviewed_signal_usage": sum(bool(item.usage) for item in endpoints),
            "unresolved_relationships": len(graph.unresolved),
        },
        "summaries": summaries,
        "findings": findings,
        "analysis_truncated": bool(truncated_reasons),
        "truncation_reasons": sorted(set(truncated_reasons)),
    }
