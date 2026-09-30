import copyreg
import pickle
from dataclasses import fields, replace
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest

import mcpserver.loxone.project.analysis as project_analysis
from mcpserver.loxone.project.analysis import analyze_knx
from mcpserver.loxone.project.graph import (
    ProjectPartSummary,
    ProjectSnapshot,
    _logical_knx_nodes,
    _source_diagnostics,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.taxonomy import AddressTaxonomyEntry
from mcpserver.loxone.project.worker import (
    _analysis_payload,
    _reduce_graph_edge,
    _reduce_graph_node,
    _reduce_semantic_edge,
    process_analysis,
)


def _view(data: bytes, controls: tuple[SimpleNamespace, ...] = ()) -> ProjectView:
    snapshot = ProjectSnapshot(
        "project",
        3,
        (ProjectPartSummary("p", 1, ()),),
        build_graph((("p", parse_project(data)),)),
    )
    return ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=controls))
    )


def test_analysis_pickler_preserves_all_graph_fields_and_shared_nodes():
    from mcpserver.loxone.project.graph import GraphEdge, SemanticEdge

    view = _view(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    view = replace(view, snapshot=replace(view.snapshot, _logical_nodes=view.snapshot.graph.nodes))
    for item, reducer in (
        (view.snapshot.graph.nodes[0], _reduce_graph_node),
        (GraphEdge("source", "target", "reference"), _reduce_graph_edge),
        (
            SemanticEdge("source", "target", "rule", "interpretation", "effect"),
            _reduce_semantic_edge,
        ),
    ):
        constructor, arguments = reducer(item)
        assert arguments == tuple(getattr(item, field.name) for field in fields(item))
        assert constructor(*arguments) == item
    dispatch_before = copyreg.dispatch_table.copy()
    payload = _analysis_payload(view, frozenset({"datatype_consistency"}), ())
    restored, selected, taxonomy = pickle.loads(payload)
    assert restored == view
    for field in fields(view.snapshot):
        assert getattr(restored.snapshot, field.name) == getattr(view.snapshot, field.name)
    assert selected == frozenset({"datatype_consistency"}) and taxonomy == ()
    assert restored.snapshot._logical_nodes[0] is restored.snapshot.graph.nodes[0]
    assert copyreg.dispatch_table == dispatch_before
    names = sorted(project_analysis.ANALYSES)
    for size in range(1, len(names) + 1):
        for combination in combinations(names, size):
            analyses = frozenset(combination)
            assert analyze_knx(restored, analyses) == analyze_knx(view, analyses)


@pytest.mark.asyncio
async def test_worker_phase_timings_are_numeric_private_and_preserve_results(caplog):
    view = _view(b'<P><C Type="EIBsensor" U="private-id" Title="private-title"/></P>')
    selected = frozenset({"datatype_consistency"})
    timings = {}
    ordinary = await process_analysis(view, selected)
    measured = await process_analysis(view, selected, timings=timings)
    assert measured == ordinary
    assert set(timings) == {
        "process_start_seconds",
        "pickle_dumps_seconds",
        "stdin_transfer_seconds",
        "child_wait_seconds",
        "stdout_transfer_seconds",
        "process_exit_seconds",
        "pickle_loads_seconds",
        "total_seconds",
        "input_bytes",
        "output_bytes",
        "child_stdin_seconds",
        "child_pickle_loads_seconds",
        "child_analysis_seconds",
        "child_pickle_dumps_seconds",
    }
    assert all(type(value) in {int, float} and value >= 0 for value in timings.values())
    assert timings["input_bytes"] > 0 and timings["output_bytes"] > 0
    phases = sum(
        timings[key]
        for key in (
            "process_start_seconds",
            "pickle_dumps_seconds",
            "stdin_transfer_seconds",
            "child_wait_seconds",
            "stdout_transfer_seconds",
            "process_exit_seconds",
            "pickle_loads_seconds",
        )
    )
    assert phases == pytest.approx(timings["total_seconds"])
    assert "private-id" not in caplog.text and "private-title" not in caplog.text


@pytest.mark.asyncio
async def test_child_timings_survive_startup_warnings_and_replace_reused_values(monkeypatch):
    monkeypatch.setenv("PYTHONWARNINGS", "invalid-warning-action")
    timings = {"child_analysis_seconds": -1, "old_measurement": -1}
    result = await process_analysis(
        _view(b"<P/>"), frozenset({"datatype_consistency"}), timings=timings
    )
    assert isinstance(result, dict)
    assert "old_measurement" not in timings
    for name in (
        "child_stdin_seconds",
        "child_pickle_loads_seconds",
        "child_analysis_seconds",
        "child_pickle_dumps_seconds",
    ):
        assert timings[name] >= 0


@pytest.mark.asyncio
async def test_absent_child_timing_frame_does_not_reuse_previous_measurements(monkeypatch):
    import mcpserver.loxone.project.worker as worker

    # Only the parent is patched; the real child emits its normal frame.
    monkeypatch.setattr(worker, "_ANALYSIS_TIMING_MARKER", b"missing-frame")
    timings = {"child_analysis_seconds": -1}
    await process_analysis(_view(b"<P/>"), frozenset({"datatype_consistency"}), timings=timings)
    assert "total_seconds" in timings
    assert not any(key.startswith("child_") and key != "child_wait_seconds" for key in timings)


@pytest.mark.asyncio
async def test_profiled_worker_retains_sanitized_failure_and_input_limit(monkeypatch):
    import mcpserver.loxone.project.worker as worker
    from mcpserver.loxone.project.models import ProjectError

    timings = {"child_analysis_seconds": -1, "old_measurement": -1}
    with pytest.raises(ProjectError, match="^project_worker_invalid$"):
        await process_analysis(None, frozenset(), timings=timings)
    assert not timings
    monkeypatch.setattr(worker, "MAX_ANALYSIS_INPUT", 1)
    with pytest.raises(ProjectError, match="^project_worker_limit$"):
        await process_analysis(_view(b"<P/>"), frozenset(), timings=timings)
    assert not timings


def test_analysis_reports_project_local_datatype_and_usage_facts_deterministically():
    view = _view(
        b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3" EIBType="1"><Co U="ao"/></C>'
        b'<C Type="EIBsensor" U="b" EibAddr="1/2/3" EIBType="5"><Co U="bo"/></C>'
        b'<C Type="EIBsensor" U="c" EibAddr="1/2/4"><Co K="AQ" U="co"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="co"/></Co>'
        b'<Co K="O" U="out"/></C></P>'
    )
    selected = frozenset({"datatype_consistency", "signal_usage_consistency"})

    first = analyze_knx(view, selected)
    second = analyze_knx(view, selected)

    assert first == second
    conflict = next(
        item for item in first["findings"] if item["finding_type"] == "raw_datatype_conflict"
    )
    assert conflict["group_address"] == "1/2/3"
    assert conflict["raw_datatypes"] == ["1", "5"]
    assert all("incompatible" not in str(item) for item in first["findings"])


def test_edge_variants_stay_separate_in_analysis_and_connectivity():
    view = _view(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    result = analyze_knx(view, frozenset({"datatype_consistency", "project_connectivity"}))

    assert result["coverage"]["endpoints"] == 6
    assert result["coverage"]["canonical_group_addresses"] == 5
    assert not any(item["finding_type"] == "raw_datatype_conflict" for item in result["findings"])
    disconnected = {
        item["address_variant"]
        for item in result["findings"]
        if item["finding_type"] == "no_project_signal_relationship"
        and item["group_address"] == "6/2/27"
    }
    assert disconnected == {None}
    assert result["analysis_version"] == 8


def test_address_hierarchy_reports_measured_prefixes_and_configured_provenance():
    view = _view(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    selected = frozenset({"address_hierarchy"})
    taxonomy = (AddressTaxonomyEntry("6/2", "Test label", "three_level"),)

    result = analyze_knx(view, selected, taxonomy)
    assert result == analyze_knx(view, selected, taxonomy)
    rows = {
        (tuple(item["hierarchy"]["prefix"]), item["hierarchy"]["address_format"]): item
        for item in result["findings"]
        if item["finding_type"] == "address_prefix_summary"
    }
    assert ((6,), "three_level") in rows
    assert ((6, 2), "three_level") in rows
    leaf = rows[((6, 2, 27), "three_level")]["hierarchy"]
    assert leaf["object_count"] == 3
    assert leaf["logical_address_count"] == 1
    assert leaf["edge_variant_count"] == 2
    assert {entry["original"] for entry in leaf["address_examples"]} == {
        "6/2/27:0",
        "6/2/27:1",
        "6/2/27",
    }
    assert rows[((6, 2), "three_level")]["hierarchy"]["configured_taxonomy"] == {
        "label": "Test label",
        "provenance": "admin_configured",
    }
    assert leaf["configured_taxonomy"] is None
    type_outlier = next(
        item
        for item in result["findings"]
        if item["finding_type"] == "address_hierarchy_outlier"
        and item["comparison_dimension"] == "source_type"
        and item["dominant_prefix"] == [6, 2]
    )
    assert type_outlier["classification"] == "outlier"
    assert type_outlier["dominant_count"] == 4
    assert type_outlier["peer_count"] == 5
    assert type_outlier["support"]["count"] == 1
    assert type_outlier["affected_project_node_ids"]
    assert all(
        item["classification"] in {"fact", "pattern", "outlier"} for item in result["findings"]
    )
    assert "DPT" not in str(result)


def test_address_hierarchy_counts_duplicate_sources_only_as_occurrences():
    parsed = parse_project(b'<P><C Type="EIBactor" U="a" EibAddr="1/2/3"/></P>')
    graph = build_graph((("one", parsed), ("two", parsed)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        5,
        (ProjectPartSummary("one", 1, ()), ProjectPartSummary("two", 1, ())),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )
    result = analyze_knx(view, frozenset({"address_hierarchy"}))
    leaf = next(
        item["hierarchy"]
        for item in result["findings"]
        if item["finding_type"] == "address_prefix_summary"
        and item["hierarchy"]["prefix"] == [1, 2, 3]
    )
    assert leaf["object_count"] == 1
    assert leaf["source_occurrence_count"] == 2


def test_address_taxonomy_does_not_cross_two_and_three_level_formats():
    view = _view(
        b'<P><C Type="EIBsensor" U="two" EibAddr="6/2"/>'
        b'<C Type="EIBsensor" U="three" EibAddr="6/2/7"/></P>'
    )
    result = analyze_knx(
        view,
        frozenset({"address_hierarchy"}),
        (
            AddressTaxonomyEntry("6/2", "Two-level leaf", "two_level"),
            AddressTaxonomyEntry("6/2", "Three-level middle", "three_level"),
        ),
    )
    rows = {
        (item["hierarchy"]["address_format"], tuple(item["hierarchy"]["prefix"])): item["hierarchy"]
        for item in result["findings"]
        if item["finding_type"] == "address_prefix_summary"
    }
    assert rows[("two_level", (6, 2))]["configured_taxonomy"]["label"] == "Two-level leaf"
    assert rows[("three_level", (6, 2))]["configured_taxonomy"]["label"] == ("Three-level middle")


@pytest.mark.asyncio
async def test_address_hierarchy_worker_preserves_admin_label_provenance():
    result = await process_analysis(
        _view(b'<P><C Type="EIBsensor" U="a" EibAddr="6/2/7"/></P>'),
        frozenset({"address_hierarchy"}),
        (AddressTaxonomyEntry("6/2", "Configured", "three_level"),),
    )
    prefix = next(
        item["hierarchy"]
        for item in result["findings"]
        if item["finding_type"] == "address_prefix_summary"
        and item["hierarchy"]["prefix"] == [6, 2]
    )
    assert prefix["configured_taxonomy"] == {
        "label": "Configured",
        "provenance": "admin_configured",
    }


def test_new_knx_families_enter_coverage_and_connectivity_without_unmodeled_types():
    parsed = parse_project(Path("tests/fixtures/project/knx-text-endpoints.xml").read_bytes())
    graph = build_graph((("p", parsed),))
    snapshot = ProjectSnapshot(
        "project",
        7,
        (ProjectPartSummary("p", 1, ()),),
        graph,
        _source_diagnostics(graph, ()),
    )
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )
    result = analyze_knx(view, frozenset({"project_connectivity"}))

    assert result["coverage"]["endpoints"] == 5
    assert result["coverage"]["canonical_group_addresses"] == 5
    assert result["coverage"]["raw_datatypes"] == 0
    assert result["analysis_version"] == 8
    assert any(
        item["code"] == "unclassified_knx_candidate" and item["source_type"] == "EIBunknown"
        for item in result["source_diagnostics"]["entries"]
    )
    assert not any(
        item["code"] == "missing_raw_datatype"
        and item["source_type"] in {"EIBtextsensor", "EIBtextactor", "EIBextactor"}
        for item in result["source_diagnostics"]["entries"]
    )
    assert result["summaries"]["project_connectivity"]["unconnected"] == 0


def test_analysis_uses_logical_knx_endpoints_and_keeps_source_occurrence_count():
    parsed = parse_project(
        b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"/>'
        b'<C Type="EIBsensor" U="sensor" EibAddr="1/2/4" EIBType="1"/></P>'
    )
    graph = build_graph((("one", parsed), ("two", parsed)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        5,
        (ProjectPartSummary("one", 3, ()), ProjectPartSummary("two", 3, ())),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )

    result = analyze_knx(view, frozenset({"project_connectivity"}))

    assert result["coverage"]["endpoints"] == 2
    assert result["coverage"]["endpoint_source_occurrences"] == 4


def test_logical_endpoint_connectivity_aggregates_all_source_occurrences():
    first = parse_project(b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3"/></P>')
    second = parse_project(
        b'<P><C Type="Logic" U="logic"><Co U="output"/></C>'
        b'<C Type="EIBactor" U="actor" EibAddr="1/2/3">'
        b'<Co U="actor-input"><In Input="output"/></Co></C></P>'
    )
    graph = build_graph((("one", first), ("two", second)))
    aliases, source_ids = _logical_knx_nodes(graph)
    snapshot = ProjectSnapshot(
        "project",
        5,
        (ProjectPartSummary("one", 1, ()), ProjectPartSummary("two", 3, ())),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )

    result = analyze_knx(view, frozenset({"project_connectivity"}))

    assert result["coverage"]["endpoints"] == 1
    assert result["coverage"]["endpoint_source_occurrences"] == 2
    assert result["summaries"]["project_connectivity"] == {
        "unconnected": 0,
        "ambiguous": 0,
        "reference_only": 0,
    }


def test_analysis_only_reports_address_deviations_for_strong_evidenced_peer_groups():
    nodes = b"".join(
        (
            f'<C Type="EIBsensor" U="s{i}" EibAddr="1/2/{i}" EIBType="1">'
            f'<Co K="AQ" U="co{i}"/></C><C Type="EIBPush" U="p{i}">'
            f'<Co K="Tg" U="t{i}"><In Input="co{i}"/></Co><Co K="O" U="o{i}"/></C>'
        ).encode()
        for i in range(5)
    )
    nodes += (
        b'<C Type="EIBsensor" U="outlier" EibAddr="2/2/9" EIBType="1">'
        b'<Co K="AQ" U="co9"/></C><C Type="EIBPush" U="p9">'
        b'<Co K="Tg" U="t9"><In Input="co9"/></Co><Co K="O" U="o9"/></C>'
    )

    result = analyze_knx(_view(b"<P>" + nodes + b"</P>"), frozenset({"address_patterns"}))

    deviations = [
        item for item in result["findings"] if item["finding_type"] == "address_pattern_deviation"
    ]
    assert {
        (item["prefix_level"], tuple(item["dominant_prefix"]), tuple(item["deviation_prefix"]))
        for item in deviations
    } == {
        (1, (1,), (2,)),
        (2, (1, 2), (2, 2)),
    }


def test_analysis_scopes_unconnected_evidence_to_the_project_graph():
    result = analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="isolated" EibAddr="1/2/3"><Co U="co"/></C></P>'),
        frozenset({"project_connectivity"}),
    )

    finding = result["findings"][0]
    assert finding["finding_type"] == "no_project_signal_relationship"
    assert "unused" not in str(finding)
    assert finding["connectivity_scope"] == "inspected_project_endpoint_connectors"
    assert finding["direct_configured_relationship_count"] == 0
    assert finding["reference_relationship_count"] == 0
    assert finding["inspected_connectors"][0]["connector_key"] is None
    assert finding["description"].startswith("No direct configured consumer found")


def test_reference_only_endpoint_reports_no_direct_wiring_without_changing_old_finding_ids():
    project = (
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co K="AQ" U="out"/>'
        b'</C><C Type="InputRef" U="alias" Ref="sensor"/></P>'
    )
    result = analyze_knx(_view(project), frozenset({"project_connectivity"}))
    finding = result["findings"][0]

    assert finding["finding_type"] == "no_direct_configured_signal_relationship"
    assert finding["direct_configured_relationship_count"] == 0
    assert finding["reference_relationship_count"] == 1
    assert finding["inspected_connectors"][0]["connector_key"] == "AQ"
    assert result["summaries"]["project_connectivity"]["reference_only"] == 1
    assert (
        project_analysis._finding_id(
            "no_project_signal_relationship", ["bus_to_loxone", "1/2/3", None], ["p:1", "p:2"]
        )
        == "knx:748cc06d3762f2fe198f"
    )


def test_connectivity_bounds_inspected_connectors_and_describes_output_direction(monkeypatch):
    connector_evidence_calls = 0
    original_connector_evidence = project_analysis._connector_evidence

    def track_connector_evidence(*args):
        nonlocal connector_evidence_calls
        connector_evidence_calls += 1
        return original_connector_evidence(*args)

    monkeypatch.setattr(project_analysis, "_connector_evidence", track_connector_evidence)
    connectors = b"".join(
        f'<Co K="{index}-{("x" * 120)}" U="connector{index}"/>'.encode() for index in range(22)
    )
    result = analyze_knx(
        _view(b'<P><C Type="EIBactor" U="actor" EibAddr="1/2/3">' + connectors + b"</C></P>"),
        frozenset({"project_connectivity"}),
    )
    finding = result["findings"][0]

    assert finding["description"].startswith("No direct configured input source found")
    assert len(finding["inspected_connectors"]) == 20
    assert finding["inspected_connectors_omitted"] == 2
    assert all(len(row["connector_key"]) == 100 for row in finding["inspected_connectors"])
    assert all(row["connector_key_truncated"] for row in finding["inspected_connectors"])
    assert connector_evidence_calls == 20


def test_unresolved_direct_wiring_remains_ambiguous():
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3">'
            b'<Co K="AQ" U="out"><In Input="unknown"/></Co></C>'
            b'<C Type="InputRef" Ref="sensor"/></P>'
        ),
        frozenset({"project_connectivity"}),
    )
    finding = result["findings"][0]
    assert finding["finding_type"] == "project_connectivity_ambiguous"
    assert finding["reference_relationship_count"] == 1
    assert "could not be resolved" in finding["description"]


def test_outgoing_graph_degree_explains_references_signals_and_logical_consumers(monkeypatch):
    parts = []
    for index in range(8):
        parts.append(
            f'<C Type="EIBsensor" U="sensor{index}" EibAddr="1/2/{index}">'
            f'<Co K="AQ" U="output{index}"/></C>'
        )
        if index < 7:
            parts.append(
                f'<C Type="EIBPush" U="consumer{index}"><Co K="Tg" U="trigger{index}">'
                f'<In Input="output{index}"/></Co><Co K="O" U="result{index}"/></C>'
            )
        else:
            for consumer in range(3):
                parts.append(
                    f'<C Type="InputRef" U="alias{consumer}" Ref="sensor7"/>'
                    f'<C Type="EIBPush" U="consumer7{consumer}">'
                    f'<Co K="Tg" U="trigger7{consumer}"><In Input="output7"/></Co>'
                    f'<Co K="X" U="extra7{consumer}"><In Input="output7"/></Co>'
                    f'<Co K="O" U="result7{consumer}"/></C>'
                )
    view = _view(("<P>" + "".join(parts) + "</P>").encode())
    result = analyze_knx(view, frozenset({"graph_outliers"}))
    finding = next(item for item in result["findings"] if item["graph_metric"] == "fan_out")

    assert finding["graph_value"] == 9
    assert finding["edge_summary"] == {
        "metric": "raw_out_degree",
        "raw_degree": 9,
        "signal_edges": 6,
        "reference_edges": 3,
        "derived_semantic_edges": 3,
        "logical_consumers": 3,
        "logical_sources": None,
    }
    assert {row["kind"] for row in finding["edge_evidence"]} == {
        "signal",
        "reference",
        "derived_semantic",
    }
    assert all(len(row["source_connector_key"] or "") <= 100 for row in finding["edge_evidence"])
    assert result == analyze_knx(view, frozenset({"graph_outliers"}))

    monkeypatch.setattr(project_analysis, "_MAX_EVIDENCE", 5)
    evidence_calls = 0
    original_edge_evidence = project_analysis._edge_evidence

    def track_edge_evidence(*args):
        nonlocal evidence_calls
        evidence_calls += 1
        return original_edge_evidence(*args)

    monkeypatch.setattr(project_analysis, "_edge_evidence", track_edge_evidence)
    bounded = analyze_knx(view, frozenset({"graph_outliers"}))
    bounded_finding = next(
        item for item in bounded["findings"] if item["graph_metric"] == "fan_out"
    )
    assert bounded_finding["finding_id"] == finding["finding_id"]
    assert len(bounded_finding["edge_evidence"]) == 5
    assert bounded_finding["edge_evidence_omitted"] == 7
    assert {row["kind"] for row in bounded_finding["edge_evidence"]} == {
        "signal",
        "reference",
        "derived_semantic",
    }
    assert evidence_calls <= 5 * bounded["summaries"]["graph_outliers"]["outliers"]


def test_incoming_graph_degree_counts_distinct_configured_sources(monkeypatch):
    monkeypatch.setattr(project_analysis, "_usage", lambda *_args: ((("level", None),), False))
    parts = []
    for index in range(8):
        source_count = 3 if index == 7 else 1
        parts.append(
            f'<C Type="Logic" U="source{index}">'
            + "".join(
                f'<Co K="O{source}" U="output{index}-{source}"/>' for source in range(source_count)
            )
            + "</C>"
        )
        parts.append(
            f'<C Type="EIBactor" U="actor{index}" EibAddr="1/2/{index}">'
            f'<Co K="I" U="input{index}">'
            + "".join(f'<In Input="output{index}-{source}"/>' for source in range(source_count))
            + "</Co></C>"
        )
    result = analyze_knx(
        _view(("<P>" + "".join(parts) + "</P>").encode()), frozenset({"graph_outliers"})
    )
    finding = next(item for item in result["findings"] if item["graph_metric"] == "fan_in")

    assert finding["graph_value"] == 3
    assert finding["edge_summary"]["metric"] == "raw_in_degree"
    assert finding["edge_summary"]["signal_edges"] == 3
    assert finding["edge_summary"]["logical_sources"] == 1
    assert finding["edge_summary"]["logical_consumers"] is None


def test_analysis_skips_signal_usage_when_the_selected_analysis_does_not_need_it(monkeypatch):
    def usage_should_not_run(*_args):
        raise AssertionError("signal usage must not be computed")

    monkeypatch.setattr(project_analysis, "_usage", usage_should_not_run)

    result = project_analysis.analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="out"/></C></P>'),
        frozenset({"project_connectivity"}),
    )

    assert result["summaries"]["project_connectivity"] == {
        "unconnected": 1,
        "ambiguous": 0,
        "reference_only": 0,
    }


@pytest.mark.parametrize(
    "analysis",
    ["naming_consistency", "datatype_consistency", "graph_outliers", "peer_group_consistency"],
)
def test_role_dependent_analyses_compute_reviewed_signal_usage(monkeypatch, analysis):
    observed = []
    original = project_analysis._usage

    def track_usage(*args):
        observed.append(args[0].key)
        return original(*args)

    monkeypatch.setattr(project_analysis, "_usage", track_usage)

    project_analysis.analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="out"/></C></P>'),
        frozenset({analysis}),
    )

    assert observed


