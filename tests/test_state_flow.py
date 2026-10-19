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
        lambda b: b.replace(b'Input0="2"', b'Input0="9"'),
        lambda b: b.replace(b'TextV="5"', b'TextV="NaN"'),
        lambda b: b.replace(b'TextV="5"', b'TextV="5" Cond0="0"'),
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
    for key in ("tq",):
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


def test_unresolved_api_metadata_does_not_invalidate_aq_table():
    data = xml().replace(
        b'<Co K="OutputAPI" U="api"/>', b'<Co K="OutputAPI" U="api"><In Input="unknown"/></Co>'
    )
    assert graph(data).state_flows[0].reason is None
    assert any(code == "api_connection_unresolved" for _, code in graph(data).unresolved)


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


def test_semantic_gap_preserves_traversal_truncation_reason():
    from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot
    from mcpserver.loxone.project.mapping import ProjectView, map_runtime
    from mcpserver.loxone.project.query import ProjectQuery
    from mcpserver.tools import ProjectTraceData

    g = graph(xml(version="17010727"))
    snap = ProjectSnapshot("synthetic", 9, (ProjectPartSummary("synthetic", 20, ()),), g)
    structure = SimpleNamespace(controls=(), last_modified="synthetic")
    q = ProjectQuery(ProjectView(snap, map_runtime(snap, structure), "synthetic"), {})
    node = next(n for n in g.nodes if n.source_id == "state")
    trace = q.trace(node, direction="upstream", max_depth=1, max_nodes=1)
    assert trace["truncated"]
    assert trace["truncation_reason"] == "max_nodes"
    assert trace["semantic_gaps"]
    ProjectTraceData.model_validate(trace)


def condition_row(input_number, code=None, numeric="2", text=None, result="5"):
    fields = f'Input0="{input_number}"'
    if code is not None:
        fields += f' Cond0="{code}"'
    if numeric is not None:
        fields += f' CondV0="{numeric}"'
    if text is not None:
        fields += f' CondT0="{text}"'
    return f'<StateText Valid="true" ValidV="true" {fields} TextV="{result}"/>'


DEFAULT_ROW = '<StateText Valid="true" ValidV="true" TextV="0"/>'


def query_for(g):
    from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot
    from mcpserver.loxone.project.mapping import ProjectView, map_runtime
    from mcpserver.loxone.project.query import ProjectQuery

    snapshot = ProjectSnapshot("synthetic", 10, (ProjectPartSummary("synthetic", 20, ()),), g)
    structure = SimpleNamespace(controls=(), last_modified="synthetic")
    return ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure), "synthetic"), {})


@pytest.mark.parametrize("input_number", range(1, 9))
@pytest.mark.parametrize("code", [None, *map(str, range(1, 10))])
def test_every_proven_operator_and_input_has_shared_occurrence_evidence(input_number, code):
    from mcpserver.tools import ProjectTraceData

    text = "2" if code in {"6", "7", "8", "9"} else None
    g = graph(xml([condition_row(input_number, code, text=text), DEFAULT_ROW]))
    assert g.state_flows[0].reason is None
    assert g.state_flows[0].dependencies == (f"I{input_number}",)
    q = query_for(g)
    for source in ("aq", f"i{input_number}"):
        node = next(n for n in g.nodes if n.source_id == source)
        for direction in ("upstream", "downstream"):
            generic = q.trace(node, direction=direction, max_depth=16, max_nodes=200)
            contact = OpeningGraph(q).trace([node.key], direction, 16, 200)
            ProjectTraceData.model_validate(generic)
            assert {
                (e["source"], e["target"], e["rule_id"]) for e in generic["semantic_edges"]
            } == {
                (e["source"], e["target"], e["semantic_rule_id"])
                for e in contact["edges"]
                if e["kind"] == "derived_semantic"
            }
            assert {(x["project_node_id"], x["code"]) for x in generic["semantic_gaps"]} == {
                (x["project_node_id"], x["reason"]) for x in contact["gaps"]
            }


