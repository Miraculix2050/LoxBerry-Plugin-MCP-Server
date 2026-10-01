from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from mcpserver.schema_reference import (
    REFERENCE_HTML_PATH,
    REFERENCE_JSON_PATH,
    schema_reference_html,
    schema_reference_json,
    tool_schema_catalog,
    write_schema_reference,
)
from mcpserver.tools import register_observability_tools

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,valid", [(1, True), (50, True), (0, False), (51, False)])
async def test_observability_published_limit_matches_validation(limit: int, valid: bool) -> None:
    server = FastMCP("observability-contract")
    register_observability_tools(server, None, None)
    published = next(
        tool for tool in await server.list_tools() if tool.name == "loxone_analyze_observability"
    )
    reference = next(
        tool
        for tool in json.loads(schema_reference_json(VERSION))["tools"]
        if tool["name"] == published.name
    )
    assert reference["inputSchema"] == published.inputSchema
    bounds = published.inputSchema["properties"]["limit"]
    assert bounds["minimum"] == 1
    assert bounds["maximum"] == 50
    assert bounds["default"] == 20
    assert bounds["type"] == "integer"

    tool = server._tool_manager.get_tool(published.name)
    assert tool is not None
    arguments = {
        "target_identifier": "control",
        "target_type": "runtime_control_uuid",
        "direction": "upstream",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-02T00:00:00Z",
        "limit": limit,
    }
    if valid:
        assert tool.fn_metadata.arg_model.model_validate(arguments).limit == limit
    else:
        with pytest.raises(ValidationError) as error:
            tool.fn_metadata.arg_model.model_validate(arguments)
        assert error.value.errors()[0]["loc"] == ("limit",)
        assert error.value.errors()[0]["type"] == (
            "greater_than_equal" if limit == 0 else "less_than_equal"
        )


EXPECTED_TOOLS = {
    "loxone_analyze_opening_contacts",
    "loxone_list_event_history_sources",
    "loxberry_clear_statistics_cache",
    "loxberry_add_event_history_source",
    "loxberry_list_event_history_sources",
    "loxberry_purge_event_history_source",
    "loxberry_remove_event_history_source",
    "loxberry_get_plugin_status",
    "loxberry_get_service_health",
    "loxberry_get_system_status",
    "loxberry_list_service_events",
    "loxone_analyze_project",
    "loxone_analyze_observability",
    "loxone_describe_control",
    "loxone_describe_project_object",
    "loxone_find_controls",
    "loxone_find_project_objects",
    "loxone_get_control_history",
    "loxone_get_event_history",
    "loxone_get_control_notes",
    "loxone_get_project_status",
    "loxone_get_room_snapshot",
    "loxone_get_skill_guide",
    "loxone_get_state_semantics",
    "loxone_read_controls",
    "loxone_get_states",
    "loxone_get_statistics",
    "loxone_get_structure_overview",
    "loxone_get_system_status",
    "loxone_get_weather",
    "loxone_list_categories",
    "loxone_list_global_metadata",
    "loxone_list_rooms",
    "loxone_operate_control",
    "loxone_trace_project_logic",
}


def test_schema_catalog_contains_complete_fastmcp_contract() -> None:
    catalog = tool_schema_catalog(VERSION)
    tools = catalog["tools"]

    assert catalog["version"] == VERSION
    assert [tool["name"] for tool in tools] == sorted(EXPECTED_TOOLS)
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool["description"]
        assert tool["annotations"]["readOnlyHint"] in {True, False}
        assert tool["inputSchema"]["type"] == "object"
        assert tool["outputSchema"]["type"] == "object"
        assert tool["outputSchema"]["properties"]["data"]["anyOf"]


