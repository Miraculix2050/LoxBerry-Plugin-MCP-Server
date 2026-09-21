from types import SimpleNamespace

import pytest

from mcpserver.loxone.project.graph import (
    ProjectPartSummary,
    ProjectSnapshot,
    ProjectSourceDiagnostic,
    ProjectSourceDiagnostics,
    build_graph,
)
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError


def control(uuid, action=None, children=()):
    return SimpleNamespace(uuid=uuid, action_uuid=action, subcontrols=children)


def query() -> ProjectQuery:
    source, target, source_connector = "a" * 32, "b" * 32, "c" * 32
    parsed = parse_project(
        (
            f'<P><C Type="Source" U="{source}"><Co K="AQ" U="{source_connector}"/></C>'
            f'<C Type="Target" U="{target}"><Co K="AI" U="d">'
            f'<In Input="{source_connector}"/></Co></C>'
            '<C Type="Unknown" U="e"/></P>'
        ).encode()
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 8, ()),), build_graph((("p", parsed),))
    )
    structure = SimpleNamespace(last_modified="v1", controls=(control(target),))
    return ProjectQuery(
        ProjectView(snapshot, map_runtime(snapshot, structure)), {target: "Living room"}
    )


def test_find_status_and_describe_are_deterministic_and_bounded():
    project = query()
    assert project.status()["mapping"] == {"exact": 1, "ambiguous": 0, "unmapped": 0}
    found = project.find(
        query="living", kind=None, block_type=None, source_id=None, runtime_control_uuid=None
    )
    assert len(found) == 1
    assert found[0]["block_type"] == "Target"
    described = project.describe(project.resolve("p:4", "project_node_id"), limit=1)
    assert described["connector_key"] == "AI"
    assert described["relationships"][0]["kind"] == "signal"
    assert described["truncated_fields"] == []
    assert (
        project.find(
            query=None,
            kind="block",
            block_type="Unknown",
            source_id=None,
            runtime_control_uuid=None,
        )[0]["block_type"]
        == "Unknown"
    )


def test_source_diagnostics_are_available_without_unknown_values():
    parsed = parse_project(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="invalid" Extra="secret"/></P>'
    )
    snapshot = ProjectSnapshot(
        "project",
        4,
        (ProjectPartSummary("p", 2, ()),),
        build_graph((("p", parsed),)),
        ProjectSourceDiagnostics(
            (
                ProjectSourceDiagnostic(
                    "unmodeled_knx_attribute", 1, "EIBsensor", "Extra", "text", "1-16", ("p:1",), 0
                ),
            ),
            True,
            0,
        ),
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    assert project.status()["source_diagnostics"]["entries"] == [
        {"code": "unmodeled_knx_attribute", "count": 1}
    ]
    described = project.describe(project.resolve("p:1", "project_node_id"), limit=10)
    unknown = next(
        item
        for item in described["source_diagnostics"]
        if item["code"] == "unmodeled_knx_attribute"
    )
    assert unknown["attribute_name"] == "Extra"
    assert "secret" not in repr(described["source_diagnostics"])


def test_describe_reports_incomplete_rules_and_diagnostic_truncation():
    attributes = " ".join(f'Extra{index}="x"' for index in range(51))
    parsed = parse_project(
        f'<P><C Type="EIBPush" U="push" {attributes}><Co K="Tg" U="trigger"/></C></P>'.encode()
    )
    snapshot = ProjectSnapshot(
        "project", 4, (ProjectPartSummary("p", 3, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    described = project.describe(project.resolve("p:1", "project_node_id"), limit=10)

    assert any(
        item["code"] == "incomplete_knx_signal_rule" for item in described["source_diagnostics"]
    )
    assert described["source_diagnostics_truncated"] is True
    assert described["source_diagnostics_omitted"] >= 1


def test_trace_excludes_containment_and_reports_limits():
    project = query()
    complete = project.trace(
        project.resolve("b" * 32, "runtime_control_uuid"),
        direction="upstream",
        max_depth=1,
        max_nodes=10,
    )
    assert complete["truncated"] is False
    assert len(complete["edges"]) == 1
    result = project.trace(
        project.resolve("b" * 32, "runtime_control_uuid"),
        direction="upstream",
        max_depth=1,
        max_nodes=1,
    )
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_nodes"
    assert all(edge["kind"] in {"signal", "reference"} for edge in result["edges"])


def test_trace_stops_containment_seeding_at_node_limit():
    parsed = parse_project(b'<P><C U="root"><Co U="one"/><Co U="two"/></C></P>')
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 4, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:1", "project_node_id"),
        direction="downstream",
        max_depth=1,
        max_nodes=1,
    )

    assert [item["project_node_id"] for item in result["nodes"]] == ["p:1"]
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_nodes"


def test_trace_caps_unresolved_relationships():
    parsed = parse_project(
        b'<P><C U="root"><Co U="connector"><In Input="missing-one"/>'
        b'<In Input="missing-two"/></Co></C></P>'
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 5, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:2", "project_node_id"),
        direction="upstream",
        max_depth=1,
        max_nodes=1,
    )

    assert len(result["unresolved_relationships"]) == 1
    assert result["unresolved_truncated"] is True


def test_ambiguous_runtime_mapping_is_never_guessed():
    project = query()
    with pytest.raises(ProjectQueryError, match="project_node_unknown"):
        project.resolve("missing", "runtime_control_uuid")


def test_describe_caps_each_relationship_collection():
    parsed = parse_project(b'<P><C U="root"><Co U="one"/><Co U="two"/></C></P>')
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 4, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.describe(project.resolve("p:1", "project_node_id"), limit=1)

    assert result["child_project_node_ids"] == ["p:2"]
    assert result["truncated_fields"] == ["child_project_node_ids"]


def test_trace_keeps_converging_edges_without_unbounded_edge_output():
    parsed = parse_project(
        b'<P><C U="a"><Co U="a1"/></C><C U="b"><Co U="b1"><In Input="a1"/>'
        b'</Co></C><C U="c"><Co U="c1"><In Input="a1"/></Co></C><C U="d">'
        b'<Co U="d1"><In Input="b1"/><In Input="c1"/></Co></C></P>'
    )
    snapshot = ProjectSnapshot(
        "project", 1, (ProjectPartSummary("p", 12, ()),), build_graph((("p", parsed),))
    )
    project = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )

    result = project.trace(
        project.resolve("p:1", "project_node_id"), direction="downstream", max_depth=3, max_nodes=10
    )

    assert len(result["edges"]) == 4
    assert result["truncated"] is False