def test_original_table_dependencies_and_all_wired_independent_neighbors():
    from pathlib import Path

    data = Path("tests/fixtures/project/state-original-274.xml").read_bytes()
    for i in range(4, 9):
        data = data.replace(
            f'<Co K="I{i}" U="i{i}"/>'.encode(),
            f'<Co K="I{i}" U="i{i}"><In Input="neighbor{i}"/></Co>'.encode(),
        )
    others = "".join(
        f'<C Type="Unknown" U="other{i}"><Co K="Q" U="neighbor{i}"/></C>' for i in range(4, 9)
    )
    g = graph(data.replace(b"</ControlList>", (others + "</ControlList>").encode()))
    flow = g.state_flows[0]
    assert flow.reason is None and flow.dependencies == ("I1", "I2", "I3")
    assert [r.numeric for r in flow.rows] == [0, 5, 4, 3, 0]
    q = query_for(g)
    aq = next(n for n in g.nodes if n.source_id == "aq")
    generic = q.trace(aq, direction="upstream", max_depth=16, max_nodes=200)
    contact = OpeningGraph(q).trace([aq.key], "upstream", 16, 200)
    assert contact["complete"] and not contact["gaps"]
    assert len(generic["semantic_edges"]) == len(contact["edges"]) == 3
    assert not any(n["connector_key"] in {f"I{i}" for i in range(4, 9)} for n in contact["nodes"])


def test_operator_specimen_preserves_empty_numeric_gap_and_four_condition_rows():
    from pathlib import Path

    data = Path("tests/fixtures/project/state-operators-274.xml").read_bytes()
    assert graph(data).state_flows[0].reason == "state_table_unsupported"
    # A separately synthetic explicit numeric default supplies a positive case.
    g = graph(data.replace(b'TextV=""', b'TextV="0"'))
    assert g.state_flows[0].reason is None
    assert g.state_flows[0].dependencies == ("I1", "I2", "I4", "I5", "I6", "I7", "I8")
    assert len(g.state_flows[0].rows[1].conditions) == 4
    assert len(g.state_flows[0].rows[2].conditions) == 4
    assert g.state_flows[0].rows[3].conditions[0].operator == "*="


def test_distinct_predicates_are_not_shadowed_and_exact_duplicates_are():
    rows = [condition_row(1), condition_row(2), condition_row(1, result="99"), DEFAULT_ROW]
    flow = graph(xml(rows)).state_flows[0]
    assert flow.dependencies == ("I1", "I2")
    assert [r.numeric for r in flow.rows] == [5, 5, 0]
    # Different encoding presence/spelling must not be equated by conversion.
    changed = condition_row(1, numeric="2.0", result="7")
    assert len(graph(xml([rows[0], changed, DEFAULT_ROW])).state_flows[0].rows) == 3


@pytest.mark.parametrize(
    "row",
    [
        condition_row(1, "0"),
        condition_row(1, "10"),
        condition_row(0),
        condition_row(9),
        condition_row(1, "6", text=None),
        condition_row(1, "2", numeric=None),
        condition_row(1, numeric="NaN"),
        condition_row(1, text="different"),
        condition_row(1, "6", text="&lt;v2&gt;"),
        condition_row(1, "6", text="x" * 257),
        condition_row(1, "1", text="2"),
        condition_row(1, result=""),
        '<StateText Valid="true" ValidV="true" Cond0="1" TextV="5"/>',
        '<StateText Valid="true" ValidV="true" CondV1="1" TextV="5"/>',
        '<StateText Valid="true" ValidV="true" Input0="1" Input4="2" TextV="5"/>',
    ],
)
def test_unknown_or_ambiguous_operands_do_not_prove_independence(row):
    g = graph(xml([row, DEFAULT_ROW]))
    assert g.state_flows[0].reason == "state_table_unsupported"
    assert not g.semantic_edges


