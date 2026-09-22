from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE
from mcpserver.loxone.event_history import EventHistoryCoverage
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneIdentity,
    LoxoneStructure,
    StateRecord,
    StatisticSeries,
)
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.query import ProjectQueryError
from mcpserver.tools import (
    PROJECT_RESPONSE_MAX_BYTES,
    register_observability_tools,
    register_project_tools,
)


class Query:
    view = SimpleNamespace(
        mapping=SimpleNamespace(structure_fingerprint="b" * 64),
        snapshot=SimpleNamespace(fingerprint="a" * 64, model_version=1),
    )

    def status(self):
        return {
            "project_fingerprint": "a" * 64,
            "model_version": 1,
            "project_parts": 1,
            "nodes": 3,
            "edges": 2,
            "unresolved_relationships": 0,
            "mapping": {"exact": 1, "ambiguous": 0, "unmapped": 0},
            "source_diagnostics": {
                "entries": [],
                "complete": True,
                "groups_omitted": 0,
                "labels_truncated": False,
            },
        }

    def find(self, **_kwargs):
        return [
            {
                "project_node_id": "p:1",
                "kind": "block",
                "block_type": "Switch",
                "source_id": "source",
                "connector_key": None,
                "runtime_control": None,
            }
        ]

    def resolve(self, identifier, _identifier_type):
        if identifier == "ambiguous":
            raise ProjectQueryError("project_mapping_ambiguous")
        return object()

    def describe(self, _node, **_kwargs):
        return {
            **self.find()[0],
            "parent_project_node_id": None,
            "child_project_node_ids": [],
            "relationships": [],
            "unresolved_relationships": [],
            "truncated_fields": [],
        }

    def trace(self, _node, **_kwargs):
        return {
            "start": self.find()[0],
            "direction": "upstream",
            "nodes": self.find(),
            "edges": [],
            "truncated": False,
            "truncation_reason": None,
            "unresolved_relationships": [],
            "unresolved_truncated": False,
        }

    def observable_controls(self, _node, **_kwargs):
        return {
            "target": self.find()[0],
            "controls": [
                {
                    "control_uuid": "control",
                    "project_node_ids": ["p:1"],
                    "directions": ["upstream"],
                }
            ],
            "truncated": False,
            "truncation_reasons": [],
            "unresolved_relationships": 0,
            "unresolved_truncated": False,
        }


@pytest.mark.asyncio
async def test_project_tools_publish_bounded_read_only_contracts(monkeypatch):
    async def project_query(_runtime):
        return Query(), SimpleNamespace(connected=True, structure_generation=7)

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    server = FastMCP("project-tools")
    register_project_tools(server, None)

    status = await server._tool_manager.get_tool("loxone_get_project_status").fn()  # type: ignore[union-attr]
    found = await server._tool_manager.get_tool("loxone_find_project_objects").fn()  # type: ignore[union-attr]
    described = await server._tool_manager.get_tool("loxone_describe_project_object").fn("p:1")  # type: ignore[union-attr]
    traced = await server._tool_manager.get_tool("loxone_trace_project_logic").fn(  # type: ignore[union-attr]
        "p:1", "project_node_id", "upstream"
    )

    assert status.data.structure_generation == 7  # type: ignore[union-attr]
    assert found.data.items[0].project_node_id == "p:1"  # type: ignore[union-attr]
    assert described.data.relationships == []  # type: ignore[union-attr]
    assert traced.data.direction == "upstream"  # type: ignore[union-attr]
    assert all(tool.annotations.readOnlyHint for tool in server._tool_manager.list_tools())


