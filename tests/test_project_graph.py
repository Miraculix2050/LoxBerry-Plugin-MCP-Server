from pathlib import Path

import pytest

from mcpserver.loxone.project.graph import build_graph
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
