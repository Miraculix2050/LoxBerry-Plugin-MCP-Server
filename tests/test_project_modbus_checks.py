"""Synthetic decision/bounds cases; public XML remains provenance-backed fixture evidence."""

from dataclasses import replace
from pathlib import Path

import pytest

import mcpserver.tools as tools
from mcpserver.loxone.project.graph import GraphEdge, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, RuntimeMapping
from mcpserver.loxone.project.modbus_analysis import (
    MODBUS_ANALYSES,
    ModbusLimits,
    ProjectModbusAnalysisData,
    analyze_modbus,
)
from mcpserver.loxone.project.parser import parse_project

ALL = frozenset(MODBUS_ANALYSES)


def view(xml, parts=("part",)):
    parsed = parse_project(xml.encode() if isinstance(xml, str) else xml)
    graph = build_graph(tuple((p, parsed) for p in parts))
    return ProjectView(
        ProjectSnapshot("fixture", 1, (), graph), RuntimeMapping("fixture", "v1", ())
    )


def run(project, selected=ALL, **kwargs):
    return ProjectModbusAnalysisData.model_validate(analyze_modbus(project, selected, **kwargs))


def sensor(command="3", address="1", polling="60", datatype="99", extra=""):
    return (
        f'<C Type="ModbusASensor" ModbusCmd="{command}" ModbusAddress="{address}" '
        f'ModbusPollingCycle="{polling}" ModbusDataType="{datatype}" '
        f'SourceValHigh="100" DestValHigh="10" {extra}/>'
    )


def device(*sensors):
    return '<C Type="ModbusServer"><C Type="ModbusDev">' + "".join(sensors) + "</C></C>"


def findings(data, kind):
    return [f for f in data.findings if f.finding_type == kind]


@pytest.mark.parametrize("address", ["0", "1", "40001", "01"])
def test_same_mapping_is_review_candidate_preserving_raw_address(address):
    data = run(view("<P>" + device(sensor(address=address), sensor(address=address)) + "</P>"))
    repeated = findings(data, "configured_mapping_repeated")
    assert len(repeated) == 1
    assert repeated[0].classification == "review_candidate"
    assert repeated[0].severity == "info"
    assert repeated[0].configured_mapping.raw_address == address
    assert repeated[0].configured_mapping.requested_register_table_semantics == "proven"
    assert "MODBUS-Application-Protocol" in repeated[0].configured_mapping.rule_reference
    assert all(e.semantics == "unknown" for e in repeated[0].evidence)
    assert repeated[0].source_occurrences.value == 2
    assert not findings(data, "configured_mapping_attributes_differ")


@pytest.mark.parametrize(
    "xml,parts",
    [
        ("<P>" + device(sensor(address="1"), sensor(address="01")) + "</P>", ("a",)),
        ("<P>" + device(sensor(command="3"), sensor(command="4")) + "</P>", ("a",)),
        ("<P>" + device(sensor()) + device(sensor()) + "</P>", ("a",)),
        ("<P>" + device(sensor()) + "</P>", ("a", "b")),
    ],
)
def test_different_space_lexical_address_device_and_part_never_join(xml, parts):
    assert not findings(run(view(xml, parts)), "configured_mapping_repeated")


@pytest.mark.parametrize("command", ["03", "3.0", " 3", "3 ", "5", ""])
def test_only_exact_fc3_fc4_are_comparable(command):
    data = run(view("<P>" + device(sensor(command=command), sensor(command=command)) + "</P>"))
    assert not findings(data, "configured_mapping_repeated")
    assert data.check_status["configured_register_mappings"].status == "blocked"
    assert data.check_status["configured_register_mappings"].excluded_occurrences.value == 2
    assert findings(data, "configured_polling_summary")
    assert (
        "mapping_command_unsupported"
        in data.check_status["configured_register_mappings"].reason_codes
    )


@pytest.mark.parametrize(
    "extra,expected_status,expected_raw,expected_pairs",
    [
        ('ModbusCmd="9"', "explicit", "9", ["9"]),
        ('ModbusCmd="03"', "explicit", "03", ["03"]),
        ('ModbusCmd="3.0"', "explicit", "3.0", ["3.0"]),
        ('ModbusCmd="3" ModbusCmd="4"', "ambiguous", None, ["3", "4"]),
        ('ModbusCmd=" 3"', "invalid", None, [None]),
        ("", "absent", None, []),
    ],
)
def test_comparison_exclusion_preserves_actual_command_evidence(
    extra, expected_status, expected_raw, expected_pairs
):
    item = sensor().replace('ModbusCmd="3"', extra)
    data = run(view("<P>" + device(item) + "</P>"))
    for check in ("configured_register_mappings", "configured_polling"):
        candidate = next(
            f for f in findings(data, "modbus_evidence_gap") if f.blocked_check == check
        )
        evidence = candidate.evidence[0]
        assert evidence.source_field == "ModbusCmd"
        assert evidence.evidence_status == expected_status
        assert evidence.raw_value == expected_raw
        assert [o.raw_value for o in evidence.occurrences] == expected_pairs
        assert evidence.semantics == "unknown"
        assert candidate.reason_code
        assert candidate.severity == (
            "warning" if expected_status in {"ambiguous", "invalid"} else "info"
        )
    assert not findings(data, "configured_mapping_repeated")
    assert data == ProjectModbusAnalysisData.model_validate_json(data.model_dump_json())


