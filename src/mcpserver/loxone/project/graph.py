"""Deterministic graph of observed C/Co/In project relationships."""

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .decoder import decode_loxcc
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .parser import ParsedProject, parse_project
from .semantics import KnxSemantics, classify_knx, signal_use_rules


def normalize_id(value: str | None) -> str:
    return (value or "").replace("-", "").lower()


@dataclass(frozen=True, slots=True)
class GraphNode:
    key: str
    project: str
    source_index: int
    kind: str
    source_id: str | None = field(repr=False)
    block_type: str | None = field(repr=False)
    attributes: tuple[tuple[str, str], ...] = field(repr=False)
    knx: KnxSemantics | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str


@dataclass(frozen=True, slots=True)
class SemanticEdge:
    """A reviewed, derived block-internal signal relationship.

    Unlike ``GraphEdge``, this is not raw project wiring. It is emitted only
    for an exact allowlisted block/connector rule and stays separate so MCP
    clients can distinguish source facts from derived semantics.
    """

    source: str
    target: str
    rule_id: str
    interpretation: str
    effect: str | None


@dataclass(frozen=True, slots=True)
class ProjectGraph:
    nodes: tuple[GraphNode, ...] = field(repr=False)
    edges: tuple[GraphEdge, ...] = field(repr=False)
    unresolved: tuple[tuple[str, str], ...]
    semantic_edges: tuple[SemanticEdge, ...] = field(default=(), repr=False)

    def traverse(
        self, start: str, *, upstream: bool = False, depth: int = 8, limit: int = 500
    ) -> tuple[str, ...]:
        if not 0 <= depth <= 64 or not 1 <= limit <= 5000:
            raise ProjectError("project_query_limit")
        if start not in {node.key for node in self.nodes}:
            raise ProjectError("project_node_unknown")
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            if edge.kind not in {"signal", "reference"}:
                continue
            source, target = (edge.target, edge.source) if upstream else (edge.source, edge.target)
            adjacency[source].append(target)
        visited = {start}
        result: list[str] = []
        queue = deque([(start, 0)])
        while queue and len(result) < limit:
            node, distance = queue.popleft()
            if distance >= depth:
                continue
            for neighbor in adjacency[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append(neighbor)
                    queue.append((neighbor, distance + 1))
                    if len(result) == limit:
                        break
        return tuple(result)


@dataclass(frozen=True, slots=True)
class ProjectPartSummary:
    namespace: str
    element_count: int
    anomaly_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    fingerprint: str
    model_version: int
    projects: tuple[ProjectPartSummary, ...] = field(repr=False)
    graph: ProjectGraph = field(repr=False)


def build_graph(
    projects: tuple[tuple[str, ParsedProject], ...], limits: ProjectLimits = DEFAULT_LIMITS
) -> ProjectGraph:
    nodes: list[GraphNode] = []
    edges: set[GraphEdge] = set()
    semantic_edges: set[SemanticEdge] = set()
    unresolved: list[tuple[str, str]] = []
    node: GraphNode | None
    for namespace, project in projects:
        local: dict[int, GraphNode] = {}
        by_id: dict[str, list[GraphNode]] = defaultdict(list)
        for index, element in enumerate(project.elements):
            if element.tag not in {"C", "Co"}:
                continue
            node = GraphNode(
                f"{namespace}:{index}",
                namespace,
                index,
                "connector" if element.tag == "Co" else "block",
                element.value("U"),
                element.value("Type"),
                element.attributes,
                classify_knx(element),
            )
            local[index] = node
            nodes.append(node)
            if len(nodes) > limits.elements:
                raise ProjectError("project_graph_limit")
            if node.source_id:
                by_id[normalize_id(node.source_id)].append(node)
        for index, element in enumerate(project.elements):
            node = local.get(index)
            if node is not None:
                ancestor = element.parent
                while ancestor is not None and ancestor not in local:
                    ancestor = project.elements[ancestor].parent
                if ancestor is not None:
                    edges.add(GraphEdge(local[ancestor].key, node.key, "contains"))
                reference = element.value("Ref")
                if reference:
                    candidates = by_id.get(normalize_id(reference), [])
                    if len(candidates) == 1:
                        edges.add(GraphEdge(candidates[0].key, node.key, "reference"))
                    else:
                        unresolved.append((node.key, "reference_unresolved"))
            if element.tag == "In" and element.parent in local:
                destination = local[element.parent]
                candidates = by_id.get(normalize_id(element.value("Input")), [])
                # Observed schema: Co(input) contains In(Input=source Co UUID).
                if len(candidates) == 1 and candidates[0].kind == destination.kind == "connector":
                    edges.add(GraphEdge(candidates[0].key, destination.key, "signal"))
                else:
                    unresolved.append((destination.key, "signal_unresolved"))
            if len(edges) > limits.edges:
                raise ProjectError("project_graph_limit")
        semantic_edges.update(_build_semantic_edges(project, local))
        if len(semantic_edges) > limits.edges:
            raise ProjectError("project_graph_limit")
    return ProjectGraph(
        tuple(nodes),
        tuple(sorted(edges, key=lambda e: (e.source, e.target, e.kind))),
        tuple(unresolved),
        tuple(sorted(semantic_edges, key=lambda e: (e.source, e.target, e.rule_id))),
    )


def _build_semantic_edges(project: ParsedProject, local: dict[int, GraphNode]) -> set[SemanticEdge]:
    """Build only explicit, allowlisted internal connector relationships."""

    result: set[SemanticEdge] = set()
    children: dict[int, list[int]] = defaultdict(list)
    for child_index, child in enumerate(project.elements):
        if child.parent is not None:
            children[child.parent].append(child_index)
    for index, element in enumerate(project.elements):
        if element.tag != "C":
            continue
        rules = signal_use_rules(element.value("Type"))
        if not rules:
            continue
        connectors: dict[str, list[GraphNode]] = defaultdict(list)
        for child_index in children.get(index, []):
            child = project.elements[child_index]
            if child.tag != "Co":
                continue
            connector = local.get(child_index)
            key = child.value("K")
            if connector is not None and key is not None:
                connectors[key].append(connector)
        for rule in rules:
            sources = connectors.get(rule.input_key, [])
            targets = connectors.get(rule.output_key, [])
            # Duplicated connector keys are not safely interpretable.
            if len(sources) != 1 or len(targets) != 1:
                continue
            source, target = sources[0], targets[0]
            result.add(
                SemanticEdge(
                    source.key,
                    target.key,
                    rule.rule_id,
                    rule.interpretation,
                    rule.effect,
                )
            )
    return result


def build_snapshot(
    bundle: ProjectBundle, limits: ProjectLimits = DEFAULT_LIMITS
) -> ProjectSnapshot:
    total_bytes = 0
    total_elements = 0
    total_attributes = 0
    projects: list[ProjectPartSummary] = []
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    semantic_edges: list[SemanticEdge] = []
    unresolved: list[tuple[str, str]] = []
    for member in bundle.files:
        data = decode_loxcc(member.content, limits)
        total_bytes += len(data)
        if total_bytes > limits.decoded_bytes:
            raise ProjectError("project_decoded_limit")
        project = parse_project(data, limits)
        total_elements += len(project.elements)
        total_attributes += sum(len(element.attributes) for element in project.elements)
        if total_elements > limits.elements or total_attributes > limits.attributes:
            raise ProjectError("project_parse_limit")
        namespace = hashlib.sha256(member.key.encode()).hexdigest()[:24]
        part_graph = build_graph(((namespace, project),), limits)
        nodes.extend(part_graph.nodes)
        edges.extend(part_graph.edges)
        semantic_edges.extend(part_graph.semantic_edges)
        unresolved.extend(part_graph.unresolved)
        if (
            len(nodes) > limits.elements
            or len(edges) > limits.edges
            or len(semantic_edges) > limits.edges
        ):
            raise ProjectError("project_graph_limit")
        projects.append(
            ProjectPartSummary(
                namespace,
                len(project.elements),
                tuple(code for _, code in project.anomalies),
            )
        )
    graph = ProjectGraph(tuple(nodes), tuple(edges), tuple(unresolved), tuple(semantic_edges))
    return ProjectSnapshot(bundle.fingerprint, 3, tuple(projects), graph)
