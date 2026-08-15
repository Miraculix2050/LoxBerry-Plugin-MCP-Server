from __future__ import annotations

import json
import tomllib
from pathlib import Path

from mcpserver.schema_reference import (
    REFERENCE_HTML_PATH,
    REFERENCE_JSON_PATH,
    schema_reference_html,
    schema_reference_json,
    tool_schema_catalog,
    write_schema_reference,
)

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

EXPECTED_TOOLS = {
    "loxberry_clear_statistics_cache",
    "loxberry_get_plugin_status",
    "loxberry_get_service_health",
    "loxberry_get_system_status",
    "loxberry_list_service_events",
    "loxone_describe_control",
    "loxone_find_controls",
    "loxone_get_control_history",
    "loxone_get_control_notes",
    "loxone_get_room_snapshot",
    "loxone_get_skill_guide",
    "loxone_get_states",
    "loxone_get_statistics",
    "loxone_get_system_status",
    "loxone_get_weather",
    "loxone_list_categories",
    "loxone_list_global_metadata",
    "loxone_list_rooms",
    "loxone_operate_control",
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
