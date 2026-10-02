"""Fixture evidence for the raw sensor slice, not live Modbus acceptance."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.loxone.project.graph import GraphEdge, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, RuntimeMapping
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError
from mcpserver.schema_reference import schema_reference_json
from mcpserver.tools import ProjectModbusData, ProjectNodeData, ProjectSearchNodeSummaryData

FIXTURES = Path(__file__).parent / "fixtures/project/modbus"


def query(source: bytes, *, parts=("part-a",)):
    graph = build_graph(tuple((part, parse_project(source)) for part in parts))
    snapshot = ProjectSnapshot("fixture", 1, (), graph)
    return ProjectQuery(ProjectView(snapshot, RuntimeMapping("fixture", "v1", ())), {})


def sensors(project):
    return project.find(
        query=None,
        kind="block",
        block_type="ModbusASensor",
        source_id=None,
        runtime_control_uuid=None,
    )


@pytest.mark.parametrize(
    "fixture,count,transport",
    [
        ("rtu-meter.xml", 9, "Comm485"),
        ("rtu-hvac.xml", 13, "Comm485"),
        ("tcp-gen24.xml", 4, "ModbusServer"),
    ],
)
def test_public_original_shapes_and_typed_projection(fixture, count, transport):
    project = query((FIXTURES / fixture).read_bytes())
    found = sensors(project)
    assert len(found) == count
    for summary in found:
        projected = ProjectSearchNodeSummaryData.model_validate(summary).modbus
        assert projected is not None
        assert projected.ancestry_truncated
        detail = project.describe(
            project.resolve(summary["project_node_id"], "project_node_id"), limit=100
        )
        validated = ProjectNodeData.model_validate(detail).modbus
        assert validated is not None
        assert [a.source_type for a in validated.ancestors] == ["ModbusDev", transport]
        assert not validated.coverage_complete
        assert not validated.ancestry_truncated
        assert detail["knx"] is None
        assert detail["child_project_node_ids"]
        assert all(a.relationship == "contains" for a in validated.ancestors)


@pytest.mark.parametrize(
    "attrs,status,value,occurrences",
    [
        ("", "absent", None, 0),
        ('ModbusAddress="0"', "explicit", "0", 1),
        ('ModbusAddress="123" ModbusAddress="123"', "explicit", "123", 2),
        ('ModbusAddress="123" ModbusAddress="124"', "ambiguous", None, 2),
        ('ModbusAddress="bad"', "invalid", None, 1),
        ('ModbusAddress=""', "invalid", None, 1),
        ('ModbusAddress="' + "1" * 65 + '"', "invalid", None, 1),
    ],
)
def test_field_evidence_status_and_occurrence_preservation(attrs, status, value, occurrences):
    project = query(f'<P><C Type="ModbusASensor" {attrs}/></P>'.encode())
    node = project.view.snapshot.graph.nodes[0]
    data = ProjectModbusData.model_validate(project.describe(node, limit=100)["modbus"])
    address = data.fields[0]
    assert address.evidence_status == status
    assert address.raw_value == value
    assert len(address.occurrences) == occurrences
    assert data.ancestry_status == "absent"
    assert len(node.attributes) == occurrences + 1
    assert all(f.semantics == "unresolved" for f in data.fields)


def test_bounded_occurrences_and_no_arbitrary_content():
    attrs = " ".join('ModbusCmd="3"' for _ in range(12))
    project = query(
        (
            f'<P><C Type="ModbusASensor" {attrs} Notes="secret" Address="private" '
            'ModbusDataType="credential"/></P>'
        ).encode()
    )
    detail = project.describe(project.view.snapshot.graph.nodes[0], limit=1)
    data = ProjectModbusData.model_validate(detail["modbus"])
    assert len(data.fields[1].occurrences) == 8
    assert data.fields[1].occurrences_omitted == 4
    serialized = json.dumps(detail)
    assert (
        "secret" not in serialized
        and "private" not in serialized
        and "credential" not in serialized
    )


@pytest.mark.parametrize(
    "source_type",
    ["Comm485", "ModbusDev", "ModbusServer", "ModbusAActor", "ModbusDSensor", "Unknown"],
)
def test_only_exact_analog_sensor_is_supported(source_type):
    project = query(f'<P><C Type="{source_type}" ModbusAddress="1"/></P>'.encode())
    detail = project.describe(project.view.snapshot.graph.nodes[0], limit=100)
    assert detail["modbus"] is None
    if source_type in {"ModbusAActor", "ModbusDSensor"}:
        assert {"code": "unsupported_modbus_source_type"} in detail["source_diagnostics"]
        ProjectNodeData.model_validate(detail)
    with pytest.raises(ProjectQueryError):
        project.find(
            query=None,
            kind=None,
            block_type=None,
            source_id=None,
            runtime_control_uuid=None,
            technology="modbus",
        )


def test_equal_registers_and_repeated_parts_are_separate_occurrences():
    source = (
        b'<P><C Type="ModbusServer"><C Type="ModbusDev" Channel="1">'
        b'<C Type="ModbusASensor" U="same" ModbusAddress="10"/></C>'
        b'<C Type="ModbusDev" Channel="2">'
        b'<C Type="ModbusASensor" U="same" ModbusAddress="10"/></C></C></P>'
    )
    project = query(source, parts=("part-a", "part-b"))
    found = sensors(project)
    assert len(found) == 4
    assert len({s["project_node_id"] for s in found}) == 4
    assert {s["modbus"]["model_source_id"] for s in found} == {"part-a", "part-b"}
    for item in found:
        assert item["source_occurrence_count"] == 1
        assert (
            item["modbus"]["ancestors"][0]["model_source_id"] == item["modbus"]["model_source_id"]
        )


def test_parent_ambiguity_and_cycle_do_not_guess():
    project = query(
        b'<P><C Type="ModbusDev"><C Type="ModbusASensor"/></C><C Type="ModbusServer"/></P>'
    )
    graph = project.view.snapshot.graph
    device, sensor, server = graph.nodes
    for extra, expected in [
        (GraphEdge(server.key, sensor.key, "contains"), "ambiguous"),
        (GraphEdge(sensor.key, device.key, "contains"), "invalid"),
    ]:
        snapshot = replace(project.view.snapshot, graph=replace(graph, edges=(*graph.edges, extra)))
        changed = ProjectQuery(ProjectView(snapshot, project.view.mapping), {})
        data = ProjectModbusData.model_validate(changed.describe(sensor, limit=100)["modbus"])
        assert data.ancestry_status == expected


def test_fixture_provenance_is_public_and_versioned():
    entries = json.loads((FIXTURES / "provenance.json").read_text())
    assert len(entries) == 3
    assert all(
        len(e["source_sha256"]) == 64 and e["public_source"].startswith("https://") for e in entries
    )
    assert [e["object_versions"] for e in entries] == [["115"], ["115"], ["163"]]


def test_ancestor_parser_diagnostics_and_direct_connector_evidence():
    project = query(
        b'<P><C Type="ModbusDev" Channel="1" Channel="2">'
        b'<C Type="ModbusASensor"><Co U="q" K="Q"/><Co U="qe" K="Qe"/></C></C>'
        b'<C Type="Other"><Co K="I"><In Input="q"/></Co></C></P>'
    )
    node = project.resolve(sensors(project)[0]["project_node_id"], "project_node_id")
    detail = project.describe(node, limit=100)
    # Parser diagnostics are populated by the snapshot builder; emulate that source index here.
    from mcpserver.loxone.project.graph import ProjectSourceDiagnostics

    snapshot = replace(
        project.view.snapshot,
        source_diagnostics=ProjectSourceDiagnostics(
            (), True, 0, parser_codes_by_node=(("part-a:1", ("parser_duplicate_attribute",)),)
        ),
    )
    changed = ProjectQuery(ProjectView(snapshot, project.view.mapping), {})
    data = ProjectNodeData.model_validate(changed.describe(node, limit=100)).modbus
    assert data.ancestors[0].fields[0].evidence_status == "ambiguous"
    assert data.ancestors[0].source_diagnostics[0].code == "parser_duplicate_attribute"
    assert len(detail["child_project_node_ids"]) == 2
    connector = changed.resolve(detail["child_project_node_ids"][0], "project_node_id")
    assert changed.describe(connector, limit=100)["relationships"][0]["kind"] == "signal"
    assert changed.describe(connector, limit=100)["modbus"] is None


@pytest.mark.asyncio
async def test_registered_description_byte_bound_and_revocation(monkeypatch):
    project = query((FIXTURES / "tcp-gen24.xml").read_bytes())
    identifier = sensors(project)[0]["project_node_id"]

    async def project_query(_runtime):
        return project, SimpleNamespace(connected=True)

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    server = FastMCP("modbus-contract")
    tools_module.register_project_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_describe_project_object")
    result = await tool.fn(identifier, limit=100)
    assert result.ok and result.data.modbus
    original_bytes = len(result.model_dump_json().encode())
    monkeypatch.setattr(tools_module, "PROJECT_RESPONSE_MAX_BYTES", original_bytes - 100)
    bounded = await tool.fn(identifier, limit=100)
    assert bounded.ok and bounded.data.modbus.ancestry_truncated
    assert len(bounded.model_dump_json().encode()) <= original_bytes - 100
    monkeypatch.setattr(tools_module, "PROJECT_RESPONSE_MAX_BYTES", 100)
    oversized = await tool.fn(identifier, limit=100)
    assert not oversized.ok and oversized.data.error == "response_too_large"

    async def revoked(_runtime):
        raise ProjectError("project_access_denied")

    monkeypatch.setattr(tools_module, "_project_query", revoked)
    denied = await tool.fn(identifier, limit=100)
    assert not denied.ok and denied.data.error == "permission_denied"
    assert "modbus" not in denied.data.model_dump()


def test_generated_schema_contains_the_optional_typed_projection():
    catalog = json.loads(schema_reference_json("test"))
    for name in ("loxone_find_project_objects", "loxone_describe_project_object"):
        schema = next(t for t in catalog["tools"] if t["name"] == name)["outputSchema"]
        assert "ProjectModbusData" in schema["$defs"]
        fields = schema["$defs"]["ProjectModbusFieldData"]["properties"]
        assert fields["evidence_status"]["enum"] == ["explicit", "absent", "ambiguous", "invalid"]
        assert fields["occurrences"]["maxItems"] == 8


def test_modbus_projection_does_not_expand_trace_or_observability():
    project = query((FIXTURES / "tcp-gen24.xml").read_bytes())
    node = project.resolve(sensors(project)[0]["project_node_id"], "project_node_id")
    trace = project.trace(node, direction="downstream", max_depth=8, max_nodes=100)
    observability = project.observable_controls(node, direction="both", max_depth=8, max_nodes=100)
    assert "modbus" not in trace["start"]
    assert all("modbus" not in item for item in trace["nodes"])
    assert "modbus" not in observability["target"]
    assert "modbus" not in json.dumps(trace)
    assert "modbus" not in json.dumps(observability)
    catalog = json.loads(schema_reference_json("test"))
    for name in ("loxone_trace_project_logic", "loxone_analyze_observability"):
        schema = next(t for t in catalog["tools"] if t["name"] == name)["outputSchema"]
        assert "ProjectModbusData" not in schema["$defs"]
        assert "modbus" not in schema["$defs"]["ProjectNodeSummaryData"]["properties"]