def test_signal_usage_peer_outliers_compare_roles_without_the_usage_signature(monkeypatch):
    def usage_by_source(node, *_args):
        usage = (("minority", None),) if node.source_id == "s4" else (("majority", None),)
        return usage, False

    monkeypatch.setattr(project_analysis, "_usage", usage_by_source)
    project = (
        b"<P>"
        + b"".join(
            f'<C Type="EIBsensor" U="s{index}" EibAddr="1/2/3"><Co U="o{index}"/></C>'.encode()
            for index in range(5)
        )
        + b"</P>"
    )

    result = analyze_knx(_view(project), frozenset({"signal_usage_consistency"}))

    peer_outliers = [
        finding
        for finding in result["findings"]
        if finding["finding_type"] == "signal_usage_peer_outlier"
    ]
    assert len(peer_outliers) == 1
    assert peer_outliers[0]["support"] == {"count": 4, "total": 5, "ratio": 0.8}


def test_usage_analysis_stops_at_the_shared_traversal_budget(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_USAGE_NODES", 1)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"signal_usage_consistency"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_usage_nodes"]
    assert result["coverage"]["reviewed_signal_usage"] == 0


def test_usage_analysis_bounds_containment_fan_out_before_enqueueing_children(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_USAGE_NODES_PER_ENDPOINT", 3)
    connectors = b"".join(f'<Co U="child{index}"/>'.encode() for index in range(4))
    result = analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3">' + connectors + b"</C></P>"),
        frozenset({"signal_usage_consistency"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_usage_nodes"]


def test_analysis_uses_runtime_evidence_only_for_a_unique_reverse_mapping():
    identifier = "a" * 32
    controls = (
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="First name",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        ),
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="Second name",
            control_type="Dimmer",
            room_uuid=None,
            category_uuid=None,
        ),
    )

    result = analyze_knx(
        _view(
            (
                f'<P><C Type="EIBsensor" U="{identifier}" EibAddr="1/2/3"><Co U="out"/></C></P>'
            ).encode(),
            controls,
        ),
        frozenset({"naming_consistency"}),
    )

    assert result["coverage"]["exact_runtime_mappings"] == 0
    assert result["coverage"]["named_endpoints"] == 0


def test_technology_architecture_does_not_reclassify_mapped_knx_endpoints_as_loxone():
    sensor_id, actor_id = "a" * 32, "b" * 32
    controls = tuple(
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="Mapped endpoint",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        )
        for identifier in (sensor_id, actor_id)
    )
    result = analyze_knx(
        _view(
            f'<P><C Type="EIBsensor" U="{sensor_id}" EibAddr="1/2/3"><Co U="source"/></C>'
            f'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            f'<Co K="O" U="output"/></C><C Type="EIBactor" U="{actor_id}" EibAddr="1/2/4">'
            f'<Co U="input"><In Input="output"/></Co></C></P>'.encode(),
            controls,
        ),
        frozenset({"technology_architecture"}),
    )

    counts = result["summaries"]["technology_architecture"]["counts"]
    assert counts["knx_to_knx"] == 1
    assert "loxone_to_loxone" not in counts


