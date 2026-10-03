"""Public-derived inventory shapes and explicitly synthetic foundation mutations.

These tests provide static fixture evidence, never live Modbus acceptance.
"""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

import mcpserver.tools as tools
from mcpserver.loxone.project.graph import (
    GraphEdge,
    ProjectPartSummary,
    ProjectSnapshot,
    ProjectSourceDiagnostics,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, RuntimeMapping
from mcpserver.loxone.project.modbus_analysis import (
    MODBUS_ANALYSES,
    ModbusLimits,
    ProjectModbusAnalysisData,
    analyze_modbus,
    finding_id,
    resolve_ancestry,
    validate_modbus_selection,
)
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.project.worker import process_analysis

FIXTURES = Path(__file__).parent / "fixtures/project/modbus"
BOTH = frozenset({"inventory", "evidence_gaps"})


def view(xml=b"<P/>", parts=("part-a",)):
    parsed = parse_project(xml)
    graph = build_graph(tuple((part, parsed) for part in parts))
    sources = tuple(ProjectPartSummary(p, len(parsed.elements), ()) for p in parts)
    return ProjectView(
        ProjectSnapshot("fixture", 1, sources, graph), RuntimeMapping("fixture", "v1", ())
    )


def analyze(project, selected=BOTH, **kwargs):
    return ProjectModbusAnalysisData.model_validate(analyze_modbus(project, selected, **kwargs))


def test_check_counts_include_unsupported_and_unresolved_occurrences():
    result = analyze(view(b'<P><C Type="ModbusAActor"/><C ModbusAddress="1"/></P>'))
    for status in result.check_status.values():
        assert status.eligible_occurrences.value == 2
        assert status.evaluated_occurrences.value == 2
        assert status.excluded_occurrences.value == 0


@pytest.mark.parametrize("padding", [b"", b"<X/>" * 7])
def test_overlapping_candidate_and_ancestor_roles_keep_distinct_occurrence_counts(padding):
    result = analyze(
        view(
            b'<P><X/><C Type="Comm485" ModbusAddress="1">'
            + padding
            + b'<C Type="ModbusDev"><C Type="ModbusASensor"/></C></C></P>'
        )
    )
    role = next(t for t in result.coverage_by_source_type if t.source_type == "Comm485")
    assert role.source_occurrences.value == 1
    assert role.unresolved_candidate_occurrences.value == 1
    for status in result.check_status.values():
        assert status.eligible_occurrences.value == 3
        assert status.evaluated_occurrences.value == 3
    identities = {
        i.project_node_id
        for f in result.findings
        if f.analysis == "inventory"
        for i in f.affected_occurrences
    }
    assert len(identities) == 3


@pytest.mark.parametrize("sensor_limit", [1, 10_000])
def test_gap_only_inspection_is_not_non_gap_sensor_evaluation(sensor_limit):
    project = view(b'<P><C Type="ModbusASensor"/><C Type="ModbusASensor"/></P>')
    result = analyze(
        project, frozenset({"evidence_gaps"}), limits=ModbusLimits(sensor_occurrences=sensor_limit)
    )
    assert result.coverage.evaluated_sensor_occurrences.value == 0
    assert result.coverage.evaluated_sensor_occurrences.count_kind == "exact"
    assert result.check_status["evidence_gaps"].evaluated_occurrences.value == min(sensor_limit, 2)


@pytest.mark.parametrize("source_type,expected", [("Other", 0), ("ModbusAActor", 1)])
def test_irrelevant_relationship_limit_does_not_make_domain_incomplete(source_type, expected):
    project = view(
        f'<P><C Type="Other"><C Type="Other"><C Type="{source_type}"/></C></C></P>'.encode()
    )
    result = analyze(project, limits=ModbusLimits(relationships=1))
    assert result.coverage.candidate_scan_complete
    assert "max_relationships" not in result.truncation_reasons
    for status in result.check_status.values():
        assert status.status == "complete"
        assert status.eligible_occurrences.value == expected
        assert status.eligible_occurrences.count_kind == "exact"
        assert status.evaluated_occurrences.value == expected
        assert status.evaluated_occurrences.count_kind == "exact"


def test_unobserved_hierarchy_is_in_inventory_but_excluded_from_raw_gap_check():
    result = analyze(view(b'<P><C Type="ModbusDev"/></P>'))
    assert result.check_status["inventory"].evaluated_occurrences.value == 1
    assert result.check_status["evidence_gaps"].eligible_occurrences.value == 1
    assert result.check_status["evidence_gaps"].excluded_occurrences.value == 1
    assert result.coverage.check_exclusions["evidence_gaps"].value == 1
    assert result.check_status["evidence_gaps"].status == "partial"
    assert "hierarchy_fields_not_inspected" in result.check_status["evidence_gaps"].reason_codes
    gap = next(f for f in result.findings if "Hierarchy raw fields" in f.description)
    assert len(gap.affected_occurrences) == 1
    assert gap.affected_occurrences[0].model_source_id == "part-a"


@pytest.mark.parametrize("selected", [BOTH, frozenset({"inventory"})])
def test_unreturned_raw_occurrences_do_not_claim_presentation_truncation(selected):
    project = view(b'<P><C Type="ModbusASensor" ModbusAddress="1"/></P>')
    sensor = next(n for n in project.snapshot.graph.nodes if n.kind == "block")
    repeated = replace(sensor, attributes=sensor.attributes + (("ModbusAddress", "1"),) * 9)
    graph = replace(
        project.snapshot.graph,
        nodes=tuple(repeated if n.key == sensor.key else n for n in project.snapshot.graph.nodes),
    )
    project = replace(project, snapshot=replace(project.snapshot, graph=graph))
    result = analyze(project, selected)
    assert "max_evidence_records" not in result.truncation_reasons


@pytest.mark.parametrize(
    "fixture,sensors,actors,dimension",
    [
        ("rtu-meter.xml", 9, 0, "comm485_ancestry"),
        ("rtu-hvac.xml", 13, 11, "comm485_ancestry"),
        ("tcp-gen24.xml", 4, 3, "modbus_server_ancestry"),
    ],
)
def test_public_fixture_inventory(fixture, sensors, actors, dimension):
    result = analyze(view((FIXTURES / fixture).read_bytes()))
    assert result.coverage.sensor_source_occurrences.value == sensors
    assert result.coverage.sensor_source_occurrences.count_kind == "exact"
    assert result.coverage.actor_source_occurrences.value == actors
    assert result.coverage.transport_dimensions[dimension].value == sensors
    assert result.coverage.installation_coverage == "unknown"
    assert result.coverage.supported_type_coverage_complete == (actors == 0)
    assert all(f.classification != "review_candidate" for f in result.findings)
    sensor_inventory = next(
        f for f in result.findings if f.analysis == "inventory" and f.source_type == "ModbusASensor"
    )
    assert sensor_inventory.ancestry_class == dimension
    assert sensor_inventory.source_occurrences.value == sensors
    assert result == ProjectModbusAnalysisData.model_validate_json(result.model_dump_json())
    assert result.analysis_version == 1


def test_synthetic_type_classification_does_not_guess_or_deduplicate():
    result = analyze(
        view(
            b"""<P>
        <C Type="ModbusASensor" Type="ModbusASensor" U="same"/>
        <C Type="ModbusASensor" Type="ModbusAActor" ModbusAddress="1"/>
        <C ModbusAddress="1"/>
        <C Type="Other" ModbusPollingCycle="2"/>
        <C Type="ModbusDSensor"/><C Type="ModbusAActor"/>
        <C Type="Comm485" Protocol="3"/><C Type="Other" Title="Modbus"/>
        </P>""",
            parts=("part-a", "part-b"),
        )
    )
    assert result.coverage.supported_sensor_occurrences.value == 2
    assert result.coverage.unresolved_candidate_occurrences.value == 6
    assert result.coverage.unsupported_occurrences.value == 4
    sampled = [
        i for f in result.findings if f.analysis == "inventory" for i in f.affected_occurrences
    ]
    assert {i.model_source_id for i in sampled} == {"part-a", "part-b"}
    assert len({(i.model_source_id, i.project_node_id) for i in sampled}) == len(sampled)
    assert "Comm485" not in {t.source_type for t in result.coverage_by_source_type}


def test_empty_domain_and_deferred_selection_contract():
    result = analyze(view())
    assert not result.findings
    assert all(s.status == "complete" for s in result.check_status.values())
    assert validate_modbus_selection(None) == frozenset(MODBUS_ANALYSES)
    with pytest.raises(ValueError, match="not yet implemented"):
        analyze_modbus(view(), validate_modbus_selection(None))


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["inventory", "inventory"],
        ["datatype_consistency"],
        ["unknown"],
        ["inventory", "address_patterns"],
    ],
)
def test_invalid_selection(selection):
    with pytest.raises(ValueError):
        validate_modbus_selection(selection)


