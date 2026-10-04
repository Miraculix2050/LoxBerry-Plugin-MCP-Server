from types import SimpleNamespace

import pytest

from mcpserver.loxone.opening_contacts import OpeningGraph
from mcpserver.loxone.project.graph import ProjectSnapshot, build_graph, is_api_connector
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.tools import ProjectDescriptionData, ProjectTraceData


def query(source_key="OutputAPI", target_key="API", extra="", source_type="State", source_attrs=""):
    data = (
        f'<P><C Type="{source_type}" U="{"a" * 32}" {source_attrs}>'
        f'<Co K="{source_key}" U="out"/></C>'
        f'<C Type="StatusMonitor" U="{"b" * 32}"><Co K="{target_key}" U="in">'
        f'<In Input="out"/>{extra}</Co></C></P>'
    ).encode()
    graph = build_graph((("synthetic", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    structure = SimpleNamespace(
        last_modified="v1",
        controls=(SimpleNamespace(uuid="b" * 32, action_uuid=None, subcontrols=()),),
    )
    return ProjectQuery(
        ProjectView(snapshot, map_runtime(snapshot, structure)), {"b" * 32: "Visible"}
    )


def port(q, key):
    return next(n for n in q.view.snapshot.graph.nodes if dict(n.attributes).get("K") == key)


@pytest.mark.parametrize("direction,key", [("downstream", "OutputAPI"), ("upstream", "API")])
def test_api_trace_exposes_block_communication_dependency_without_scalar_semantics(direction, key):
    q = query()
    result = q.trace(port(q, key), direction=direction, max_depth=4, max_nodes=20)
    typed = ProjectTraceData.model_validate(result)
    assert len(typed.edges) == 1
    edge = typed.edges[0]
    assert edge.kind == "api_connection"
    assert edge.api_connection.semantics == "block_communication_dependency"
    assert (
        edge.api_connection.source_block_project_node_id
        != edge.api_connection.target_block_project_node_id
    )
    assert edge.api_connection.payload_semantics == "unknown"
    assert edge.api_connection.value_available is False
    assert typed.semantic_edges == []
    assert typed.technology_paths == []
    assert typed.semantic_gaps == []
    assert typed.truncated is False
    assert typed.start.api_connector.semantics == "connection_metadata_only"


def test_describe_block_lists_own_api_connections_with_limits():
    q = query(extra='<In Input="other"/>')
    block = next(n for n in q.view.snapshot.graph.nodes if n.block_type == "StatusMonitor")
    result = ProjectDescriptionData.model_validate(q.describe(block, limit=1))
    assert len(result.api_connections) == 1
    assert result.api_connections[0].kind == "api_connection"
    assert result.api_connections_truncated is False
    destination = port(q, "API")
    detail = q.describe(destination, limit=100)
    assert detail["unresolved_relationships"] == ["api_connection_unresolved"]
    assert detail["relationships"][0]["api_connection"]["target_block_project_node_id"] == block.key


@pytest.mark.parametrize(
    "source_key,target_key,kind",
    [
        ("AQ", "AI", "signal"),
        ("OutputAPI", "AI", "api_connection"),
        ("AQ", "API", "api_connection"),
        ("api", "InputAPI", "signal"),
    ],
)
def test_exact_api_port_keys_do_not_alias_other_names(source_key, target_key, kind):
    q = query(source_key, target_key)
    edges = [e for e in q.view.snapshot.graph.edges if e.kind != "contains"]
    assert [e.kind for e in edges] == [kind]


def test_api_links_are_not_opening_contact_signal_paths():
    q = query()
    result = OpeningGraph(q).trace([port(q, "OutputAPI").key], "downstream", 8, 50)
    assert result["edges"] == []
    assert result["complete"] is True


def test_api_links_cannot_prove_knx_technology_path():
    q = query(source_type="EIBsensor", source_attrs='EibAddr="1/2/3"')
    start = next(n for n in q.view.snapshot.graph.nodes if n.block_type == "EIBsensor")
    result = q.trace(start, direction="downstream", max_depth=8, max_nodes=50)
    assert any(e["kind"] == "api_connection" for e in result["edges"])
    assert result["technology_paths"] == []
    assert all(
        n.get("runtime_control") is None or n["runtime_control"]["name"] == "Visible"
        for n in result["nodes"]
    )


def test_unresolved_api_and_boundary_limit_remain_explicit():
    q = query(extra='<In Input="missing"/>')
    result = q.trace(port(q, "API"), direction="upstream", max_depth=1, max_nodes=2)
    assert result["unresolved_relationships"][0]["code"] == "api_connection_unresolved"
    assert result["semantic_truncated"] is True


def test_api_reference_retains_explicit_orientation():
    data = (
        b"<P>"
        b'<C Type="Unknown" U="source">'
        b'<Co K="OutputAPI" U="out"/>'
        b"</C>"
        b'<C Type="Unknown" U="target">'
        b'<Co K="API" U="in" Ref="out"/>'
        b"</C>"
        b"</P>"
    )
    graph = build_graph((("p", parse_project(data)),))
    edge = next(e for e in graph.edges if e.kind == "api_connection")
    assert graph.traverse(edge.source) == (edge.target,)
    assert graph.semantic_edges == ()


def test_malformed_duplicate_api_key_is_not_classified():
    graph = build_graph(
        (("p", parse_project(b'<P><C Type="Unknown"><Co K="API" K="AQ" U="out"/></C></P>')),)
    )
    assert not is_api_connector(next(n for n in graph.nodes if n.kind == "connector"))


def test_multiple_api_links_are_bounded_and_do_not_merge_source_occurrences():
    data = (
        b"<P>"
        b'<C Type="Unknown" U="one">'
        b'<Co K="OutputAPI" U="first"/>'
        b"</C>"
        b'<C Type="Unknown" U="two">'
        b'<Co K="OutputAPI" U="second"/>'
        b"</C>"
        b'<C Type="Unknown" U="sink">'
        b'<Co K="API" U="in">'
        b'<In Input="first"/>'
        b'<In Input="second"/>'
        b"</Co>"
        b"</C>"
        b"</P>"
    )
    graph = build_graph((("one", parse_project(data)), ("two", parse_project(data))))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    q = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )
    target = next(n for n in graph.nodes if n.project == "one" and n.source_id == "sink")
    result = q.describe(target, limit=1)
    assert result["api_connections_truncated"] is True
    assert len(result["api_connections"]) == 1
    assert all(e.source.split(":")[0] == e.target.split(":")[0] for e in graph.edges)
    assert sum(e.kind == "api_connection" for e in graph.edges) == 4


def test_duplicate_api_source_uuid_and_cycle_never_create_inferred_edges():
    data = (
        b"<P>"
        b'<C Type="Unknown">'
        b'<Co K="API" U="a">'
        b'<In Input="b"/>'
        b"</Co>"
        b'<Co K="OutputAPI" U="b">'
        b'<In Input="a"/>'
        b"</Co>"
        b"</C>"
        b"</P>"
    )
    graph = build_graph((("p", parse_project(data)),))
    q = ProjectQuery(
        ProjectView(
            ProjectSnapshot("synthetic", 12, (), graph),
            map_runtime(
                ProjectSnapshot("synthetic", 12, (), graph),
                SimpleNamespace(last_modified="v", controls=()),
            ),
        ),
        {},
    )
    result = q.trace(port(q, "API"), direction="downstream", max_depth=4, max_nodes=20)
    assert len(result["edges"]) == 2
    assert result["semantic_edges"] == []
    assert result["truncated"] is False
    duplicate = data.replace(b"</C>", b'<Co K="OutputAPI" U="b"/></C>')
    graph = build_graph((("p", parse_project(duplicate)),))
    assert any(code == "api_connection_unresolved" for _, code in graph.unresolved)


def test_trace_node_limit_exposes_api_truncation():
    q = query()
    result = q.trace(port(q, "OutputAPI"), direction="downstream", max_depth=4, max_nodes=1)
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_nodes"
    assert result["edges"] == []


def test_unresolved_api_neighbor_does_not_invalidate_reviewed_scalar_or_path():
    data = (
        b'<P><C Type="Or"><Co K="I1" U="i1"/><Co K="I2" U="i2"/><Co K="Q" U="q"/>'
        b'<Co K="OutputAPI" U="api"><In Input="missing"/></Co></C></P>'
    )
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    q = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )
    result = OpeningGraph(q).trace([port(q, "Q").key], "upstream", 8, 50)
    assert result["complete"] is True
    assert result["gaps"] == []


def test_api_neighbor_does_not_suppress_independent_knx_signal_path():
    data = (
        b'<P><C Type="EIBsensor" EibAddr="1/2/3" U="source">'
        b'<Co K="OutputAPI" U="api"/><Co K="Q" U="signal"/></C>'
        b'<C Type="Target" U="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">'
        b'<Co K="API" U="in"><In Input="api"/></Co>'
        b'<Co K="AI" U="value"><In Input="signal"/></Co></C></P>'
    )
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    structure = SimpleNamespace(
        last_modified="v",
        controls=(SimpleNamespace(uuid="b" * 32, action_uuid=None, subcontrols=()),),
    )
    q = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    start = next(n for n in graph.nodes if n.block_type == "EIBsensor")
    result = q.trace(start, direction="downstream", max_depth=8, max_nodes=50)
    assert len(result["technology_paths"]) == 1
    path = result["technology_paths"][0]
    assert path["classification"] == "knx_to_loxone"
    assert port(q, "OutputAPI").key not in path["evidence_project_node_ids"]
    assert port(q, "API").key not in path["evidence_project_node_ids"]


@pytest.mark.parametrize("sources", ["", '<Co K="AQ" U="source"/><Co K="AQ" U="source"/>'])
@pytest.mark.parametrize(
    "key,code",
    [
        ("API", "api_connection_unresolved"),
        ("OutputAPI", "api_connection_unresolved"),
        ("AI", "reference_unresolved"),
    ],
)
def test_unresolved_ref_keeps_exact_api_classification(sources, key, code):
    data = f'<P><C Type="Unknown">{sources}<Co K="{key}" U="target" Ref="source"/></C></P>'.encode()
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    q = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )
    target = port(q, key)
    assert q.describe(target, limit=100)["unresolved_relationships"] == [code]
    result = q.trace(target, direction="upstream", max_depth=4, max_nodes=20)
    assert result["unresolved_relationships"] == [{"project_node_id": target.key, "code": code}]
    assert result["edges"] == []


