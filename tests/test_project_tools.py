from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.loxone.project.query import ProjectQueryError
from mcpserver.tools import register_project_tools


class Query:
    def status(self):
        return {
            "project_fingerprint": "a" * 64,
            "model_version": 1,
            "project_parts": 1,
            "nodes": 3,
            "edges": 2,
            "unresolved_relationships": 0,
            "mapping": {"exact": 1, "ambiguous": 0, "unmapped": 0},
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
