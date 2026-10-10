from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneIdentity,
    LoxoneStructure,
    Room,
    StateRecord,
    WindowMonitorItem,
    WindowMonitorSummary,
)
from mcpserver.loxone.opening_contacts import (
    OpeningGraph,
    OpeningScopeError,
    analyze_opening_contacts,
)
from mcpserver.loxone.project.graph import (
    ProjectPartSummary,
    ProjectSnapshot,
    _logical_knx_nodes,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable

CONTACT = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
CONSUMER = "00000000-0000-0000-0000-000000000003"


def control(uuid, kind="EIBsensor", room="room", **kwargs):
    return Control(uuid, "Same display name", kind, room, None, None, (), **kwargs)


def fixture(xml=None, *, extra=()):
    monitor = control(
        "monitor",
        "WindowMonitor",
        window_monitor_items=(
            WindowMonitorItem(0, "Contact", "room", CONTACT, None),
            WindowMonitorItem(1, "Other", "room", OTHER, None),
        ),
        window_monitor_summary=WindowMonitorSummary(2, 2),
    )
    monitor = replace(monitor, state_uuids=(("windowStates", "state"),))
    structure = LoxoneStructure(
        LoxoneIdentity("fixture", "fixture"),
        "v1",
        (Room("room", "Room"),),
        (),
        (monitor, control(CONTACT), control(OTHER), control(CONSUMER, "AutoJalousie"), *extra),
    )
    xml = xml or Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    parsed = parse_project(xml)
    snapshot = ProjectSnapshot(
        "fixture",
        8,
        (ProjectPartSummary("p", len(parsed.elements), ()),),
        build_graph((("p", parsed),)),
    )
    project = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure), "marker"), {})
    return structure, project


def analyze(structure=None, project=None, **kwargs):
    if structure is None:
        structure, project = fixture()
    return analyze_opening_contacts(
        structure,
        project,
        scope_type=kwargs.pop("scope_type", "monitor"),
        scope_uuid=kwargs.pop("scope_uuid", "monitor"),
        candidate_contact_uuids=kwargs.pop("candidate_contact_uuids", []),
        **kwargs,
    )


def test_motivating_topology_proves_review_candidate_without_physical_verdict():
    result = analyze()
    assert result["physical_opening_coverage"] == "not_assessable"
    assert result["completeness"]["graph"]
    assert result["connections"][0]["contact_uuid"] == CONTACT
    kinds = [f["finding_type"] for f in result["findings"]]
    assert "cross_assignment_review_candidate" in kinds
    assert "monitored_without_supported_consumer" in kinds
    upstream = next(e for e in result["evidence"] if e["evidence_id"].startswith("upstream"))
    assert {n["block_type"] for n in upstream["nodes"]} >= {"InputRef", "EIBsensor"}
    assert {n["connector_key"] for n in upstream["nodes"]} >= {"Window", "I1", "I2", "AQ", "Q"}
    assert {e["semantic_rule_id"] for e in upstream["edges"]} >= {
        "or_i1_q_v1",
        "or_i2_q_v1",
        "input_ref_aq_v1",
    }
    tools.OpeningAnalysisData.model_validate(result)


def test_existing_project_describe_and_trace_schemas_accept_reviewed_opening_semantics():
    _, project = fixture()
    graph = OpeningGraph(project)
    consumer = project.resolve(CONSUMER, "runtime_control_uuid")
    window = graph.nodes[graph.connectors(consumer, "Window")[0]]
    trace = project.trace(window, direction="upstream", max_depth=16, max_nodes=200)
    public_trace = tools.ProjectTraceData.model_validate(trace)
    assert {e.interpretation for e in public_trace.semantic_edges} >= {
        "logical_or",
        "reference_projection",
    }
    description = project.describe(project.resolve(CONTACT, "runtime_control_uuid"), limit=100)
    public_description = tools.ProjectDescriptionData.model_validate(description)
    assert {e.interpretation for e in public_description.knx.usage_observations} >= {
        "logical_or",
        "reference_projection",
    }


