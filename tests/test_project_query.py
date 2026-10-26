from dataclasses import replace
from types import SimpleNamespace

import pytest

from mcpserver.loxone.project.graph import (
    GraphEdge,
    ProjectPartSummary,
    ProjectSnapshot,
    ProjectSourceDiagnostic,
    ProjectSourceDiagnostics,
    _logical_knx_nodes,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError


def control(uuid, action=None, children=()):
    return SimpleNamespace(uuid=uuid, action_uuid=action, subcontrols=children)


def query(*, shared_mapping: bool = False) -> ProjectQuery:
    source, target, source_connector = "a" * 32, "b" * 32, "c" * 32
    parsed = parse_project(
        (
            f'<P><C Type="Source" U="{source}"><Co K="AQ" U="{source_connector}"/></C>'
            f'<C Type="Target" U="{target}"><Co K="AI" U="d">'
            f'<In Input="{source_connector}"/></Co></C>'
            '<C Type="Unknown" U="e"/></P>'
        ).encode()
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 8, ()),), build_graph((("p", parsed),))
    )
    controls = (
        (control("first", target), control("second", target))
        if shared_mapping
        else (control(target),)
    )
    structure = SimpleNamespace(last_modified="v1", controls=controls)
    return ProjectQuery(
        ProjectView(snapshot, map_runtime(snapshot, structure)), {target: "Living room"}
    )


def test_find_status_and_describe_are_deterministic_and_bounded():
    project = query()
    assert project.status()["mapping"] == {"exact": 1, "ambiguous": 0, "unmapped": 0}
    found = project.find(
        query="living", kind=None, block_type=None, source_id=None, runtime_control_uuid=None
    )
    assert len(found) == 1
    assert found[0]["block_type"] == "Target"
    described = project.describe(project.resolve("p:4", "project_node_id"), limit=1)
    assert described["connector_key"] == "AI"
    assert described["relationships"][0]["kind"] == "signal"
    assert described["truncated_fields"] == []
    assert (
        project.find(
            query=None,
            kind="block",
            block_type="Unknown",
            source_id=None,
            runtime_control_uuid=None,
        )[0]["block_type"]
        == "Unknown"
    )


@pytest.mark.parametrize("text", [None, "", " ", "LiViNg", "no-match", "AQ", "Target"])
def test_find_projects_only_matched_nodes(monkeypatch, text):
    project = query()
    projected = []
    original = ProjectQuery._summary

    def summary(self, node, **kwargs):
        projected.append(node.key)
        return original(self, node, **kwargs)

    monkeypatch.setattr(ProjectQuery, "_summary", summary)
    found = project.find(
        query=text, kind=None, block_type=None, source_id=None, runtime_control_uuid=None
    )
    assert projected == [item["project_node_id"] for item in found]
    if text == "no-match":
        assert not found
    if text == "LiViNg":
        assert len(found) == 1 and found[0]["runtime_control"]["name"] == "Living room"


def test_find_does_not_search_names_from_multiple_exact_mappings():
    project = query(shared_mapping=True)
    project.control_names.update({"first": "private-name", "second": "private-name"})
    assert not project.find(
        query="private-name", kind=None, block_type=None, source_id=None, runtime_control_uuid=None
    )


def test_indexed_describe_and_trace_do_not_iterate_full_edge_table():
    project = query()

    class IndexedEdges(tuple):
        forbid_iteration = False

        def __iter__(self):
            assert not self.forbid_iteration, "query scanned the entire edge table"
            return super().__iter__()

    edges = IndexedEdges(project.view.snapshot.graph.edges)
    graph = replace(project.view.snapshot.graph, edges=edges)
    snapshot = replace(project.view.snapshot, graph=graph)
    indexed = ProjectQuery(replace(project.view, snapshot=snapshot), project.control_names)
    source = indexed.resolve("p:1", "project_node_id")
    expected_description = indexed.describe(source, limit=1)
    expected_trace = indexed.trace(source, direction="downstream", max_depth=2, max_nodes=20)
    edges.forbid_iteration = True
    assert indexed.describe(source, limit=1) == expected_description
    assert (
        indexed.trace(source, direction="downstream", max_depth=2, max_nodes=20) == expected_trace
    )
    with pytest.raises(TypeError):
        indexed.graph_index.outgoing[source.key] = ()