@pytest.mark.parametrize("api_first", [True, False])
def test_same_destination_preserves_scalar_alternative_regardless_of_api_order(api_first):
    api = '<Co K="OutputAPI" U="api"/>'
    signal = '<Co K="Q" U="signal"/>'
    ports = api + signal if api_first else signal + api
    data = (
        f'<P><C Type="EIBsensor" EibAddr="1/2/3" U="source">{ports}</C>'
        '<C Type="Target" U="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">'
        '<Co K="AI" U="value"><In Input="api"/><In Input="signal"/></Co></C></P>'
    ).encode()
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    structure = SimpleNamespace(
        last_modified="v",
        controls=(SimpleNamespace(uuid="b" * 32, action_uuid=None, subcontrols=()),),
    )
    q = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    start = next(n for n in graph.nodes if n.block_type == "EIBsensor")
    result = q.trace(start, direction="downstream", max_depth=8, max_nodes=50)
    assert {edge["kind"] for edge in result["edges"]} == {"signal", "api_connection"}
    assert len(result["technology_paths"]) == 1
    evidence = result["technology_paths"][0]["evidence_project_node_ids"]
    assert port(q, "Q").key in evidence
    assert port(q, "OutputAPI").key not in evidence


def test_signal_alternative_search_preserves_depth_bound_and_cycles():
    relationships = [
        {"source": "start", "target": "end", "kind": "api_connection"},
        {"source": "start", "target": "middle", "kind": "signal"},
        {"source": "middle", "target": "end", "kind": "reference"},
        {"source": "end", "target": "start", "kind": "signal"},
    ]
    limited, truncated = ProjectQuery._signal_predecessors(
        ["start"], relationships, "downstream", 1
    )
    assert truncated is True
    assert "end" not in limited
    complete, truncated = ProjectQuery._signal_predecessors(
        ["start"], relationships, "downstream", 2
    )
    assert truncated is False
    assert complete["end"] == "middle"


