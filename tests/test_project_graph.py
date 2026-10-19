from pathlib import Path

import pytest

from mcpserver.loxone.project.graph import _logical_knx_nodes, _source_diagnostics, build_graph
from mcpserver.loxone.project.models import ProjectError, ProjectLimits
from mcpserver.loxone.project.parser import parse_project


def test_observed_input_reference_direction_and_namespace():
    project = parse_project(Path("tests/fixtures/project/observed-topology.xml").read_bytes())
    graph = build_graph((("one", project), ("two", project)))
    wires = [edge for edge in graph.edges if edge.kind == "signal"]
    assert len(wires) == 2
    for edge in wires:
        assert edge.source.split(":")[0] == edge.target.split(":")[0]
        assert graph.traverse(edge.source) == (edge.target,)
        assert graph.traverse(edge.target, upstream=True) == (edge.source,)
    assert not graph.unresolved


def test_cycle_fanout_and_unknown_reference_are_bounded():
    project = parse_project(
        b'<P><C U="a" Ref="b"/><C U="b" Ref="a"/><C U="c" Ref="b"/><C U="d" Ref="missing"/></P>'
    )
    graph = build_graph((("p", project),))
    assert len(graph.traverse("p:1")) == 2
    assert len(graph.traverse("p:1", limit=1)) == 1
    assert graph.unresolved == (("p:4", "reference_unresolved"),)
    with pytest.raises(ProjectError):
        graph.traverse("p:1", depth=100)


def test_duplicate_source_ids_do_not_guess_edges():
    project = parse_project(b'<P><C U="a"/><C U="a"/><C U="b" Ref="a"/></P>')
    graph = build_graph((("p", project),))
    assert not graph.edges
    assert graph.unresolved


def test_outputref_resolves_unique_virtual_output_in_other_model_source():
    reference = parse_project(
        b'<P><C Type="Page"><C Type="OutputRef" '
        b'Ref="ABCDEF01-2345-6789-ABCD-EF0123456789"/></C></P>'
    )
    target = parse_project(b'<P><C Type="VirtualOutCmd" U="abcdef0123456789abcdef0123456789"/></P>')
    for projects in (
        (("ref", reference), ("target", target)),
        (("target", target), ("ref", reference)),
    ):
        graph = build_graph(projects)
        assert not graph.unresolved
        edges = [edge for edge in graph.edges if edge.kind == "reference"]
        assert [(edge.source, edge.target) for edge in edges] == [("target:1", "ref:2")]
        assert graph.traverse("ref:2", upstream=True) == ("target:1",)


@pytest.mark.parametrize(
    ("ref_type", "target_type", "identifier", "duplicate", "local"),
    [
        ("InputRef", "VirtualOutCmd", "a" * 32, False, False),
        ("OutputRef", "EIBactor", "a" * 32, False, False),
        ("OutputRef", "VirtualOutCmd", "not-a-uuid", False, False),
        ("OutputRef", "VirtualOutCmd", "a" * 32, True, False),
        ("OutputRef", "VirtualOutCmd", "a" * 32, True, True),
    ],
)
def test_cross_source_outputref_preserves_unproven_or_ambiguous_targets(
    ref_type, target_type, identifier, duplicate, local
):
    target_xml = f'<C Type="{target_type}" U="{identifier}"/>'
    reference = parse_project(
        (
            f'<P><C Type="{ref_type}" Ref="{identifier}"/>'
            + (target_xml * 2 if local else "")
            + "</P>"
        ).encode()
    )
    target = parse_project(("<P>" + target_xml * (2 if duplicate else 1) + "</P>").encode())
    graph = build_graph((("ref", reference), ("target", target)))
    assert graph.unresolved == (("ref:1", "reference_unresolved"),)
    assert not any(edge.kind == "reference" for edge in graph.edges)


def test_outputref_keeps_local_target_precedence():
    project = parse_project(
        b'<P><C Type="OutputRef" Ref="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/>'
        b'<C Type="VirtualOutCmd" U="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></P>'
    )
    graph = build_graph((("one", project), ("two", project)))
    assert not graph.unresolved
    assert all(edge.source.split(":")[0] == edge.target.split(":")[0] for edge in graph.edges)