def test_window_monitor_summary_is_in_generated_description_contract() -> None:
    tools = {tool["name"]: tool for tool in tool_schema_catalog(VERSION)["tools"]}
    definitions = tools["loxone_describe_control"]["outputSchema"]["$defs"]
    assert "window_monitor_summary" in definitions["ControlModelData"]["properties"]
    summary = definitions["WindowMonitorSummaryData"]["properties"]
    assert set(summary) == {
        "total",
        "returned",
        "omitted",
        "truncated",
        "diagnostics",
        "resolved",
        "partially_resolved",
        "unresolved",
    }
    assert "malformed" in summary["returned"]["description"]
    assert "invalid_window_monitor_collection" in str(summary["diagnostics"])
    item = definitions["WindowMonitorItemData"]["properties"]
    assert item["resolution_status"]["enum"] == ["resolved", "partially_resolved", "unresolved"]
    assert item["room_consistency"]["enum"] == ["match", "mismatch", "unknown"]
    assert set(item["diagnostics"]["items"]["enum"]) == {
        "invalid_window_monitor_entry",
        "invalid_name",
        "invalid_install_place",
        "invalid_control_reference",
        "invalid_room_reference",
        "missing_control_reference",
        "control_reference_unavailable",
        "missing_room_reference",
        "room_reference_unavailable",
        "room_reference_mismatch",
    }


def test_describe_schema_publishes_minimal_state_refs_contract() -> None:
    describe = next(
        tool
        for tool in tool_schema_catalog(VERSION)["tools"]
        if tool["name"] == "loxone_describe_control"
    )
    view = describe["inputSchema"]["properties"]["view"]
    assert view["default"] == "full"
    assert view["enum"] == ["full", "history_targets", "operation_targets", "state_refs"]
    definitions = describe["outputSchema"]["$defs"]
    state_refs = definitions["ControlStateRefsData"]
    fields = {"uuid", "name", "type", "visibility", "view", "states"}
    assert set(state_refs["properties"]) == fields
    assert set(state_refs["required"]) == fields
    assert state_refs["properties"]["view"]["const"] == "state_refs"
    assert state_refs["properties"]["states"]["items"]["$ref"] == "#/$defs/StateReferenceData"
    assert {"$ref": "#/$defs/ControlStateRefsData"} in describe["outputSchema"]["properties"][
        "data"
    ]["anyOf"]


def test_project_status_schema_distinguishes_model_sources_from_config_projects() -> None:
    tools = {tool["name"]: tool for tool in tool_schema_catalog(VERSION)["tools"]}
    status = tools["loxone_get_project_status"]
    definitions = status["outputSchema"]["$defs"]
    properties = definitions["ProjectStatusData"]["properties"]
    source_properties = definitions["ProjectModelSourceData"]["properties"]

    assert "model sources, not Loxone Config projects" in status["description"]
    assert "model sources, not Loxone Config projects" in properties["project_parts"]["description"]
    assert "project_parts" in properties["model_sources"]["description"]
    assert "not a Loxone Config project ID" in source_properties["model_source_id"]["description"]
    assert "parsed elements" in source_properties["element_count"]["description"]

    for tool_name in ("loxone_find_project_objects", "loxone_describe_project_object"):
        node_definitions = tools[tool_name]["outputSchema"]["$defs"]
        node_name = (
            "ProjectNodeSummaryData"
            if tool_name == "loxone_find_project_objects"
            else "ProjectDescriptionData"
        )
        node_properties = node_definitions[node_name]["properties"]
        assert "source occurrences" in node_properties["source_occurrence_count"]["description"]
        assert "not Loxone Config project IDs" in node_properties["model_source_ids"]["description"]


def test_schema_reference_formats_are_deterministic_and_equivalent() -> None:
    first_json = schema_reference_json(VERSION)
    first_html = schema_reference_html(VERSION)

    assert schema_reference_json(VERSION) == first_json
    assert schema_reference_html(VERSION) == first_html
    catalog = json.loads(first_json)
    rendered = first_html.decode("utf-8")
    assert f"Plugin version <strong>{VERSION}</strong>" in rendered
    assert "through <code>tools/list</code>" in rendered
    assert 'href="tool-schema-reference.json"' in rendered
    for tool in catalog["tools"]:
        assert f'<article id="{tool["name"]}"' in rendered


def test_schema_reference_writer_uses_installed_paths(tmp_path: Path) -> None:
    html_path, json_path = write_schema_reference(tmp_path, VERSION)

    assert html_path == tmp_path / REFERENCE_HTML_PATH
    assert json_path == tmp_path / REFERENCE_JSON_PATH
    assert html_path.read_bytes() == schema_reference_html(VERSION)
    assert json_path.read_bytes() == schema_reference_json(VERSION)