def test_technology_path_analysis_never_reverses_at_a_logic_input_merge():
    loxone_id = "a" * 32
    view = _view(
        f'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="sensor-out"/></C>'
        f'<C Type="DigitalInput" U="{loxone_id}"><Co U="loxone-out"/></C>'
        f'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="sensor-out"/></Co>'
        f'<Co K="On" U="on"><In Input="loxone-out"/></Co><Co K="O" U="output"/></C>'
        f'<C Type="EIBactor" U="actor" EibAddr="1/2/4"><Co U="actor-in"><In Input="output"/>'
        f"</Co></C></P>".encode(),
        (SimpleNamespace(uuid=loxone_id, action_uuid=None, subcontrols=()),),
    )

    result = analyze_knx(view, frozenset({"technology_architecture"}))

    counts = result["summaries"]["technology_architecture"]["counts"]
    assert counts.get("knx_to_loxone", 0) == 0
    assert counts["knx_to_knx"] == 1
    sample = result["summaries"]["technology_architecture"]["samples"]["knx_to_knx"][0]
    endpoint_blocks = {
        node.knx.group_address.canonical: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.knx and node.knx.group_address
    }
    assert sample["source_project_node_id"] == endpoint_blocks["1/2/3"]
    assert sample["target_project_node_id"] == endpoint_blocks["1/2/4"]


