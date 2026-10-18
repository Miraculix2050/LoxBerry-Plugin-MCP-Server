from dataclasses import replace
from types import SimpleNamespace

import pytest

from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, NamedGroup, Room
from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import map_runtime, prepare_runtime_mapping
from mcpserver.loxone.project.parser import parse_project


def test_prepared_mapping_is_immutable_and_bound_to_its_structure():
    uuid = "a" * 32
    parsed = parse_project(f'<P><C U="{uuid}"/></P>'.encode())
    snapshot = ProjectSnapshot(
        "hash", 1, (ProjectPartSummary("p", 2, ()),), build_graph((("p", parsed),))
    )
    structure = LoxoneStructure(
        LoxoneIdentity("reader", "serial"),
        "marker",
        (Room("room", "Room"),),
        (NamedGroup("category", "Category"),),
        (Control(uuid, "Visible", "Switch", "room", "category", None, ()),),
    )
    prepared = prepare_runtime_mapping(structure)
    assert map_runtime(snapshot, structure, prepared=prepared) == map_runtime(snapshot, structure)
    with pytest.raises(TypeError):
        prepared.rooms["room"] = "Changed"
    with pytest.raises(TypeError):
        prepared.categories["category"] = "Changed"
    with pytest.raises(ValueError, match="another structure"):
        map_runtime(snapshot, replace(structure), prepared=prepared)


def control(uuid, action=None, children=(), **kwargs):
    return SimpleNamespace(uuid=uuid, action_uuid=action, subcontrols=children, **kwargs)


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


def test_runtime_presentation_evidence_is_attached_only_to_exact_uuid_mappings():
    exact, ambiguous = "a" * 32, "b" * 32
    parsed = parse_project(
        f'<P><C U="{exact}"/><C U="{ambiguous}"/><C U="{ambiguous}"/></P>'.encode()
    )
    snapshot = ProjectSnapshot(
        "hash", 1, (ProjectPartSummary("p", 3, ()),), build_graph((("p", parsed),))
    )
    structure = SimpleNamespace(
        last_modified="v1",
        rooms=(SimpleNamespace(uuid="room", name="Office"),),
        categories=(SimpleNamespace(uuid="category", name="Lights"),),
        controls=(
            control(
                exact,
                name="Office light",
                control_type="Switch",
                room_uuid="room",
                category_uuid="category",
            ),
            control(ambiguous, name="Not attributable", control_type="Switch"),
        ),
    )

    result = map_runtime(snapshot, structure)

    assert result.entries[0].evidence is not None
    assert result.entries[0].evidence.name == "Office light"
    assert result.entries[0].evidence.room_name == "Office"
    assert result.entries[0].evidence.category_name == "Lights"
    assert result.entries[1].evidence is None


def parent_snapshot(*, ambiguous=False):
    xml = '<P><C U="' + "a" * 32 + '"/>'
    if ambiguous:
        xml += '<C U="' + "a" * 32 + '"/>'
    parsed = parse_project((xml + "</P>").encode())
    return ProjectSnapshot("parent-project", 1, (), build_graph((("p", parsed),)))


@pytest.mark.parametrize(
    "parent_type,child_type,key",
    [
        ("LightControllerV2", "Switch", "AI1"),
        ("LightControllerV2", "Dimmer", "AI2"),
        ("LightControllerV2", "ColorPickerV2", "AI3"),
        ("Intercom", "Pushbutton", "bell"),
        ("DoorController", "Pushbutton", "button"),
        ("SmokeAlarm", "Tracker", "activities"),
        ("Irrigation", "Tracker", "activities"),
        ("IRoomControllerV2", "IRCV2Daytimer", "b" * 32),
    ],
)
def test_normalized_explicit_children_have_parent_provenance(parent_type, child_type, key):
    from mcpserver.loxone.structure import normalize_structure

    parent_uuid = "a" * 32
    child_uuid = key if child_type == "IRCV2Daytimer" else parent_uuid + "/" + key
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": "synthetic"},
            "controls": {
                parent_uuid: {
                    "name": "Parent",
                    "type": parent_type,
                    "subControls": {
                        child_uuid: {"name": "Child", "type": child_type, "uuidAction": child_uuid}
                    },
                }
            },
        },
        username="reader",
    )
    entries = map_runtime(parent_snapshot(), structure).entries
    child = entries[1]
    assert child.status == "unmapped" and child.node_keys == () and child.evidence is None
    assert child.mapping_status == "derived_from_parent"
    assert child.parent.parent_runtime_control_uuid == parent_uuid
    assert child.parent.subcontrol_key == key
    assert child.parent.parent_project_node_ids == ("p:1",)
    assert child.parent.runtime_parent_chain == (parent_uuid,)
    assert child.parent.mapping_rule == "explicit_runtime_parent_v1"