def test_operator_data_stays_internal_and_equal_outputs_remain_independent():
    g = graph(
        xml([condition_row(8, "6", numeric=None, text="private-marker", result="0"), DEFAULT_ROW])
    )
    assert g.state_flows[0].reason is None and not g.state_flows[0].dependencies
    q = query_for(g)
    state = next(n for n in g.nodes if n.source_id == "state")
    assert "private-marker" not in repr(g.state_flows)
    assert "private-marker" not in str(q.describe(state, limit=100))


def test_state_cycle_and_traversal_bound_remain_explicit():
    data = xml().replace(b'<Co K="I2" U="i2"/>', b'<Co K="I2" U="i2"><In Input="aq"/></Co>')
    g = graph(data)
    node = next(n for n in g.nodes if n.source_id == "aq")
    q = query_for(g)
    assert len(q.trace(node, direction="upstream", max_depth=16, max_nodes=200)["nodes"]) == 3
    assert (
        q.trace(node, direction="upstream", max_depth=16, max_nodes=1)["truncation_reason"]
        == "max_nodes"
    )


@pytest.mark.parametrize("input_number", range(1, 9))
def test_each_relevant_unresolved_provider_remains_incomplete(input_number):
    data = xml([condition_row(input_number), DEFAULT_ROW])
    data = data.replace(
        f'<Co K="I{input_number}" U="i{input_number}"/>'.encode(),
        f'<Co K="I{input_number}" U="i{input_number}"><In Input="missing"/></Co>'.encode(),
    )
    g = graph(data)
    aq = next(n for n in g.nodes if n.source_id == "aq")
    q = query_for(g)
    assert q.trace(aq, direction="upstream", max_depth=16, max_nodes=200)[
        "unresolved_relationships"
    ]
    result = OpeningGraph(q).trace([aq.key], "upstream", 16, 200)
    assert not result["complete"] and "unresolved_relationship" in result["warnings"]


def visible_query(data, visible=True):
    from mcpserver.loxone.models import Control
    from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot
    from mcpserver.loxone.project.mapping import ProjectView, map_runtime
    from mcpserver.loxone.project.query import ProjectQuery

    uuid = "00000000-0000-0000-0000000000000009"
    g = graph(data.replace(b'U="state"', f'U="{uuid}"'.encode()))
    snap = ProjectSnapshot("synthetic", 11, (ProjectPartSummary("synthetic", 20, ()),), g)
    control = Control(uuid, "Visible State", "TextState", None, None, None, ())
    structure = SimpleNamespace(controls=(control,) if visible else (), last_modified="synthetic")
    q = ProjectQuery(
        ProjectView(snap, map_runtime(snap, structure), "synthetic"), {uuid: "Visible State"}
    )
    return q, next(n for n in g.nodes if n.source_id == uuid)


def test_sparse_positions_are_active_conditions_not_missing_zero_inputs():
    from pathlib import Path

    from mcpserver.tools import ProjectDescriptionData

    q, node = visible_query(Path("tests/fixtures/project/state-sparse-274.xml").read_bytes())
    detail = q.describe(node, limit=100, include_state_table=True)
    ProjectDescriptionData.model_validate(detail)
    assert detail["state_semantics"]["aq_dependencies"] == ["I1", "I2", "I3"]
    table = detail["state_table"]
    assert table["complete"] and len(table["rows"]) == 11
    first = table["rows"][0]
    assert first["conditions"] == [
        {
            "position": 2,
            "input_key": "I3",
            "operator": "==",
            "numeric_operand": "3",
            "text_operand": "3",
        }
    ]
    assert first["aq_value"] == "4000"
    assert [c["input_key"] for c in table["rows"][1]["conditions"]] == ["I1", "I3"]
    assert "state_table" not in q.describe(node, limit=100)
    aq = next(n for n in q.view.snapshot.graph.nodes if n.source_id == "aq")
    generic = q.trace(aq, direction="upstream", max_depth=16, max_nodes=200)
    contact = OpeningGraph(q).trace([aq.key], "upstream", 16, 200)
    assert len(generic["semantic_edges"]) == 3 and contact["complete"]


