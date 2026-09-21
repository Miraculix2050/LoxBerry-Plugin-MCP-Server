"""Deterministic graph of observed C/Co/In project relationships."""

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .decoder import decode_loxcc
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .parser import ParsedProject, parse_project
from .semantics import KnxSemantics, classify_knx, signal_use_rules

_DIAGNOSTIC_GROUP_LIMIT = 2048
_DIAGNOSTIC_SAMPLE_LIMIT = 3
_DIAGNOSTIC_LABEL_LIMIT = 100
_KNOWN_KNX_ATTRIBUTES = frozenset({"Type", "U", "Title", "Desc", "IName", "EibAddr", "EIBType"})
_KNX_MARKER_ATTRIBUTES = frozenset({"EibAddr", "EIBType"})


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
class ProjectSourceDiagnostic:
    """A bounded, value-free project-source diagnostic group."""

    code: str
    count: int
    source_type: str | None
    attribute_name: str | None
    value_shape: str | None
    length_bucket: str | None
    sample_node_ids: tuple[str, ...]
    sample_omitted: int


@dataclass(frozen=True, slots=True)
class ProjectSourceDiagnostics:
    entries: tuple[ProjectSourceDiagnostic, ...]
    complete: bool
    groups_omitted: int
    labels_truncated: bool = False
    parser_codes_by_node: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(slots=True)
class _DiagnosticAccumulator:
    count: int = 0
    samples: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    fingerprint: str
    model_version: int
    projects: tuple[ProjectPartSummary, ...] = field(repr=False)
    graph: ProjectGraph = field(repr=False)
    source_diagnostics: ProjectSourceDiagnostics = field(
        default_factory=lambda: ProjectSourceDiagnostics((), True, 0), repr=False
    )


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


def _value_shape(value: str) -> tuple[str, str]:
    if not value:
        return "empty", "0"
    if value.isdecimal() or (value.startswith(("+", "-")) and value[1:].isdecimal()):
        shape = "integer"
    else:
        try:
            float(value)
            shape = "decimal"
        except ValueError:
            shape = "text"
    length = len(value)
    bucket = (
        "1-16"
        if length <= 16
        else "17-64"
        if length <= 64
        else "65-200"
        if length <= 200
        else ">200"
    )
    return shape, bucket


def _diagnostic_label(value: str | None) -> tuple[str | None, bool]:
    if value is None or len(value) <= _DIAGNOSTIC_LABEL_LIMIT:
        return value, False
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return value[:80] + "…#" + digest, True


def _source_diagnostics(
    graph: ProjectGraph, anomalies: tuple[tuple[str, int | None, str], ...]
) -> ProjectSourceDiagnostics:
    """Summarize unsupported source forms without retaining their values."""

    groups: dict[
        tuple[str, str | None, str | None, str | None, str | None], _DiagnosticAccumulator
    ] = {}
    overflow_groups: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    labels_truncated = False

    def add(
        code: str,
        node: GraphNode | None,
        attribute_name: str | None = None,
        value: str | None = None,
    ) -> None:
        nonlocal labels_truncated
        source_type, source_type_truncated = _diagnostic_label(node.block_type if node else None)
        attribute_name, attribute_truncated = _diagnostic_label(attribute_name)
        labels_truncated = labels_truncated or source_type_truncated or attribute_truncated
        shape, bucket = _value_shape(value) if value is not None else (None, None)
        key = (code, source_type, attribute_name, shape, bucket)
        group = groups.get(key)
        if group is None:
            if len(groups) >= _DIAGNOSTIC_GROUP_LIMIT:
                overflow_groups.add(key)
                return
            group = _DiagnosticAccumulator()
            groups[key] = group
        group.count += 1
        if node is not None and len(group.samples) < _DIAGNOSTIC_SAMPLE_LIMIT:
            group.samples.append(node.key)

    nodes = graph.nodes
    by_part_index = {(node.project, node.source_index): node for node in nodes}
    parser_codes_by_node: dict[str, list[str]] = defaultdict(list)
    for namespace, index, code in anomalies:
        node = by_part_index.get((namespace, index)) if index is not None else None
        if node is not None:
            parser_codes_by_node[node.key].append(f"parser_{code}")
        add(f"parser_{code}", node)

    for node in nodes:
        if node.knx is None and any(key in _KNX_MARKER_ATTRIBUTES for key, _ in node.attributes):
            add("unclassified_knx_candidate", node)
        if node.knx is None:
            continue
        knx = node.knx
        if knx.object_kind == "endpoint":
            if knx.group_address is None:
                add("missing_group_address", node)
            elif knx.group_address.canonical is None:
                add("invalid_group_address", node)
            if knx.datatype is None:
                add("missing_raw_datatype", node)
        for key, value in node.attributes:
            if key not in _KNOWN_KNX_ATTRIBUTES:
                add("unmodeled_knx_attribute", node, key, value)

    children: dict[str, list[GraphNode]] = defaultdict(list)
    by_key = {node.key: node for node in nodes}
    for edge in graph.edges:
        if edge.kind == "contains" and edge.source in by_key and edge.target in by_key:
            children[edge.source].append(by_key[edge.target])
    for node in nodes:
        logic_knx = node.knx
        if logic_knx is None or logic_knx.object_kind != "logic_block":
            continue
        rules = signal_use_rules(node.block_type)
        if not rules:
            add("unreviewed_knx_logic", node)
            continue
        connectors: dict[str, int] = defaultdict(int)
        for child in children[node.key]:
            connector_key: str | None = next(
                (value for name, value in child.attributes if name == "K"), None
            )
            if connector_key is not None:
                connectors[connector_key] += 1
        reviewed = {rule.input_key for rule in rules} | {rule.output_key for rule in rules}
        for key in sorted(connectors):
            if key not in reviewed:
                add("unreviewed_knx_connector", node, key)
        for rule in rules:
            if connectors[rule.input_key] != 1 or connectors[rule.output_key] != 1:
                add("incomplete_knx_signal_rule", node, rule.rule_id)
    entries: list[ProjectSourceDiagnostic] = []
    for group_key, accumulator in sorted(
        groups.items(), key=lambda item: tuple(value or "" for value in item[0])
    ):
        code, source_type, attribute_name, shape, bucket = group_key
        count = accumulator.count
        samples = tuple(sorted(accumulator.samples))
        entries.append(
            ProjectSourceDiagnostic(
                code,
                count,
                source_type,
                attribute_name,
                shape,
                bucket,
                samples,
                count - len(samples),
            )
        )
    return ProjectSourceDiagnostics(
        tuple(entries),
        not overflow_groups,
        len(overflow_groups),
        labels_truncated,
        tuple(
            (key, tuple(sorted(set(codes)))) for key, codes in sorted(parser_codes_by_node.items())
        ),
    )


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
    anomalies: list[tuple[str, int | None, str]] = []
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
        for index, code in project.anomalies:
            context: int | None = index
            while context is not None and project.elements[context].tag not in {"C", "Co"}:
                context = project.elements[context].parent
            anomalies.append((namespace, context, code))
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
    return ProjectSnapshot(
        bundle.fingerprint,
        4,
        tuple(projects),
        graph,
        _source_diagnostics(graph, tuple(anomalies)),
    )
