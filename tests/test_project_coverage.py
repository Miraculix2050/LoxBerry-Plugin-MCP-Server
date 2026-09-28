from types import SimpleNamespace

from mcpserver.loxone.project.analysis import analyze_knx
from mcpserver.loxone.project.coverage import coverage_by_source_type
from mcpserver.loxone.project.graph import (
    ProjectPartSummary,
    ProjectSnapshot,
    _logical_knx_nodes,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery


def _snapshot(*parts: bytes) -> ProjectSnapshot:
    projects = tuple((f"p{index}", parse_project(part)) for index, part in enumerate(parts))
    graph = build_graph(projects)
    aliases, source_ids = _logical_knx_nodes(graph)
    return ProjectSnapshot(
        "project",
        7,
        tuple(ProjectPartSummary(name, len(part.elements), ()) for name, part in projects),
        graph,
        logical_aliases=aliases,
        logical_source_ids=source_ids,
    )


def test_coverage_distinguishes_raw_occurrences_logical_objects_and_uncertainty():
    shared = b'<C Type="EIBactor" U="same" EibAddr="1/2/3"/>'
    snapshot = _snapshot(
        b"<P>" + shared + b'<C Type="EIBsensor" U="bad" EibAddr="invalid"/>'
        b'<C Type="EIBsensor" U="missing"/>'
        b'<C Type="EIBPush" U="logic"/><C Type="EIBline" U="line"/>'
        b'<C Type="EIBunknown" U="unsupported"/>'
        b'<C U="untyped" EibAddr="1/2/4"/>'
        b'<C Type="Other" U="marker" EIBType="5"/></P>',
        b"<P>" + shared + b"</P>",
    )
    coverage = coverage_by_source_type(snapshot)
    rows = {item["source_type"]: item for item in coverage["entries"]}

    assert coverage["complete"] is False
    assert coverage["ambiguous_source_objects"] == 2
    assert rows["EIBactor"]["source_objects"] == 2
    assert rows["EIBactor"]["modeled_endpoints"] == 1
    assert rows["EIBactor"]["duplicate_source_occurrences"] == 1
    assert rows["EIBsensor"]["invalid_or_missing_address"] == 2
    assert rows["EIBPush"]["modeled_logic_blocks"] == 1
    assert rows["EIBline"]["modeled_lines"] == 1
    assert rows["EIBunknown"]["unsupported"] == 1
    assert "Other" not in rows

    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
    )
    assert ProjectQuery(view, {}).status()["coverage_by_source_type"] == coverage
    assert (
        analyze_knx(view, frozenset({"project_connectivity"}))["coverage_by_source_type"]
        == coverage
    )


def test_coverage_caps_groups_and_labels_without_losing_uncertainty():
    types = [f"EIBunknown{i:02d}" for i in range(51)]
    types.append("EIB" + "x" * 150)
    data = "<P>" + "".join(f'<C Type="{name}"/>' for name in types) + "</P>"
    coverage = coverage_by_source_type(_snapshot(data.encode()))

    assert len(coverage["entries"]) == 50
    assert coverage["groups_omitted"] == 2
    assert coverage["complete"] is False
    assert coverage["entries"] == sorted(coverage["entries"], key=lambda row: row["source_type"])
    assert all(len(row["source_type"]) <= 100 for row in coverage["entries"])


def test_coverage_long_type_label_has_stable_bounded_identity():
    source_type = "EIB" + "x" * 150
    coverage = coverage_by_source_type(_snapshot(f'<P><C Type="{source_type}"/></P>'.encode()))
    row = coverage["entries"][0]

    assert row["source_type_truncated"] is True
    assert len(row["source_type"]) == 100
    assert row["unsupported"] == 1