def test_contact_traces_include_every_exact_logical_source_occurrence():
    structure, _ = fixture()
    canonical = parse_project(
        (f'<P><C Type="EIBsensor" U="{CONTACT}"><Co K="AQ" U="unused-output"/></C></P>').encode()
    )
    wired = parse_project(Path("tests/fixtures/project/opening-contacts.xml").read_bytes())
    graph = build_graph((("a", canonical), ("b", wired)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "multi-source",
        8,
        (
            ProjectPartSummary("a", len(canonical.elements), ()),
            ProjectPartSummary("b", len(wired.elements), ()),
        ),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )
    project = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    mapped = project.resolve(CONTACT, "runtime_control_uuid")
    assert mapped.project == "a"
    result = analyze(structure, project)
    assert result["completeness"]["graph"]
    assert {c["contact_uuid"] for c in result["connections"]} == {CONTACT}
    assert not any(
        f["finding_type"] == "consumer_without_resolved_contact" for f in result["findings"]
    )
    downstream = next(e for e in result["evidence"] if e["evidence_id"] == f"downstream:{CONTACT}")
    assert {n["project_node_id"].split(":")[0] for n in downstream["nodes"]} == {"a", "b"}
    bounded = analyze(structure, project, max_nodes=4)
    assert not bounded["completeness"]["graph"]
    assert not bounded["findings"]


@pytest.mark.parametrize("limit", [{"max_depth": 1}, {"max_nodes": 1}])
def test_trace_limits_prevent_negative_and_cross_assignment_findings(limit):
    result = analyze(**limit)
    assert not result["completeness"]["graph"]
    assert not result["findings"]
    assert result["warnings"]


@pytest.mark.parametrize("replacement", [b'Type="Unknown"', b'Type="OrUnknown"'])
def test_unmodeled_internal_flow_does_not_invent_edges(replacement):
    xml = (
        Path("tests/fixtures/project/opening-contacts.xml")
        .read_bytes()
        .replace(b'Type="Or"', replacement)
    )
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["connections"]
    assert not result["findings"]


def test_unknown_block_with_reference_input_remains_semantically_incomplete():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(b'Type="Or"', b'Type="Unknown"')
    xml = xml.replace(
        b'<Co K="I1" U="or-input-1"><In Input="reference-output"/></Co>',
        f'<Co K="I1" U="or-input-1" Ref="{CONTACT}"/>'.encode(),
    )
    xml = xml.replace(b'<In Input="lockout-output"/>', b"")
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["findings"]


def test_gap_evidence_identifies_both_warning_paths_deterministically():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(b'Type="Or" U="or"', b'Type="Unknown" U="or" Ref="' + CONTACT.encode() + b'"')
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert result == analyze(structure, project)
    gaps = [g for e in result["evidence"] for g in e["gaps"]]
    assert {g["reason"] for g in gaps} == {
        "block_reference_projection_unavailable",
        "parent_boundary_incomplete",
    }
    assert {g["direction"] for g in gaps} == {"upstream", "downstream"}
    assert all(g["block_type"] == "Unknown" for g in gaps)
    for evidence in result["evidence"]:
        nodes = {n["project_node_id"] for n in evidence["nodes"]}
        for gap in evidence["gaps"]:
            assert set(gap["evidence_node_ids"]) <= nodes
            assert gap["project_node_id"] in nodes
            assert not gap["rule_ids"]
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["completeness"]["graph"]
    tools.OpeningAnalysisData.model_validate(result)


def test_gap_evidence_sanitizes_source_tokens_and_preserves_rule_references():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(
        b'<Co K="Q" U="or-output"/>',
        b'<Co K="Q" U="or-output"/><Co K="I3" U="extra" Ref="missing"/>',
    )
    structure, project = fixture(xml)
    gaps = [g for e in analyze(structure, project)["evidence"] for g in e["gaps"]]
    assert any(g["rule_ids"] == ["or_i1_q_v1", "or_i2_q_v1"] for g in gaps)
    xml = xml.replace(b'Type="Or"', b'Type="private / unsafe"').replace(
        b'K="Q"', b'K="' + b"X" * 65 + b'"'
    )
    structure, project = fixture(xml)
    result = analyze(structure, project)
    gaps = [g for e in result["evidence"] for g in e["gaps"]]
    assert gaps
    assert all(g["block_type"] is None for g in gaps)
    assert all(g["connector_key"] is None or len(g["connector_key"]) <= 64 for g in gaps)
    graph = OpeningGraph(project)
    extra = next(n.key for n in graph.nodes.values() if dict(n.attributes).get("K") == "I3")
    trace = graph.trace([extra], "upstream", 16, 200)
    assert "unresolved_relationship" in trace["warnings"]
    assert trace["gaps"][0]["reason"] == "parent_boundary_incomplete"


def test_gap_limits_bound_materialization_and_keep_incompleteness(monkeypatch):
    import mcpserver.loxone.opening_contacts as opening

    xml = (
        Path("tests/fixtures/project/opening-contacts.xml")
        .read_bytes()
        .replace(b'Type="Or"', b'Type="Unknown"')
    )
    structure, project = fixture(xml)
    monkeypatch.setattr(opening, "MAX_GAPS_PER_TRACE", 1)
    monkeypatch.setattr(opening, "MAX_GAPS_PER_CALL", 1)
    result = analyze(structure, project)
    assert sum(len(e["gaps"]) for e in result["evidence"]) == 1
    assert all(len(e["gaps"]) <= 1 for e in result["evidence"])
    assert sum(e["gaps_omitted"] for e in result["evidence"]) > 0
    assert "max_gap_evidence" in result["warnings"]
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["completeness"]["graph"]
    assert not result["findings"]


@pytest.mark.parametrize("direction", ["input", "output", "reference", "disconnected"])
def test_extra_or_connectors_only_allow_negatives_when_disconnected(direction):
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    if direction == "input":
        extra = b'<Co K="I3" U="extra"><In Input="other-output"/></Co>'
    elif direction == "reference":
        extra = f'<Co K="I3" U="extra" Ref="{OTHER}"/>'.encode()
    else:
        extra = b'<Co K="Q2" U="extra"/>'
    xml = xml.replace(b'<Co K="Q" U="or-output"/>', b'<Co K="Q" U="or-output"/>' + extra)
    if direction == "output":
        xml = xml.replace(b'Input="or-output"', b'Input="extra"')
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert result["completeness"]["graph"] is (direction == "disconnected")
    if direction != "disconnected":
        assert "unmodeled_internal_flow" in result["warnings"]
        assert not result["findings"]
    else:
        assert result["findings"]


@pytest.mark.parametrize("relationship", [b'<In Input="missing"/>', b"", b"reference"])
def test_unresolved_extra_or_connector_prevents_negative_findings(relationship):
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    if relationship == b"reference":
        extra = b'<Co K="I3" U="extra" Ref="missing"/>'
    elif relationship:
        extra = b'<Co K="I3" U="extra">' + relationship + b"</Co>"
    else:
        # Two exact source occurrences prevent resolving the raw signal link.
        xml = xml.replace(
            b"</P>", b'<C Type="PushButton" U="duplicate"><Co K="Q" U="other-output"/></C></P>'
        )
        extra = b'<Co K="I3" U="extra"><In Input="other-output"/></Co>'
    xml = xml.replace(b'<Co K="Q" U="or-output"/>', b'<Co K="Q" U="or-output"/>' + extra)
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["completeness"]["graph"]
    assert not result["findings"]


@pytest.mark.parametrize("source", ["contact-output", "missing", None])
def test_extra_consumer_input_is_not_an_alias_for_window(source):
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(b'<In Input="or-output"/>', b"")
    extra = b'<Co K="Dwc" U="extra">'
    if source:
        extra += f'<In Input="{source}"/>'.encode()
    extra += b"</Co>"
    xml = xml.replace(
        b'<Co K="Window" U="window-input"></Co>', b'<Co K="Window" U="window-input"></Co>' + extra
    )
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert not result["connections"]
    assert result["completeness"]["graph"] is (source is None)
    if source:
        assert "unmodeled_internal_flow" in result["warnings"]
        assert not result["findings"]
    else:
        assert any(
            f["finding_type"] == "consumer_without_resolved_contact" for f in result["findings"]
        )


@pytest.mark.parametrize("source", ["other-output", "missing"])
def test_extra_reference_projection_input_is_incomplete(source):
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(
        b'<Co K="AQ" U="reference-output"/>',
        b'<Co K="AQ" U="reference-output"/>'
        + f'<Co K="I3" U="extra"><In Input="{source}"/></Co>'.encode(),
    )
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert "unmodeled_internal_flow" in result["warnings"]
    assert not result["completeness"]["graph"]
    assert not result["findings"]


def test_reference_projection_requires_exact_ref_and_unique_output():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    for broken in (
        xml.replace(CONTACT.encode(), b"missing", 1),
        xml.replace(b'K="AQ" U="reference-output"', b'K="Q" U="reference-output"'),
    ):
        structure, project = fixture(broken)
        result = analyze(structure, project)
        assert not result["completeness"]["graph"]
        assert not result["connections"]
        assert not result["findings"]


def test_names_and_room_membership_do_not_discover_contact_roles():
    structure, project = fixture(extra=(control("not-a-contact", "Switch"),))
    result = analyze(structure, project)
    assert "not-a-contact" not in {c["control_uuid"] for c in result["contacts"]}
    result = analyze(structure, project, candidate_contact_uuids=["not-a-contact"])
    candidate = next(c for c in result["contacts"] if c["control_uuid"] == "not-a-contact")
    assert candidate["evidence_kinds"] == ["caller_selected_candidate"]
    assert not result["completeness"]["mapping"]


@pytest.mark.parametrize(
    "scope,uuid", [("room", "room"), ("contact", CONTACT), ("consumer", CONSUMER)]
)
def test_exact_scopes(scope, uuid):
    result = analyze(scope_type=scope, scope_uuid=uuid)
    assert result["scope_uuid"] == uuid
    assert result["connections"]


def test_monitor_only_result_and_unknown_hidden_targets_are_indistinguishable():
    structure, _ = fixture()
    unknown = control(
        "monitor",
        "WindowMonitor",
        window_monitor_items=(
            WindowMonitorItem(0, None, "missing-room", "unavailable", None),
            WindowMonitorItem(1, None, "room", "unavailable", None),
            WindowMonitorItem(2, None, None, None, None, ("invalid_window_monitor_entry",)),
        ),
        window_monitor_summary=WindowMonitorSummary(101, 3, 98, True),
    )
    structure = replace(structure, controls=(unknown,))
    result = analyze(structure)
    hidden = replace(structure, hidden_controls=(control("unavailable"),))
    assert analyze(hidden) == result
    assert result["duplicates"][0]["control_uuid"] == "unavailable"
    assert result["counts"]["unresolved"] == 2
    assert result["counts"]["partially_resolved"] == 1
    assert "project_unavailable" in result["warnings"]
    assert not result["completeness"]["monitors"]


@pytest.mark.parametrize(
    "value,alignment",
    [("0,1", "match"), ("0", "mismatch"), ("0,1,2", "mismatch"), (1.0, "invalid")],
)
def test_state_vector_uses_original_positions(value, alignment):
    structure, project = fixture()
    result = analyze(
        structure,
        project,
        include_current_state=True,
        records={"state": StateRecord("state", value, Freshness.CURRENT, 123.0)},
    )
    assert result["monitors"][0]["state"]["alignment"] == alignment
    assert result["monitors"][0]["state"]["observed_at"] == 123.0
    if value == "0":
        assert [i["state_value"] for i in result["monitors"][0]["items"]] == ["0", None]


@pytest.mark.parametrize("freshness", list(Freshness))
def test_window_analysis_keeps_decoder_and_observation_quality_separate(freshness):
    from mcpserver.loxone.window_states import decode_window_states

    structure, project = fixture()
    value = None if freshness is Freshness.UNAVAILABLE else "1,18"
    result = analyze(
        structure,
        project,
        include_current_state=True,
        records={"state": StateRecord("state", value, freshness, 1)},
    )
    monitor = result["monitors"][0]
    assert monitor["state"]["freshness"] == freshness.value
    assert monitor["state"]["observed_at"] == 1
    if value is not None:
        decoded = decode_window_states(structure.controls[0], value)
        assert [i["decoded_state"] for i in monitor["items"]] == decoded["contacts"]
        assert monitor["state"]["mapping_complete"]
    else:
        assert monitor["state"]["alignment"] == "unavailable"


def test_state_missing_stale_and_invalid_tokens_are_explicit():
    result = analyze(include_current_state=True)
    assert "state_unavailable" in result["monitors"][0]["state"]["warnings"]
    structure, project = fixture()
    result = analyze(
        structure,
        project,
        include_current_state=True,
        records={"state": StateRecord("state", "0,private-value", Freshness.STALE, 1)},
    )
    assert result["completeness"]["states"] == "incomplete"
    assert "private-value" not in str(result)


def test_trace_budget_and_cycles_are_bounded():
    _, project = fixture()
    graph = OpeningGraph(project)
    graph.starts = 200
    assert graph.trace([next(iter(graph.nodes))], "upstream", 16, 200)["warnings"] == [
        "max_trace_starts"
    ]
    structure, project = fixture(b'<P><C U="a" Ref="b"/><C U="b" Ref="a"/></P>')
    graph = OpeningGraph(project)
    trace = graph.trace(["p:1"], "downstream", 16, 200)
    assert len(trace["nodes"]) == 2
    assert len(trace["edges"]) == 2


def test_response_trimming_never_dangles_evidence_or_duplicate_positions(monkeypatch):
    envelope = tools._result(tools.OpeningAnalysisEnvelope, analyze())
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 2500)
    assert tools._fit_opening_analysis(envelope)
    assert len(envelope.model_dump_json().encode()) <= 2500
    data = envelope.data
    ids = {e.evidence_id for e in data.evidence}
    assert all(set(c.evidence_ids) <= ids for c in data.connections)
    assert all(set(f.evidence_ids) <= ids for f in data.findings)
    assert not data.completeness.graph
    assert data.response_units_omitted


