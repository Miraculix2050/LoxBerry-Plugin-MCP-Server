"""Bounded, evidence-based projection of immutable project graphs."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from .graph import GraphEdge, GraphNode
from .mapping import ControlMapping, ProjectView


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

    def _summary(self, node: GraphNode) -> dict[str, object]:
        mapping = self._mapped_nodes.get(node.key, [])
        exact = [item for item in mapping if item.status == "exact"]
        runtime_control = exact[0] if len(exact) == 1 else None
        connector_key = next((value for key, value in node.attributes if key == "K"), None)
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
        }

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
        }

    def find(
        self,
        *,
        query: str | None,
        kind: str | None,
        block_type: str | None,
        source_id: str | None,
        runtime_control_uuid: str | None,
    ) -> list[dict[str, object]]:
        if kind is not None and kind not in {"block", "connector"}:
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
            if candidates is not None and node.key not in candidates:
                continue
            if kind is not None and node.kind != kind:
                continue
            if block_type is not None and node.block_type != block_type:
                continue
            if source_id is not None and node.source_id != source_id:
                continue
            item = self._summary(node)
            if needle is not None:
                connector_key = next((value for key, value in node.attributes if key == "K"), None)
                searchable = (node.key, node.source_id, node.block_type, connector_key)
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
            **self._summary(node),
            "parent_project_node_id": contains_in[0] if len(contains_in) == 1 else None,
            "child_project_node_ids": child_ids[:limit],
            "relationships": direct[:limit],
            "unresolved_relationships": unresolved[:limit],
            "truncated_fields": truncated_fields,
        }

    def trace(
        self, node: GraphNode, *, direction: str, max_depth: int, max_nodes: int
    ) -> dict[str, object]:
        if (
            direction not in {"upstream", "downstream"}
            or not 1 <= max_depth <= 16
            or not 1 <= max_nodes <= 200
        ):
            raise ProjectQueryError("project_query_invalid")
        adjacency: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in self.view.snapshot.graph.edges:
            if edge.kind not in {"signal", "reference"}:
                continue
            key = edge.target if direction == "upstream" else edge.source
            adjacency[key].append(edge)
        children: dict[str, list[str]] = defaultdict(list)
        for edge in self.view.snapshot.graph.edges:
            if edge.kind == "contains":
                children[edge.source].append(edge.target)
        seeds = [node.key]
        seed_set = {node.key}
        pending = deque([node.key])
        seed_truncated = False
        while pending and not seed_truncated:
            current = pending.popleft()
            for child in children[current]:
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
        truncated = seed_truncated
        reason: str | None = "max_nodes" if seed_truncated else None
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                if adjacency[current]:
                    truncated, reason = True, "max_depth"
                continue
            for edge in adjacency[current]:
                neighbor = edge.source if direction == "upstream" else edge.target
                if neighbor in visited:
                    if len(edges) >= max_nodes:
                        truncated, reason = True, "max_edges"
                        break
                    edges.append({"kind": edge.kind, "source": edge.source, "target": edge.target})
                    continue
                if len(keys) >= max_nodes:
                    truncated, reason = True, "max_nodes"
                    break
                if len(edges) >= max_nodes:
                    truncated, reason = True, "max_edges"
                    break
                visited.add(neighbor)
                keys.append(neighbor)
                queue.append((neighbor, depth + 1))
                edges.append({"kind": edge.kind, "source": edge.source, "target": edge.target})
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
        return {
            "start": self._summary(node),
            "direction": direction,
            "nodes": [self._summary(self._nodes[key]) for key in keys],
            "edges": edges,
            "truncated": truncated,
            "truncation_reason": reason,
            "unresolved_relationships": unresolved_relationships,
            "unresolved_truncated": unresolved_truncated,
        }