def test_technology_path_analysis_stops_inside_a_high_fan_out_expansion(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_VISITED_PER_START", 3)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"technology_architecture"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_path_nodes"]


def test_technology_path_analysis_reports_a_depth_limit(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_PATH_DEPTH", 0)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"technology_architecture"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_depth"]


def test_technology_path_analysis_stops_all_endpoint_expansion_at_the_global_path_limit(
    monkeypatch,
):
    monkeypatch.setattr(project_analysis, "_MAX_PATHS", 1)
    observed_descendants = []
    original = project_analysis._bounded_descendants

    def track_descendants(key, children, limit):
        observed_descendants.append(key)
        return original(key, children, limit)

    monkeypatch.setattr(project_analysis, "_bounded_descendants", track_descendants)
    view = _view(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
        b'<Co K="O" U="output"/></C><C Type="EIBactor" U="actor1" EibAddr="1/2/4">'
        b'<Co U="input1"><In Input="output"/></Co></C>'
        b'<C Type="EIBactor" U="actor2" EibAddr="1/2/5">'
        b'<Co U="input2"><In Input="output"/></Co></C></P>'
    )

    result = analyze_knx(view, frozenset({"technology_architecture"}))

    blocks = {
        node.source_id: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.source_id in {"sensor", "actor1", "actor2"}
    }
    assert result["truncation_reasons"] == ["max_paths"]
    assert observed_descendants.count(blocks["sensor"]) == 1
    assert observed_descendants.count(blocks["actor1"]) == 0
    assert observed_descendants.count(blocks["actor2"]) == 0