def test_raw_statuses_unknown_codes_and_hierarchy_do_not_imply_device_defects():
    result = analyze(
        view(b"""<P><C Type="ModbusASensor" ModbusAddress="0"
        ModbusCmd="3" ModbusCmd="4" ModbusDataType="9999"
        SourceValHigh="bad" DestValHigh="1" DestValHigh="1"/></P>""")
    )
    counts = result.coverage.field_status_counts
    assert {key: value.value for key, value in counts.items()} == {
        "explicit": 3,
        "absent": 1,
        "ambiguous": 1,
        "invalid": 1,
    }
    assert result.coverage.hierarchy_unresolved_occurrences.value == 1
    assert not any(
        e.source_field == "ModbusDataType" and e.evidence_status == "invalid"
        for f in result.findings
        for e in f.evidence
    )
    assert all(f.severity in {"info", "warning"} for f in result.findings)
    assert all(
        f.finding_type in {"modbus_inventory", "modbus_evidence_gap"} for f in result.findings
    )


def test_synthetic_ancestry_conflicts_cycles_depth_and_part_boundary():
    project = view(
        b'<P><C Type="ModbusServer"><C Type="ModbusDev"><C Type="ModbusASensor"/></C></C></P>'
    )
    nodes = {n.key: n for n in project.snapshot.graph.nodes}
    sensor = next(n for n in nodes.values() if n.block_type == "ModbusASensor")
    device = next(n for n in nodes.values() if n.block_type == "ModbusDev")
    server = next(n for n in nodes.values() if n.block_type == "ModbusServer")
    ancestors, status = resolve_ancestry(
        sensor, nodes, {sensor.key: [device.key], device.key: [server.key]}, 1
    )
    assert ancestors == [device] and status == "max_ancestry_depth"
    assert (
        resolve_ancestry(sensor, nodes, {sensor.key: [device.key, server.key]}, 32)[1]
        == "ambiguous"
    )
    assert resolve_ancestry(sensor, nodes, {sensor.key: [sensor.key]}, 32)[1] == "invalid"
    assert (
        resolve_ancestry(
            sensor,
            {**nodes, device.key: replace(device, project="other")},
            {sensor.key: [device.key]},
            32,
        )[1]
        == "invalid"
    )
    assert resolve_ancestry(sensor, nodes, {sensor.key: ["missing"]}, 32)[1] == "invalid"