@pytest.mark.parametrize(
    "extra,status,raw",
    [
        ('ModbusAddress=""', "invalid", None),
        ('ModbusAddress="1" ModbusAddress="2"', "ambiguous", None),
        ("", "absent", None),
    ],
)
def test_mapping_address_exclusion_retains_field_evidence(extra, status, raw):
    data = run(view("<P>" + device(sensor().replace('ModbusAddress="1"', extra)) + "</P>"))
    gaps = [
        f
        for f in findings(data, "modbus_evidence_gap")
        if f.blocked_check in {"configured_register_mappings", "configured_polling"}
    ]
    assert len(gaps) == 2
    assert all(f.evidence[0].source_field == "ModbusAddress" for f in gaps)
    assert all(f.evidence[0].evidence_status == status for f in gaps)
    assert all(f.evidence[0].raw_value == raw for f in gaps)


def test_reversed_and_conflicting_ancestry_never_establish_comparison_identity():
    for xml in (
        '<P><C Type="ModbusDev"><C Type="ModbusServer">' + sensor() * 2 + "</C></C></P>",
        '<P><C Type="ModbusServer" Type="Other"><C Type="ModbusDev">'
        + sensor() * 2
        + "</C></C></P>",
    ):
        data = run(view(xml))
        assert not findings(data, "configured_mapping_repeated")
        assert (
            "mapping_ancestry_unresolved"
            in data.check_status["configured_register_mappings"].reason_codes
        )
        assert data.check_status["configured_polling"].evaluated_occurrences.value == 2
        gap = next(
            f
            for f in findings(data, "modbus_evidence_gap")
            if f.reason_code == "mapping_ancestry_unresolved"
        )
        assert gap.evidence[0].evidence_status in {"explicit", "ambiguous"}


def test_raw_differences_and_polling_never_imply_device_invalidity():
    data = run(
        view(
            "<P>"
            + device(sensor(datatype="999", polling="60"), sensor(datatype="888", polling="120"))
            + "</P>"
        )
    )
    differences = findings(data, "configured_mapping_attributes_differ")
    assert {f.comparison_field for f in differences} == {"ModbusDataType", "ModbusPollingCycle"}
    assert all(f.severity == "info" and f.classification == "review_candidate" for f in differences)
    assert all(e.semantics == "unknown" for f in differences for e in f.evidence)
    assert findings(data, "configured_polling_values_differ")[0].polling_unit == "unknown"


def test_absent_conflicting_address_and_attribute_evidence_is_gap_not_difference():
    conflicted = sensor(extra='ModbusAddress="2"')
    missing = sensor().replace('ModbusAddress="1"', "")
    data = run(view("<P>" + device(conflicted, missing) + "</P>"))
    assert data.check_status["configured_register_mappings"].status == "blocked"
    assert not findings(data, "configured_mapping_repeated")
    data = run(view("<P>" + device(sensor(), sensor().replace('ModbusDataType="99"', "")) + "</P>"))
    assert findings(data, "configured_mapping_repeated")
    assert not findings(data, "configured_mapping_attributes_differ")
    assert data.check_status["configured_register_mappings"].status == "partial"
    assert any(
        f.blocked_check == "configured_register_mappings"
        for f in findings(data, "modbus_evidence_gap")
    )


def test_polling_summary_does_not_require_mapping_or_include_actor_repeat_rate():
    xml = "<P>" + sensor(command="7", polling="0") + '<C Type="ModbusAActor" RepeatRate="9"/></P>'
    data = run(view(xml), frozenset({"configured_polling"}))
    summary = findings(data, "configured_polling_summary")
    assert len(summary) == 1 and summary[0].raw_variants == ["0"]
    assert summary[0].polling_unit == "unknown"
    assert data.coverage.evaluated_sensor_occurrences.value == 1
    assert data.check_status["configured_polling"].status == "partial"
    assert data.check_status["configured_polling"].reason_codes


def wired(extra_source="", destination=""):
    return view(
        '<P><C Type="ModbusASensor"><Co U="src" K="Q">' + extra_source + "</Co></C>"
        '<C Type="Other"><Co U="dst" K="I"><In Input="src"/></Co>' + destination + "</C></P>"
    )


