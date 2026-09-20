from pathlib import Path
from types import SimpleNamespace

from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery


def _query(data: bytes) -> ProjectQuery:
    snapshot = ProjectSnapshot(
        "project",
        2,
        (ProjectPartSummary("p", 1, ()),),
        build_graph((("p", parse_project(data)),)),
    )
    return ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=())),
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