class Runtime:
    def __init__(self, structure, project):
        self.snapshot = AsyncMock(return_value=RuntimeSnapshot("family", structure, True))
        self.projects = SimpleNamespace(
            query=AsyncMock(return_value=project), authorize=AsyncMock(), invalidate=Mock()
        )
        self._require_access = AsyncMock()
        self.state = Mock(return_value=StateRecord("state", "0,1", Freshness.CURRENT, 1))

    @asynccontextmanager
    async def call_slot(self, access):
        if "loxone:read" not in access.scopes:
            raise PermissionError
        yield

    project_call_slot = call_slot


async def invoke(monkeypatch, runtime, **kwargs):
    monkeypatch.setattr(
        tools, "_access", lambda: SimpleNamespace(family_id="family", scopes={"loxone:read"})
    )
    server = FastMCP("opening-test")
    tools.register_opening_contact_tool(server, runtime)
    return await server._tool_manager.get_tool("loxone_analyze_opening_contacts").fn(
        scope_type="monitor", scope_uuid="monitor", **kwargs
    )


@pytest.mark.asyncio
async def test_tool_uses_one_fresh_snapshot_and_no_unrequested_states(monkeypatch):
    runtime = Runtime(*fixture())
    result = await invoke(monkeypatch, runtime)
    assert result.ok
    runtime.snapshot.assert_awaited_once()
    assert runtime.snapshot.call_args.kwargs == {"fresh_visibility": True}
    runtime.state.assert_not_called()
    runtime.projects.authorize.assert_awaited_once()
    runtime._require_access.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["project_permission_denied", "project_transport_error"])
