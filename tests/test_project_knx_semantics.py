from pathlib import Path
from types import SimpleNamespace

from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery


def _query(data: bytes, controls: tuple[SimpleNamespace, ...] = ()) -> ProjectQuery:
    snapshot = ProjectSnapshot(
        "project",
        2,
        (ProjectPartSummary("p", 1, ()),),
        build_graph((("p", parse_project(data)),)),
    )
    return ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=controls)),
        ),
        {},
    )


def test_knx_endpoints_keep_direction_source_data_and_bounded_address():
    project = _query(
        b'<P><C Type="EIBsensor" U="sensor" Title="Bus input" IName="input" EibAddr="14/1/5" '
        b'EIBType="5"/><C Type="EIBactor" U="actor" EibAddr="14/1/6"/></P>'
    )

    sensor = project.describe(project.resolve("p:1", "project_node_id"), limit=10)["knx"]
    actor = project.describe(project.resolve("p:2", "project_node_id"), limit=10)["knx"]

    assert sensor == {
        "object_kind": "endpoint",
        "flow_direction": "bus_to_loxone",
        "source_type": "EIBsensor",
        "title": "Bus input",
        "description": None,
        "internal_name": "input",
        "group_address": {
            "original": "14/1/5",
            "canonical": "14/1/5",
            "format": "three_level",
            "segments": [14, 1, 5],
        },
        "datatype": {
            "source_field": "EIBType",
            "source_value": "5",
            "system": "unknown",
            "normalized_code": None,
        },
        "truncated_fields": [],
        "usage_observations": [],
        "usage_observations_truncated": False,
    }
    assert actor["flow_direction"] == "loxone_to_bus"


def test_observed_knx_fixture_keeps_semantics_and_existing_graph_paths():
    project = _query(Path("tests/fixtures/project/observed-knx.xml").read_bytes())

    found = project.find(
        query=None,
        kind=None,
        block_type=None,
        source_id=None,
        runtime_control_uuid=None,
        technology="knx_eib",
        knx_object_kind="endpoint",
        knx_flow_direction=None,
        knx_group_address=None,
    )
    detailed = project.describe(project.resolve("p:2", "project_node_id"), limit=10)

    assert [item["knx"] for item in found] == [
        {
            "object_kind": "endpoint",
            "flow_direction": "bus_to_loxone",
            "source_type": "EIBsensor",
            "group_address": {"canonical": "14/1/5"},
        },
        {
            "object_kind": "endpoint",
            "flow_direction": "loxone_to_bus",
            "source_type": "EIBactor",
            "group_address": {"canonical": "14/1/6"},
        },
    ]
    assert detailed["knx"]["datatype"]["source_value"] == "5"
    assert project.trace(
        project.resolve("p:3", "project_node_id"), direction="downstream", max_depth=4, max_nodes=20
    )["edges"]


def test_knx_group_address_never_guesses_invalid_or_line_values():
    project = _query(
        b'<P><C Type="EIBline" U="line" EibAddr="1.1.250 14/"/>'
        b'<C Type="EIBsensor" U="bad" EibAddr="14/8/256"/>'
        b'<C Type="EIBactor" U="two" EibAddr="31/2047"/></P>'
    )

    line = project.describe(project.resolve("p:1", "project_node_id"), limit=10)["knx"]
    bad = project.describe(project.resolve("p:2", "project_node_id"), limit=10)["knx"]
    two = project.describe(project.resolve("p:3", "project_node_id"), limit=10)["knx"]

    assert line["group_address"] is None
    assert bad["group_address"] == {
        "original": "14/8/256",
        "canonical": None,
        "format": None,
        "segments": None,
    }
    assert two["group_address"]["format"] == "two_level"


def test_knx_truncated_group_address_is_not_normalized():
    project = _query(
        (f'<P><C Type="EIBsensor" U="sensor" EibAddr="{"1/2/3" + "x" * 200}"/></P>').encode()
    )

    knx = project.describe(project.resolve("p:1", "project_node_id"), limit=10)["knx"]

    assert knx["group_address"]["canonical"] is None
    assert knx["group_address"]["format"] is None
    assert knx["truncated_fields"] == ["group_address.original"]


def test_knx_unknown_and_caption_types_remain_generic_and_find_filters_are_exact():
    project = _query(
        b'<P><C Type="EIBsensorCaption" U="caption" Title="Sensors"/>'
        b'<C Type="EIBsensorNew" U="unknown" EibAddr="1/2/3"/>'
        b'<C Type="EIBsensor" U="known" Title="Kitchen" EibAddr="1/2/3"/></P>'
    )

    assert project.describe(project.resolve("p:1", "project_node_id"), limit=10)["knx"] is None
    assert project.describe(project.resolve("p:2", "project_node_id"), limit=10)["knx"] is None
    found = project.find(
        query="kitchen",
        kind=None,
        block_type=None,
        source_id=None,
        runtime_control_uuid=None,
        technology="knx_eib",
        knx_object_kind="endpoint",
        knx_flow_direction="bus_to_loxone",
        knx_group_address="1/2/3",
    )
    assert [item["project_node_id"] for item in found] == ["p:3"]


