"""Synthetic end-to-end contracts for explicit runtime containment evidence."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE
from mcpserver.loxone.models import Freshness, StateRecord
from mcpserver.loxone.project.graph import ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery, ProjectQueryError
from mcpserver.loxone.structure import normalize_structure

PARENT = "a" * 32
CHILD = PARENT + "/AI1"


def derived_query(count=2):
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": "synthetic"},
            "controls": {
                PARENT: {
                    "name": "Parent",
                    "type": "LightControllerV2",
                    "states": {"value": "parent-state"},
                    "subControls": {
                        PARENT + f"/AI{index + 1}": {
                            "name": "Child",
                            "type": "Switch",
                            "states": {"active": f"child-{index}"},
                        }
                        for index in range(count)
                    },
                }
            },
        },
        username="reader",
    )
    parsed = parse_project(f'<P><C U="{PARENT}" Type="LightControllerV2"/></P>'.encode())
    snapshot = ProjectSnapshot("synthetic-project", 1, (), build_graph((("p", parsed),)))
    query = ProjectQuery(
        ProjectView(snapshot, map_runtime(snapshot, structure)), {PARENT: "Parent"}
    )
    return query, SimpleNamespace(structure=structure, connected=True, structure_generation=1)


def test_query_keeps_parent_topology_and_legacy_counters_separate():
    query, _ = derived_query()
    assert query.status()["mapping"] == {"exact": 1, "ambiguous": 0, "unmapped": 2}
    breakdown = query.status()["mapping_breakdown"]
    assert breakdown["derived_from_parent"] == 2 and breakdown["independent_unmapped"] == 0
    assert query.resolve(CHILD, "runtime_control_uuid").key == "p:1"
    inventory = [
        query.mapping_evidence(entry.control_uuid)
        for entry in query.mapping_inventory_entries(mapping_status="derived_from_parent")
    ]
    assert len(inventory) == 2
    assert inventory[0]["project_node_ids"] == []
    assert inventory[0]["parent_project_node_ids"] == ["p:1"]
    assert inventory[0]["model_source_ids"] == ["p"]
    found = query.find(
        query=None, kind=None, block_type=None, source_id=None, runtime_control_uuid=CHILD
    )
    assert found[0]["runtime_target_mapping"] == inventory[0]
    assert found[0]["runtime_control"]["uuid"] == PARENT
    analysis = query.observable_controls(
        query.resolve(CHILD, "runtime_control_uuid"), direction="both", max_depth=2, max_nodes=10
    )
    assert [item["control_uuid"] for item in analysis["controls"]] == [PARENT]


def test_hidden_parent_subtree_never_enters_mapping_inventory():
    query, snapshot = derived_query()
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": "synthetic"},
            "controls": {
                PARENT: {
                    "name": "Hidden",
                    "type": "LightControllerV2",
                    "restrictions": 1,
                    "subControls": {CHILD: {"name": "Hidden child", "type": "Switch"}},
                }
            },
        },
        username="reader",
    )
    hidden = ProjectQuery(
        ProjectView(query.view.snapshot, map_runtime(query.view.snapshot, structure)), {}
    )
    assert hidden.mapping_inventory_entries() == []
    with pytest.raises(ProjectQueryError, match="project_node_unknown"):
        hidden.resolve(CHILD, "runtime_control_uuid")
    assert snapshot.structure.controls


@pytest.mark.parametrize("candidate_count", [0, 2, 40])
def test_parent_failure_and_bounded_candidate_provenance(candidate_count):
    query, snapshot = derived_query()
    parsed = parse_project(("<P>" + f'<C U="{PARENT}"/>' * candidate_count + "</P>").encode())
    project = ProjectSnapshot("changed-project", 1, (), build_graph((("p", parsed),)))
    query = ProjectQuery(ProjectView(project, map_runtime(project, snapshot.structure)), {})
    expected = "derived_parent_ambiguous" if candidate_count else "derived_parent_unmapped"
    entry = query.mapping_inventory_entries(runtime_control_uuid=CHILD)[0]
    row = query.mapping_evidence(entry.control_uuid)
    assert row["mapping_status"] == expected
    assert len(row["parent_project_node_ids"]) == min(candidate_count, 32)
    assert row["references_truncated"] == (candidate_count > 32)
    error = "project_mapping_ambiguous" if candidate_count else "project_node_unknown"
    with pytest.raises(ProjectQueryError, match=error):
        query.resolve(CHILD, "runtime_control_uuid")


def install_tools(monkeypatch, query, snapshot):
    access = SimpleNamespace(family_id="family", scopes={READ_SCOPE, HISTORY_SCOPE})
    monkeypatch.setattr(tools, "_access", lambda: access)
    monkeypatch.setattr(tools, "_project_query", AsyncMock(return_value=(query, snapshot)))
    monkeypatch.setattr(tools, "_history_project_query", AsyncMock(return_value=(query, snapshot)))
    runtime = SimpleNamespace(
        projects=SimpleNamespace(authorize=AsyncMock()),
        state=lambda _snapshot, uuid: StateRecord(uuid, True, Freshness.CURRENT, 1.0),
    )
    server = FastMCP("derived-mapping")
    tools.register_project_tools(server, runtime)
    tools.register_observability_tools(server, runtime, None)
    return server, access


@pytest.mark.asyncio
async def test_inventory_cursor_filters_and_fresh_authorization(monkeypatch):
    query, snapshot = derived_query(3)
    server, access = install_tools(monkeypatch, query, snapshot)
    status = server._tool_manager.get_tool("loxone_get_project_status").fn
    for invalid in (
        {"mapping_status": "exact"},
        {"cursor": "bad"},
        {"runtime_control_uuid": CHILD},
    ):
        result = await status(**invalid)
        assert not result.ok and result.data.error == "invalid_input"
    first = await status(include_mapping_inventory=True, limit=1)
    cursor = first.data.mapping_inventory.next_cursor
    assert first.data.mapping_inventory.items[0].runtime_control_uuid == PARENT
    second = await status(include_mapping_inventory=True, limit=1, cursor=cursor)
    assert second.data.mapping_inventory.items[0].runtime_control_uuid == CHILD
    filtered = await status(
        include_mapping_inventory=True,
        mapping_status="derived_from_parent",
        runtime_control_uuid=CHILD,
    )
    assert len(filtered.data.mapping_inventory.items) == 1
    for kwargs in ({"mapping_status": "exact"}, {"runtime_control_uuid": CHILD}):
        invalid = await status(include_mapping_inventory=True, cursor=cursor, **kwargs)
        assert not invalid.ok and invalid.data.error == "invalid_input"
    access.family_id = "other-family"
    assert not (await status(include_mapping_inventory=True, cursor=cursor)).ok
    access.family_id = "family"
    changed_view = replace(
        query.view, mapping=replace(query.view.mapping, structure_fingerprint="new")
    )
    changed = ProjectQuery(changed_view, {})
    monkeypatch.setattr(tools, "_project_query", AsyncMock(return_value=(changed, snapshot)))
    assert not (await status(include_mapping_inventory=True, cursor=cursor)).ok
    monkeypatch.setattr(tools, "_project_query", AsyncMock(side_effect=PermissionError()))
    denied = await status(include_mapping_inventory=True, cursor=cursor)
    assert not denied.ok and denied.data.error == "unauthenticated"


@pytest.mark.asyncio
async def test_child_trace_describe_and_observability_do_not_claim_child_topology(monkeypatch):
    query, snapshot = derived_query()
    server, _ = install_tools(monkeypatch, query, snapshot)
    trace = await server._tool_manager.get_tool("loxone_trace_project_logic").fn(
        CHILD, "runtime_control_uuid", "upstream"
    )
    assert trace.data.start.project_node_id == "p:1"
    assert trace.data.runtime_target_mapping.runtime_control_uuid == CHILD
    assert len(trace.data.nodes) == 1 and trace.data.edges == []
    description = await server._tool_manager.get_tool("loxone_describe_project_object").fn(
        CHILD, "runtime_control_uuid"
    )
    assert description.data.runtime_target_mapping.parent_project_node_ids == ["p:1"]
    observable = await server._tool_manager.get_tool("loxone_analyze_observability").fn(
        CHILD, "runtime_control_uuid", "both", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"
    )
    assert observable.ok
    data = observable.data
    assert data.summary.relevant_controls == 1 and data.summary.current_state_controls == 1
    assert data.summary.historical_missing == 0 and data.summary.historical_unverified == 1
    assert [item.control_uuid for item in data.controls] == [PARENT]
    child = data.target_runtime_evidence
    assert child.control_uuid == CHILD and child.project_node_ids == []
    assert child.current_states[0].uuid == "child-0"
    assert child.runtime_target_mapping.mapping_status == "derived_from_parent"
    assert data.controls[0].current_states[0].uuid == "parent-state"


@pytest.mark.asyncio
async def test_inventory_byte_trimming_continues_without_skips(monkeypatch):
    query, snapshot = derived_query(20)
    server, _ = install_tools(monkeypatch, query, snapshot)
    status = server._tool_manager.get_tool("loxone_get_project_status").fn
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 3000)
    seen, cursor = [], None
    while True:
        result = await status(include_mapping_inventory=True, limit=100, cursor=cursor)
        assert result.ok and len(result.model_dump_json().encode()) <= 3000
        page = result.data.mapping_inventory
        assert page.items
        seen.extend(item.runtime_control_uuid for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        assert page.truncated and len(seen) <= 21
    assert seen == sorted([PARENT] + [PARENT + f"/AI{i + 1}" for i in range(20)])
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", 100)
    oversized = await status(include_mapping_inventory=True)
    assert not oversized.ok and oversized.data.error == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_large_inventory_projects_only_the_requested_page(monkeypatch):
    query, snapshot = derived_query(19_999)
    server, _ = install_tools(monkeypatch, query, snapshot)
    projected = []
    original = ProjectQuery.mapping_evidence

    def record_projection(self, identifier):
        projected.append(identifier)
        return original(self, identifier)

    monkeypatch.setattr(ProjectQuery, "mapping_evidence", record_projection)
    status = server._tool_manager.get_tool("loxone_get_project_status").fn
    first = await status(include_mapping_inventory=True, limit=1)
    assert first.ok and projected == [PARENT]
    projected.clear()
    second = await status(
        include_mapping_inventory=True, limit=1, cursor=first.data.mapping_inventory.next_cursor
    )
    assert second.ok and projected == [CHILD]