def test_direct_edges_and_distinct_consumers_are_separate_counts():
    data = run(wired(destination='<Co U="dst2" K="I2"><In Input="src"/></Co>'))
    item = findings(data, "direct_consumer_summary")[0]
    assert item.direct_edge_count.value == 2
    assert item.consumer_occurrence_count.value == 1
    assert item.direct_slice_complete
    assert len(item.direct_edges) == 2
    assert data.check_status["direct_consumers"].status == "complete"


def test_reference_only_and_no_connectors_never_mean_unused():
    data = run(
        view('<P><C Type="ModbusASensor"><Co U="src" K="Q"/></C><C Type="Other" Ref="src"/></P>')
    )
    item = findings(data, "no_direct_consumer_observed")[0]
    assert item.direct_edge_count.value == 0
    assert item.reference_edge_count.value == 1
    assert item.direct_slice_complete
    assert "indirect or unmodeled use is not excluded" in item.description
    empty = run(view('<P><C Type="ModbusASensor"/></P>'))
    assert empty.check_status["direct_consumers"].status == "partial"
    assert (
        findings(empty, "no_direct_consumer_observed")[0].direct_edge_count.count_kind
        == "lower_bound"
    )


def test_target_owner_ambiguity_preserves_successful_other_edge():
    project = wired(destination='<Co U="dst2" K="I2"><In Input="src"/></Co>')
    graph = project.snapshot.graph
    target = next(n for n in graph.nodes if n.source_id == "dst")
    sensor_node = next(n for n in graph.nodes if n.block_type == "ModbusASensor")
    graph = replace(
        graph,
        edges=(*graph.edges, GraphEdge(sensor_node.key, target.key, "contains")),
    )
    data = run(replace(project, snapshot=replace(project.snapshot, graph=graph)))
    item = findings(data, "direct_consumer_summary")[0]
    assert item.direct_edge_count.value == 1
    assert not item.direct_slice_complete
    assert "target_owner_ambiguous" in data.check_status["direct_consumers"].reason_codes


def test_unresolved_signal_sources_make_zero_observations_partial():
    project = view(
        '<P><C Type="ModbusASensor"><Co U="src" K="Q"/></C>'
        '<C Type="Other"><Co U="dst"><In Input="unknown"/></Co></C></P>'
    )
    data = run(project)
    assert data.check_status["direct_consumers"].status == "partial"
    assert any(f.reason_code == "unresolved_signal_source_not_attributable" for f in data.findings)


def test_connector_and_shared_relationship_limits_preserve_lower_bounds():
    project = view('<P><C Type="ModbusASensor"><Co U="a"/><Co U="b"/></C></P>')
    data = run(project, limits=ModbusLimits(connectors_per_sensor=1))
    assert "max_connectors" in data.truncation_reasons
    item = findings(data, "no_direct_consumer_observed")[0]
    assert item.connectors_inspected.value == 1 and item.connectors_omitted == 1
    assert not item.direct_slice_complete
    data = run(wired(), limits=ModbusLimits(relationships=1))
    assert "max_relationships" in data.truncation_reasons
    assert data.check_status["direct_consumers"].status == "partial"


def test_fair_quotas_and_global_sensor_union_do_not_sum_checks():
    project = view(
        "<P>" + device(sensor(polling="1"), sensor(polling="2"), sensor(polling="3")) + "</P>"
    )
    data = run(project, limits=ModbusLimits(findings_per_check=1, evidence_records=1))
    assert all(sum(f.analysis == a for f in data.findings) <= 1 for a in ALL)
    assert data.coverage.evaluated_sensor_occurrences.value == 3
    assert data.coverage.sensor_source_occurrences.count_kind == "exact"
    assert any(f.affected_occurrences_omitted for f in data.findings)
    gap_only = run(project, frozenset({"evidence_gaps"}))
    assert gap_only.coverage.evaluated_sensor_occurrences.value == 0


@pytest.mark.parametrize("fixture", ["rtu-meter.xml", "rtu-hvac.xml", "tcp-gen24.xml"])
def test_all_checks_serialize_on_public_provenance_fixtures(fixture):
    xml = (Path(__file__).parent / "fixtures/project/modbus" / fixture).read_bytes()
    data = run(view(xml))
    assert data.analyses == list(MODBUS_ANALYSES)
    assert set(data.check_status) == ALL
    assert data.coverage.installation_coverage == "unknown"
    assert ProjectModbusAnalysisData.model_validate_json(data.model_dump_json()) == data


def test_common_check_ids_are_selection_independent():
    project = view("<P>" + device(sensor(polling="1"), sensor(polling="2")) + "</P>")
    all_data = run(project)
    for check in ("configured_register_mappings", "configured_polling", "direct_consumers"):
        alone = run(project, frozenset({check}))
        assert [f.finding_id for f in alone.findings] == [
            f.finding_id for f in all_data.findings if f.analysis == check
        ]