def test_knx_semantics_do_not_create_signal_edges_from_equal_group_addresses():
    project = parse_project(
        b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3"><Co U="ao"/></C>'
        b'<C Type="EIBactor" U="b" EibAddr="1/2/3"><Co U="bi"/></C></P>'
    )
    graph = build_graph((("p", project),))

    assert not [edge for edge in graph.edges if edge.kind == "signal"]
    assert graph.nodes[0].knx is not None
    assert graph.nodes[2].knx is not None


def test_knx_technology_paths_never_reverse_the_requested_trace_direction():
    project = _query(
        b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"><Co U="source"/></C>'
        b'<C Type="EIBsensor" U="sensor" EibAddr="1/2/4"><Co U="target">'
        b'<In Input="source"/></Co></C></P>'
    )

    traced = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=4,
        max_nodes=20,
    )

    assert traced["edges"] == [{"kind": "signal", "source": "p:2", "target": "p:4"}]
    assert traced["technology_paths"] == []


def test_knx_technology_paths_cover_exactly_mapped_loxone_endpoints():
    loxone_output = "a" * 32
    knx_to_loxone = _query(
        f'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
        f'<C Type="DigitalOutput" U="{loxone_output}"><Co U="target">'
        f'<In Input="source"/></Co></C></P>'.encode(),
        (SimpleNamespace(uuid=loxone_output, action_uuid=None, subcontrols=()),),
    )
    knx_path = knx_to_loxone.trace(
        knx_to_loxone.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=4,
        max_nodes=20,
    )["technology_paths"]

    loxone_input = "b" * 32
    loxone_to_knx = _query(
        f'<P><C Type="DigitalInput" U="{loxone_input}"><Co U="source"/></C>'
        f'<C Type="EIBactor" U="actor" EibAddr="1/2/4"><Co U="target">'
        f'<In Input="source"/></Co></C></P>'.encode(),
        (SimpleNamespace(uuid=loxone_input, action_uuid=None, subcontrols=()),),
    )
    loxone_path = loxone_to_knx.trace(
        loxone_to_knx.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=4,
        max_nodes=20,
    )["technology_paths"]

    assert [
        (path["classification"], path["source_project_node_id"], path["target_project_node_id"])
        for path in knx_path
    ] == [("knx_to_loxone", "p:1", "p:3")]
    assert [
        (path["classification"], path["source_project_node_id"], path["target_project_node_id"])
        for path in loxone_path
    ] == [("loxone_to_knx", "p:1", "p:3")]


def test_knx_usage_observation_and_cross_technology_path_need_a_reviewed_block_rule():
    project = _query(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co K="AQ" U="source"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/>'
        b'</Co><Co K="O" U="output"/></C>'
        b'<C Type="EIBactor" U="actor" EibAddr="1/2/4"><Co K="AI" U="target">'
        b'<In Input="output"/></Co></C></P>'
    )

    described = project.describe(project.resolve("p:1", "project_node_id"), limit=20)
    traced = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=6,
        max_nodes=20,
    )

    assert described["knx"]["usage_observations"] == [
        {
            "source": "p:4",
            "target": "p:6",
            "rule_id": "eib_push_toggle",
            "interpretation": "rising_edge",
            "effect": "toggle",
        }
    ]
    assert described["knx"]["usage_observations_truncated"] is False
    assert traced["semantic_edges"] == described["knx"]["usage_observations"]
    assert {item["project_node_id"] for item in traced["nodes"]} >= {
        "p:1",
        "p:7",
    }
    assert traced["technology_paths"] == [
        {
            "classification": "knx_to_knx",
            "source_project_node_id": "p:1",
            "target_project_node_id": "p:7",
            "evidence_project_node_ids": ["p:1", "p:2", "p:4", "p:6", "p:8", "p:7"],
        }
    ]

    depth_limited = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=1,
        max_nodes=20,
    )
    assert depth_limited["truncated"] is True
    assert depth_limited["semantic_truncated"] is True
    assert depth_limited["semantic_edges"] == []


def test_unknown_block_connector_pairs_never_create_derived_edges_or_usage():
    project = _query(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co K="AQ" U="source"/></C>'
        b'<C Type="UnknownLogic" U="logic"><Co K="Tg" U="trigger"><In Input="source"/>'
        b'</Co><Co K="O" U="output"/></C></P>'
    )

    described = project.describe(project.resolve("p:1", "project_node_id"), limit=20)
    traced = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=6,
        max_nodes=20,
    )

    assert described["knx"]["usage_observations"] == []
    assert traced["semantic_edges"] == []