def test_limit_boundaries_keep_count_truth_and_quota_fairness():
    project = view(b"<P>" + b'<C Type="ModbusASensor"/>' * 3 + b"</P>")
    full = analyze(project, limits=ModbusLimits(candidate_nodes=3, sensor_occurrences=3))
    assert full.coverage.candidate_scan_complete
    assert full.coverage.evaluated_sensor_occurrences.count_kind == "exact"
    over = analyze(project, limits=ModbusLimits(candidate_nodes=2, findings_per_check=1))
    assert not over.coverage.candidate_scan_complete
    assert over.coverage.sensor_source_occurrences.value == 2
    assert over.coverage.sensor_source_occurrences.count_kind == "lower_bound"
    assert {f.analysis for f in over.findings} == BOTH
    assert over.check_status["evidence_gaps"].omitted_count is None
    sensor_cap = analyze(project, limits=ModbusLimits(sensor_occurrences=2, evidence_records=1))
    assert sensor_cap.coverage.sensor_source_occurrences.count_kind == "exact"
    assert sensor_cap.coverage.sensor_source_occurrences.value == 3
    assert sensor_cap.coverage.evaluated_sensor_occurrences.value == 2
    assert sensor_cap.coverage.evaluated_sensor_occurrences.count_kind == "lower_bound"
    assert sensor_cap.coverage.check_exclusions["inventory"].value == 1
    assert any(f.affected_occurrences_omitted for f in sensor_cap.findings)
    assert "max_evidence_records" in sensor_cap.truncation_reasons


