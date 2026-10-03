from types import SimpleNamespace

import pytest

from mcpserver.loxone.opening_contacts import OpeningGraph
from mcpserver.loxone.project.graph import build_graph
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.semantics import STATE_RULE_ID


def xml(rows=None, version="17020828", revision="178", extra=""):
    rows = (
        rows
        if rows is not None
        else [
            '<StateText Valid="true" ValidV="true" Input0="2" CondV0="1" CondT0="1" TextV="5"/>',
            '<StateText Valid="true" ValidV="true" TextV="0"/>',
        ]
    )
    ports = "".join(f'<Co K="I{i}" U="i{i}"/>' for i in range(1, 9))
    return (
        f'<ControlList Version="274"><C Type="Document" ConfigVersion="{version}"/>'
        f'<C Type="State" V="{revision}" U="state">{ports}'
        '<Co K="AQ" U="aq"/><Co K="TQ" U="tq"/><Co K="OutputAPI" U="api"/>'
        f'{extra}<StateTexts Num="{len(rows)}">{"".join(rows)}</StateTexts></C></ControlList>'
    ).encode()


def graph(data):
    return build_graph((("synthetic", parse_project(data)),))


def opening(g):
    return OpeningGraph(
        SimpleNamespace(
            view=SimpleNamespace(
                snapshot=SimpleNamespace(
                    graph=g, source_diagnostics=SimpleNamespace(parser_codes_by_node=())
                )
            )
        )
    )


def test_confirmed_pattern_is_configuration_dependent_with_provenance():
    g = graph(xml())
    (flow,) = g.state_flows
    assert flow.reason is None
    assert flow.version == ("17020828", "274", "178")
    assert flow.dependencies == ("I2",)
    assert len(flow.rows) == 2
    assert g.semantic_edges[0].rule_id == STATE_RULE_ID
    assert g.semantic_edges[0].interpretation == "configured_state_selection"
    assert "Decimal" not in repr(flow)
    o = opening(g)
    aq = next(n.key for n in g.nodes if n.source_id == "aq")
    t = o.trace([aq], "upstream", 16, 200)
    assert t["complete"]
    assert not t["gaps"]
    assert any(e["kind"] == "derived_semantic" for e in t["edges"])
    assert {n["connector_key"] for n in t["nodes"]} == {"I2", "AQ"}


@pytest.mark.parametrize("value", ["0", "5"])
def test_equal_results_or_early_default_prove_numeric_independence(value):
    rows = [
        f'<StateText Valid="true" ValidV="true" TextV="{value}"/>',
        '<StateText Valid="true" ValidV="true" Input0="2" CondV0="1" CondT0="1" TextV="5"/>',
    ]
    g = graph(xml(rows))
    assert g.state_flows[0].dependencies == ()
    assert not g.semantic_edges


def test_equal_conditional_and_default_values_are_independent():
    g = graph(xml().replace(b'TextV="5"', b'TextV="0"'))
    assert g.state_flows[0].reason is None
    assert not g.state_flows[0].dependencies


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.replace(b"17020828", b"17010727"),
        lambda b: b.replace(b'V="178"', b'V="175"'),
        lambda b: b.replace(b'CondT0="1"', b'CondT0="0"'),
        lambda b: b.replace(b'Input0="2"', b'Input0="1"'),
        lambda b: b.replace(b'TextV="5"', b'TextV="NaN"'),
        lambda b: b.replace(b'TextV="5"', b'TextV="5" Cond0="1"'),
        lambda b: b.replace(b'TextV="5"', b'TextV="5" TextV="0"'),
        lambda b: b.replace(b'Valid="true"', b'Valid="false"'),
    ],
)
def test_unverified_tables_never_emit_a_rule(change):
    g = graph(change(xml()))
    assert g.state_flows[0].reason is not None
    assert not g.semantic_edges
    aq = next(n.key for n in g.nodes if n.source_id == "aq")
    assert opening(g).trace([aq], "upstream", 16, 200)["gaps"]