async def test_project_failure_retains_monitor_analysis(monkeypatch, code):
    runtime = Runtime(*fixture())
    runtime.projects.query.side_effect = ProjectError(code)
    result = await invoke(monkeypatch, runtime, include_current_state=True)
    assert result.ok
    assert result.data.monitors
    assert not result.data.completeness.graph
    assert result.data.monitors[0].state.alignment == "match"


@pytest.mark.asyncio
async def test_scope_candidates_revocation_and_fresh_visibility_fail_closed(monkeypatch):
    runtime = Runtime(*fixture())
    result = await invoke(monkeypatch, runtime, candidate_contact_uuids=["hidden"])
    assert result.data.error == "not_found"
    runtime.projects.query.assert_not_called()
    runtime.snapshot.side_effect = RuntimeUnavailable("visibility unavailable")
    result = await invoke(monkeypatch, runtime)
    assert not result.ok
    runtime.projects.invalidate.assert_called_once_with("family")
    runtime.snapshot.side_effect = None
    runtime.projects.query.side_effect = ProjectError("project_access_denied")
    assert not (await invoke(monkeypatch, runtime)).ok


def test_unknown_scope_and_candidate_do_not_reveal_hidden_controls():
    structure, project = fixture()
    with pytest.raises(OpeningScopeError):
        analyze(structure, project, scope_uuid="hidden")
    with pytest.raises(OpeningScopeError):
        analyze(structure, project, candidate_contact_uuids=["hidden"])