def test_indexed_description_preserves_duplicate_edges_and_limit_flag():
    project = query()
    graph = project.view.snapshot.graph
    signal = next(edge for edge in graph.edges if edge.kind == "signal")
    snapshot = replace(project.view.snapshot, graph=replace(graph, edges=(*graph.edges, signal)))
    indexed = ProjectQuery(replace(project.view, snapshot=snapshot), project.control_names)
    node = indexed.resolve(signal.source, "project_node_id")
    full = indexed.describe(node, limit=100)
    assert full["relationships"][0] == full["relationships"][-1]
    limited = indexed.describe(node, limit=1)
    assert limited["relationships"] == full["relationships"][:1]
    assert "relationships" in limited["truncated_fields"]


def test_find_projects_logical_knx_objects_with_source_provenance():
    parsed = parse_project(b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"/></P>')
    graph = build_graph((("one", parsed), ("two", parsed)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        5,
        (ProjectPartSummary("one", 2, ()), ProjectPartSummary("two", 2, ())),
        graph,
        ProjectSourceDiagnostics((), True, 0),
        aliases,
        source_ids,
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    found = project.find(
        query=None,
        kind="block",
        block_type="EIBactor",
        source_id=None,
        runtime_control_uuid=None,
        technology="knx_eib",
    )

    assert len(found) == 1
    assert found[0]["source_occurrence_count"] == 2
    assert found[0]["model_source_ids"] == ["one", "two"]
    status = project.status()
    assert status["project_parts"] == 2
    assert status["model_sources"] == [
        {"model_source_id": "one", "element_count": 2},
        {"model_source_id": "two", "element_count": 2},
    ]


def test_describe_preserves_a_raw_occurrence_id_for_its_diagnostics():
    first = parse_project(b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"/></P>')
    second = parse_project(
        b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3" Extra="source-only"/></P>'
    )
    graph = build_graph((("one", first), ("two", second)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        5,
        (ProjectPartSummary("one", 2, ()), ProjectPartSummary("two", 2, ())),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    described = project.describe(project.resolve("two:1", "project_node_id"), limit=10)

    assert described["project_node_id"] == "two:1"
    assert "unmodeled_knx_attribute" in {item["code"] for item in described["source_diagnostics"]}


def test_observable_controls_keep_only_exact_runtime_mappings():
    project = query()

    result = project.observable_controls(
        project.resolve("p:4", "project_node_id"),
        direction="both",
        max_depth=6,
        max_nodes=100,
    )

    assert result["target"]["project_node_id"] == "p:4"
    assert result["controls"] == [
        {
            "control_uuid": "b" * 32,
            "project_node_ids": ["p:3"],
            "directions": ["upstream", "downstream"],
        }
    ]
    assert result["truncated"] is False


def test_observable_controls_include_all_exact_shared_mappings():
    project = query(shared_mapping=True)

    result = project.observable_controls(
        project.resolve("first", "runtime_control_uuid"),
        direction="both",
        max_depth=6,
        max_nodes=100,
    )

    assert result["controls"] == [
        {
            "control_uuid": "first",
            "project_node_ids": ["p:3"],
            "directions": ["upstream", "downstream"],
        },
        {
            "control_uuid": "second",
            "project_node_ids": ["p:3"],
            "directions": ["upstream", "downstream"],
        },
    ]
    assert result["mapping_coverage"]["exact_runtime_controls"] == 2


def test_observable_controls_preserve_semantic_truncation_and_deduplicate_unresolved(
    monkeypatch,
):
    project = query()
    mapped = project.resolve("p:3", "project_node_id")

    def semantic_boundary_trace(self, _node, *, direction, max_depth, max_nodes):
        return {
            "nodes": [self._summary(mapped)],
            "truncated": False,
            "semantic_truncated": True,
            "truncation_reason": None,
            "unresolved_relationships": [
                {"project_node_id": "p:1", "code": "unresolved_signal"},
                {"project_node_id": "p:1", "code": "unresolved_signal"},
            ],
            "unresolved_truncated": False,
        }

    monkeypatch.setattr(ProjectQuery, "trace", semantic_boundary_trace)

    result = project.observable_controls(
        project.resolve("p:4", "project_node_id"),
        direction="both",
        max_depth=6,
        max_nodes=100,
    )

    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["semantic_incomplete"]
    assert result["unresolved_relationships"] == 2
    assert result["mapping_coverage"]["complete"] is False
    assert result["mapping_coverage"]["truncated"] is True


@pytest.mark.parametrize(
    ("runtime_controls", "ambiguous", "unmapped", "exact"),
    [
        ((control("a" * 32), control("b" * 32)), 0, 0, 2),
        ((control("b" * 32),), 0, 1, 1),
        ((control("a" * 32, "b" * 32),), 2, 0, 0),
        ((control("shared", "a" * 32), control("a" * 32, "b" * 32)), 2, 0, 1),
        ((), 0, 2, 0),
    ],
)
def test_observability_mapping_coverage_is_target_local(
    runtime_controls, ambiguous, unmapped, exact
):
    project = query()
    structure = SimpleNamespace(last_modified="coverage", controls=runtime_controls)
    project = ProjectQuery(
        replace(project.view, mapping=map_runtime(project.view.snapshot, structure)), {}
    )
    result = project.observable_controls(
        project.resolve("p:4", "project_node_id"), direction="both", max_depth=6, max_nodes=100
    )
    # The disconnected Unknown block and the connectors are not mapping gaps.
    assert result["mapping_coverage"] == {
        "exact_runtime_controls": exact,
        "ambiguous_project_objects": ambiguous,
        "unmapped_project_objects": unmapped,
        "complete": not (ambiguous or unmapped),
        "truncated": False,
    }
    assert len(result["controls"]) == exact


@pytest.mark.parametrize(
    ("reason", "semantic", "unresolved", "unresolved_truncated", "complete", "truncated"),
    [
        (None, False, [], False, True, False),
        ("max_nodes", False, [], False, False, True),
        ("max_edges", False, [], False, False, True),
        ("max_depth", False, [], False, False, True),
        (None, True, [], False, False, True),
        (
            None,
            False,
            [{"project_node_id": "p:3", "code": "unresolved_signal"}],
            False,
            False,
            False,
        ),
        (None, False, [], True, False, True),
    ],
)
def test_observability_mapping_coverage_preserves_trace_limits(
    monkeypatch, reason, semantic, unresolved, unresolved_truncated, complete, truncated
):
    project = query()
    mapped = project.resolve("p:3", "project_node_id")

    def bounded_trace(self, _node, **_kwargs):
        return {
            "nodes": [self._summary(mapped)],
            "truncated": reason is not None,
            "semantic_truncated": semantic,
            "truncation_reason": reason,
            "unresolved_relationships": unresolved,
            "unresolved_truncated": unresolved_truncated,
        }

    monkeypatch.setattr(ProjectQuery, "trace", bounded_trace)
    result = project.observable_controls(mapped, direction="both", max_depth=6, max_nodes=100)
    assert result["mapping_coverage"] == {
        "exact_runtime_controls": 1,
        "ambiguous_project_objects": 0,
        "unmapped_project_objects": 0,
        "complete": complete,
        "truncated": truncated,
    }


def test_observability_mapping_coverage_deduplicates_canonical_source_occurrences(monkeypatch):
    parsed = parse_project(b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"/></P>')
    graph = build_graph((("one", parsed), ("two", parsed)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project", 1, (), graph, logical_aliases=aliases, logical_source_ids=source_ids
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    def source_trace(self, _node, *, direction, **_kwargs):
        source = "one" if direction == "upstream" else "two"
        return {
            "nodes": [
                self._summary(self.resolve(f"{source}:{index}", "project_node_id"))
                for index in (1,)
            ],
            "truncated": False,
            "truncation_reason": None,
            "unresolved_relationships": [],
            "unresolved_truncated": False,
        }

    monkeypatch.setattr(ProjectQuery, "trace", source_trace)
    result = project.observable_controls(
        project.resolve("one:1", "project_node_id"), direction="both", max_depth=6, max_nodes=100
    )
    assert result["mapping_coverage"]["unmapped_project_objects"] == 1


@pytest.mark.parametrize(
    ("edges", "max_depth", "max_nodes", "reason", "unmapped"),
    [
        (((1, 2), (2, 3)), 6, 2, "max_nodes", 1),
        (((1, 1), (1, 1), (1, 2)), 6, 2, "max_edges", 0),
        (((1, 2), (2, 3)), 1, 100, "max_depth", 1),
    ],
)
def test_observability_mapping_coverage_counts_only_the_truncated_traversal(
    edges, max_depth, max_nodes, reason, unmapped
):
    uuid = "a" * 32
    parsed = parse_project(f'<P><C U="{uuid}"/><C U="unmapped"/><C U="outside"/></P>'.encode())
    graph = replace(
        build_graph((("p", parsed),)),
        edges=tuple(GraphEdge(f"p:{source}", f"p:{target}", "signal") for source, target in edges),
    )
    snapshot = ProjectSnapshot("project", 1, (), graph)
    project = ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=(control(uuid),))),
        ),
        {},
    )
    result = project.observable_controls(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    assert result["truncation_reasons"] == [reason]
    assert result["mapping_coverage"] == {
        "exact_runtime_controls": 1,
        "ambiguous_project_objects": 0,
        "unmapped_project_objects": unmapped,
        "complete": False,
        "truncated": True,
    }


@pytest.mark.parametrize("diagnostics_truncated", [False, True])
def test_observability_mapping_coverage_checks_unresolved_appended_boundaries(
    diagnostics_truncated,
):
    uuid = "a" * 32
    parsed = parse_project(f'<P><C U="{uuid}" Ref="missing"><Co U="connector"/></C></P>'.encode())
    graph = build_graph((("p", parsed),))
    if diagnostics_truncated:
        graph = replace(graph, unresolved=graph.unresolved * 3)
    snapshot = ProjectSnapshot("project", 1, (), graph)
    project = ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=(control(uuid),))),
        ),
        {},
    )
    node = project.resolve("p:2", "project_node_id")
    trace = project.trace(node, direction="upstream", max_depth=6, max_nodes=2)
    assert {item["project_node_id"] for item in trace["nodes"]} == {"p:1", "p:2"}
    assert trace["unresolved_relationships"]
    assert trace["unresolved_truncated"] is diagnostics_truncated
    result = project.observable_controls(node, direction="both", max_depth=6, max_nodes=2)
    assert result["mapping_coverage"] == {
        "exact_runtime_controls": 1,
        "ambiguous_project_objects": 0,
        "unmapped_project_objects": 0,
        "complete": False,
        "truncated": diagnostics_truncated,
    }


def test_source_diagnostics_are_available_without_unknown_values():
    parsed = parse_project(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="invalid" Extra="secret"/></P>'
    )
    snapshot = ProjectSnapshot(
        "project",
        4,
        (ProjectPartSummary("p", 2, ()),),
        build_graph((("p", parsed),)),
        ProjectSourceDiagnostics(
            (
                ProjectSourceDiagnostic(
                    "unmodeled_knx_attribute", 1, "EIBsensor", "Extra", "text", "1-16", ("p:1",), 0
                ),
            ),
            True,
            0,
        ),
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    assert project.status()["source_diagnostics"]["entries"] == [
        {"code": "unmodeled_knx_attribute", "count": 1}
    ]
    described = project.describe(project.resolve("p:1", "project_node_id"), limit=10)
    unknown = next(
        item
        for item in described["source_diagnostics"]
        if item["code"] == "unmodeled_knx_attribute"
    )
    assert unknown["attribute_name"] == "Extra"
    assert "secret" not in repr(described["source_diagnostics"])


def test_describe_reports_incomplete_rules_and_diagnostic_truncation():
    attributes = " ".join(f'Extra{index}="x"' for index in range(51))
    parsed = parse_project(
        f'<P><C Type="EIBPush" U="push" {attributes}><Co K="Tg" U="trigger"/></C></P>'.encode()
    )
    snapshot = ProjectSnapshot(
        "project", 4, (ProjectPartSummary("p", 3, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    described = project.describe(project.resolve("p:1", "project_node_id"), limit=10)

    assert any(
        item["code"] == "incomplete_knx_signal_rule" for item in described["source_diagnostics"]
    )
    assert described["source_diagnostics_truncated"] is True
    assert described["source_diagnostics_omitted"] >= 1


def test_trace_excludes_containment_and_reports_limits():
    project = query()
    complete = project.trace(
        project.resolve("b" * 32, "runtime_control_uuid"),
        direction="upstream",
        max_depth=1,
        max_nodes=10,
    )
    assert complete["truncated"] is False
    assert len(complete["edges"]) == 1
    result = project.trace(
        project.resolve("b" * 32, "runtime_control_uuid"),
        direction="upstream",
        max_depth=1,
        max_nodes=1,
    )
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_nodes"
    assert all(edge["kind"] in {"signal", "reference"} for edge in result["edges"])


def test_trace_stops_containment_seeding_at_node_limit():
    parsed = parse_project(b'<P><C U="root"><Co U="one"/><Co U="two"/></C></P>')
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 4, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=1,
        max_nodes=1,
    )

    assert [item["project_node_id"] for item in result["nodes"]] == ["p:1"]
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_nodes"


def test_trace_caps_unresolved_relationships():
    parsed = parse_project(
        b'<P><C U="root"><Co U="connector"><In Input="missing-one"/>'
        b'<In Input="missing-two"/></Co></C></P>'
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 5, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:2", "project_node_id"),
        direction="upstream",
        max_depth=1,
        max_nodes=1,
    )

    assert len(result["unresolved_relationships"]) == 1
    assert result["unresolved_truncated"] is True


def test_ambiguous_runtime_mapping_is_never_guessed():
    project = query()
    with pytest.raises(ProjectQueryError, match="project_node_unknown"):
        project.resolve("missing", "runtime_control_uuid")


def test_describe_caps_each_relationship_collection():
    parsed = parse_project(b'<P><C U="root"><Co U="one"/><Co U="two"/></C></P>')
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 4, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.describe(project.resolve("p:1", "project_node_id"), limit=1)

    assert result["child_project_node_ids"] == ["p:2"]
    assert result["truncated_fields"] == ["child_project_node_ids"]


def test_trace_keeps_converging_edges_without_unbounded_edge_output():
    parsed = parse_project(
        b'<P><C U="a"><Co U="a1"/></C><C U="b"><Co U="b1"><In Input="a1"/>'
        b'</Co></C><C U="c"><Co U="c1"><In Input="a1"/></Co></C><C U="d">'
        b'<Co U="d1"><In Input="b1"/><In Input="c1"/></Co></C></P>'
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 12, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:1", "project_node_id"), direction="downstream", max_depth=3, max_nodes=10
    )

    assert len(result["edges"]) == 4
    assert result["truncated"] is False


def test_shared_topology_keeps_visible_mappings_and_names_separate():
    first = query()
    snapshot = first.view.snapshot
    other_structure = SimpleNamespace(last_modified="v2", controls=())
    second = ProjectQuery(
        ProjectView(snapshot, map_runtime(snapshot, other_structure)),
        {},
        graph_index=first.graph_index,
    )
    assert second.graph_index is first.graph_index
    arguments = dict(
        query="living", kind=None, block_type=None, source_id=None, runtime_control_uuid=None
    )
    assert first.find(**arguments)
    assert second.find(**arguments) == []
    with pytest.raises(ProjectQueryError, match="project_node_unknown"):
        second.resolve("b" * 32, "runtime_control_uuid")
    assert first.resolve("b" * 32, "runtime_control_uuid")
    first.control_names.clear()
    assert second.control_names == {}


def test_shared_index_is_immutable_and_leaf_reads_do_not_grow_it():
    project = query()
    index = project.graph_index
    assert index is not None and index.container_bytes > 0
    before = dict(index.children)
    with pytest.raises(KeyError):
        index.children["missing"]
    assert dict(index.children) == before
    with pytest.raises(TypeError):
        index.nodes["injected"] = next(iter(index.nodes.values()))
    with pytest.raises(TypeError):
        index.parents["injected"] = "parent"
    with pytest.raises(AttributeError):
        next(iter(index.children.values())).append("injected")
    for node in project.view.snapshot.graph.nodes:
        project.describe(node, limit=3)
        project.trace(node, direction="downstream", max_depth=1, max_nodes=3)
    assert dict(index.children) == before


def test_equal_but_distinct_graph_cannot_borrow_index():
    project = query()
    graph = replace(project.view.snapshot.graph)
    assert graph == project.view.snapshot.graph and graph is not project.view.snapshot.graph
    view = replace(project.view, snapshot=replace(project.view.snapshot, graph=graph))
    with pytest.raises(ProjectQueryError, match="project_index_mismatch"):
        ProjectQuery(view, {}, graph_index=project.graph_index)


def test_repeated_containment_preserves_ambiguity_order_and_last_parent():
    from mcpserver.loxone.project.graph import GraphEdge
    from mcpserver.loxone.project.query import ProjectQueryIndex

    project = query()
    graph = project.view.snapshot.graph
    edge = next(edge for edge in graph.edges if edge.kind == "contains")
    other_parent = next(node.key for node in graph.nodes if node.key != edge.source)
    extra = (GraphEdge(other_parent, edge.target, "contains"),) * 1000
    index = ProjectQueryIndex(replace(graph, edges=graph.edges + extra))
    parents = index.containment_parents[edge.target]
    assert parents[0] == edge.source and parents[-1000:] == (other_parent,) * 1000
    assert index.parents[edge.target] == other_parent
    assert index.children[other_parent].count(edge.target) >= 1000
    assert isinstance(parents, tuple)