def test_technology_path_analysis_stops_when_it_records_the_final_allowed_path(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_PATHS", 1)
    observed_descendants = []
    original = project_analysis._bounded_descendants

    def track_descendants(key, children, limit):
        observed_descendants.append(key)
        return original(key, children, limit)

    monkeypatch.setattr(project_analysis, "_bounded_descendants", track_descendants)
    view = _view(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
        b'<Co K="O" U="output"/></C><C Type="EIBactor" U="actor" EibAddr="1/2/4">'
        b'<Co U="input"><In Input="output"/></Co></C></P>'
    )

    result = analyze_knx(view, frozenset({"technology_architecture"}))

    blocks = {
        node.source_id: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.source_id in {"sensor", "actor"}
    }
    assert result["truncation_reasons"] == ["max_paths"]
    assert observed_descendants.count(blocks["sensor"]) == 1
    assert observed_descendants.count(blocks["actor"]) == 0


def test_technology_architecture_requires_unique_reverse_mapping_for_loxone_boundaries():
    loxone_id = "c" * 32
    controls = tuple(
        SimpleNamespace(
            uuid=loxone_id,
            action_uuid=None,
            subcontrols=(),
            name=name,
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        )
        for name in ("First", "Second")
    )
    result = analyze_knx(
        _view(
            f'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            f'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            f'<Co K="O" U="output"/></C><C Type="DigitalInput" U="{loxone_id}">'
            f'<Co U="input"><In Input="output"/></Co></C></P>'.encode(),
            controls,
        ),
        frozenset({"technology_architecture"}),
    )

    counts = result["summaries"]["technology_architecture"]["counts"]
    assert "knx_to_loxone" not in counts


def test_v2_uses_exact_runtime_evidence_for_naming_without_inventing_knx_semantics():
    identifiers = tuple(f"{index:032x}" for index in range(1, 7))
    project = (
        b"<P>"
        + b"".join(
            (
                f'<C Type="EIBsensor" U="{identifier}" EibAddr="1/2/{index}" '
                f'EIBType="1"><Co U="o{index}"/></C>'
            ).encode()
            for index, identifier in enumerate(identifiers, 1)
        )
        + b"</P>"
    )
    controls = tuple(
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name=f"Zone {index}" if index < 6 else "Different",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        )
        for index, identifier in enumerate(identifiers, 1)
    )

    result = analyze_knx(_view(project, controls), frozenset({"naming_consistency"}))

    assert result["analysis_version"] == 8
    assert result["coverage"]["exact_runtime_mappings"] == 6
    assert result["coverage"]["reviewed_signal_usage"] == 0
    assert any(item["finding_type"] == "naming_deviation" for item in result["findings"])
    assert {item["code"] for item in result["limitations"]} >= {
        "normalized_dpt_unavailable",
        "semantic_domain_unavailable",
        "usage_semantics_unreviewed",
    }