def test_table_projection_retains_shadowed_rows_and_literal_text_templates():
    rows = [DEFAULT_ROW, condition_row(2).replace("/>", ' Text="example &lt;v1&gt;"/>')]
    q, node = visible_query(xml(rows))
    table = q.describe(node, limit=100, include_state_table=True)["state_table"]
    assert len(table["rows"]) == 2
    assert table["rows"][1]["text_template"] == "example <v1>"
    assert table["text_semantics"] == "literal_template_only"
    assert table["output_api_complete"] is False
    limited = q.describe(node, limit=1, include_state_table=True)["state_table"]
    assert not limited["complete"] and limited["rows_omitted"] == 1
    assert limited["rows_total"] == 2


def test_table_contents_are_not_exposed_for_unmapped_or_hidden_state():
    data = xml().replace(b'TextV="5"', b'TextV="5" Text="private text"')
    q, node = visible_query(data, visible=False)
    result = q.describe(node, limit=100, include_state_table=True)
    assert result["state_table"]["reason"] == "state_table_unavailable"
    assert not result["state_table"]["rows"] and "private text" not in str(result)


def test_text_and_response_limits_do_not_claim_complete_delivery(monkeypatch):
    import mcpserver.tools as tools

    rows = [DEFAULT_ROW.replace("/>", ' Text="' + "x" * 600 + '"/>')] * 100
    q, node = visible_query(xml(rows))
    detail = q.describe(node, limit=100, include_state_table=True)
    assert detail["state_table"]["rows"][0]["text_truncated"]
    assert not detail["state_table"]["complete"]
    envelope = tools.ProjectDescriptionEnvelope(
        ok=True, data=detail, observed_at="synthetic", stale=False, trace_id="synthetic"
    )
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 4000)
    assert tools._fit_project_state_table(envelope)
    table = envelope.data.state_table
    assert table.rows_omitted > 0 and table.rows_total == 100
    assert len(table.rows) + table.rows_omitted == 100
    assert table.reason == "max_response_bytes" and not table.complete
    assert len(envelope.model_dump_json().encode()) <= 4000


def test_ambiguous_state_mapping_does_not_expose_rows():
    data = xml().replace(
        b"</ControlList>",
        xml()
        .split(b'<C Type="State"')[1]
        .split(b"</ControlList>")[0]
        .join([b'<C Type="State"', b"</ControlList>"]),
    )
    q, node = visible_query(data)
    table = q.describe(node, limit=100, include_state_table=True)["state_table"]
    assert table["reason"] == "state_table_unavailable" and not table["rows"]


@pytest.mark.asyncio
async def test_optional_table_tool_contract_and_fresh_authorization(monkeypatch):
    from unittest.mock import AsyncMock

    from mcp.server.fastmcp import FastMCP

    import mcpserver.tools as tools

    q, node = visible_query(xml())
    query = AsyncMock(return_value=(q, SimpleNamespace(connected=True)))
    monkeypatch.setattr(tools, "_project_query", query)
    server = FastMCP("state-table")
    tools.register_project_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_describe_project_object")
    assert tool.parameters["properties"]["include_state_table"]["default"] is False
    result = await tool.fn(node.key, include_state_table=True, limit=100)
    assert result.ok and result.data.state_table.complete
    query.assert_awaited_once()
    query.side_effect = PermissionError()
    denied = await tool.fn(node.key, include_state_table=True)
    assert not denied.ok and denied.data.error == "unauthenticated"


def test_api_port_metadata_has_no_scalar_gap_in_either_direction():
    g = graph(xml())
    node = next(n.key for n in g.nodes if n.source_id == "api")
    for direction in ("upstream", "downstream"):
        result = opening(g).trace([node], direction, 16, 200)
        assert result["gaps"] == []
        assert result["complete"] is True
