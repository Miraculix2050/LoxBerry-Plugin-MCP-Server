"""Configured wiring is evidence; synthetic block names never supply semantics."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.project.graph import (
    PROJECT_MODEL_VERSION,
    GraphEdge,
    ProjectPartSummary,
    ProjectSnapshot,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError

SOURCE, LIGHT, OTHER = "a" * 32, "b" * 32, "c" * 32
OUTPUT, INPUT, CENTRAL, CENTRAL_INPUT, CENTRAL_OUTPUT = (str(i) * 32 for i in range(1, 6))
CHILD = LIGHT + "/AI1"


def lighting_query(
    central_type=None,
    *,
    duplicate_parent=False,
    unmapped_source=False,
    central_input_key="I1",
    central_output_key="Q",
    duplicate_output=False,
    keep_reviewed_input=False,
):
    intermediary = (
        f'<C Type="{central_type}" U="{CENTRAL}">'
        f'<Co K="{central_input_key}" U="{CENTRAL_INPUT}"><In Input="{OUTPUT}"/></Co>'
        f'<Co K="{central_output_key}" U="{CENTRAL_OUTPUT}"/>'
        + (f'<Co K="Q" U="{"6" * 32}"/>' if duplicate_output else "")
        + (f'<Co K="I1" U="{"7" * 32}"/>' if keep_reviewed_input else "")
        + "</C>"
        if central_type
        else ""
    )
    parsed = parse_project(
        (
            f'<P><C Type="SyntheticPresence" U="{SOURCE}"><Co K="Q" U="{OUTPUT}"/></C>'
            + intermediary
            + f'<C Type="SyntheticLighting" U="{LIGHT}"><Co K="P" U="{INPUT}">'
            f'<In Input="{CENTRAL_OUTPUT if central_type else OUTPUT}"/></Co></C>'
            f'<C Type="Unrelated" U="{OTHER}"/>'
            + (f'<C Type="Duplicate" U="{LIGHT}"/>' if duplicate_parent else "")
            + "</P>"
        ).encode()
    )
    graph = build_graph((("p", parsed),))
    snapshot = ProjectSnapshot(
        "synthetic",
        PROJECT_MODEL_VERSION,
        (ProjectPartSummary("p", len(parsed.elements), ()),),
        graph,
    )
    child = Control(CHILD, "Same", "Dimmer", "room", "category", None, ())
    light = Control(
        LIGHT, "Same", "LightControllerV2", "room", "category", None, (), subcontrols=(child,)
    )
    source = replace(light, uuid=SOURCE, control_type="UserSelectedSource", subcontrols=())
    unrelated = replace(light, uuid=OTHER, subcontrols=())
    controls = (light, unrelated) if unmapped_source else (source, light, unrelated)
    structure = LoxoneStructure(LoxoneIdentity("reader", "synthetic"), "v1", (), (), controls)
    return ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})


def trace(project, target=SOURCE, direction="downstream", **limits):
    return project.trace(
        project.resolve(target, "runtime_control_uuid"),
        direction=direction,
        max_depth=limits.get("max_depth", 16),
        max_nodes=limits.get("max_nodes", 200),
        include_internal_flow_gaps=True,
    )


def source_ids(project, result):
    keys = {row["project_node_id"] for row in result["nodes"]}
    return {node.source_id for node in project.view.snapshot.graph.nodes if node.key in keys}


def test_direct_wiring_retains_unknown_internal_flow_without_name_associations():
    project = lighting_query()
    result = trace(project)
    assert LIGHT in source_ids(project, result) and OTHER not in source_ids(project, result)
    assert len(result["edges"]) == 1 and not result["semantic_edges"]
    assert {gap["code"] for gap in result["semantic_gaps"]} == {"internal_flow_not_modeled"}
    assert len(result["semantic_gaps"]) == 2
    assert not project.trace(
        project.resolve(SOURCE, "runtime_control_uuid"),
        direction="downstream",
        max_depth=16,
        max_nodes=200,
    )["semantic_gaps"]


def test_indirect_wiring_uses_only_existing_reviewed_or_rule():
    project = lighting_query("Or")
    result = trace(project)
    assert LIGHT in source_ids(project, result)
    assert {edge["rule_id"] for edge in result["semantic_edges"]} == {"or_i1_q_v1"}
    assert len(result["edges"]) == 2


@pytest.mark.parametrize(
    "options",
    [
        {"central_output_key": "UnknownOutput"},
        {"duplicate_output": True},
        {"central_input_key": "UnknownInput", "keep_reviewed_input": True},
    ],
)
def test_catalog_rule_does_not_hide_an_unmodeled_reached_connector(options):
    project = lighting_query("Or", **options)
    result = trace(project)
    connector = next(n for n in project.view.snapshot.graph.nodes if n.source_id == CENTRAL_INPUT)
    assert {"project_node_id": connector.key, "code": "internal_flow_not_modeled"} in result[
        "semantic_gaps"
    ]
    assert LIGHT not in source_ids(project, result)


def test_reviewed_input_reference_flow_is_not_reported_as_unknown():
    parsed = parse_project(
        (
            f'<P><C Type="SyntheticSource" U="{SOURCE}"/>'
            f'<C Type="InputRef" U="{CENTRAL}" Ref="{SOURCE}"><Co K="AQ" U="{CENTRAL_OUTPUT}"/></C>'
            f'<C Type="SyntheticLighting" U="{LIGHT}"><Co K="P" U="{INPUT}">'
            f'<In Input="{CENTRAL_OUTPUT}"/></Co></C></P>'
        ).encode()
    )
    graph = build_graph((("p", parsed),))
    snapshot = ProjectSnapshot(
        "synthetic",
        PROJECT_MODEL_VERSION,
        (ProjectPartSummary("p", len(parsed.elements), ()),),
        graph,
    )
    structure = LoxoneStructure(LoxoneIdentity("reader", "synthetic"), "v1", (), (), ())
    project = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    source = next(n for n in graph.nodes if n.source_id == SOURCE)
    result = project.trace(
        source, direction="downstream", max_depth=16, max_nodes=200, include_internal_flow_gaps=True
    )
    assert {e["rule_id"] for e in result["semantic_edges"]} == {"input_ref_aq_v1"}
    assert LIGHT in source_ids(project, result)
    reviewed = {n.key for n in graph.nodes if n.source_id in {CENTRAL, CENTRAL_OUTPUT}}
    assert not any(g["project_node_id"] in reviewed for g in result["semantic_gaps"])


@pytest.mark.parametrize("direction,target", [("downstream", SOURCE), ("upstream", LIGHT)])
def test_unknown_central_flow_stops_before_inventing_a_relationship(direction, target):
    project = lighting_query("UnknownCentral")
    result = trace(project, target, direction)
    assert CENTRAL in source_ids(project, result)
    assert (LIGHT if target == SOURCE else SOURCE) not in source_ids(project, result)
    assert not result["semantic_edges"]
    assert any(gap["code"] == "internal_flow_not_modeled" for gap in result["semantic_gaps"])


def test_child_keeps_exact_identity_and_separate_parent_topology():
    project = lighting_query()
    result = trace(project, CHILD, "upstream")
    mapping = project.derived_target(CHILD, "runtime_control_uuid")
    assert mapping["runtime_control_uuid"] == CHILD
    assert mapping["parent_runtime_control_uuid"] == LIGHT
    assert mapping["mapping_status"] == "derived_from_parent"
    assert result["start"]["project_node_id"] == project.resolve(LIGHT, "runtime_control_uuid").key
    assert SOURCE in source_ids(project, result)


def test_ambiguous_parent_is_not_resolved_by_matching_names():
    project = lighting_query(duplicate_parent=True)
    with pytest.raises(ProjectQueryError, match="project_mapping_ambiguous"):
        trace(project, CHILD, "upstream")


def test_unmapped_source_keeps_project_wiring_without_runtime_identity_guess():
    project = lighting_query(unmapped_source=True)
    result = trace(project, LIGHT, "upstream")
    assert SOURCE in source_ids(project, result)
    source_node = next(n for n in project.view.snapshot.graph.nodes if n.source_id == SOURCE)
    assert project.describe(source_node, limit=10)["runtime_control"] is None
    with pytest.raises(ProjectQueryError, match="project_node_unknown"):
        trace(project)


def test_ambiguous_connector_containment_is_a_gap_not_an_internal_rule():
    project = lighting_query()
    graph = project.view.snapshot.graph
    connector = next(n for n in graph.nodes if n.source_id == INPUT)
    other = next(n for n in graph.nodes if n.source_id == OTHER)
    graph = replace(graph, edges=(*graph.edges, GraphEdge(other.key, connector.key, "contains")))
    snapshot = replace(project.view.snapshot, graph=graph)
    project = ProjectQuery(ProjectView(snapshot, project.view.mapping), {})
    result = trace(project)
    assert {"project_node_id": connector.key, "code": "internal_flow_parent_ambiguous"} in result[
        "semantic_gaps"
    ]
    assert not result["semantic_edges"]
    assert project.describe(connector, limit=10)["parent_project_node_id"] is None


def test_output_reference_is_preserved_without_inventing_block_internal_flow():
    parsed = parse_project(
        (
            f'<P><C Type="VirtualOutCmd" U="{SOURCE}"/>'
            f'<C Type="OutputRef" Ref="{SOURCE}"><Co K="Q" U="{OUTPUT}"/></C>'
            f'<C Type="SyntheticLighting" U="{LIGHT}"><Co K="P" U="{INPUT}">'
            f'<In Input="{OUTPUT}"/></Co></C></P>'
        ).encode()
    )
    graph = build_graph((("p", parsed),))
    snapshot = ProjectSnapshot(
        "synthetic",
        PROJECT_MODEL_VERSION,
        (ProjectPartSummary("p", len(parsed.elements), ()),),
        graph,
    )
    structure = LoxoneStructure(LoxoneIdentity("reader", "synthetic"), "v1", (), (), ())
    project = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    source = next(n for n in graph.nodes if n.source_id == SOURCE)
    result = project.trace(
        source, direction="downstream", max_depth=16, max_nodes=200, include_internal_flow_gaps=True
    )
    assert [e["kind"] for e in result["edges"]] == ["reference"]
    assert LIGHT not in source_ids(project, result)
    assert not result["semantic_edges"] and result["semantic_gaps"]


@pytest.mark.parametrize("max_nodes", [1, 2, 4])
def test_internal_flow_diagnostics_share_existing_trace_bounds(max_nodes):
    project = lighting_query("Or")
    result = trace(project, max_nodes=max_nodes)
    retained = {node["project_node_id"] for node in result["nodes"]}
    assert len(retained) <= max_nodes
    assert all(gap["project_node_id"] in retained for gap in result["semantic_gaps"])
    assert result["truncated"] or result["semantic_truncated"]


@pytest.mark.asyncio
async def test_existing_trace_tool_exposes_opt_in_gaps_and_exact_child_provenance(monkeypatch):
    project = lighting_query()
    reader = AsyncMock(return_value=(project, SimpleNamespace(connected=True)))
    monkeypatch.setattr(tools, "_project_query", reader)
    server = FastMCP("lighting-relationships")
    tools.register_project_tools(server, SimpleNamespace(projects=SimpleNamespace()))
    tool = server._tool_manager.get_tool("loxone_trace_project_logic")
    assert tool.parameters["properties"]["include_internal_flow_gaps"]["default"] is False
    original = await tool.fn(CHILD, "runtime_control_uuid", "upstream")
    result = await tool.fn(
        CHILD, "runtime_control_uuid", "upstream", include_internal_flow_gaps=True
    )
    assert original.ok and not original.data.semantic_gaps
    assert result.ok and result.data.semantic_gaps
    assert result.data.runtime_target_mapping.runtime_control_uuid == CHILD
    assert reader.await_count == 2