def test_suffix_and_names_alone_never_establish_parent_evidence():
    child_uuid = "a" * 32 + "/AI1"
    result = map_runtime(
        parent_snapshot(),
        SimpleNamespace(
            last_modified="v", controls=(control("a" * 32), control(child_uuid, name="Parent"))
        ),
    )
    assert result.entries[1].parent is None
    assert result.entries[1].mapping_status == "unmapped"


@pytest.mark.parametrize(
    "ambiguous,expected", [(False, "derived_parent_unmapped"), (True, "derived_parent_ambiguous")]
)
def test_unresolved_parents_are_explicit(ambiguous, expected):
    parent_uuid = "a" * 32 if ambiguous else "f" * 32
    result = map_runtime(
        parent_snapshot(ambiguous=ambiguous),
        SimpleNamespace(
            last_modified="v", controls=(control(parent_uuid, children=(control("child"),)),)
        ),
    )
    assert result.entries[1].mapping_status == expected
    assert result.entries[1].node_keys == ()


def test_explicit_nested_parent_chain_and_relationship_fingerprint():
    root = "a" * 32
    child = control("child")
    first = SimpleNamespace(
        last_modified="same",
        controls=(control(root, children=(control("middle", children=(child,)),)),),
    )
    second = SimpleNamespace(
        last_modified="same", controls=(control(root, children=(child, control("middle"))),)
    )
    result = map_runtime(parent_snapshot(), first)
    assert result.entries[2].parent.runtime_parent_chain == ("middle", root)
    assert result.entries[2].parent.anchor_runtime_control_uuid == root
    assert result.entries[2].mapping_status == "derived_from_parent"
    assert result.entries[2].parent.parent_mapping_status == "derived_from_parent"
    assert (
        result.structure_fingerprint != map_runtime(parent_snapshot(), second).structure_fingerprint
    )


def test_conflicting_parents_and_cycles_never_choose_an_anchor():
    shared = control("child")
    structure = SimpleNamespace(
        last_modified="v",
        controls=(control("a" * 32, children=(shared,)), control("other", children=(shared,))),
    )
    result = map_runtime(parent_snapshot(), structure)
    assert result.entries[1].mapping_status == "derived_parent_ambiguous"
    assert result.entries[1].parent.reason == "conflicting_runtime_parents"
    cycle = control("cycle")
    cycle.subcontrols = (cycle,)
    result = map_runtime(parent_snapshot(), SimpleNamespace(last_modified="v", controls=(cycle,)))
    assert result.entries[0].parent.reason == "conflicting_runtime_parents"


def test_parent_depth_limit_is_not_successful_mapping():
    nested = control("leaf")
    for index in range(17):
        nested = control(f"nested-{index}", children=(nested,))
    root = control("a" * 32, children=(nested,))
    result = map_runtime(parent_snapshot(), SimpleNamespace(last_modified="v", controls=(root,)))
    assert result.entries[-1].mapping_status == "derived_parent_unmapped"
    assert result.entries[-1].parent.reason == "parent_depth_limit"
    assert result.entries[-1].parent.parent_mapping_status == "derived_parent_unmapped"
    assert result.entries[-2].parent.parent_mapping_status == "derived_from_parent"


@pytest.mark.parametrize("ambiguous", [False, True])
def test_own_mapping_always_precedes_runtime_parent(ambiguous):
    result = map_runtime(
        parent_snapshot(ambiguous=ambiguous),
        SimpleNamespace(
            last_modified="v", controls=(control("missing", children=(control("a" * 32),)),)
        ),
    )
    assert result.entries[1].status == ("ambiguous" if ambiguous else "exact")
    assert result.entries[1].parent is None