def test_relationship_cap_never_establishes_unique_or_absent_parent():
    project = view(
        b'<P><C Type="ModbusServer"><C Type="ModbusDev"><C Type="ModbusASensor"/></C></C></P>'
    )
    graph = project.snapshot.graph
    sensor = next(n for n in graph.nodes if n.block_type == "ModbusASensor")
    server = next(n for n in graph.nodes if n.block_type == "ModbusServer")
    graph = replace(graph, edges=(*graph.edges, GraphEdge(server.key, sensor.key, "contains")))
    project = replace(project, snapshot=replace(project.snapshot, graph=graph))
    result = analyze(project, limits=ModbusLimits(relationships=1))
    assert result.coverage.transport_dimensions["modbus_server_ancestry"].value == 0
    assert result.coverage.graph_gap_counts["max_relationships"].value == 1
    assert "max_relationships" in result.truncation_reasons
    result = analyze(project)
    assert result.coverage.graph_gap_counts["ambiguous"].value == 1


def test_ancestry_derived_counts_are_lower_bounds_when_sensor_evaluation_is_capped():
    project = view(
        b"<P>"
        + (b'<C Type="Comm485"><C Type="ModbusDev"><C Type="ModbusASensor"/></C></C>') * 2
        + b"</P>"
    )
    result = analyze(project, limits=ModbusLimits(sensor_occurrences=1))
    role = next(t for t in result.coverage_by_source_type if t.source_type == "Comm485")
    assert role.source_occurrences.value == 1
    assert role.source_occurrences.count_kind == "lower_bound"
    assert result.coverage.sensor_source_occurrences.value == 2
    assert result.coverage.sensor_source_occurrences.count_kind == "exact"


def test_source_and_presentation_completeness_are_independent():
    project = view(b'<P><C Type="ModbusASensor"/></P>')
    diagnostic_only = replace(
        project,
        snapshot=replace(
            project.snapshot, source_diagnostics=ProjectSourceDiagnostics((), False, 1)
        ),
    )
    result = analyze(diagnostic_only)
    assert result.coverage.source_ingestion_complete
    assert result.coverage.sensor_source_occurrences.count_kind == "exact"
    assert not result.coverage.presentation_complete
    partial = replace(project, snapshot=replace(project.snapshot, source_ingestion_complete=False))
    result = analyze(partial)
    assert not result.coverage.source_ingestion_complete
    assert result.coverage.sensor_source_occurrences.count_kind == "lower_bound"
    assert all(s.status == "partial" for s in result.check_status.values())


def test_source_type_and_model_source_omissions_preserve_aggregate_counts():
    xml = b"<P>" + b"".join(f'<C Type="ModbusUnknown{i}"/>'.encode() for i in range(51)) + b"</P>"
    result = analyze(view(xml, parts=tuple(f"part-{i:02d}" for i in range(33))))
    assert len(result.coverage_by_source_type) == 50 and result.source_types_omitted == 1
    assert len(result.model_sources) == 32 and result.model_sources_omitted == 1
    assert result.coverage.unsupported_occurrences.value == 51 * 33
    assert result.coverage.unsupported_occurrences.count_kind == "exact"


def test_ids_order_and_gap_context_are_selection_independent():
    project = view(b'<P><C Type="ModbusASensor"/></P>')
    both = analyze(project)
    inventory = analyze(project, frozenset({"inventory"}))
    assert [f for f in both.findings if f.analysis == "inventory"] == inventory.findings
    assert inventory.coverage.field_status_counts["absent"].value == 6
    assert inventory.limitations
    reversed_project = replace(
        project,
        snapshot=replace(
            project.snapshot,
            graph=replace(
                project.snapshot.graph, nodes=tuple(reversed(project.snapshot.graph.nodes))
            ),
        ),
    )
    assert analyze(reversed_project) == both
    assert finding_id("inventory", "modbus_inventory", ["a", "b"]) != finding_id(
        "inventory", "modbus_inventory", ["a", "b-more"]
    )


@pytest.mark.asyncio
async def test_real_worker_dispatch_and_unimplemented_default():
    project = view((FIXTURES / "rtu-meter.xml").read_bytes())
    result = await process_analysis(project, BOTH, scope="modbus")
    assert result == analyze_modbus(project, BOTH)
    with pytest.raises(ValueError, match="not yet implemented"):
        await process_analysis(project, frozenset(MODBUS_ANALYSES), scope="modbus")


def envelope(data):
    return tools._PreparedProjectAnalysisEnvelope(
        ok=True,
        data=data.model_copy(deep=True),
        observed_at="fixture",
        stale=False,
        trace_id="trace",
    )