@pytest.mark.parametrize("relation", ["input", "ref"])
@pytest.mark.parametrize("mixed", [False, True])
def test_source_ambiguity_retains_api_category_only_for_exclusively_api_candidates(relation, mixed):
    second_key = "AQ" if mixed else "API"
    link = '<In Input="source"/>' if relation == "input" else ""
    ref = 'Ref="source"' if relation == "ref" else ""
    data = (
        '<P><C Type="Unknown"><Co K="OutputAPI" U="source"/>'
        f'<Co K="{second_key}" U="source"/></C>'
        f'<C Type="Unknown"><Co K="AI" U="destination" {ref}>{link}</Co></C></P>'
    ).encode()
    graph = build_graph((("p", parse_project(data)),))
    normal_code = "signal_unresolved" if relation == "input" else "reference_unresolved"
    assert graph.unresolved[0][1] == (normal_code if mixed else "api_connection_unresolved")
    assert not any(e.kind in {"signal", "reference", "api_connection"} for e in graph.edges)


@pytest.mark.parametrize("source_type", ["EIBsensor", "EIBactor"])
@pytest.mark.parametrize(
    "key,scalar_ambiguous", [("OutputAPI", False), ("API", False), ("AQ", True)]
)
def test_api_only_failure_does_not_change_knx_scalar_connectivity_or_hierarchy(
    source_type, key, scalar_ambiguous
):
    from mcpserver.loxone.project.analysis import analyze_knx

    data = (
        f'<P><C Type="{source_type}" U="endpoint" EibAddr="1/2/3">'
        f'<Co K="{key}" U="port"><In Input="missing"/></Co></C></P>'
    ).encode()
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    q = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )
    result = analyze_knx(q.view, frozenset({"project_connectivity", "address_hierarchy"}))
    connectivity = [f for f in result["findings"] if f["analysis"] == "project_connectivity"]
    assert len(connectivity) == 1
    expected = (
        "project_connectivity_ambiguous" if scalar_ambiguous else "no_project_signal_relationship"
    )
    assert connectivity[0]["finding_type"] == expected
    wiring = "unresolved" if scalar_ambiguous else "without_relationship"
    prefixes = [f for f in result["findings"] if f["finding_type"] == "address_prefix_summary"]
    assert all(f["hierarchy"]["direct_wiring"] == {wiring: 1} for f in prefixes)
    assert result["coverage"]["unresolved_relationships"] == 1