@pytest.mark.asyncio
async def test_project_tools_keep_structured_mapping_and_cursor_errors(monkeypatch):
    async def project_query(_runtime):
        return Query(), SimpleNamespace(connected=True, structure_generation=1)

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    server = FastMCP("project-tool-errors")
    register_project_tools(server, None)

    describe = await server._tool_manager.get_tool("loxone_describe_project_object").fn(  # type: ignore[union-attr]
        "ambiguous"
    )
    invalid_cursor = await server._tool_manager.get_tool("loxone_find_project_objects").fn(  # type: ignore[union-attr]
        cursor="invalid"
    )

    assert describe.ok is False
    assert describe.data.error == "ambiguous_mapping"  # type: ignore[union-attr]
    assert invalid_cursor.data.error == "invalid_input"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_observability_reports_current_sources_and_explicit_history_gaps(monkeypatch):
    control = Control(
        "control",
        "Temperature",
        "Switch",
        None,
        None,
        None,
        (("value", "state-complete"), ("window", "state-missing")),
        statistic_series=(
            StatisticSeries("series", "statistic_v2", "group", "output", "Trend", "°C"),
        ),
    )
    structure = LoxoneStructure(LoxoneIdentity("user", "serial"), "modified", (), (), (control,))
    snapshot = SimpleNamespace(connected=True, structure=structure, structure_generation=1)

    async def history_project_query(_runtime, access):
        assert HISTORY_SCOPE in access.scopes
        return Query(), snapshot

    class Runtime:
        def state(self, _snapshot, state_uuid):
            return StateRecord(
                state_uuid,
                21.5 if state_uuid == "state-complete" else None,
                Freshness.CURRENT if state_uuid == "state-complete" else Freshness.UNKNOWN,
                100.0 if state_uuid == "state-complete" else None,
            )

    class EventHistory:
        async def coverage(self, _access, _sources, **_kwargs):
            return True, {
                ("control", "state-complete"): EventHistoryCoverage(1.0, 1.0, "complete", True)
            }

    monkeypatch.setattr(tools_module, "_history_project_query", history_project_query)
    monkeypatch.setattr(
        tools_module,
        "_access",
        lambda: SimpleNamespace(scopes=frozenset((READ_SCOPE, HISTORY_SCOPE)), family_id="family"),
    )
    server = FastMCP("observability")
    register_observability_tools(server, Runtime(), EventHistory())  # type: ignore[arg-type]

    result = await server._tool_manager.get_tool("loxone_analyze_observability").fn(  # type: ignore[union-attr]
        "control",
        "runtime_control_uuid",
        "upstream",
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
    )

    assert result.ok is True
    data = result.data
    assert data.controls[0].current_states[0].available is True
    assert data.controls[0].native_statistics[0].temporal_coverage == "not_checked"
    assert data.controls[0].local_event_history[0].status == "complete"
    assert data.controls[0].local_event_history[1].status == "not_configured"
    assert data.controls[0].historical_status == "partial"
    assert data.summary.local_history_partial == 1
    assert result.stale is True


@pytest.mark.asyncio
async def test_observability_state_truncation_without_history_remains_missing(monkeypatch):
    control = Control(
        "control",
        "Many states",
        "Switch",
        None,
        None,
        None,
        tuple((f"state-{index}", f"uuid-{index}") for index in range(21)),
    )
    structure = LoxoneStructure(LoxoneIdentity("user", "serial"), "modified", (), (), (control,))
    snapshot = SimpleNamespace(connected=True, structure=structure, structure_generation=1)

    async def history_project_query(_runtime, _access):
        return Query(), snapshot

    class Runtime:
        def state(self, _snapshot, state_uuid):
            return StateRecord(state_uuid, None, Freshness.UNKNOWN, None)

    class EventHistory:
        async def coverage(self, _access, _sources, **_kwargs):
            return False, {}

    monkeypatch.setattr(tools_module, "_history_project_query", history_project_query)
    monkeypatch.setattr(
        tools_module,
        "_access",
        lambda: SimpleNamespace(scopes=frozenset((READ_SCOPE, HISTORY_SCOPE)), family_id="family"),
    )
    server = FastMCP("observability-state-truncation")
    register_observability_tools(server, Runtime(), EventHistory())  # type: ignore[arg-type]

    result = await server._tool_manager.get_tool("loxone_analyze_observability").fn(  # type: ignore[union-attr]
        "control",
        "runtime_control_uuid",
        "upstream",
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
    )

    assert result.ok is True
    data = result.data
    assert data.controls[0].states_truncated is True
    assert data.controls[0].historical_status == "missing"
    assert data.summary.local_history_missing == 1
    assert data.summary.historical_missing == 1