def test_full_envelope_bytes_context_omissions_and_cursor_progress(monkeypatch):
    data = analyze(view(b'<P><C Type="ModbusASensor"/></P>'))
    # Synthetic multibyte identity stresses byte measurement without adding
    # device/project secrets. The finding itself remains within typed limits.
    for f in data.findings:
        f.description = "ä" * 500
    prepared = envelope(data)
    codec = tools._CursorCodec()
    minimal = data.model_copy(deep=True)
    minimal.findings = [data.findings[0]]
    minimal.coverage_by_source_type = []
    minimal.model_sources = []
    cap = len(envelope(minimal).model_dump_json().encode()) + 1000
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", cap)
    assert tools._fit_project_analysis_page(prepared, codec, "scope", None)
    assert len(prepared.model_dump_json().encode()) <= cap
    assert prepared.data.next_cursor
    assert codec.decode("scope", prepared.data.next_cursor) == len(prepared.data.findings)
    assert 0 < len(prepared.data.findings) < len(data.findings)
    assert not prepared.data.coverage.presentation_complete
    assert prepared.data.source_types_omitted == 1
    assert prepared.data.coverage.field_status_counts == data.coverage.field_status_counts
    assert prepared.data.check_status == data.check_status
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 1)
    assert not tools._fit_project_analysis_page(envelope(data), codec, "scope", None)


def test_actual_65536_byte_pages_emit_every_bounded_finding_once():
    xml = (
        b"<P>"
        + b"".join(f'<C Type="ModbusUnknown{i}"/>'.encode() for i in range(50) for _ in range(20))
        + b"</P>"
    )
    data = analyze(view(xml), frozenset({"inventory"}))
    for finding in data.findings:
        finding.description = "ä" * 500
    assert len(envelope(data).model_dump_json().encode("utf-8")) > 65_536
    expected = [f.finding_id for f in data.findings]
    codec = tools._CursorCodec()
    emitted = []
    cursor = None
    while True:
        offset = codec.decode("scope", cursor)
        page = data.model_copy(deep=True)
        page.findings = data.findings[offset : offset + 50]
        page.next_cursor = None
        prepared = envelope(page)
        assert tools._fit_project_analysis_page(prepared, codec, "scope", cursor)
        assert len(prepared.model_dump_json().encode("utf-8")) <= 65_536
        assert prepared.data.findings
        emitted.extend(f.finding_id for f in prepared.data.findings)
        cursor = prepared.data.next_cursor
        if cursor is None:
            break
        assert codec.decode("scope", cursor) > offset
    assert emitted == expected
    assert len(set(emitted)) == len(emitted)


def test_conflicting_raw_pairs_remain_evidence_not_device_invalidity():
    result = analyze(view(b'<P><C Type="ModbusASensor" ModbusCmd="3" ModbusCmd="4"/></P>'))
    evidence = next(e for f in result.findings for e in f.evidence if e.source_field == "ModbusCmd")
    assert evidence.evidence_status == "ambiguous" and evidence.raw_value is None
    assert [o.raw_value for o in evidence.occurrences] == ["3", "4"]
    assert evidence.semantics == "unknown"


def test_truncated_type_labels_do_not_merge_identity_or_change_count_truth():
    prefix = "Modbus" + "A" * 100
    project = view(f'<P><C Type="{prefix}1"/><C Type="{prefix}2"/></P>'.encode())
    result = analyze(project, frozenset({"inventory"}))
    assert len(result.findings) == 2
    assert result.findings[0].source_type == result.findings[1].source_type
    assert result.findings[0].finding_id != result.findings[1].finding_id
    assert all(f.source_type_truncated for f in result.findings)
    assert result.coverage.unsupported_occurrences.value == 2
    assert result.coverage.unsupported_occurrences.count_kind == "exact"
    assert not result.coverage.presentation_complete


@pytest.mark.asyncio
async def test_public_contract_stays_knx_only():
    server = FastMCP("modbus-foundation")
    tools.register_project_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_analyze_project")
    assert tool.parameters["properties"]["scope"]["const"] == "knx"
    assert "ProjectModbusAnalysisData" not in json.dumps(tool.output_schema)
    assert tool.parameters["properties"]["limit"]["minimum"] == 1
    assert tool.parameters["properties"]["limit"]["maximum"] == 50
    with pytest.raises(ValidationError):
        tools.ProjectAnalysisEnvelope.model_validate(envelope(analyze(view())).model_dump())