def test_outputref_cross_source_uniqueness_includes_other_types_and_sources():
    reference = parse_project(
        b'<P><C Type="OutputRef" Ref="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></P>'
    )
    target = parse_project(b'<P><C Type="VirtualOutCmd" U="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></P>')
    for other in (target, parse_project(b'<P><Co U="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></P>')):
        graph = build_graph((("ref", reference), ("target", target), ("other", other)))
        assert graph.unresolved == (("ref:1", "reference_unresolved"),)
        assert not graph.edges
    assert build_graph((("ref", reference),)).unresolved
    with pytest.raises(ProjectError, match="project_graph_limit"):
        build_graph((("ref", reference), ("target", target)), ProjectLimits(edges=0))
    with pytest.raises(ProjectError, match="project_graph_limit"):
        build_graph((("ref", reference), ("target", target)), ProjectLimits(elements=1))


def test_logical_knx_nodes_merge_only_identical_cross_source_occurrences():
    first = parse_project(
        b'<P><C Type="EIBline" U="line"/><C Type="EIBactor" U="actor" EibAddr="1/2/3"/>'
        b'<C Type="EIBactor" U="other" EibAddr="1/2/3"/></P>'
    )
    second = parse_project(
        b'<P><C Type="EIBline" U="line"/><C Type="EIBactor" U="actor" EibAddr="1/2/3"/>'
        b'<C Type="EIBactor" U="other" EibAddr="1/2/4"/></P>'
    )

    aliases, sources = _logical_knx_nodes(build_graph((("one", first), ("two", second))))

    grouped = {key: values for key, values in sources}
    assert len(grouped) == 2
    assert set(grouped.values()) == {("one", "two")}
    assert len(aliases) == 4


def test_source_diagnostics_expose_shapes_not_unknown_values():
    parsed = parse_project(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="invalid" Extra="secret-value"/></P>'
    )
    graph = build_graph((("p", parsed),))
    diagnostics = _source_diagnostics(
        graph, tuple(("p", index, code) for index, code in parsed.anomalies)
    )

    codes = {item.code for item in diagnostics.entries}
    assert {"invalid_group_address", "missing_raw_datatype", "unmodeled_knx_attribute"} <= codes
    unknown = next(item for item in diagnostics.entries if item.code == "unmodeled_knx_attribute")
    assert unknown.attribute_name == "Extra"
    assert unknown.value_shape == "text"
    assert "secret-value" not in repr(diagnostics)


def test_extsensor_pulse_is_known_and_invalid_primary_is_reported():
    parsed = parse_project(Path("tests/fixtures/project/knx-edge-variants.xml").read_bytes())
    diagnostics = _source_diagnostics(build_graph((("p", parsed),)), ())
    entries = {(item.code, item.source_type): item.count for item in diagnostics.entries}

    assert entries[("invalid_group_address", "EIBextsensor")] == 1
    assert ("unclassified_knx_candidate", "EIBextsensor") not in entries
    assert not any(item.attribute_name == "EibAddrPulse" for item in diagnostics.entries)


def test_source_diagnostics_report_unreviewed_logic_and_bound_labels():
    long_attribute = "A" * 120
    source = (
        f'<P><C Type="EibDimmer" U="logic" {long_attribute}="x">'
        '<Co K="extra" U="connector"/></C></P>'
    )
    parsed = parse_project(source.encode())
    graph = build_graph((("p", parsed),))
    diagnostics = _source_diagnostics(graph, ())

    assert {item.code for item in diagnostics.entries} >= {
        "unreviewed_knx_logic",
        "unmodeled_knx_attribute",
    }
    attribute = next(item for item in diagnostics.entries if item.attribute_name is not None)
    assert len(attribute.attribute_name) <= 100
    assert diagnostics.labels_truncated is True


def test_source_diagnostics_sort_mixed_absent_and_present_source_types():
    parsed = parse_project(b'<P><C Type="EIBsensor" U="one" Duplicate="a"/><C U="two"/></P>')
    graph = build_graph((("p", parsed),))

    diagnostics = _source_diagnostics(
        graph, (("p", 1, "duplicate_attribute"), ("p", 2, "duplicate_attribute"))
    )

    parser_entries = [
        item for item in diagnostics.entries if item.code == "parser_duplicate_attribute"
    ]
    assert [item.source_type for item in parser_entries] == [None, "EIBsensor"]
