"""Deterministic, bounded KNX evidence derived from an authorized project view."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass

from .coverage import coverage_by_source_type
from .graph import GraphEdge, GraphNode, SemanticEdge
from .mapping import ProjectView, RuntimeEvidence
from .taxonomy import AddressTaxonomyEntry

ANALYSIS_VERSION = 7
_FINDING_ID_VERSION = 6
ANALYSES = frozenset(
    {
        "address_hierarchy",
        "address_patterns",
        "naming_consistency",
        "datatype_consistency",
        "signal_usage_consistency",
        "technology_architecture",
        "graph_outliers",
        "project_connectivity",
        "peer_group_consistency",
    }
)
_MAX_FINDINGS = 10_000
_MAX_EVIDENCE = 20
_MAX_PATHS = 5_000
_MAX_VISITED_PER_START = 2_000
_MAX_PATH_DEPTH = 16
_MAX_USAGE_NODES_PER_ENDPOINT = 2_000
_MAX_USAGE_NODES = 100_000
_AddressGroupKey = tuple[str, str, str, tuple[tuple[str, str | None], ...]]
_DirectionalAdjacency = dict[str, list[GraphEdge | SemanticEdge]]


@dataclass(frozen=True, slots=True)
class _Endpoint:
    node: GraphNode
    block: GraphNode
    blocks: tuple[GraphNode, ...]
    direction: str
    address: str | None
    address_variant: str | None
    address_format: str | None
    segments: tuple[int, ...] | None
    datatype: str | None
    usage: tuple[tuple[str, str | None], ...]
    runtime: RuntimeEvidence | None
    names: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class _UsageBudget:
    remaining: int = _MAX_USAGE_NODES

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _finding_id(kind: str, basis: object, nodes: list[str]) -> str:
    material = json.dumps(
        [_FINDING_ID_VERSION, kind, basis, sorted(nodes)],
        separators=(",", ":"),
        sort_keys=True,
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
    return node if node.kind == "block" else nodes.get(parents.get(node.key, ""), node)


def _descendants(key: str, children: dict[str, list[str]]) -> list[str]:
    result, pending = [key], deque([key])
    while pending:
        current = pending.popleft()
        for child in children[current]:
            result.append(child)
            pending.append(child)
    return result


def _endpoint_descendants(item: _Endpoint, children: dict[str, list[str]]) -> list[str]:
    """Return graph evidence for every source occurrence of one logical endpoint."""
    return sorted({key for block in item.blocks for key in _descendants(block.key, children)})


def _connector_evidence(node: GraphNode) -> dict[str, object]:
    raw_key = next((value for name, value in node.attributes if name == "K"), None)
    return {
        "project_node_id": node.key,
        "connector_key": raw_key[:100] if raw_key is not None else None,
        "connector_key_truncated": raw_key is not None and len(raw_key) > 100,
    }


def _edge_evidence(
    edge: GraphEdge | SemanticEdge, nodes: dict[str, GraphNode]
) -> dict[str, object]:
    if isinstance(edge, SemanticEdge):
        kind, provenance, rule_id = "derived_semantic", "reviewed_rule", edge.rule_id
    else:
        kind = edge.kind
        provenance = "configured_input" if kind == "signal" else "configured_reference"
        rule_id = None
    source = nodes[edge.source]
    target = nodes[edge.target]
    source_connector = _connector_evidence(source) if source.kind == "connector" else None
    target_connector = _connector_evidence(target) if target.kind == "connector" else None
    return {
        "kind": kind,
        "provenance": provenance,
        "source_project_node_id": edge.source,
        "target_project_node_id": edge.target,
        "source_connector_key": source_connector["connector_key"] if source_connector else None,
        "source_connector_key_truncated": source_connector["connector_key_truncated"]
        if source_connector
        else False,
        "target_connector_key": target_connector["connector_key"] if target_connector else None,
        "target_connector_key_truncated": target_connector["connector_key_truncated"]
        if target_connector
        else False,
        "semantic_rule_id": rule_id,
    }


def _edge_sort_key(edge: GraphEdge | SemanticEdge) -> tuple[str, str, str, str]:
    return (
        "derived_semantic" if isinstance(edge, SemanticEdge) else edge.kind,
        edge.source,
        edge.target,
        edge.rule_id if isinstance(edge, SemanticEdge) else "None",
    )


def _outlier_edges(
    raw: dict[str, list[GraphEdge]],
    semantic: dict[str, list[SemanticEdge]],
    seeds: set[str],
    adjacent: set[str],
) -> Iterator[GraphEdge | SemanticEdge]:
    for key in sorted(seeds):
        yield from raw[key]
    for key in sorted(adjacent):
        yield from semantic[key]


def _bounded_descendants(
    key: str, children: dict[str, list[str]], limit: int
) -> tuple[list[str], bool]:
    result, pending = [key], deque([key])
    while pending:
        current = pending.popleft()
        for child in children[current]:
            if len(result) >= limit:
                return result, True
            result.append(child)
            pending.append(child)
    return result, False


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
    budget: _UsageBudget,
) -> tuple[tuple[tuple[str, str | None], ...], bool]:
    assert node.knx is not None and node.knx.flow_direction is not None
    seeds, seed_pending = [], deque([node.key])
    seen = set[str]()
    while seed_pending:
        current = seed_pending.popleft()
        if current in seen:
            continue
        if len(seen) >= _MAX_USAGE_NODES_PER_ENDPOINT or not budget.consume():
            return (), True
        seen.add(current)
        seeds.append(current)
        for child in children[current]:
            if child in seen:
                continue
            if len(seen) + len(seed_pending) >= _MAX_USAGE_NODES_PER_ENDPOINT:
                return (), True
            seed_pending.append(child)
    upstream = node.knx.flow_direction == "loxone_to_bus"
    pending, result = deque(seeds), set[tuple[str, str | None]]()
    while pending:
        current = pending.popleft()
        for relationship in adjacency[current]:
            other = relationship.source if upstream else relationship.target
            if isinstance(relationship, SemanticEdge):
                result.add((relationship.interpretation, relationship.effect))
            if other not in seen:
                if len(seen) >= _MAX_USAGE_NODES_PER_ENDPOINT or not budget.consume():
                    return (), True
                seen.add(other)
                pending.append(other)
    return tuple(sorted(result)), False


_NAME_PART = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])|[^\w]+")


def _name_shape(value: str) -> tuple[str, ...]:
    """Return a language-neutral, deterministic name skeleton without assigning a role."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    parts = [part.casefold() for part in _NAME_PART.split(normalized) if part]
    return tuple("{number}" if part.isdecimal() else part for part in parts)