def test_all_five_check_pages_preserve_every_finding_and_full_byte_bound():
    project = view(
        "<P>" + device(*(sensor(address=str(i // 2), polling=str(i)) for i in range(120))) + "</P>"
    )
    data = run(project)
    expected = [finding.finding_id for finding in data.findings]
    assert len(expected) > 50
    codec = tools._CursorCodec()
    cursor = None
    emitted = []
    while True:
        offset = codec.decode("modbus-pages", cursor)
        page = data.model_copy(deep=True)
        page.findings = data.findings[offset : offset + 50]
        end = offset + len(page.findings)
        page.next_cursor = codec.encode("modbus-pages", end) if end < len(expected) else None
        envelope = tools.ProjectAnalysisEnvelope(
            ok=True, data=page, observed_at="synthetic", stale=False, trace_id="trace"
        )
        assert tools._fit_project_analysis_page(envelope, codec, "modbus-pages", cursor)
        assert len(envelope.model_dump_json().encode("utf-8")) <= 65_536
        assert page.findings
        emitted.extend(f.finding_id for f in page.findings)
        assert page.check_status == data.check_status
        assert (
            page.coverage.evaluated_sensor_occurrences == data.coverage.evaluated_sensor_occurrences
        )
        cursor = page.next_cursor
        if cursor is None:
            break
        assert codec.decode("modbus-pages", cursor) == offset + len(page.findings)
    assert emitted == expected


def test_selection_independent_relationship_budget_preserves_mapping_ids():
    project = view(
        '<P><C Type="ModbusASensor"><Co K="Q"/></C>' + device(sensor(), sensor()) + "</P>"
    )
    limits = ModbusLimits(relationships=2)
    alone = run(project, frozenset({"configured_register_mappings"}), limits=limits)
    together = run(project, ALL, limits=limits)
    assert alone.check_status["configured_register_mappings"].status == "partial"
    assert alone.check_status["configured_register_mappings"].evaluated_occurrences.count_kind == (
        "lower_bound"
    )
    assert alone.summaries["configured_register_mappings"][0].count.count_kind == "lower_bound"
    assert alone.coverage.evaluated_sensor_occurrences.count_kind == "lower_bound"
    assert together.check_status["configured_polling"].evaluated_occurrences.count_kind == "exact"
    assert together.coverage.evaluated_sensor_occurrences.count_kind == "exact"
    assert [f.finding_id for f in alone.findings] == [
        f.finding_id for f in together.findings if f.analysis == "configured_register_mappings"
    ]


def test_unresolved_record_limit_preserves_complete_ancestry_and_positive_edges():
    project = view(
        "<P>"
        + device(
            sensor().replace("/>", '><Co U="src" K="Q"/></C>'),
            sensor(),
        )
        + '<C Type="Other"><Co U="dst" K="I"><In Input="src"/></Co></C></P>'
    )
    graph = project.snapshot.graph
    target = next(node for node in graph.nodes if node.block_type == "Other")
    graph = replace(graph, unresolved=((target.key, "signal_unresolved"),))
    project = replace(project, snapshot=replace(project.snapshot, graph=graph))
    data = run(project, limits=ModbusLimits(relationships=len(graph.edges)))
    assert len(findings(data, "configured_mapping_repeated")) == 1
    assert data.check_status["configured_register_mappings"].status == "complete"
    positive = findings(data, "direct_consumer_summary")
    assert len(positive) == 1 and positive[0].direct_edge_count.value == 1
    assert positive[0].direct_edge_count.count_kind == "lower_bound"
    assert not positive[0].direct_slice_complete
    assert data.check_status["direct_consumers"].status == "partial"
    assert (
        "unresolved_relationships_truncated" in data.check_status["direct_consumers"].reason_codes
    )
    assert data.check_status["inventory"].status == "complete"


def test_ancestry_depth_limit_marks_mapping_count_domains_as_lower_bounds():
    project = view("<P>" + device(sensor(), sensor()) + "</P>")
    data = run(
        project, frozenset({"configured_register_mappings"}), limits=ModbusLimits(ancestry_depth=1)
    )
    status = data.check_status["configured_register_mappings"]
    assert status.status == "partial"
    assert status.eligible_occurrences.value == 2
    assert status.eligible_occurrences.count_kind == "exact"
    assert status.evaluated_occurrences.value == 0
    assert status.evaluated_occurrences.count_kind == "lower_bound"
    assert data.summaries["configured_register_mappings"][0].count.count_kind == "lower_bound"
    assert data.coverage.evaluated_sensor_occurrences.count_kind == "lower_bound"