def test_consumer_allowlist_checks_project_type_as_well_as_connector():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    structure, project = fixture(xml.replace(b'Type="AutoJalousie"', b'Type="UnreviewedConsumer"'))
    result = analyze(structure, project)
    assert "consumer_connector_unresolved" in result["warnings"]
    assert not result["connections"]
    assert not result["findings"]


def test_dense_paths_bound_connection_and_finding_materialization(monkeypatch):
    import mcpserver.loxone.opening_contacts as opening

    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    another = "00000000-0000-0000-0000-000000000004"
    xml = xml.replace(
        b"</P>",
        (
            f'<C Type="AutoJalousie" U="{another}"><Co K="Window" U="second-window">'
            '<In Input="or-output"/></Co></C></P>'
        ).encode(),
    )
    structure, project = fixture(xml, extra=(control(another, "AutoJalousie"),))
    monkeypatch.setattr(opening, "MAX_RESULT_RELATIONSHIPS", 1)
    result = analyze(structure, project)
    assert len(result["connections"]) == 1
    assert result["connections_omitted"] == 1
    assert len(result["findings"]) <= 1
    assert not result["completeness"]["graph"]
    assert all(f["finding_type"] == "contact_feeds_multiple_consumers" for f in result["findings"])


def test_consumer_bound_counts_omissions_without_tracing_unmapped_targets():
    structure, _ = fixture()
    consumers = tuple(control(f"consumer-{i:03}", "AutoJalousie") for i in range(101))
    structure = replace(structure, controls=(*structure.controls[:3], *consumers))
    result = analyze(structure)
    assert result["consumers_omitted"] == 1
    assert "max_consumers" in result["warnings"]


