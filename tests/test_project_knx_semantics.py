from pathlib import Path
from types import SimpleNamespace

import pytest

from mcpserver.loxone.project.graph import (
    ProjectPartSummary,
    ProjectSnapshot,
    _logical_knx_nodes,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError


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
            "source_field": "EibAddr",
            "variant": None,
        },
        "datatype": {
            "source_field": "EIBType",
            "source_value": "5",
            "source_kind": "loxone_config",
            "system": "unknown",
            "normalized_code": None,
        },
        "normalized_dpt_evidence": None,
        "truncated_fields": [],
        "usage_observations": [],
        "usage_observations_truncated": False,
        "connector_evidence": [],
        "connector_evidence_truncated": False,
    }
    assert actor["flow_direction"] == "loxone_to_bus"
    assert actor["datatype"] is None
    assert actor["normalized_dpt_evidence"] is None


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
            "group_address": {
                "canonical": "14/1/5",
                "original": "14/1/5",
                "source_field": "EibAddr",
                "variant": None,
            },
        },
        {
            "object_kind": "endpoint",
            "flow_direction": "loxone_to_bus",
            "source_type": "EIBactor",
            "group_address": {
                "canonical": "14/1/6",
                "original": "14/1/6",
                "source_field": "EibAddr",
                "variant": None,
            },
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
        "source_field": "EibAddr",
        "variant": None,
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


def test_extsensor_variants_and_pulse_fallback_are_distinct_and_source_backed():
    project = _query(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())

    def find(address: str) -> list[dict[str, object]]:
        return project.find(
            query=None,
            kind=None,
            block_type=None,
            source_id=None,
            runtime_control_uuid=None,
            technology="knx_eib",
            knx_object_kind="endpoint",
            knx_flow_direction=None,
            knx_group_address=address,
        )

    zero = find("6/2/27:0")
    one = find("6/2/27:1")
    base = find("6/2/27")
    pulse = find("6/2/28:1")
    assert [item["source_id"] for item in zero] == ["edge-zero"]
    assert [item["source_id"] for item in one] == ["edge-one"]
    assert {item["source_id"] for item in base} == {"edge-zero", "edge-one", "base"}
    assert [item["source_id"] for item in pulse] == ["pulse-fallback"]
    assert zero[0]["knx"]["group_address"] == {
        "canonical": "6/2/27",
        "original": "6/2/27:0",
        "source_field": "EibAddr",
        "variant": {"kind": "edge", "value": "0"},
    }
    assert one[0]["knx"]["group_address"]["variant"]["value"] == "1"
    pulse_id = pulse[0]["project_node_id"]
    described = project.describe(project.resolve(pulse_id, "project_node_id"), limit=10)
    assert described["knx"]["group_address"]["source_field"] == "EibAddrPulse"
    assert described["knx"]["flow_direction"] == "bus_to_loxone"
    assert project.trace(
        project.resolve(pulse_id, "project_node_id"),
        direction="downstream",
        max_depth=4,
        max_nodes=20,
    )["edges"]
    assert not any(
        item["code"] == "unclassified_knx_candidate" for item in described["source_diagnostics"]
    )

    both = find("6/2/29:0")[0]
    assert both["knx"]["group_address"]["source_field"] == "EibAddr"
    assert find("6/2/30:1") == []
    invalid = next(
        item
        for item in project.find(
            query=None,
            kind=None,
            block_type=None,
            source_id="invalid-primary",
            runtime_control_uuid=None,
            technology="knx_eib",
        )
    )
    invalid_detail = project.describe(
        project.resolve(invalid["project_node_id"], "project_node_id"), limit=10
    )
    assert invalid_detail["knx"]["group_address"]["canonical"] is None
    assert invalid_detail["knx"]["group_address"]["source_field"] == "EibAddr"
    assert {item["code"] for item in invalid_detail["source_diagnostics"]} >= {
        "invalid_group_address"
    }


def test_text_and_external_actor_endpoints_use_exact_source_evidence():
    project = _query(Path("tests/fixtures/project/knx-text-endpoints.xml").read_bytes())

    def find(*, block_type: str | None = None, address: str | None = None):
        return project.find(
            query=None,
            kind=None,
            block_type=block_type,
            source_id=None,
            runtime_control_uuid=None,
            technology="knx_eib",
            knx_group_address=address,
        )

    assert len(find()) == 5
    assert len(find(block_type="EIBtextactor")) == 2
    assert [item["source_id"] for item in find(address="7/3/10")] == ["text-sensor"]
    assert [item["source_id"] for item in find(address="7/3/13:0")] == ["ext-actor-zero"]
    assert [item["source_id"] for item in find(address="7/3/13:1")] == ["ext-actor-one"]
    assert {item["source_id"] for item in find(address="7/3/13")} == {
        "ext-actor-zero",
        "ext-actor-one",
    }
    assert find(address="7/3/14") == []

    def describe(address: str):
        return project.describe(
            project.resolve(find(address=address)[0]["project_node_id"], "project_node_id"),
            limit=10,
        )

    sensor = describe("7/3/10")
    actor = describe("7/3/11")
    external = describe("7/3/13:0")
    unsupported = project.describe(project.resolve("p:20", "project_node_id"), limit=10)
    sensor_connector = sensor["knx"]["connector_evidence"][0]
    actor_connector = actor["knx"]["connector_evidence"][0]
    assert sensor["knx"]["flow_direction"] == "bus_to_loxone"
    assert sensor_connector["connector_key"] == "Q"
    assert sensor_connector["incoming_signals"] == 0
    assert sensor_connector["outgoing_signals"] == 1
    assert actor["knx"]["flow_direction"] == "loxone_to_bus"
    assert actor_connector["connector_key"] == "I"
    assert actor_connector["incoming_signals"] == 1
    assert actor_connector["outgoing_signals"] == 0
    assert external["knx"]["group_address"]["original"] == "7/3/13:0"
    assert external["knx"]["group_address"]["canonical"] == "7/3/13"
    assert external["knx"]["group_address"]["source_field"] == "EibAddr"
    assert external["knx"]["group_address"]["variant"] == {"kind": "edge", "value": "0"}
    assert external["knx"]["datatype"] is None
    assert "missing_raw_datatype" not in {item["code"] for item in external["source_diagnostics"]}
    assert "unmodeled_knx_attribute" in {item["code"] for item in external["source_diagnostics"]}
    assert "private-value" not in repr(external)
    assert unsupported["knx"] is None
    assert "unclassified_knx_candidate" in {
        item["code"] for item in unsupported["source_diagnostics"]
    }

    assert any(
        edge["source"] == sensor_connector["project_node_id"]
        for edge in project.trace(
            project.resolve(sensor["project_node_id"], "project_node_id"),
            direction="downstream",
            max_depth=4,
            max_nodes=20,
        )["edges"]
    )
    assert any(
        edge["target"] == actor_connector["project_node_id"]
        for edge in project.trace(
            project.resolve(actor["project_node_id"], "project_node_id"),
            direction="upstream",
            max_depth=4,
            max_nodes=20,
        )["edges"]
    )


def test_new_endpoint_connector_evidence_is_bounded_and_text_variants_are_unmodeled():
    long_key = "K" * 130
    project = _query(
        (
            '<P><C Type="EIBtextsensor" U="sensor" EibAddr="7/3/10:0" '
            'EibAddrPulse="7/3/11"><Co K="' + long_key + '" U="one"/>'
            '<Co K="two" U="two"/></C></P>'
        ).encode()
    )
    detail = project.describe(project.resolve("p:1", "project_node_id"), limit=1)
    knx = detail["knx"]
    assert knx["group_address"]["original"] == "7/3/10:0"
    assert knx["group_address"]["canonical"] is None
    assert knx["group_address"]["source_field"] == "EibAddr"
    assert len(knx["connector_evidence"]) == 1
    assert knx["connector_evidence_truncated"] is True
    assert knx["connector_evidence"][0]["connector_key"] == long_key[:100]
    assert knx["connector_evidence"][0]["connector_key_truncated"] is True
    assert {item["code"] for item in detail["source_diagnostics"]} >= {
        "invalid_group_address",
    }


def test_connector_evidence_includes_all_logical_source_occurrences():
    first = parse_project(
        b'<P><C Type="EIBtextactor" U="actor" EibAddr="7/3/11"><Co K="I" U="first-input"/></C></P>'
    )
    second = parse_project(
        b'<P><C Type="Logic" U="source"><Co U="output"/></C>'
        b'<C Type="EIBtextactor" U="actor" EibAddr="7/3/11">'
        b'<Co K="I" U="second-input"><In Input="output"/></Co></C></P>'
    )
    graph = build_graph((("one", first), ("two", second)))
    aliases, sources = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        7,
        (ProjectPartSummary("one", 1, ()), ProjectPartSummary("two", 1, ())),
        graph,
        logical_aliases=aliases,
        logical_source_ids=sources,
    )
    project = ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=())),
        ),
        {},
    )

    actor = next(
        item
        for item in project.find(
            query=None,
            kind=None,
            block_type="EIBtextactor",
            source_id=None,
            runtime_control_uuid=None,
            technology="knx_eib",
        )
    )
    described = project.describe(
        project.resolve(actor["project_node_id"], "project_node_id"), limit=10
    )
    evidence = described["knx"]["connector_evidence"]
    assert described["source_occurrence_count"] == 2
    assert len(evidence) == 2
    assert {item["incoming_signals"] for item in evidence} == {0, 1}
    assert described["knx"]["connector_evidence_truncated"] is False


