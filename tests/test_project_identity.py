"""Whole-group identity decisions through the production snapshot and worker paths."""

import struct
import zipfile
import zlib
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest

from mcpserver.loxone.project.graph import build_snapshot
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectBundle, ProjectFile
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError
from mcpserver.loxone.project.worker import process_project
from mcpserver.tools import ProjectDescriptionData, ProjectObjectPageData, ProjectTraceData

UUID = "a" * 32
OTHER = "b" * 32
PORT = "c" * 32


def envelope(plain):
    plain = plain.encode()
    extra = len(plain) - 15
    length = bytes([0xF0]) + bytes([255]) * (extra // 255) + bytes([extra % 255])
    packed = length + plain
    return struct.pack("<IIII", 0xAABBCCEE, len(packed), len(plain), zlib.crc32(plain)) + packed


def block(*, uuid=UUID, kind="Actor", attrs="", children=""):
    return f'<C Type="{kind}" U="{uuid}" {attrs}>{children}</C>'


def snapshot(*sources):
    return build_snapshot(
        ProjectBundle(
            "fixture",
            tuple(
                ProjectFile(f"{index}.LoxCC", envelope(f"<P>{source}</P>"))
                for index, source in enumerate(sources)
            ),
            0,
        )
    )


def project_query(model, *uuids):
    structure = SimpleNamespace(
        last_modified="v1",
        controls=tuple(
            SimpleNamespace(uuid=uuid, action_uuid=None, subcontrols=()) for uuid in uuids
        ),
    )
    return ProjectQuery(ProjectView(model, map_runtime(model, structure)), {})


@pytest.mark.parametrize("kind", ["SysVar", "DigitalIn", "Actor", "Online", "Mode", "VoltageOut"])
def test_equal_occurrences_map_exact_without_using_names(kind):
    model = snapshot(
        block(kind=kind, attrs='Title="First" Desc="one"'),
        block(kind=kind, attrs='Title="Second" Desc="two"'),
    )
    query = project_query(model, UUID)
    assert query.view.mapping.entries[0].status == "exact"
    node = query.resolve(UUID, "runtime_control_uuid")
    detail = query.describe(node, limit=100)
    assert detail["source_occurrence_count"] == 2
    assert len(detail["model_source_ids"]) == 2
    assert len(detail["source_project_node_ids"]) == 2
    assert detail["logical_identity"]["classification"] == "equivalent"
    assert len(model.graph.nodes) == 2
    ProjectDescriptionData.model_validate(detail)
    found = query.find(
        query=None, kind="block", block_type=None, source_id=None, runtime_control_uuid=UUID
    )
    assert len(found) == 1
    ProjectObjectPageData.model_validate({"items": found, "next_cursor": None})


@pytest.mark.parametrize(
    ("sources", "reason"),
    [
        ((block(), block(kind="Mode")), "type_conflict"),
        ((block(), block(attrs='Unknown="value"')), "attribute_conflict"),
        ((block() + block(), block()), "duplicate_source"),
        ((block(children=f'<Co K="I" U="{UUID}"/>'),) * 2, "duplicate_source"),
        ((block(), block(), block(kind="Mode")), "type_conflict"),
        ((block(), block(children='<Co K="I"><In Input="missing"/></Co>')), "topology_unresolved"),
        ((block(), block(children="<Co/><Co/>")), "topology_unresolved"),
        ((block(), block(children='<Co K="I"/><Co K="I"/>')), "topology_unresolved"),
        ((block(), block(children=block(uuid=OTHER))), "topology_unresolved"),
        ((block(), block(children='<PRM Value="unknown"/>')), "topology_unresolved"),
        ((block(children='<PRM Value="unknown"/>'),) * 2, "topology_unresolved"),
        ((block(children="unmodeled text"),) * 2, "topology_unresolved"),
        ((block(children='<Co K="I" K="I"/>'),) * 2, "topology_unresolved"),
        (
            (block(children='<Co K="I" V="1"/>'), block(children='<Co K="I" V="2"/>')),
            "topology_conflict",
        ),
    ],
)
def test_conflicts_never_partially_merge(sources, reason):
    model = snapshot(*sources)
    query = project_query(model, UUID)
    assert query.view.mapping.entries[0].status == "ambiguous"
    assert not model.logical_aliases
    evidence = [
        item
        for key, item in model.logical_identity.items()
        if next(node for node in model.graph.nodes if node.key == key).source_id == UUID
    ]
    assert evidence and all(item.reason == reason for item in evidence)
    assert all(item.classification == "ambiguous" for item in evidence)
    with pytest.raises(ProjectQueryError, match="project_mapping_ambiguous"):
        query.resolve(UUID, "runtime_control_uuid")


def test_disjoint_connector_topology_preserves_every_source_in_queries():
    source = block(uuid=OTHER, kind="Source", children=f'<Co K="Q" U="{PORT}"/>')
    first = source + block(children=f'<Co K="I1"><In Input="{PORT}"/></Co>')
    second = source + block(children=f'<Co K="I2"><In Input="{PORT}"/></Co>')
    model = snapshot(first, second)
    query = project_query(model, UUID, OTHER)
    node = query.resolve(UUID, "runtime_control_uuid")
    assert model.logical_identity[node.key].classification == "complementary"
    detail = query.describe(node, limit=10)
    assert len(detail["child_project_node_ids"]) == 2
    trace = query.trace(node, direction="upstream", max_depth=3, max_nodes=20)
    assert len(trace["edges"]) == 2
    assert not trace["truncated"]
    ProjectTraceData.model_validate(trace)
    observable = query.observable_controls(node, direction="upstream", max_depth=3, max_nodes=20)
    assert not observable["truncated"]
    limited = query.trace(node, direction="upstream", max_depth=3, max_nodes=1)
    assert limited["truncated"] and len(limited["nodes"]) == 1
    alternate = query._nodes[model.occurrence_keys_for(node.key)[-1]]
    limited_alias = query.trace(alternate, direction="upstream", max_depth=3, max_nodes=1)
    assert limited_alias["nodes"][0]["project_node_id"] == alternate.key
    assert "child_project_node_ids" in query.describe(node, limit=1)["truncated_fields"]


def test_same_port_different_neighbors_and_third_source_conflicts_remain_ambiguous():
    def wired(other, port):
        return block(uuid=other, kind="Source", children=f'<Co K="Q" U="{port}"/>') + block(
            children=f'<Co K="I"><In Input="{port}"/></Co>'
        )

    first = wired(OTHER, PORT)
    conflicting = wired("d" * 32, "e" * 32)
    for sources in [(first, conflicting), (first, first, conflicting)]:
        query = project_query(snapshot(*sources), UUID)
        assert query.view.mapping.entries[0].status == "ambiguous"
        assert all(
            item.reason == "topology_conflict"
            for item in query.view.snapshot.logical_identity.values()
        )


def test_conflicting_neighbor_port_attributes_do_not_prove_equivalent_topology():
    def wired(value):
        return block(
            uuid=OTHER, kind="Source", children=f'<Co K="Q" U="{PORT}" Unknown="{value}"/>'
        ) + block(children=f'<Co K="I"><In Input="{PORT}"/></Co>')

    model = snapshot(wired("first"), wired("second"))
    query = project_query(model, UUID)
    assert query.view.mapping.entries[0].status == "ambiguous"
    assert all(item.reason == "topology_unresolved" for item in model.logical_identity.values())


def test_uuid_normalization_single_source_and_control_action_conflicts():
    normalized = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    model = snapshot(block(), block(uuid=normalized))
    assert project_query(model, UUID).view.mapping.entries[0].status == "exact"
    distinct = snapshot(block(), block(uuid=OTHER))
    query = project_query(distinct, UUID, OTHER)
    assert [item.status for item in query.view.mapping.entries] == ["exact", "exact"]
    assert all(
        item.classification == "single_source" for item in distinct.logical_identity.values()
    )
    control = SimpleNamespace(uuid=UUID, action_uuid=OTHER, subcontrols=())
    mapped = map_runtime(distinct, SimpleNamespace(last_modified="v", controls=(control,)))
    assert mapped.entries[0].status == "ambiguous"
    invalid = snapshot(block(uuid="invalid"), block(uuid="invalid"))
    assert not invalid.logical_aliases and not invalid.logical_identity


def test_group_bounds_order_and_unmodeled_families():
    assert len(snapshot(*[block()] * 32).logical_aliases) == 32
    model = snapshot(*[block()] * 33)
    assert not model.logical_aliases
    assert all(
        item.reason == "source_limit" and item.candidates_omitted == 1
        for item in model.logical_identity.values()
    )
    query = project_query(model, UUID)
    for node in model.graph.nodes:
        ProjectDescriptionData.model_validate(query.describe(node, limit=1))
    first, second = block(attrs='Title="one"'), block(attrs='Title="two"')
    original = snapshot(first, second)
    reverse = replace(
        ProjectBundle(
            "fixture",
            (
                ProjectFile("1.LoxCC", envelope(f"<P>{second}</P>")),
                ProjectFile("0.LoxCC", envelope(f"<P>{first}</P>")),
            ),
            0,
        )
    )
    reordered = build_snapshot(reverse)
    assert original.logical_aliases == reordered.logical_aliases
    assert original.logical_identity == reordered.logical_identity
    assert not snapshot(block(kind="Other"), block(kind="Other")).logical_aliases


def test_hierarchy_conflict_and_cycles_do_not_create_unbounded_or_guessed_traces():
    parent = block(uuid=OTHER, kind="Parent", children=block())
    conflicting = snapshot(block(), parent)
    assert project_query(conflicting, UUID).view.mapping.entries[0].status == "ambiguous"
    cycle = block(children=(f'<Co K="Q" U="{PORT}"><In Input="{PORT}"/></Co>'))
    model = snapshot(cycle, cycle)
    query = project_query(model, UUID)
    node = query.resolve(UUID, "runtime_control_uuid")
    trace = query.trace(node, direction="upstream", max_depth=3, max_nodes=20)
    assert len(trace["edges"]) == 2 and not trace["truncated"]
    assert len(trace["nodes"]) == 4


@pytest.mark.asyncio
async def test_real_worker_preserves_logical_identity_and_provenance():
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for index in range(2):
            archive.writestr(f"{index}.LoxCC", envelope(f"<P>{block()}</P>"))
    model, _ = await process_project(stream.getvalue())
    query = project_query(model, UUID)
    assert model.model_version == 15
    node = query.resolve(UUID, "runtime_control_uuid")
    assert model.logical_identity[node.key].reason == "equal_topology"
    assert len(model.occurrence_keys_for(node.key)) == 2