def test_limit_and_duplicate_connectors_are_explicit():
    row = '<StateText Valid="true" ValidV="true" TextV="0"/>'
    assert graph(xml([row] * 101)).state_flows[0].reason == "state_table_limit"
    assert graph(xml([row] * 100)).state_flows[0].reason is None
    assert (
        graph(xml(extra='<Co K="I2" U="duplicate"/>')).state_flows[0].reason
        == "state_connector_unverified"
    )


def test_unknown_outputs_remain_gaps_in_both_directions():
    g = graph(xml())
    for key in ("tq", "api"):
        node = next(n.key for n in g.nodes if n.source_id == key)
        for direction in ("upstream", "downstream"):
            t = opening(g).trace([node], direction, 16, 200)
            assert t["gaps"][0]["reason"] == "state_connector_unverified"
            assert t["gaps"][0]["rule_ids"] == [STATE_RULE_ID]


def test_generic_trace_matches_opening_edges_and_gaps():
    from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot
    from mcpserver.loxone.project.mapping import ProjectView, map_runtime
    from mcpserver.loxone.project.query import ProjectQuery
    from mcpserver.tools import ProjectDescriptionData, ProjectTraceData

    g = graph(xml())
    snap = ProjectSnapshot("synthetic", 9, (ProjectPartSummary("synthetic", 20, ()),), g)
    structure = SimpleNamespace(controls=(), last_modified="synthetic")
    q = ProjectQuery(ProjectView(snap, map_runtime(snap, structure), "synthetic"), {})
    for source in ("aq", "i2", "tq", "api"):
        node = next(n for n in g.nodes if n.source_id == source)
        for direction in ("upstream", "downstream"):
            generic = q.trace(node, direction=direction, max_depth=16, max_nodes=200)
            opening_trace = OpeningGraph(q).trace([node.key], direction, 16, 200)
            assert {
                (e["source"], e["target"], e["rule_id"]) for e in generic["semantic_edges"]
            } == {
                (e["source"], e["target"], e["semantic_rule_id"])
                for e in opening_trace["edges"]
                if e["kind"] == "derived_semantic"
            }
            assert {(g["project_node_id"], g["code"]) for g in generic["semantic_gaps"]} == {
                (g["project_node_id"], g["reason"]) for g in opening_trace["gaps"]
            }
            ProjectTraceData.model_validate(generic)
    state = next(n for n in g.nodes if n.source_id == "state")
    detail = q.describe(state, limit=100)
    assert detail["state_semantics"]["aq_dependencies"] == ["I2"]
    ProjectDescriptionData.model_validate(detail)


def test_wired_independent_neighbor_does_not_contaminate_aq_upstream():
    data = xml().replace(b'<Co K="I1" U="i1"/>', b'<Co K="I1" U="i1"><In Input="neighbor"/></Co>')
    data = data.replace(
        b"</ControlList>", b'<C Type="Unknown" U="other"><Co K="Q" U="neighbor"/></C></ControlList>'
    )
    g = graph(data)
    aq = next(n.key for n in g.nodes if n.source_id == "aq")
    trace = opening(g).trace([aq], "upstream", 16, 200)
    assert trace["complete"]
    assert not any(n["connector_key"] == "I1" for n in trace["nodes"])


def test_unresolved_relevant_input_stays_explicit():
    data = xml().replace(b'<Co K="I2" U="i2"/>', b'<Co K="I2" U="i2"><In Input="missing"/></Co>')
    g = graph(data)
    aq = next(n.key for n in g.nodes if n.source_id == "aq")
    trace = opening(g).trace([aq], "upstream", 16, 200)
    assert not trace["complete"]
    assert "unresolved_relationship" in trace["warnings"]