@pytest.mark.parametrize(
    ("address", "source_id"),
    [
        ("6/2/27:0", "edge-zero"),
        ("6/2/27:1", "edge-one"),
        ("6/2/28:1", "pulse-fallback"),
        ("31/7/255", None),
        ("31/2047", None),
        ("06/02/027", None),
    ],
)
def test_knx_search_accepts_valid_original_variant_and_absent_forms(address, source_id):
    project = _query(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    found = project.find(
        query=None,
        kind=None,
        block_type=None,
        source_id=None,
        runtime_control_uuid=None,
        knx_group_address=address,
    )
    assert [item["source_id"] for item in found] == ([source_id] if source_id else [])


@pytest.mark.parametrize(
    "address",
    [
        "",
        "6/",
        "6/2/",
        "6/2/27:2",
        "6/2/27:0:1",
        "32/0/0",
        "1/8/0",
        "1/2/256",
        "31/2048",
        "6/2/27x",
        "6/2/27" + " " * 200,
    ],
)
def test_knx_search_rejects_malformed_and_out_of_range_filters(address):
    project = _query(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    with pytest.raises(ProjectQueryError, match="project_query_invalid"):
        project.find(
            query=None,
            kind=None,
            block_type=None,
            source_id=None,
            runtime_control_uuid=None,
            knx_group_address=address,
        )


def test_edge_variants_do_not_merge_as_one_logical_object():
    zero = parse_project(b'<P><C Type="EIBextsensor" U="shared" EibAddr="6/2/27:0"/></P>')
    one = parse_project(b'<P><C Type="EIBextsensor" U="shared" EibAddr="6/2/27:1"/></P>')
    graph = build_graph((("first", zero), ("second", one)))
    assert _logical_knx_nodes(graph) == ((), ())

    graph = build_graph((("first", zero), ("second", zero)))
    aliases, sources = _logical_knx_nodes(graph)
    assert len(aliases) == 2
    assert len(sources) == 1


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
