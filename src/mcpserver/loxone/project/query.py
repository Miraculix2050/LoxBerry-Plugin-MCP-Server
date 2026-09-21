"""Bounded, evidence-based projection of immutable project graphs."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .graph import GraphEdge, GraphNode, SemanticEdge
from .mapping import ControlMapping, ProjectView
from .semantics import signal_use_rules

_KNOWN_KNX_ATTRIBUTES = frozenset({"Type", "U", "Title", "Desc", "IName", "EibAddr", "EIBType"})
_KNX_MARKER_ATTRIBUTES = frozenset({"EibAddr", "EIBType"})
_DIAGNOSTIC_LABEL_LIMIT = 100


class ProjectQueryError(ValueError):
    """A fixed public query category; never carries source content."""


@dataclass(frozen=True, slots=True)
class ProjectQuery:
    """One read-only, identity-bound view of a project graph."""

    view: ProjectView
    control_names: dict[str, str]
    _nodes: dict[str, GraphNode] = field(init=False, repr=False)
    _mappings: dict[str, ControlMapping] = field(init=False, repr=False)
    _mapped_nodes: dict[str, list[ControlMapping]] = field(init=False, repr=False)
    _parents: dict[str, str] = field(init=False, repr=False)
    _children: dict[str, list[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_nodes", {node.key: node for node in self.view.snapshot.graph.nodes}
        )
        mappings = {entry.control_uuid: entry for entry in self.view.mapping.entries}
        object.__setattr__(self, "_mappings", mappings)
        mapped_nodes: dict[str, list[ControlMapping]] = defaultdict(list)
        for entry in mappings.values():
            for key in entry.node_keys:
                mapped_nodes[key].append(entry)
        object.__setattr__(self, "_mapped_nodes", mapped_nodes)
        parents: dict[str, str] = {}
        children: dict[str, list[str]] = defaultdict(list)
        for edge in self.view.snapshot.graph.edges:
            if edge.kind == "contains":
                parents[edge.target] = edge.source
                children[edge.source].append(edge.target)
        object.__setattr__(self, "_parents", parents)
        object.__setattr__(self, "_children", children)

    @staticmethod
    def _semantic_edge_data(edge: SemanticEdge) -> dict[str, object]:
        return {
            "source": edge.source,
            "target": edge.target,
            "rule_id": edge.rule_id,
            "interpretation": edge.interpretation,
            "effect": edge.effect,
        }

    def _descendants(self, key: str, limit: int) -> tuple[list[str], bool]:
        result = [key]
        seen = {key}
        pending = deque([key])
        while pending:
            current = pending.popleft()
            for child in self._children[current]:
                if child in seen:
                    continue
                if len(result) >= limit:
                    return result, True
                seen.add(child)
                result.append(child)
                pending.append(child)
        return result, False

    def _semantic_observations(
        self, node: GraphNode, limit: int
    ) -> tuple[list[dict[str, object]], bool]:
        """Return bounded rule evidence reachable from one KNX endpoint."""

        knx = node.knx
        if knx is None or knx.object_kind != "endpoint" or knx.flow_direction is None:
            return [], False
        upstream = knx.flow_direction == "loxone_to_bus"
        seeds, truncated = self._descendants(node.key, limit)
        visited = set(seeds)
        pending = deque(seeds)
        adjacency: dict[str, list[GraphEdge | SemanticEdge]] = defaultdict(list)
        for edge in self.view.snapshot.graph.edges:
            if edge.kind in {"signal", "reference"}:
                adjacency[edge.target if upstream else edge.source].append(edge)
        for semantic_edge in self.view.snapshot.graph.semantic_edges:
            adjacency[semantic_edge.target if upstream else semantic_edge.source].append(
                semantic_edge
            )
        observations: list[dict[str, object]] = []
        seen_rules: set[tuple[str, str, str]] = set()
        while pending and not truncated:
            current = pending.popleft()
            for relationship in adjacency[current]:
                neighbor = relationship.source if upstream else relationship.target
                if isinstance(relationship, SemanticEdge):
                    identity = (relationship.rule_id, relationship.source, relationship.target)
                    if identity not in seen_rules:
                        if len(observations) >= limit:
                            truncated = True
                            break
                        seen_rules.add(identity)
                        observations.append(self._semantic_edge_data(relationship))
                if neighbor not in visited:
                    if len(visited) >= limit:
                        truncated = True
                        break
                    visited.add(neighbor)
                    pending.append(neighbor)
        return observations, truncated

    def _summary(self, node: GraphNode) -> dict[str, object]:
        mapping = self._mapped_nodes.get(node.key, [])
        exact = [item for item in mapping if item.status == "exact"]
        runtime_control = exact[0] if len(exact) == 1 else None
        connector_key = next((value for key, value in node.attributes if key == "K"), None)
        knx = node.knx
        return {
            "project_node_id": node.key,
            "kind": node.kind,
            "block_type": node.block_type,
            "source_id": node.source_id,
            "connector_key": connector_key,
            "runtime_control": (
                {
                    "uuid": runtime_control.control_uuid,
                    "name": self.control_names.get(runtime_control.control_uuid),
                    "mapping_status": runtime_control.status,
                    "mapping_rule": runtime_control.rule,
                }
                if runtime_control is not None
                else None
            ),
            "knx": (
                {
                    "object_kind": knx.object_kind,
                    "flow_direction": knx.flow_direction,
                    "source_type": knx.source_type,
                    "group_address": (
                        {
                            "canonical": knx.group_address.canonical,
                        }
                        if knx.group_address is not None
                        else None
                    ),
                }
                if knx is not None
                else None
            ),
        }

    def _detail(self, node: GraphNode, *, limit: int) -> dict[str, object]:
        """Return the one-object projection including all KNX source evidence."""
        result = self._summary(node)
        source_diagnostics, labels_truncated = self._node_source_diagnostics(node)
        result["source_diagnostics"] = source_diagnostics
        result["source_diagnostics_labels_truncated"] = labels_truncated
        for item in self.view.snapshot.source_diagnostics.entries:
            if item.code.startswith("parser_") and node.key in item.sample_node_ids:
                source_diagnostics.append({"code": item.code})
        knx = node.knx
        if knx is None:
            return result
        observations, observations_truncated = self._semantic_observations(node, limit)
        result["knx"] = {
            "object_kind": knx.object_kind,
            "flow_direction": knx.flow_direction,
            "source_type": knx.source_type,
            "title": knx.title,
            "description": knx.description,
            "internal_name": knx.internal_name,
            "group_address": (
                {
                    "original": knx.group_address.original,
                    "canonical": knx.group_address.canonical,
                    "format": knx.group_address.format,
                    "segments": list(knx.group_address.segments)
                    if knx.group_address.segments is not None
                    else None,
                }
                if knx.group_address is not None
                else None
            ),
            "datatype": (
                {
                    "source_field": knx.datatype.source_field,
                    "source_value": knx.datatype.source_value,
                    "system": knx.datatype.system,
                    "normalized_code": knx.datatype.normalized_code,
                }
                if knx.datatype is not None
                else None
            ),
            "truncated_fields": list(knx.truncated_fields),
            "usage_observations": observations,
            "usage_observations_truncated": observations_truncated,
        }
        return result

    def _node_source_diagnostics(self, node: GraphNode) -> tuple[list[dict[str, object]], bool]:
        """Return a value-free diagnostic projection for one authorized node."""

        diagnostics: list[dict[str, object]] = []
        labels_truncated = False

        def label(value: str) -> str:
            nonlocal labels_truncated
            if len(value) <= _DIAGNOSTIC_LABEL_LIMIT:
                return value
            labels_truncated = True
            return value[:80] + "…#" + hashlib.sha256(value.encode()).hexdigest()[:12]

        knx = node.knx
        if knx is None:
            markers = sorted(
                label(key) for key, _ in node.attributes if key in _KNX_MARKER_ATTRIBUTES
            )
            if markers:
                diagnostics.append({"code": "unclassified_knx_candidate", "marker_fields": markers})
            return diagnostics, labels_truncated
        if knx.object_kind == "endpoint":
            if knx.group_address is None:
                diagnostics.append({"code": "missing_group_address"})
            elif knx.group_address.canonical is None:
                diagnostics.append({"code": "invalid_group_address"})
            if knx.datatype is None:
                diagnostics.append({"code": "missing_raw_datatype"})
        if knx.object_kind == "logic_block":
            rules = signal_use_rules(node.block_type)
            if not rules:
                diagnostics.append({"code": "unreviewed_knx_logic"})
            else:
                connectors = {
                    next(
                        (value for name, value in self._nodes[key].attributes if name == "K"), None
                    )
                    for key in self._children[node.key]
                }
                reviewed = {rule.input_key for rule in rules} | {rule.output_key for rule in rules}
                for key in sorted(
                    item for item in connectors if item is not None and item not in reviewed
                ):
                    diagnostics.append(
                        {"code": "unreviewed_knx_connector", "attribute_name": label(key)}
                    )
        for key, value in node.attributes:
            if key in _KNOWN_KNX_ATTRIBUTES:
                continue
            length = len(value)
            if not value:
                shape = "empty"
            elif value.isdecimal() or (value.startswith(("+", "-")) and value[1:].isdecimal()):
                shape = "integer"
            else:
                try:
                    float(value)
                    shape = "decimal"
                except ValueError:
                    shape = "text"
            bucket = (
                "0"
                if not value
                else "1-16"
                if length <= 16
                else "17-64"
                if length <= 64
                else "65-200"
                if length <= 200
                else ">200"
            )
            diagnostics.append(
                {
                    "code": "unmodeled_knx_attribute",
                    "attribute_name": label(key),
                    "value_shape": shape,
                    "length_bucket": bucket,
                }
            )
        return diagnostics[:50], labels_truncated

    def status(self) -> dict[str, object]:
        graph = self.view.snapshot.graph
        mapping_counts: dict[str, int] = {"exact": 0, "ambiguous": 0, "unmapped": 0}
        for entry in self.view.mapping.entries:
            mapping_counts[entry.status] = mapping_counts.get(entry.status, 0) + 1
        return {
            "project_fingerprint": self.view.snapshot.fingerprint,
            "model_version": self.view.snapshot.model_version,
            "project_parts": len(self.view.snapshot.projects),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "unresolved_relationships": len(graph.unresolved),
            "mapping": mapping_counts,
            "source_diagnostics": {
                "entries": [
                    {
                        "code": code,
                        "count": sum(
                            item.count
                            for item in self.view.snapshot.source_diagnostics.entries
                            if item.code == code
                        ),
                    }
                    for code in sorted(
                        {item.code for item in self.view.snapshot.source_diagnostics.entries}
                    )
                ],
                "complete": self.view.snapshot.source_diagnostics.complete,
                "groups_omitted": self.view.snapshot.source_diagnostics.groups_omitted,
                "labels_truncated": self.view.snapshot.source_diagnostics.labels_truncated,
            },
        }

    def find(
        self,
        *,
        query: str | None,
        kind: str | None,
        block_type: str | None,
        source_id: str | None,
        runtime_control_uuid: str | None,
        technology: str | None = None,
        knx_object_kind: str | None = None,
        knx_flow_direction: str | None = None,
        knx_group_address: str | None = None,
    ) -> list[dict[str, object]]:
        if kind is not None and kind not in {"block", "connector"}:
            raise ProjectQueryError("project_query_invalid")
        if technology is not None and technology != "knx_eib":
            raise ProjectQueryError("project_query_invalid")
        if knx_object_kind is not None and knx_object_kind not in {
            "line",
            "endpoint",
            "logic_block",
        }:
            raise ProjectQueryError("project_query_invalid")
        if knx_flow_direction is not None and knx_flow_direction not in {
            "bus_to_loxone",
            "loxone_to_bus",
        }:
            raise ProjectQueryError("project_query_invalid")
        if runtime_control_uuid is not None:
            mapping = self._mappings.get(runtime_control_uuid)
            if mapping is None:
                return []
            candidates = set(mapping.node_keys)
        else:
            candidates = None
        needle = query.casefold().strip() if query else None
        result = []
        for node in self.view.snapshot.graph.nodes:
            knx = node.knx
            if candidates is not None and node.key not in candidates:
                continue
            if kind is not None and node.kind != kind:
                continue
            if block_type is not None and node.block_type != block_type:
                continue
            if source_id is not None and node.source_id != source_id:
                continue
            if technology == "knx_eib" and knx is None:
                continue
            if knx_object_kind is not None and (knx is None or knx.object_kind != knx_object_kind):
                continue
            if knx_flow_direction is not None and (
                knx is None or knx.flow_direction != knx_flow_direction
            ):
                continue
            if knx_group_address is not None and (
                knx is None
                or knx.group_address is None
                or knx_group_address
                not in {knx.group_address.original, knx.group_address.canonical}
            ):
                continue
            item = self._summary(node)
            if needle is not None:
                connector_key = next((value for key, value in node.attributes if key == "K"), None)
                knx_values = (
                    (knx.title, knx.description, knx.internal_name)
                    + (
                        (knx.group_address.original, knx.group_address.canonical)
                        if knx is not None and knx.group_address is not None
                        else ()
                    )
                    if knx is not None
                    else ()
                )
                searchable = (node.key, node.source_id, node.block_type, connector_key, *knx_values)
                runtime = item["runtime_control"]
                runtime_name = runtime.get("name") if isinstance(runtime, dict) else None
                if not any(
                    needle in value.casefold() for value in (*searchable, runtime_name) if value
                ):
                    continue
            result.append(item)
        return result

    def resolve(self, identifier: str, identifier_type: str) -> GraphNode:
        if identifier_type == "project_node_id":
            node = self._nodes.get(identifier)
            if node is None:
                raise ProjectQueryError("project_node_unknown")
            return node
        if identifier_type != "runtime_control_uuid":
            raise ProjectQueryError("project_query_invalid")
        mapping = self._mappings.get(identifier)
        if mapping is None or mapping.status == "unmapped":
            raise ProjectQueryError("project_node_unknown")
        if mapping.status != "exact":
            raise ProjectQueryError("project_mapping_ambiguous")
        return self._nodes[mapping.node_keys[0]]

    def describe(self, node: GraphNode, *, limit: int) -> dict[str, object]:
        if not 1 <= limit <= 100:
            raise ProjectQueryError("project_query_invalid")
        graph = self.view.snapshot.graph
        contains_in = [
            edge.source
            for edge in graph.edges
            if edge.kind == "contains" and edge.target == node.key
        ]
        contains_out = [
            edge.target
            for edge in graph.edges
            if edge.kind == "contains" and edge.source == node.key
        ]
        direct = [
            {"kind": edge.kind, "source": edge.source, "target": edge.target}
            for edge in graph.edges
            if edge.kind != "contains" and (edge.source == node.key or edge.target == node.key)
        ]
        child_ids = sorted(contains_out)
        unresolved = [code for key, code in graph.unresolved if key == node.key]
        truncated_fields = []
        if len(child_ids) > limit:
            truncated_fields.append("child_project_node_ids")
        if len(direct) > limit:
            truncated_fields.append("relationships")
        if len(unresolved) > limit:
            truncated_fields.append("unresolved_relationships")
        return {
            **self._detail(node, limit=limit),
            "parent_project_node_id": contains_in[0] if len(contains_in) == 1 else None,
            "child_project_node_ids": child_ids[:limit],
            "relationships": direct[:limit],
            "unresolved_relationships": unresolved[:limit],
            "truncated_fields": truncated_fields,
        }

    def _endpoint_block(self, key: str) -> GraphNode | None:
        """Resolve a connector to its containing block without treating containment as flow."""

        node = self._nodes[key]
        if node.kind == "block":
            return node
        parent = self._parents.get(key)
        return self._nodes.get(parent) if parent is not None else None

    def _endpoint_kind(self, node: GraphNode) -> str | None:
        knx = node.knx
        if knx is not None and knx.object_kind == "endpoint":
            return knx.flow_direction
        mapping = self._mapped_nodes.get(node.key, [])
        return "loxone" if len([item for item in mapping if item.status == "exact"]) == 1 else None

    def _technology_paths(
        self,
        node: GraphNode,
        keys: list[str],
        predecessors: dict[str, str | None],
        limit: int,
        direction: str,
    ) -> tuple[list[dict[str, object]], bool]:
        """Project only fully identified KNX/Loxone boundary paths."""

        start = self._endpoint_block(node.key)
        if start is None:
            return [], False
        start_kind = self._endpoint_kind(start)
        if start_kind is None:
            return [], False
        paths: list[dict[str, object]] = []
        identities: set[tuple[str, str, str]] = set()
        truncated = False
        included_keys = set(keys)
        for key in keys:
            end = self._endpoint_block(key)
            if end is None or end.key == start.key:
                continue
            end_kind = self._endpoint_kind(end)
            if end_kind is None:
                continue
            classification: str | None = None
            source, target = start, end
            if direction == "downstream":
                if start_kind == "bus_to_loxone" and end_kind == "loxone":
                    classification = "knx_to_loxone"
                elif start_kind == "loxone" and end_kind == "loxone_to_bus":
                    classification = "loxone_to_knx"
                elif start_kind == "bus_to_loxone" and end_kind == "loxone_to_bus":
                    classification = "knx_to_knx"
            elif start_kind == "loxone_to_bus" and end_kind == "loxone":
                classification, source, target = "loxone_to_knx", end, start
            elif start_kind == "loxone" and end_kind == "bus_to_loxone":
                classification, source, target = "knx_to_loxone", end, start
            elif start_kind == "loxone_to_bus" and end_kind == "bus_to_loxone":
                classification, source, target = "knx_to_knx", end, start
            if classification is None:
                continue
            if source.key not in included_keys or target.key not in included_keys:
                # Do not return paths whose boundary nodes are absent from the
                # trace.  The caller marks this as semantically incomplete.
                truncated = True
                continue
            identity = (classification, source.key, target.key)
            if identity in identities:
                continue
            if len(paths) >= limit:
                truncated = True
                break
            identities.add(identity)
            walked = [key]
            current = key
            previous = predecessors.get(current)
            while previous is not None:
                current = previous
                walked.append(current)
                previous = predecessors.get(current)
            walked.reverse()
            if source is not start:
                walked.reverse()
            paths.append(
                {
                    "classification": classification,
                    "source_project_node_id": source.key,
                    "target_project_node_id": target.key,
                    "evidence_project_node_ids": list(
                        dict.fromkeys([source.key, *walked, target.key])
                    ),
                }
            )
        return paths, truncated

    def _append_trace_boundaries(self, keys: list[str], limit: int) -> bool:
        """Include containing endpoint blocks referenced by technology paths."""

        included_keys = set(keys)
        truncated = False
        for key in list(keys):
            boundary = self._endpoint_block(key)
            if boundary is None or boundary.key in included_keys:
                continue
            if len(keys) >= limit:
                truncated = True
                continue
            included_keys.add(boundary.key)
            keys.append(boundary.key)
        return truncated

    def trace(
        self, node: GraphNode, *, direction: str, max_depth: int, max_nodes: int
    ) -> dict[str, object]:
        if (
            direction not in {"upstream", "downstream"}
            or not 1 <= max_depth <= 16
            or not 1 <= max_nodes <= 200
        ):
            raise ProjectQueryError("project_query_invalid")
        adjacency: dict[str, list[GraphEdge | SemanticEdge]] = defaultdict(list)
        for edge in self.view.snapshot.graph.edges:
            if edge.kind not in {"signal", "reference"}:
                continue
            key = edge.target if direction == "upstream" else edge.source
            adjacency[key].append(edge)
        for semantic_edge in self.view.snapshot.graph.semantic_edges:
            key = semantic_edge.target if direction == "upstream" else semantic_edge.source
            adjacency[key].append(semantic_edge)
        seeds = [node.key]
        seed_set = {node.key}
        pending = deque([node.key])
        seed_truncated = False
        while pending and not seed_truncated:
            current = pending.popleft()
            for child in self._children[current]:
                if child in seed_set:
                    continue
                if len(seeds) >= max_nodes:
                    seed_truncated = True
                    break
                seed_set.add(child)
                seeds.append(child)
                pending.append(child)
        visited = seed_set
        queue = deque((key, 0) for key in seeds)
        keys = seeds
        edges: list[dict[str, str]] = []
        semantic_edges: list[dict[str, object]] = []
        predecessors: dict[str, str | None] = {key: None for key in seeds}
        truncated = seed_truncated
        reason: str | None = "max_nodes" if seed_truncated else None
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                if adjacency[current]:
                    truncated, reason = True, "max_depth"
                continue
            for relationship in adjacency[current]:
                neighbor = relationship.source if direction == "upstream" else relationship.target
                if neighbor in visited:
                    if len(edges) + len(semantic_edges) >= max_nodes:
                        truncated, reason = True, "max_edges"
                        break
                    if isinstance(relationship, SemanticEdge):
                        semantic_edges.append(self._semantic_edge_data(relationship))
                    else:
                        edges.append(
                            {
                                "kind": relationship.kind,
                                "source": relationship.source,
                                "target": relationship.target,
                            }
                        )
                    continue
                if len(keys) >= max_nodes:
                    truncated, reason = True, "max_nodes"
                    break
                if len(edges) + len(semantic_edges) >= max_nodes:
                    truncated, reason = True, "max_edges"
                    break
                visited.add(neighbor)
                keys.append(neighbor)
                queue.append((neighbor, depth + 1))
                predecessors[neighbor] = current
                if isinstance(relationship, SemanticEdge):
                    semantic_edges.append(self._semantic_edge_data(relationship))
                else:
                    edges.append(
                        {
                            "kind": relationship.kind,
                            "source": relationship.source,
                            "target": relationship.target,
                        }
                    )
            if truncated:
                break
        unresolved_relationships: list[dict[str, str]] = []
        unresolved_truncated = False
        for key, code in self.view.snapshot.graph.unresolved:
            if key not in visited:
                continue
            if len(unresolved_relationships) >= max_nodes:
                unresolved_truncated = True
                break
            unresolved_relationships.append({"project_node_id": key, "code": code})
        boundary_truncated = self._append_trace_boundaries(keys, max_nodes)
        technology_paths, paths_truncated = self._technology_paths(
            node, keys, predecessors, max_nodes, direction
        )
        return {
            "start": self._summary(node),
            "direction": direction,
            "nodes": [self._summary(self._nodes[key]) for key in keys],
            "edges": edges,
            "semantic_edges": semantic_edges,
            "technology_paths": technology_paths,
            # A raw traversal limit can hide a semantic edge or a projected
            # technology path, so semantic output must not claim completeness.
            "semantic_truncated": truncated or boundary_truncated or paths_truncated,
            "truncated": truncated,
            "truncation_reason": reason,
            "unresolved_relationships": unresolved_relationships,
            "unresolved_truncated": unresolved_truncated,
        }