@pytest.mark.asyncio
async def test_observability_requires_history_scope(monkeypatch):
    monkeypatch.setattr(
        tools_module,
        "_access",
        lambda: SimpleNamespace(scopes=frozenset((READ_SCOPE,)), family_id="family"),
    )
    server = FastMCP("observability-scope")
    register_observability_tools(server, None, None)

    result = await server._tool_manager.get_tool("loxone_analyze_observability").fn(  # type: ignore[union-attr]
        "control",
        "runtime_control_uuid",
        "upstream",
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
    )

    assert result.ok is False
    assert result.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_project_tools_publish_fixed_source_failure_diagnostics(monkeypatch):
    async def project_query(_runtime):
        raise ProjectError("project_xml_invalid")

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    server = FastMCP("project-source-errors")
    register_project_tools(server, None)

    result = await server._tool_manager.get_tool("loxone_get_project_status").fn()  # type: ignore[union-attr]

    assert result.ok is False
    assert result.data.error == "temporarily_unavailable"  # type: ignore[union-attr]
    assert result.data.diagnostic_code == "project_source_invalid"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_project_tools_bound_large_find_and_trace_responses(monkeypatch):
    class LargeQuery(Query):
        def find(self, **_kwargs):
            return [
                {
                    "project_node_id": f"p:{index}",
                    "kind": "block",
                    "block_type": "x" * 2_000,
                    "source_id": "source",
                    "connector_key": None,
                    "runtime_control": None,
                    "knx": None,
                }
                for index in range(100)
            ]

        def trace(self, _node, **_kwargs):
            nodes = self.find()
            return {
                "start": nodes[0],
                "direction": "upstream",
                "nodes": nodes,
                "edges": [
                    {"kind": "signal", "source": f"p:{index}", "target": f"p:{index + 1}"}
                    for index in range(99)
                ],
                "truncated": False,
                "truncation_reason": None,
                "unresolved_relationships": [],
                "unresolved_truncated": False,
            }

    async def project_query(_runtime):
        return LargeQuery(), SimpleNamespace(connected=True, structure_generation=1)

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    server = FastMCP("project-tool-size-limit")
    register_project_tools(server, None)

    found = await server._tool_manager.get_tool("loxone_find_project_objects").fn(limit=100)  # type: ignore[union-attr]
    traced = await server._tool_manager.get_tool("loxone_trace_project_logic").fn(  # type: ignore[union-attr]
        "p:0", "project_node_id", "upstream", max_nodes=100
    )

    assert len(found.model_dump_json().encode("utf-8")) <= PROJECT_RESPONSE_MAX_BYTES
    assert found.data.truncated is True  # type: ignore[union-attr]
    assert found.data.truncation_reason == "max_response_bytes"  # type: ignore[union-attr]
    assert found.data.next_cursor is not None  # type: ignore[union-attr]
    assert len(traced.model_dump_json().encode("utf-8")) <= PROJECT_RESPONSE_MAX_BYTES
    assert traced.data.truncated is True  # type: ignore[union-attr]
    assert traced.data.truncation_reason == "max_response_bytes"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_project_analysis_is_read_only_bounded_and_cursor_scoped(monkeypatch):
    class Runtime:
        def __init__(self):
            self.active_workers = 0
            self.projects = SimpleNamespace(authorize=AsyncMock())

        @asynccontextmanager
        async def worker_slot(self):
            self.active_workers += 1
            try:
                yield
            finally:
                self.active_workers -= 1

    async def project_query(_runtime):
        return Query(), SimpleNamespace(connected=True, structure_generation=1)

    runtime = Runtime()

    async def analysis(_view, _selected):
        assert runtime.active_workers == 1
        return {
            "analysis_version": 2,
            "project_fingerprint": "a" * 64,
            "model_version": 3,
            "scope": "knx",
            "analyses": ["project_connectivity"],
            "coverage": {
                "endpoints": 1,
                "canonical_group_addresses": 1,
                "raw_datatypes": 0,
                "reviewed_signal_usage": 0,
                "unresolved_relationships": 0,
            },
            "summaries": {"project_connectivity": {"unconnected": 1, "ambiguous": 0}},
            "limitations": [],
            "source_diagnostics": {
                "entries": [],
                "complete": True,
                "groups_omitted": 0,
                "labels_truncated": False,
            },
            "findings": [
                {
                    "finding_id": "knx:1",
                    "analysis": "project_connectivity",
                    "finding_type": "no_project_signal_relationship",
                    "classification": "fact",
                    "group_address": "1/2/3",
                    "affected_project_node_ids": ["p:1"],
                    "affected_omitted": 0,
                }
            ],
            "analysis_truncated": False,
            "truncation_reasons": [],
        }

    monkeypatch.setattr(tools_module, "_project_query", project_query)
    monkeypatch.setattr(tools_module, "process_analysis", analysis)
    monkeypatch.setattr(tools_module, "_access", lambda: SimpleNamespace())
    server = FastMCP("project-analysis")
    register_project_tools(server, runtime)

    result = await server._tool_manager.get_tool("loxone_analyze_project").fn()  # type: ignore[union-attr]

    assert result.ok is True
    assert runtime.active_workers == 0
    assert result.data.findings[0].finding_id == "knx:1"  # type: ignore[union-attr]
    assert result.data.next_cursor is None  # type: ignore[union-attr]
    runtime.projects.authorize.assert_awaited_once()
