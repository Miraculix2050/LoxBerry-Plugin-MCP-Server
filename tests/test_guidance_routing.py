"""Routing metadata keeps the distinctions needed to select safe read workflows."""

from mcpserver.schema_reference import tool_schema_catalog


def test_descriptions_distinguish_sources_observability_and_causation():
    tools = {t["name"]: t for t in tool_schema_catalog("test")["tools"]}
    assert "not an energy balance" in tools["loxone_get_statistics"]["description"]
    assert "not fetched" in tools["loxone_analyze_observability"]["description"]
    assert "historical causation" in tools["loxone_trace_project_logic"]["description"]
    assert "loxone:history" in tools["loxone_analyze_history"]["description"]
    assert "fresh Loxone administrator" in tools["loxone_read_controls"]["description"]
    assert "independent loxberry:read approval" in tools["loxone_get_weather"]["description"]
    read = tools["loxone_read_controls"]["inputSchema"]["properties"]
    assert read["targets"]["maxItems"] == 25 and read["include_semantics"]["default"] is False
    assert read["native_result_view"]["default"] is None
    assert (
        tools["loxone_describe_control"]["inputSchema"]["properties"]["view"]["default"] == "full"
    )


def test_write_descriptions_keep_uncertainty_and_independent_approval():
    tools = {t["name"]: t for t in tool_schema_catalog("test")["tools"]}
    for name in ("loxberry_save_installation_profile", "loxberry_delete_installation_profile"):
        assert "explicit user confirmation" in tools[name]["description"]
        assert "independent exact local profile approval" in tools[name]["description"]
        assert "Never retry an uncertain write" in tools[name]["description"]
    assert "Never retries an uncertain command" in tools["loxone_operate_control"]["description"]