def test_high_fanout_bounds_edges_and_never_leaves_dangling_nodes():
    xml = b'<P><C U="source"><Co K="AQ" U="out"/></C>'
    xml += (
        b"".join(
            f'<C U="t{i}"><Co U="in{i}"><In Input="out"/></Co></C>'.encode() for i in range(1000)
        )
        + b"</P>"
    )
    _, project = fixture(xml)
    graph = OpeningGraph(project)
    seed = next(n.key for n in graph.nodes.values() if n.source_id == "out")
    trace = graph.trace([seed], "downstream", 16, 5)
    assert len(trace["nodes"]) <= 5
    assert len(trace["edges"]) <= 5
    ids = {n["project_node_id"] for n in trace["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in trace["edges"])
    assert not trace["complete"]


def test_multiple_contact_sources_and_multiple_consumers_keep_positive_evidence():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    structure, project = fixture(xml.replace(b'Input="lockout-output"', b'Input="other-output"'))
    result = analyze(structure, project)
    assert len(result["connections"]) == 2
    assert [f["finding_type"] for f in result["findings"]] == ["multiple_contact_sources"]
    another = "00000000-0000-0000-0000-000000000004"
    xml = xml.replace(
        b"</P>",
        (
            f'<C Type="AutoJalousie" U="{another}"><Co K="Window" U="second-window">'
            '<In Input="or-output"/></Co></C></P>'
        ).encode(),
    )
    structure, project = fixture(xml, extra=(control(another, "AutoJalousie"),))
    result = analyze(structure, project)
    assert len(result["connections"]) == 2
    finding = next(
        f for f in result["findings"] if f["finding_type"] == "contact_feeds_multiple_consumers"
    )
    assert set(finding["consumer_uuids"]) == {CONSUMER, another}


@pytest.mark.parametrize("connector", [b"Stop", b"Dwc"])
def test_exact_window_connector_never_uses_other_inputs_or_ui_aliases(connector):
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    structure, project = fixture(xml.replace(b'K="Window"', b'K="' + connector + b'"'))
    result = analyze(structure, project)
    assert "consumer_connector_unresolved" in result["warnings"]
    assert not result["connections"]
    assert not result["findings"]


def test_ambiguous_runtime_mapping_does_not_choose_a_project_node():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(b"</P>", f'<C U="{CONTACT}" Type="EIBsensor"/></P>'.encode())
    structure, project = fixture(xml)
    result = analyze(structure, project)
    assert result["contacts"][0]["mapping_status"] == "ambiguous"
    assert not result["completeness"]["mapping"]
    assert not result["connections"]
    assert not result["findings"]


def test_missing_or_duplicated_connectors_do_not_get_derived_rules():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    for broken in (
        xml.replace(b'K="I2"', b'K="UnknownInput"'),
        xml.replace(
            b'<Co K="Q" U="or-output"/>', b'<Co K="Q" U="or-output"/><Co K="Q" U="duplicate"/>'
        ),
    ):
        structure, project = fixture(broken)
        result = analyze(structure, project)
        assert not result["completeness"]["graph"]
        assert not result["findings"]


def test_monitor_and_candidate_omissions_are_counted_and_prevent_absence_claims():
    structure, project = fixture()
    original = structure.controls[0]
    monitors = tuple(replace(original, uuid=f"monitor-{i:03}") for i in range(101))
    bounded = replace(structure, controls=(*monitors, *structure.controls[1:]))
    result = analyze(bounded, scope_type="room", scope_uuid="room")
    assert len(result["monitors"]) == 100
    assert result["monitors_omitted"] == 1
    assert not result["completeness"]["monitors"]
    candidates = [f"candidate-{i:03}" for i in range(100)]
    structure = replace(
        structure, controls=(*structure.controls, *(control(c) for c in candidates))
    )
    result = analyze(
        structure,
        project,
        scope_type="contact",
        scope_uuid=CONTACT,
        candidate_contact_uuids=candidates,
    )
    assert len(result["contacts"]) == 100
    assert result["contacts_omitted"] >= 1
    assert CONTACT in {c["control_uuid"] for c in result["contacts"]}
    assert not result["findings"]


def test_unselected_truncated_monitor_prevents_complete_scoped_inventory_claim():
    structure, project = fixture()
    monitor = replace(
        structure.controls[0],
        window_monitor_items=(),
        window_monitor_summary=WindowMonitorSummary(101, 0, 101, True),
    )
    structure = replace(structure, controls=(monitor, *structure.controls[1:]))
    result = analyze(structure, project, scope_type="contact", scope_uuid=CONTACT)
    assert result["monitors"] == []
    assert "scope_selection_incomplete" in result["warnings"]
    assert not result["findings"]


def test_room_mismatch_and_explicit_links_have_separate_provenance():
    structure, project = fixture()
    monitor = structure.controls[0]
    items = (
        replace(monitor.window_monitor_items[0], room_uuid="other-room"),
        monitor.window_monitor_items[1],
    )
    source = replace(structure.controls[1], linked_control_uuids=(OTHER, "hidden"))
    structure = replace(
        structure,
        rooms=(*structure.rooms, Room("other-room", "Other")),
        controls=(replace(monitor, window_monitor_items=items), source, *structure.controls[2:]),
    )
    result = analyze(structure, project)
    assert result["counts"]["mismatched"] == 1
    other = next(c for c in result["contacts"] if c["control_uuid"] == OTHER)
    assert set(other["evidence_kinds"]) == {"direct_monitor_reference", "explicit_control_link"}
    assert "hidden" not in str(result)


@pytest.mark.asyncio
async def test_tool_schema_validation_and_read_scope_are_enforced(monkeypatch):
    runtime = Runtime(*fixture())
    server = FastMCP("opening-contract")
    tools.register_opening_contact_tool(server, runtime)
    tool = server._tool_manager.get_tool("loxone_analyze_opening_contacts")
    assert tool.annotations.readOnlyHint
    assert set(tool.parameters["required"]) == {"scope_type", "scope_uuid"}
    assert tool.parameters["properties"]["max_depth"]["maximum"] == 16
    for arguments in (
        {"max_nodes": 201},
        {"scope_type": "all"},
        {"candidate_contact_uuids": ["x"] * 101},
    ):
        with pytest.raises(Exception, match="validation"):
            await server._tool_manager.call_tool(
                "loxone_analyze_opening_contacts",
                {"scope_type": "monitor", "scope_uuid": "monitor", **arguments},
            )
    monkeypatch.setattr(tools, "_access", lambda: SimpleNamespace(scopes=set()))
    result = await tool.fn(scope_type="monitor", scope_uuid="monitor")
    assert not result.ok
    assert result.data.error == "unauthenticated"


@pytest.mark.asyncio
async def test_release_authorization_and_next_identity_visibility_are_rechecked(monkeypatch):
    runtime = Runtime(*fixture())
    runtime._require_access.side_effect = RuntimeUnavailable("authorization revoked")
    result = await invoke(monkeypatch, runtime)
    assert not result.ok
    runtime._require_access.side_effect = None
    structure, _ = fixture()
    runtime.snapshot.return_value = RuntimeSnapshot(
        "new-family", replace(structure, controls=()), True
    )
    result = await invoke(monkeypatch, runtime)
    assert result.data.error == "not_found"


def test_anonymized_live_state_gap_preserves_exact_wiring_without_internal_inference():
    # Authorized target: InputRef.AQ -> State.I2; State.AQ -> WindowsMonitor.Wh.
    # Synthetic identities and only the two configured relationships are retained.
    _, project = fixture(Path("tests/fixtures/project/opening-gap-state.xml").read_bytes())
    graph = OpeningGraph(project)
    source = next(n.key for n in graph.nodes.values() if n.source_id == "reference-output")
    trace = graph.trace([source], "downstream", 16, 200)
    assert not trace["complete"]
    assert trace["warnings"] == ["unmodeled_internal_flow"]
    gap = next(g for g in trace["gaps"] if g["block_type"] == "State")
    assert gap["direction"] == "downstream"
    assert gap["connector_key"] == "I2"
    assert gap["reason"] == "state_version_unverified"
    assert not gap["rule_ids"]
    assert gap["reference_projection_rule_id"] is None
    assert not any(n["connector_key"] == "Wh" for n in trace["nodes"])
    assert not any(e["kind"] == "derived_semantic" for e in trace["edges"])
    assert any(
        e.kind == "signal"
        and graph.nodes[e.source].source_id == "state-output"
        and graph.nodes[e.target].source_id == "monitor-input"
        for e in project.view.snapshot.graph.edges
    )


def test_default_per_trace_gap_limit_and_exhausted_trace_shape():
    xml = (
        b'<P><C Type="Source" U="source"><Co K="Q" U="source-out"/></C>'
        b'<C Type="Unknown" U="unknown">'
    )
    xml += b"".join(
        f'<Co K="I{i}" U="in{i}"><In Input="source-out"/></Co>'.encode() for i in range(25)
    )
    xml += (
        b'<Co K="Q" U="output"/></C><C Type="Sink" U="sink">'
        b'<Co K="I" U="sink-in"><In Input="output"/></Co></C></P>'
    )
    _, project = fixture(xml)
    graph = OpeningGraph(project)
    seeds = [
        n.key
        for n in graph.nodes.values()
        if n.kind == "connector" and n.source_id.startswith("in")
    ]
    trace = graph.trace(seeds, "upstream", 16, 200)
    assert len(trace["gaps"]) == 20
    assert trace["gaps_omitted"] == 5
    assert "max_gap_evidence" in trace["warnings"]
    graph.starts = 200
    exhausted = graph.trace(seeds, "upstream", 16, 200)
    assert exhausted["gaps"] == []
    assert exhausted["gaps_omitted"] == 0
    assert exhausted["warnings"] == ["max_trace_starts"]


def test_gap_evidence_does_not_expand_runtime_visibility():
    xml = (
        Path("tests/fixtures/project/opening-contacts.xml")
        .read_bytes()
        .replace(b'Type="Or"', b'Type="Unknown"')
    )
    structure, project = fixture(xml)
    result = analyze(structure, project)
    hidden = replace(structure, hidden_controls=(control("private-hidden"),))
    assert analyze(hidden, project) == result
    with pytest.raises(OpeningScopeError):
        analyze(hidden, project, scope_type="contact", scope_uuid="private-hidden")
    with pytest.raises(OpeningScopeError):
        analyze(hidden, project, candidate_contact_uuids=["private-hidden"])
    assert "private-hidden" not in str(result)


def test_response_trimming_keeps_gap_references_inside_retained_traces(monkeypatch):
    xml = (
        Path("tests/fixtures/project/opening-contacts.xml")
        .read_bytes()
        .replace(b'Type="Or"', b'Type="Unknown"')
    )
    structure, project = fixture(xml)
    data = tools.OpeningAnalysisData.model_validate(analyze(structure, project))
    assert any(e.gaps for e in data.evidence)
    envelope = tools.OpeningAnalysisEnvelope(
        ok=True, data=data, observed_at="now", stale=False, trace_id="fixture"
    )
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 4500)
    assert tools._fit_opening_analysis(envelope)
    assert len(envelope.model_dump_json().encode()) <= 4500
    assert "unmodeled_internal_flow" in data.warnings
    assert not data.completeness.graph
    for trace in data.evidence:
        ids = {n.project_node_id for n in trace.nodes}
        assert all(set(g.evidence_node_ids) <= ids and g.project_node_id in ids for g in trace.gaps)


def test_old_trace_shape_remains_schema_compatible():
    result = analyze()
    for evidence in result["evidence"]:
        del evidence["gaps"]
        del evidence["gaps_omitted"]
    data = tools.OpeningAnalysisData.model_validate(result)
    assert all(not e.gaps and e.gaps_omitted == 0 for e in data.evidence)


def test_nested_block_gap_uses_reached_block_metadata_not_containing_block():
    xml = Path("tests/fixtures/project/opening-contacts.xml").read_bytes()
    xml = xml.replace(
        b'<C Type="Or" U="or">',
        b'<C Type="Or" U="outer"><C Type="Unknown" U="or" Ref="' + CONTACT.encode() + b'">',
    )
    xml = xml.replace(b'<Co K="Q" U="or-output"/>', b'<Co K="Q" U="or-output"/></C>')
    structure, project = fixture(xml)
    result = analyze(structure, project)
    gaps = [
        g
        for e in result["evidence"]
        for g in e["gaps"]
        if g["reason"] == "block_reference_projection_unavailable"
    ]
    assert gaps
    assert all(g["node_kind"] == "block" and g["block_type"] == "Unknown" for g in gaps)
    assert all(not g["rule_ids"] and g["reference_projection_rule_id"] is None for g in gaps)


def test_supported_state_edges_preserve_hidden_scope_boundary():
    xml = Path("tests/fixtures/project/state-original-274.xml").read_bytes()
    structure, project = fixture(xml)
    assert len(project.view.snapshot.graph.semantic_edges) == 3
    result = analyze(structure, project)
    hidden = replace(structure, hidden_controls=(control("private-hidden"),))
    assert analyze(hidden, project) == result
    with pytest.raises(OpeningScopeError):
        analyze(hidden, project, scope_type="contact", scope_uuid="private-hidden")
    with pytest.raises(OpeningScopeError):
        analyze(hidden, project, candidate_contact_uuids=["private-hidden"])
    assert "private-hidden" not in str(result)
