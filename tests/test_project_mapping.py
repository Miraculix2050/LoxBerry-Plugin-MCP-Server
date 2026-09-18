from dataclasses import replace
from types import SimpleNamespace

from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import map_runtime
from mcpserver.loxone.project.parser import parse_project


def control(uuid, action=None, children=()):
    return SimpleNamespace(uuid=uuid, action_uuid=action, subcontrols=children)


def test_exact_nested_ambiguous_and_unmapped_are_explicit():
    first, second, missing = "a" * 32, "b" * 32, "c" * 32
    parsed = parse_project(f'<P><C U="{first}"/><C U="{second}"/><C U="{second}"/></P>'.encode())
    snapshot = ProjectSnapshot(
        "hash", 1, (ProjectPartSummary("p", 4, ()),), build_graph((("p", parsed),))
    )
    structure = SimpleNamespace(
        last_modified="v1",
        controls=(control(first, children=(control(second), control(missing))),),
    )
    mapped = map_runtime(snapshot, structure)
    assert [entry.status for entry in mapped.entries] == ["exact", "ambiguous", "unmapped"]
    assert mapped.entries[0].node_keys == ("p:1",)
    assert mapped.entries[0].rule == "control_uuid"
    assert map_runtime(replace(snapshot, fingerprint="new"), structure).project_fingerprint == "new"
    structure.last_modified = "v2"
    assert map_runtime(snapshot, structure).structure_fingerprint != mapped.structure_fingerprint


def test_conflicting_uuid_and_action_matches_are_not_guessed():
    first, second = "a" * 32, "b" * 32
    parsed = parse_project(f'<P><C U="{first}"/><C U="{second}"/></P>'.encode())
    snapshot = ProjectSnapshot(
        "hash", 1, (ProjectPartSummary("p", 3, ()),), build_graph((("p", parsed),))
    )
    result = map_runtime(
        snapshot, SimpleNamespace(last_modified="v", controls=(control(first, second),))
    )
    assert result.entries[0].status == "ambiguous"
    assert result.entries[0].rule == "control_uuid+action_uuid"


def test_missing_action_uuid_cannot_match_an_invalid_project_identifier():
    parsed = parse_project(b'<P><C U="-"/></P>')
    snapshot = ProjectSnapshot(
        "hash", 1, (ProjectPartSummary("p", 2, ()),), build_graph((("p", parsed),))
    )
    result = map_runtime(
        snapshot, SimpleNamespace(last_modified="v", controls=(control("a" * 32),))
    )
    assert result.entries[0].status == "unmapped"
    assert result.entries[0].rule == "none"
