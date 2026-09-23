from pathlib import Path

import pytest

from mcpserver.loxone.project.graph import _logical_knx_nodes, _source_diagnostics, build_graph
from mcpserver.loxone.project.models import ProjectError
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