@pytest.mark.asyncio
async def test_internal_runner_validation_precedes_loading(monkeypatch):
    load = AsyncMock(side_effect=AssertionError("must not load"))
    monkeypatch.setattr(tools, "_project_query", load)
    runner = tools._ProjectAnalysisRunner(None)
    for scope, selected in [
        ("modbus", None),
        ("modbus", []),
        ("modbus", ["inventory", "inventory"]),
        ("modbus", ["address_patterns"]),
        ("knx", ["inventory"]),
        ("other", None),
    ]:
        result = await runner.run(scope, selected)
        assert not result.ok and result.data.error == "invalid_input"
    load.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed", ["family_id", "miniserver_id", "identity_id", "marker", "version"]
)
async def test_internal_cache_cursor_binding_and_reauthorization(monkeypatch, changed):
    project = view(b'<P><C Type="ModbusASensor"/></P>')
    access = SimpleNamespace(family_id="family", miniserver_id="server", identity_id="identity")
    authorize = AsyncMock()

    @asynccontextmanager
    async def slot():
        yield

    runtime = SimpleNamespace(projects=SimpleNamespace(authorize=authorize), worker_slot=slot)
    current = [project]
    monkeypatch.setattr(tools, "_access", lambda: access)
    monkeypatch.setattr(
        tools,
        "_project_query",
        AsyncMock(
            side_effect=lambda _: (ProjectQuery(current[0], {}), SimpleNamespace(connected=False))
        ),
    )
    worker = AsyncMock(side_effect=lambda v, selected, **_: analyze_modbus(v, selected))
    monkeypatch.setattr(tools, "process_analysis", worker)
    runner = tools._ProjectAnalysisRunner(runtime)
    first = await runner.run("modbus", ["inventory", "evidence_gaps"], limit=1)
    assert first.ok and first.stale and first.data.next_cursor
    second = await runner.run("modbus", ["evidence_gaps", "inventory"], first.data.next_cursor, 1)
    assert second.ok and worker.await_count == 1 and authorize.await_count == 2
    cross_scope = await runner.run("knx", ["project_connectivity"], first.data.next_cursor, 1)
    assert not cross_scope.ok and cross_scope.data.error == "invalid_input"
    if changed == "marker":
        current[0] = replace(project, marker="changed")
    elif changed == "version":
        monkeypatch.setattr(tools, "MODBUS_ANALYSIS_VERSION", 2)
    else:
        setattr(access, changed, "changed")
    invalid = await runner.run("modbus", ["inventory", "evidence_gaps"], first.data.next_cursor, 1)
    assert not invalid.ok and invalid.data.error == "invalid_input"
    assert worker.await_count == 1
    current[0] = project
    setattr(
        access,
        changed,
        "family"
        if changed == "family_id"
        else "server"
        if changed == "miniserver_id"
        else "identity",
    )
    monkeypatch.setattr(tools, "MODBUS_ANALYSIS_VERSION", 1)
    authorize.side_effect = PermissionError
    revoked = await runner.run("modbus", ["inventory", "evidence_gaps"], first.data.next_cursor, 1)
    assert not revoked.ok and revoked.data.error == "unauthenticated"
    assert worker.await_count == 1


@pytest.mark.asyncio
async def test_worker_completion_reauthorization_prevents_cache_population(monkeypatch):
    project = view(b'<P><C Type="ModbusASensor"/></P>')
    access = SimpleNamespace(family_id="f", miniserver_id="m", identity_id="i")

    @asynccontextmanager
    async def slot():
        yield

    runtime = SimpleNamespace(
        projects=SimpleNamespace(authorize=AsyncMock(side_effect=PermissionError)), worker_slot=slot
    )
    monkeypatch.setattr(tools, "_access", lambda: access)
    monkeypatch.setattr(
        tools,
        "_project_query",
        AsyncMock(return_value=(ProjectQuery(project, {}), SimpleNamespace(connected=True))),
    )
    monkeypatch.setattr(
        tools, "process_analysis", AsyncMock(return_value=analyze_modbus(project, BOTH))
    )
    runner = tools._ProjectAnalysisRunner(runtime)
    result = await runner.run("modbus", ["inventory"])
    assert not result.ok and result.data.error == "unauthenticated"
    assert not runner.cache