def _role_key(item: _Endpoint, *, include_usage: bool = True) -> tuple[object, ...] | None:
    """Build a peer key only from exact runtime or reviewed signal evidence."""

    runtime_type = item.runtime.control_type if item.runtime is not None else None
    if runtime_type is None and not item.usage:
        return None
    key: tuple[object, ...] = (
        item.direction,
        item.node.knx.source_type if item.node.knx else None,
        runtime_type,
    )
    return (*key, item.usage) if include_usage else key


def _support(members: list[_Endpoint], selected: list[_Endpoint]) -> dict[str, object]:
    return {"count": len(selected), "total": len(members), "ratio": len(selected) / len(members)}


def analyze_knx(
    view: ProjectView,
    analyses: frozenset[str],
    taxonomy: tuple[AddressTaxonomyEntry, ...] = (),
) -> dict[str, object]:
    """Return facts and review candidates, never a configuration verdict."""
    if not analyses or not analyses <= ANALYSES:
        raise ValueError("project_analysis_invalid")
    graph = view.snapshot.graph
    source_diagnostics = view.snapshot.source_diagnostics
    nodes = {node.key: node for node in graph.nodes}
    children, parents = _children(graph.edges)
    needs_usage = bool(
        {
            "address_patterns",
            "naming_consistency",
            "datatype_consistency",
            "signal_usage_consistency",
            "graph_outliers",
            "peer_group_consistency",
        }
        & analyses
    )
    needs_directional_adjacency = needs_usage or "technology_architecture" in analyses
    downstream: _DirectionalAdjacency = {}
    upstream: _DirectionalAdjacency = {}
    if needs_directional_adjacency:
        downstream, upstream = _directional_adjacencies(graph.edges, graph.semantic_edges)
    runtime_candidates: dict[str, list[RuntimeEvidence]] = defaultdict(list)
    for entry in view.mapping.entries:
        if entry.status != "exact" or entry.evidence is None:
            continue
        for key in entry.node_keys:
            runtime_candidates[key].append(entry.evidence)
    runtime_by_node = {
        key: evidence[0] for key, evidence in runtime_candidates.items() if len(evidence) == 1
    }
    usage_budget = _UsageBudget(_MAX_USAGE_NODES)
    usage_truncated = False
    endpoints: list[_Endpoint] = []
    for node in view.snapshot.logical_nodes():
        knx = node.knx
        if knx is None or knx.object_kind != "endpoint" or knx.flow_direction is None:
            continue
        address = knx.group_address
        occurrences = tuple(
            nodes[key] for key in view.snapshot.occurrence_keys_for(node.key) if key in nodes
        ) or (node,)
        blocks = tuple(
            dict.fromkeys(_block(occurrence, nodes, parents) for occurrence in occurrences)
        )
        usage_adjacency = upstream if knx.flow_direction == "loxone_to_bus" else downstream
        usages: set[tuple[str, str | None]] = set()
        truncated = False
        if needs_usage:
            for occurrence in occurrences:
                occurrence_usage, occurrence_truncated = _usage(
                    occurrence, children, usage_adjacency, usage_budget
                )
                usages.update(occurrence_usage)
                truncated = truncated or occurrence_truncated
        usage = tuple(sorted(usages))
        usage_truncated = usage_truncated or truncated
        runtime = runtime_by_node.get(_block(node, nodes, parents).key)
        names: list[tuple[str, str]] = []
        if knx.title:
            names.append(("knx_title", knx.title))
        if knx.internal_name:
            names.append(("knx_internal_name", knx.internal_name))
        if runtime is not None and runtime.name:
            names.append(("runtime_control_name", runtime.name))
        endpoints.append(
            _Endpoint(
                node,
                blocks[0],
                blocks,
                knx.flow_direction,
                address.canonical if address else None,
                address.variant.value if address and address.variant else None,
                address.format if address else None,
                address.segments if address else None,
                knx.datatype.source_value if knx.datatype else None,
                usage,
                runtime,
                tuple(names),
            )
        )
    findings: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    truncated_reasons: list[str] = ["max_usage_nodes"] if usage_truncated else []
    hierarchy_limit = _MAX_FINDINGS if analyses == {"address_hierarchy"} else _MAX_FINDINGS // 2
    hierarchy_findings = 0

    def emit(kind: str, basis: object, evidence: list[str], payload: dict[str, object]) -> None:
        """Add one bounded finding while hashing the complete evidence set."""

        nonlocal hierarchy_findings
        is_hierarchy = payload["analysis"] == "address_hierarchy"
        if len(findings) >= _MAX_FINDINGS or (
            is_hierarchy and hierarchy_findings >= hierarchy_limit
        ):
            truncated_reasons.append("max_findings")
            return
        ids, omitted = _bounded_nodes(evidence)
        findings.append(
            {
                "finding_id": _finding_id(kind, basis, evidence),
                **payload,
                "affected_project_node_ids": ids,
                "affected_omitted": omitted,
            }
        )
        hierarchy_findings += is_hierarchy

    if "address_hierarchy" in analyses:
        hierarchy_outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        hierarchy_incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            if edge.kind in {"signal", "reference"}:
                hierarchy_outgoing[edge.source].append(edge)
                hierarchy_incoming[edge.target].append(edge)
        unresolved = {key for key, _ in graph.unresolved}
        wiring: dict[str, str] = {}
        for item in endpoints:
            seed = _endpoint_descendants(item, children)
            directional = (
                hierarchy_outgoing if item.direction == "bus_to_loxone" else hierarchy_incoming
            )
            wiring[item.node.key] = (
                "with_relationship"
                if any(directional[key] for key in seed)
                else "unresolved"
                if any(key in unresolved for key in seed)
                else "without_relationship"
            )
        hierarchy_prefixes: dict[tuple[str, tuple[int, ...]], list[_Endpoint]] = defaultdict(list)
        for item in endpoints:
            if item.segments is None or item.address_format is None:
                continue
            for depth in range(1, len(item.segments) + 1):
                hierarchy_prefixes[(item.address_format, item.segments[:depth])].append(item)
        labels: dict[tuple[str, tuple[int, ...]], str] = {
            (entry.address_format, entry.segments): entry.label for entry in taxonomy
        }
        prefix_rows = patterns = outliers = 0
        for (address_format, prefix), members in sorted(hierarchy_prefixes.items()):
            members = sorted(members, key=lambda item: item.node.key)
            examples = []
            for item in members[:_MAX_EVIDENCE]:
                address = item.node.knx.group_address if item.node.knx else None
                if address is not None:
                    examples.append(
                        {
                            "project_node_id": item.node.key,
                            "original": address.original,
                            "canonical": address.canonical,
                            "variant": item.address_variant,
                        }
                    )
            source_types = Counter(
                item.node.knx.source_type for item in members if item.node.knx is not None
            )
            directions = Counter(item.direction for item in members)
            wiring_counts = Counter(wiring[item.node.key] for item in members)
            shapes = Counter(
                _name_shape(item.node.knx.title)
                for item in members
                if item.node.knx is not None and item.node.knx.title
            )
            shape_count = max(shapes.values(), default=0)
            label = labels.get((address_format, prefix))
            hierarchy: dict[str, object] = {
                "prefix": list(prefix),
                "prefix_level": len(prefix),
                "address_format": address_format,
                "object_count": len(members),
                "source_occurrence_count": sum(
                    len(view.snapshot.source_ids_for(item.node.key)) or 1 for item in members
                ),
                "logical_address_count": len({item.address for item in members}),
                "edge_variant_count": sum(item.address_variant is not None for item in members),
                "source_type_counts": dict(sorted(source_types.items())),
                "flow_direction_counts": dict(sorted(directions.items())),
                "direct_wiring": dict(sorted(wiring_counts.items())),
                "exact_runtime_mapping_count": sum(item.runtime is not None for item in members),
                "name_pattern_support": {
                    "kind": "literal_shape_only",
                    "count": shape_count,
                    "total": len(members),
                },
                "configured_taxonomy": (
                    {"label": label, "provenance": "admin_configured"} if label else None
                ),
                "address_examples": examples,
                "address_examples_omitted": max(0, len(members) - len(examples)),
                "evidence_categories": [
                    "address_structure",
                    "object_type",
                    "direct_wiring",
                    "runtime_mapping",
                    "name_pattern",
                    *(["configured_taxonomy"] if label else []),
                ],
            }
            emit(
                "address_prefix_summary",
                [address_format, prefix],
                [item.node.key for item in members],
                {
                    "analysis": "address_hierarchy",
                    "finding_type": "address_prefix_summary",
                    "classification": "fact",
                    "evidence_category": "address_structure",
                    "hierarchy": hierarchy,
                },
            )
            prefix_rows += 1

            if len(members) < 5:
                continue
            dimensions: list[tuple[str, str, list[str]]] = [
                (
                    "object_type",
                    "source_type",
                    [item.node.knx.source_type for item in members if item.node.knx],
                ),
                (
                    "address_structure",
                    "variant",
                    [item.address_variant or "none" for item in members],
                ),
                ("address_structure", "direction", [item.direction for item in members]),
                ("direct_wiring", "wiring", [wiring[item.node.key] for item in members]),
            ]
            if all(item.node.knx and item.node.knx.title for item in members):
                dimensions.append(
                    (
                        "name_pattern",
                        "literal_name_shape",
                        [
                            json.dumps(_name_shape(item.node.knx.title))
                            for item in members
                            if item.node.knx is not None and item.node.knx.title
                        ],
                    )
                )
            if taxonomy:
                dimensions.append(
                    (
                        "configured_taxonomy",
                        "configured_label",
                        [
                            labels.get((address_format, item.segments or ()), "unlabeled")
                            for item in members
                        ],
                    )
                )
            for category, dimension, values in dimensions:
                if len(values) != len(members):
                    continue
                hierarchy_counts = Counter(values)
                hierarchy_dominant, support_count = sorted(
                    hierarchy_counts.items(), key=lambda pair: (-pair[1], pair[0])
                )[0]
                if len(hierarchy_counts) < 2 or support_count * 5 < len(members) * 4:
                    continue
                for value in sorted(hierarchy_counts):
                    selected = [
                        item.node.key
                        for item, observed in zip(members, values, strict=True)
                        if observed == value
                    ]
                    is_pattern = value == hierarchy_dominant
                    emit(
                        "address_hierarchy_pattern" if is_pattern else "address_hierarchy_outlier",
                        [address_format, prefix, dimension, hierarchy_dominant, value],
                        selected,
                        {
                            "analysis": "address_hierarchy",
                            "finding_type": (
                                "address_hierarchy_pattern"
                                if is_pattern
                                else "address_hierarchy_outlier"
                            ),
                            "classification": "pattern" if is_pattern else "outlier",
                            "evidence_category": category,
                            "comparison_dimension": dimension,
                            "baseline_value": hierarchy_dominant,
                            "observed_value": value,
                            "dominant_count": support_count,
                            "peer_count": len(members),
                            "support": _support(
                                members,
                                [
                                    item
                                    for item, observed in zip(members, values, strict=True)
                                    if observed == value
                                ],
                            ),
                            "prefix_level": len(prefix),
                            "dominant_prefix": list(prefix),
                        },
                    )
                    patterns += is_pattern
                    outliers += not is_pattern
        summaries["address_hierarchy"] = {
            "prefix_rows": prefix_rows,
            "patterns": patterns,
            "outliers": outliers,
            "unaddressed_endpoints": sum(item.segments is None for item in endpoints),
        }

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
                    evidence = [item.node.key for item in minority]
                    emit(
                        "address_pattern_deviation",
                        [basis, level, prefix],
                        evidence,
                        {
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
                        },
                    )
                    pattern_count += 1
        summaries["address_patterns"] = {
            "comparison_groups": len(groups),
            "deviations": pattern_count,
        }

    if "naming_consistency" in analyses:
        name_groups: dict[
            tuple[str, tuple[object, ...]], list[tuple[_Endpoint, tuple[str, ...]]]
        ] = defaultdict(list)
        for item in endpoints:
            role = _role_key(item)
            if role is None:
                continue
            for source, name in item.names:
                shape = _name_shape(name)
                if shape:
                    name_groups[(source, role)].append((item, shape))
        patterns = deviations = 0
        for (source, role), name_members in sorted(
            name_groups.items(), key=lambda pair: repr(pair[0])
        ):
            if len(name_members) < 5:
                continue
            by_shape: dict[tuple[str, ...], list[_Endpoint]] = defaultdict(list)
            for item, shape in name_members:
                by_shape[shape].append(item)
            dominant_shape, dominant_members = max(
                by_shape.items(), key=lambda pair: (len(pair[1]), pair[0])
            )
            if len(dominant_members) / len(name_members) < 0.8:
                continue
            all_members = [item.node.key for item, _ in name_members]
            emit(
                "naming_pattern",
                [source, role, dominant_shape],
                all_members,
                {
                    "analysis": "naming_consistency",
                    "finding_type": "naming_pattern",
                    "classification": "pattern",
                    "name_source": source,
                    "name_shape": list(dominant_shape),
                    "support": _support([item for item, _ in name_members], dominant_members),
                },
            )
            patterns += 1
            for shape, minority in sorted(by_shape.items()):
                if shape == dominant_shape:
                    continue
                emit(
                    "naming_deviation",
                    [source, role, dominant_shape, shape],
                    [item.node.key for item in minority],
                    {
                        "analysis": "naming_consistency",
                        "finding_type": "naming_deviation",
                        "classification": "outlier",
                        "name_source": source,
                        "name_shape": list(shape),
                        "dominant_name_shape": list(dominant_shape),
                        "support": _support([item for item, _ in name_members], dominant_members),
                    },
                )
                deviations += 1
        summaries["naming_consistency"] = {"patterns": patterns, "deviations": deviations}

    if "datatype_consistency" in analyses:
        by_address: dict[tuple[str, str], list[_Endpoint]] = defaultdict(list)
        for item in endpoints:
            if item.address and item.datatype:
                by_address[(item.address, item.address_variant or "")].append(item)
        conflicts = 0
        for (group_address, variant), members in sorted(by_address.items()):
            values = sorted({item.datatype for item in members if item.datatype is not None})
            if len(values) < 2:
                continue
            evidence = [item.node.key for item in members]
            emit(
                "raw_datatype_conflict",
                [group_address, variant, values],
                evidence,
                {
                    "analysis": "datatype_consistency",
                    "finding_type": "raw_datatype_conflict",
                    "group_address": group_address,
                    "address_variant": variant or None,
                    "raw_datatypes": values,
                },
            )
            conflicts += 1
        summaries["datatype_consistency"] = {"conflicts": conflicts, "peer_outliers": 0}

    if "signal_usage_consistency" in analyses:
        by_address = defaultdict(list)
        for item in endpoints:
            if item.address and item.usage:
                by_address[(item.address, item.address_variant or "")].append(item)
        mixed = 0
        for (group_address, variant), members in sorted(by_address.items()):
            signatures = sorted({item.usage for item in members})
            if len(signatures) < 2:
                continue
            evidence = [item.node.key for item in members]
            emit(
                "mixed_signal_usage",
                [group_address, variant, signatures],
                evidence,
                {
                    "analysis": "signal_usage_consistency",
                    "finding_type": "mixed_signal_usage",
                    "group_address": group_address,
                    "address_variant": variant or None,
                    "usage_signatures": [
                        [{"interpretation": x, "effect": y} for x, y in signature]
                        for signature in signatures
                    ],
                },
            )
            mixed += 1
        summaries["signal_usage_consistency"] = {"mixed_group_addresses": mixed, "peer_outliers": 0}

    role_groups: dict[tuple[object, ...], list[_Endpoint]] = defaultdict(list)
    for item in endpoints:
        role = _role_key(item)
        if role is not None:
            role_groups[role].append(item)

    if "datatype_consistency" in analyses:
        peer_outliers = 0
        for role, members in sorted(role_groups.items(), key=lambda pair: repr(pair[0])):
            known = [item for item in members if item.datatype is not None]
            if len(known) < 5:
                continue
            by_value: dict[str, list[_Endpoint]] = defaultdict(list)
            for item in known:
                assert item.datatype is not None
                by_value[item.datatype].append(item)
            dominant_datatype, dominant_members = max(
                by_value.items(), key=lambda pair: (len(pair[1]), pair[0])
            )
            if len(dominant_members) / len(known) < 0.8 or len(by_value) == 1:
                continue
            for value, minority in sorted(by_value.items()):
                if value == dominant_datatype:
                    continue
                emit(
                    "datatype_peer_outlier",
                    [role, dominant_datatype, value],
                    [item.node.key for item in minority],
                    {
                        "analysis": "datatype_consistency",
                        "finding_type": "datatype_peer_outlier",
                        "classification": "outlier",
                        "raw_datatype": value,
                        "dominant_raw_datatype": dominant_datatype,
                        "support": _support(known, dominant_members),
                    },
                )
                peer_outliers += 1
        summaries["datatype_consistency"]["peer_outliers"] = peer_outliers  # type: ignore[index]

    if "signal_usage_consistency" in analyses:
        peer_outliers = 0
        usage_role_groups: dict[tuple[object, ...], list[_Endpoint]] = defaultdict(list)
        for item in endpoints:
            role = _role_key(item, include_usage=False)
            if role is not None:
                usage_role_groups[role].append(item)
        for role, members in sorted(usage_role_groups.items(), key=lambda pair: repr(pair[0])):
            known = [item for item in members if item.usage]
            if len(known) < 5:
                continue
            by_usage: dict[tuple[tuple[str, str | None], ...], list[_Endpoint]] = defaultdict(list)
            for item in known:
                by_usage[item.usage].append(item)
            dominant_usage, dominant_members = max(
                by_usage.items(), key=lambda pair: (len(pair[1]), pair[0])
            )
            if len(dominant_members) / len(known) < 0.8 or len(by_usage) == 1:
                continue
            for usage, minority in sorted(by_usage.items()):
                if usage == dominant_usage:
                    continue
                emit(
                    "signal_usage_peer_outlier",
                    [role, dominant_usage, usage],
                    [item.node.key for item in minority],
                    {
                        "analysis": "signal_usage_consistency",
                        "finding_type": "signal_usage_peer_outlier",
                        "classification": "outlier",
                        "usage_signatures": [
                            [{"interpretation": x, "effect": y} for x, y in usage]
                        ],
                        "support": _support(known, dominant_members),
                    },
                )
                peer_outliers += 1
        summaries["signal_usage_consistency"]["peer_outliers"] = peer_outliers  # type: ignore[index]

    if "peer_group_consistency" in analyses:
        patterns = 0
        for role, members in sorted(role_groups.items(), key=lambda pair: repr(pair[0])):
            if len(members) < 5:
                continue
            by_signature: dict[tuple[object, ...], list[_Endpoint]] = defaultdict(list)
            for item in members:
                by_signature[
                    (item.runtime.control_type if item.runtime else None, item.datatype, item.usage)
                ].append(item)
            dominant_signature, dominant_members = max(
                by_signature.items(), key=lambda pair: (len(pair[1]), repr(pair[0]))
            )
            if len(dominant_members) / len(members) < 0.8:
                continue
            emit(
                "peer_group_pattern",
                [role, dominant_signature],
                [item.node.key for item in members],
                {
                    "analysis": "peer_group_consistency",
                    "finding_type": "peer_group_pattern",
                    "classification": "pattern",
                    "support": _support(members, dominant_members),
                },
            )
            patterns += 1
        summaries["peer_group_consistency"] = {"patterns": patterns}

    if "graph_outliers" in analyses:
        outliers = 0
        graph_outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        graph_incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        semantic_outgoing: dict[str, list[SemanticEdge]] = defaultdict(list)
        semantic_incoming: dict[str, list[SemanticEdge]] = defaultdict(list)
        for edge in graph.edges:
            if edge.kind in {"signal", "reference"}:
                graph_outgoing[edge.source].append(edge)
                graph_incoming[edge.target].append(edge)
        for semantic_edge in graph.semantic_edges:
            semantic_outgoing[semantic_edge.source].append(semantic_edge)
            semantic_incoming[semantic_edge.target].append(semantic_edge)
        for role, members in sorted(role_groups.items(), key=lambda pair: repr(pair[0])):
            if len(members) < 8:
                continue
            metric_sets: dict[str, list[tuple[_Endpoint, int]]] = {
                "fan_out": [
                    (
                        item,
                        sum(
                            len(graph_outgoing[key])
                            for key in _endpoint_descendants(item, children)
                        ),
                    )
                    for item in members
                ],
                "fan_in": [
                    (
                        item,
                        sum(
                            len(graph_incoming[key])
                            for key in _endpoint_descendants(item, children)
                        ),
                    )
                    for item in members
                ],
            }
            for metric, metric_values in metric_sets.items():
                ordered = sorted(metric_value for _, metric_value in metric_values)
                q1 = ordered[(len(ordered) - 1) // 4]
                q3 = ordered[((len(ordered) - 1) * 3) // 4]
                iqr = q3 - q1
                for item, metric_value in metric_values:
                    unusual = (
                        metric_value < q1 - 1.5 * iqr or metric_value > q3 + 1.5 * iqr
                        if iqr
                        else abs(metric_value - ordered[len(ordered) // 2]) >= 2
                    )
                    if not unusual:
                        continue
                    outlier_seed_keys = set(_endpoint_descendants(item, children))
                    directional = graph_outgoing if metric == "fan_out" else graph_incoming
                    signal_count = 0
                    counterparts: set[str] = set()
                    adjacent = set(outlier_seed_keys)
                    for key in outlier_seed_keys:
                        for raw_edge in directional[key]:
                            other = raw_edge.target if metric == "fan_out" else raw_edge.source
                            adjacent.add(other)
                            if raw_edge.kind == "signal":
                                signal_count += 1
                                counterparts.add(
                                    view.snapshot.canonical_node_key(
                                        _block(nodes[other], nodes, parents).key
                                    )
                                )
                    semantic_directional = (
                        semantic_outgoing if metric == "fan_out" else semantic_incoming
                    )
                    derived_count = sum(len(semantic_directional[key]) for key in adjacent)
                    sampled_edges = heapq.nsmallest(
                        _MAX_EVIDENCE,
                        _outlier_edges(
                            directional,
                            semantic_directional,
                            outlier_seed_keys,
                            adjacent,
                        ),
                        key=_edge_sort_key,
                    )
                    edge_evidence_rows = [_edge_evidence(edge, nodes) for edge in sampled_edges]
                    emit(
                        "graph_metric_outlier",
                        [role, metric, q1, q3, metric_value],
                        [item.node.key],
                        {
                            "analysis": "graph_outliers",
                            "finding_type": "graph_metric_outlier",
                            "classification": "outlier",
                            "graph_metric": metric,
                            "graph_value": metric_value,
                            "graph_q1": q1,
                            "graph_q3": q3,
                            "edge_summary": {
                                "metric": "raw_out_degree"
                                if metric == "fan_out"
                                else "raw_in_degree",
                                "raw_degree": metric_value,
                                "signal_edges": signal_count,
                                "reference_edges": metric_value - signal_count,
                                "derived_semantic_edges": derived_count,
                                "logical_consumers": len(counterparts)
                                if metric == "fan_out"
                                else None,
                                "logical_sources": len(counterparts)
                                if metric == "fan_in"
                                else None,
                            },
                            "edge_evidence": edge_evidence_rows,
                            "edge_evidence_omitted": max(
                                0, metric_value + derived_count - len(edge_evidence_rows)
                            ),
                        },
                    )
                    outliers += 1
        summaries["graph_outliers"] = {"outliers": outliers}

    if "project_connectivity" in analyses:
        outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            if edge.kind in {"signal", "reference"}:
                outgoing[edge.source].append(edge)
                incoming[edge.target].append(edge)
        unresolved = {key for key, _ in graph.unresolved}
        disconnected = ambiguous = reference_only = 0
        for item in endpoints:
            seed = _endpoint_descendants(item, children)
            directional = outgoing if item.direction == "bus_to_loxone" else incoming
            relationships = [edge for key in seed for edge in directional[key]]
            direct_count = sum(edge.kind == "signal" for edge in relationships)
            reference_count = len(relationships) - direct_count
            if direct_count:
                continue
            unresolved_count = sum(key in unresolved for key in seed)
            finding_type = (
                "project_connectivity_ambiguous"
                if unresolved_count
                else "no_direct_configured_signal_relationship"
                if reference_count
                else "no_project_signal_relationship"
            )
            connectors = sorted(
                (_connector_evidence(nodes[key]) for key in seed if nodes[key].kind == "connector"),
                key=lambda entry: str(entry["project_node_id"]),
            )
            description = (
                "No direct configured consumer found in the inspected project connectors."
                if item.direction == "bus_to_loxone"
                else "No direct configured input source found in the inspected project connectors."
            )
            if unresolved_count:
                description += " Some connector relationships could not be resolved."
            emit(
                finding_type,
                [item.direction, item.address, item.address_variant],
                seed,
                {
                    "analysis": "project_connectivity",
                    "finding_type": finding_type,
                    "classification": "ambiguity"
                    if finding_type == "project_connectivity_ambiguous"
                    else "fact",
                    "flow_direction": item.direction,
                    "group_address": item.address,
                    "address_variant": item.address_variant,
                    "description": description,
                    "connectivity_scope": "inspected_project_endpoint_connectors",
                    "inspected_connectors": connectors[:_MAX_EVIDENCE],
                    "inspected_connectors_omitted": max(0, len(connectors) - _MAX_EVIDENCE),
                    "direct_configured_relationship_count": direct_count,
                    "reference_relationship_count": reference_count,
                },
            )
            disconnected += finding_type == "no_project_signal_relationship"
            ambiguous += finding_type == "project_connectivity_ambiguous"
            reference_only += finding_type == "no_direct_configured_signal_relationship"
        summaries["project_connectivity"] = {
            "unconnected": disconnected,
            "ambiguous": ambiguous,
            "reference_only": reference_only,
        }

    if "technology_architecture" in analyses:
        counts: Counter[str] = Counter()
        samples: dict[str, list[dict[str, object]]] = defaultdict(list)
        endpoint_blocks = {item.block.key for item in endpoints}
        mapped = {
            key
            for key, evidence in runtime_candidates.items()
            if len(evidence) == 1
            if key not in endpoint_blocks
        }
        seen_paths: set[tuple[str, str, str]] = set()
        path_limit_reached = False
        for start in endpoints:
            if path_limit_reached:
                break
            is_downstream = start.direction == "bus_to_loxone"
            path_adjacency = downstream if is_downstream else upstream
            seeds, seeds_truncated = _bounded_descendants(
                start.block.key, children, _MAX_VISITED_PER_START
            )
            if seeds_truncated:
                truncated_reasons.append("max_path_nodes")
            pending = deque((key, [key], 0) for key in seeds)
            visited = {key for key, _, _ in pending}
            while pending:
                current, path, depth = pending.popleft()
                if len(visited) > _MAX_VISITED_PER_START:
                    truncated_reasons.append("max_path_nodes")
                    break
                if depth >= _MAX_PATH_DEPTH:
                    if path_adjacency[current]:
                        truncated_reasons.append("max_depth")
                    continue
                for traversal_edge in path_adjacency[current]:
                    other = traversal_edge.target if is_downstream else traversal_edge.source
                    if other in visited:
                        continue
                    if len(visited) >= _MAX_VISITED_PER_START:
                        truncated_reasons.append("max_path_nodes")
                        pending.clear()
                        break
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
                                path_limit_reached = True
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
                            if len(seen_paths) >= _MAX_PATHS:
                                truncated_reasons.append("max_paths")
                                path_limit_reached = True
                                pending.clear()
                                break
                    if path_limit_reached:
                        pending.clear()
                        break
                    pending.append((other, next_path, depth + 1))
        # A Loxone-to-Loxone path is included only when the directed path crosses
        # a confirmed KNX endpoint; this keeps the KNX scope bounded.
        for start_key in sorted(mapped):
            if path_limit_reached:
                break
            seeds, seeds_truncated = _bounded_descendants(
                start_key, children, _MAX_VISITED_PER_START
            )
            if seeds_truncated:
                truncated_reasons.append("max_path_nodes")
            loxone_pending = deque((key, [key], 0, False) for key in seeds)
            loxone_visited = {(key, crossed_knx) for key, _, _, crossed_knx in loxone_pending}
            while loxone_pending:
                current, path, depth, crossed_knx = loxone_pending.popleft()
                if len(loxone_visited) > _MAX_VISITED_PER_START:
                    truncated_reasons.append("max_path_nodes")
                    break
                if depth >= _MAX_PATH_DEPTH:
                    if downstream[current]:
                        truncated_reasons.append("max_depth")
                    continue
                for traversal_edge in downstream[current]:
                    other = traversal_edge.target
                    next_path = [*path, other]
                    target_block = _block(nodes[other], nodes, parents)
                    next_crossed = crossed_knx or bool(
                        target_block.knx and target_block.knx.object_kind == "endpoint"
                    )
                    visit_key = (other, next_crossed)
                    if visit_key in loxone_visited:
                        continue
                    if len(loxone_visited) >= _MAX_VISITED_PER_START:
                        truncated_reasons.append("max_path_nodes")
                        loxone_pending.clear()
                        break
                    loxone_visited.add(visit_key)
                    if (
                        next_crossed
                        and target_block.key in mapped
                        and target_block.key != start_key
                    ):
                        identity = ("loxone_to_loxone", start_key, target_block.key)
                        if identity not in seen_paths:
                            if len(seen_paths) >= _MAX_PATHS:
                                truncated_reasons.append("max_paths")
                                path_limit_reached = True
                                loxone_pending.clear()
                                break
                            seen_paths.add(identity)
                            counts["loxone_to_loxone"] += 1
                            if len(samples["loxone_to_loxone"]) < 3:
                                samples["loxone_to_loxone"].append(
                                    {
                                        "source_project_node_id": start_key,
                                        "target_project_node_id": target_block.key,
                                        "evidence_project_node_ids": next_path,
                                    }
                                )
                            if len(seen_paths) >= _MAX_PATHS:
                                truncated_reasons.append("max_paths")
                                path_limit_reached = True
                                loxone_pending.clear()
                                break
                    if path_limit_reached:
                        loxone_pending.clear()
                        break
                    loxone_pending.append((other, next_path, depth + 1, next_crossed))
        summaries["technology_architecture"] = {
            "counts": dict(sorted(counts.items())),
            "samples": dict(sorted(samples.items())),
        }

    if len(findings) > _MAX_FINDINGS:
        findings = findings[:_MAX_FINDINGS]
        truncated_reasons.append("max_findings")

    def finding_order(item: dict[str, object]) -> tuple[str, int, str, tuple[int, ...], str]:
        hierarchy = item.get("hierarchy")
        if item["finding_type"] == "address_prefix_summary" and isinstance(hierarchy, dict):
            return (
                "address_hierarchy",
                0,
                str(hierarchy["address_format"]),
                tuple(hierarchy["prefix"]),
                str(item["finding_id"]),
            )
        return (
            str(item["analysis"]),
            1,
            str(item["finding_type"]),
            (),
            str(item["finding_id"]),
        )

    findings.sort(key=finding_order)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "project_fingerprint": view.snapshot.fingerprint,
        "model_version": view.snapshot.model_version,
        "scope": "knx",
        "analyses": sorted(analyses),
        "coverage": {
            "endpoints": len(endpoints),
            "endpoint_source_occurrences": sum(
                len(view.snapshot.source_ids_for(endpoint.node.key)) or 1 for endpoint in endpoints
            ),
            "canonical_group_addresses": sum(item.address is not None for item in endpoints),
            "raw_datatypes": sum(item.datatype is not None for item in endpoints),
            "reviewed_signal_usage": sum(bool(item.usage) for item in endpoints),
            "unresolved_relationships": len(graph.unresolved),
            "exact_runtime_mappings": sum(item.runtime is not None for item in endpoints),
            "named_endpoints": sum(bool(item.names) for item in endpoints),
        },
        "coverage_by_source_type": coverage_by_source_type(view.snapshot),
        "summaries": summaries,
        "limitations": [
            {
                "code": "normalized_dpt_unavailable",
                "count": sum(item.datatype is not None for item in endpoints),
            },
            {"code": "semantic_domain_unavailable", "count": len(endpoints)},
            {
                "code": "usage_semantics_unreviewed",
                "count": sum(not item.usage for item in endpoints),
            },
            {
                "code": "runtime_mapping_incomplete",
                "count": sum(item.runtime is None for item in endpoints),
            },
            {"code": "unresolved_relationships", "count": len(graph.unresolved)},
        ],
        "source_diagnostics": {
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
                for item in source_diagnostics.entries[:50]
            ],
            "complete": source_diagnostics.complete and len(source_diagnostics.entries) <= 50,
            "groups_omitted": source_diagnostics.groups_omitted
            + max(0, len(source_diagnostics.entries) - 50),
            "labels_truncated": source_diagnostics.labels_truncated,
        },
        "findings": findings,
        "analysis_truncated": bool(truncated_reasons),
        "truncation_reasons": sorted(set(truncated_reasons)),
    }