def test_every_finding_type_honors_the_shared_result_limit(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_FINDINGS", 1)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3" EIBType="1"><Co U="ao"/></C>'
            b'<C Type="EIBsensor" U="b" EibAddr="1/2/3" EIBType="5"><Co U="bo"/></C>'
            b'<C Type="EIBsensor" U="c" EibAddr="1/2/4" EIBType="1"><Co U="co"/></C>'
            b'<C Type="EIBsensor" U="d" EibAddr="1/2/4" EIBType="5"><Co U="do"/></C></P>'
        ),
        frozenset({"datatype_consistency"}),
    )

    assert len(result["findings"]) == 1
    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_findings"]


def test_hierarchy_limit_preserves_findings_from_other_requested_analyses(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_FINDINGS", 4)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3" EIBType="1"/>'
            b'<C Type="EIBsensor" U="b" EibAddr="1/2/3" EIBType="5"/></P>'
        ),
        frozenset({"address_hierarchy", "datatype_consistency"}),
    )

    assert len(result["findings"]) <= 4
    assert sum(item["analysis"] == "address_hierarchy" for item in result["findings"]) == 2
    assert any(item["finding_type"] == "raw_datatype_conflict" for item in result["findings"])
    assert result["truncation_reasons"] == ["max_findings"]