def test_unresolved_api_transport_does_not_invalidate_scalar_opening_trace():
    q = query(extra='<In Input="missing"/>')
    result = OpeningGraph(q).trace([port(q, "API").key], "upstream", 8, 50)
    assert result["complete"] is True
    assert result["gaps"] == []
    generic = q.trace(port(q, "API"), direction="upstream", max_depth=8, max_nodes=50)
    assert generic["unresolved_relationships"][0]["code"] == "api_connection_unresolved"


def test_modbus_scalar_consumer_evidence_ignores_api_only_failure():
    from mcpserver.loxone.project.modbus_analysis import analyze_modbus

    data = (
        b'<P><C Type="ModbusServer" U="server"><C Type="ModbusDev" U="device">'
        b'<C Type="ModbusASensor" U="sensor"><Co K="AQ" U="value"/>'
        b'<Co K="OutputAPI" U="api"><In Input="missing"/></Co></C></C></C></P>'
    )
    graph = build_graph((("p", parse_project(data)),))
    snapshot = ProjectSnapshot("synthetic", 12, (), graph)
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )
    result = analyze_modbus(view, frozenset({"direct_consumers"}))
    assert "endpoint_reference_unresolved" not in str(result)
    assert "unresolved_signal_source_not_attributable" not in str(result)