def test_missing_default_is_unknown_and_private_version_is_sanitized():
    conditional = (
        '<StateText Valid="true" ValidV="true" Input0="2" CondV0="1" CondT0="1" TextV="5"/>'
    )
    assert graph(xml([conditional])).state_flows[0].reason == "state_table_unsupported"
    flow = graph(xml(version="private-value")).state_flows[0]
    assert flow.version[0] is None
    assert "private-value" not in repr(flow)


def test_multiple_sources_keep_individual_state_provenance():
    g = build_graph((("one", parse_project(xml())), ("two", parse_project(xml()))))
    assert len(g.state_flows) == 2
    assert len({f.block_key for f in g.state_flows}) == 2
    assert len(g.semantic_edges) == 2


def test_fixture_is_synthetic_and_matches_confirmed_table():
    from pathlib import Path

    assert graph(Path("tests/fixtures/project/state-equality-274.xml").read_bytes()).state_flows[
        0
    ].dependencies == ("I2",)


def test_unknown_inbound_api_cannot_be_declared_independent():
    data = xml().replace(
        b'<Co K="OutputAPI" U="api"/>', b'<Co K="OutputAPI" U="api"><In Input="unknown"/></Co>'
    )
    assert graph(data).state_flows[0].reason == "state_connector_unverified"


def test_duplicate_version_marker_fails_closed():
    assert (
        graph(xml().replace(b'Version="274"', b'Version="274" Version="274"')).state_flows[0].reason
        is not None
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.replace(b'Type="Document"', b'Type="Unknown"'),
        lambda b: b.replace(b'K="I2"', b'K="I2" K="I2"'),
        lambda b: b.replace(b'Num="2">', b'Num="2">unexpected'),
        lambda b: b.replace(b'TextV="5"/>', b'TextV="5">unexpected</StateText>'),
        lambda b: b.replace(b'Type="State"', b'Type="State" Type="State"'),
    ],
)
def test_reviewed_ambiguous_or_misplaced_evidence_is_rejected(change):
    assert graph(change(xml())).state_flows[0].reason is not None


def test_nested_state_block_retains_own_description_and_version_gap():
    from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot
    from mcpserver.loxone.project.mapping import ProjectView, map_runtime
    from mcpserver.loxone.project.query import ProjectQuery

    data = (
        xml(version="17010727")
        .replace(b'<C Type="State"', b'<C Type="Container" U="container"><C Type="State"')
        .replace(b"</ControlList>", b"</C></ControlList>")
    )
    g = graph(data)
    snap = ProjectSnapshot("synthetic", 9, (ProjectPartSummary("synthetic", 20, ()),), g)
    structure = SimpleNamespace(controls=(), last_modified="synthetic")
    q = ProjectQuery(ProjectView(snap, map_runtime(snap, structure), "synthetic"), {})
    node = next(n for n in g.nodes if n.source_id == "state")
    assert q.describe(node, limit=100)["state_semantics"]["reason"] == "state_version_unverified"
    assert any(
        gap["project_node_id"] == node.key
        for gap in q.trace(node, direction="upstream", max_depth=16, max_nodes=200)["semantic_gaps"]
    )


def test_trace_fitting_keeps_gap_references_and_reports_omission(monkeypatch):
    import mcpserver.tools as tools

    nodes = [
        {
            "project_node_id": str(i),
            "kind": "connector",
            "block_type": "State",
            "source_id": None,
            "connector_key": "AQ",
        }
        for i in range(40)
    ]
    data = tools.ProjectTraceData(
        start=nodes[0],
        direction="upstream",
        nodes=nodes,
        edges=[],
        semantic_gaps=[{"project_node_id": "39", "code": "state_version_unverified"}],
        truncated=False,
        truncation_reason=None,
        unresolved_relationships=[],
        unresolved_truncated=False,
    )
    envelope = tools.ProjectTraceEnvelope(
        ok=True, data=data, observed_at="synthetic", stale=False, trace_id="synthetic"
    )
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 2000)
    assert tools._fit_project_trace(envelope)
    assert data.semantic_truncated
    assert not data.semantic_gaps
    assert len(envelope.model_dump_json().encode()) <= 2000
