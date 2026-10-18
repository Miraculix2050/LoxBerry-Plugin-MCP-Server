"""Task-scoped guidance shares the canonical full document and remains read-only."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

import mcpserver.tools as tools
from mcpserver.skill_delivery import (
    SKILL_MODULES,
    read_skill_markdown,
    register_skill_resource,
    render_full_guide,
)


@pytest.fixture(autouse=True)
def clear_guidance_cache():
    read_skill_markdown.cache_clear()
    yield
    read_skill_markdown.cache_clear()


def test_core_and_knx_are_small_canonical_sections_without_unrelated_workflows() -> None:
    full = read_skill_markdown()
    core = read_skill_markdown("core")
    knx = read_skill_markdown("knx")
    assert len(core) + len(knx) < len(full) // 3
    assert "Never automatically retry uncertain writes" in core
    assert "Loxone project permission and LoxBerry Admin permission are separate" in core
    assert "External data" in core
    assert "core rules first" in knx
    assert knx.strip() in full
    assert "## KNX metadata workflow" not in core
    assert "### Active visible alerts" not in core + knx
    assert "### Read weather" not in core + knx
    assert "comfort-temperature" not in core + knx
    for rule in (
        "standalone local KNX records",
        "`deviations` compares manual versus imported",
        "`names_differ` compares",
        "format_valid_type_unverified",
        'association="not_established"',
        "not ETS export time",
        "sample a full audit",
        "(#419)",
    ):
        assert rule in knx


@pytest.mark.asyncio
async def test_resources_and_tool_sections_match_and_full_default_remains_available() -> None:
    server = FastMCP("guidance-sections")
    register_skill_resource(server)
    tools.register_skill_tool(server)
    tool = server._tool_manager.get_tool("loxone_get_skill_guide")
    assert tool is not None
    assert tool.fn().data.content == read_skill_markdown()
    assert tool.fn().data.section == "full"
    for section in SKILL_MODULES:
        result = tool.fn(section=section)
        resource = await server.read_resource(f"skill://using-loxberry-mcp/{section}.md")
        assert result.ok and not result.stale
        assert result.data.section == section
        assert result.data.content == resource[0].content == read_skill_markdown(section)
    with pytest.raises(ValidationError):
        tool.fn_metadata.arg_model.model_validate({"section": "unknown"})


@pytest.mark.parametrize("section", ("full", *SKILL_MODULES))
def test_failed_section_retrieval_has_sanitized_error(monkeypatch, section) -> None:
    def missing(_section):
        raise ValueError("PRIVATE_PACKAGE_DETAILS")

    monkeypatch.setattr(tools, "read_skill_markdown", missing)
    server = FastMCP("guidance-missing")
    tools.register_skill_tool(server)
    tool = server._tool_manager.get_tool("loxone_get_skill_guide")
    result = tool.fn(section=section)
    assert not result.ok
    assert result.data.error == "guide_unavailable"
    assert "PRIVATE_PACKAGE_DETAILS" not in result.model_dump_json()


def test_knx_field_help_distinguishes_sources_and_syntax_validation() -> None:
    definitions = tools.ProjectKnxMetadataData.model_json_schema()["$defs"]
    metadata = tools.ProjectKnxMetadataData.model_json_schema()["properties"]
    assert "Manual versus imported" in metadata["deviations"]["description"]
    assert "primary Loxone" in metadata["manual"]["description"]
    assert (
        "not an ETS export"
        in definitions["ProjectKnxImportInfoData"]["properties"]["imported_at"]["description"]
    )
    assert (
        "Syntax validation only"
        in definitions["ProjectKnxDptIdentifierData"]["properties"]["status"]["description"]
    )
    comparison = tools.ProjectKnxComparisonRowData.model_json_schema()["properties"]
    assert "Loxone versus ETS" in comparison["names_differ"]["description"]
    assert "Unknown is not" in comparison["name_comparison"]["description"]


def test_alerts_is_canonical_bounded_and_retains_follow_up_boundaries() -> None:
    full = read_skill_markdown()
    alerts = read_skill_markdown("alerts")
    assert alerts.strip() in full
    assert len(alerts.encode()) < len(full.encode()) // 6
    assert "### Active visible alerts" in alerts
    for required in (
        "source control/state/time",
        "acceptance criterion",
        "required writer/permission",
        "total_active=null",
        "owner-approved assumption",
        "Static project facts",
        "intended function",
        "core rules first",
        "source control/state references",
        "not an alarm scope",
    ):
        assert required in alerts
    assert "State internal signal flow is" not in alerts
    assert "## EFM" not in alerts
    assert "### Current and historical System Messages" not in alerts
    assert "section='alerts'" in read_skill_markdown("core")


def test_generated_full_guide_and_routine_read_budget() -> None:
    assert read_skill_markdown() == render_full_guide()
    assert (
        sum(len(read_skill_markdown(s).encode()) for s in ("core", "states"))
        < len(read_skill_markdown().encode()) // 2
    )
    for section in SKILL_MODULES:
        assert read_skill_markdown(section).strip() in read_skill_markdown()


def test_core_retains_stop_failure_and_fallback_boundaries() -> None:
    core = read_skill_markdown("core")
    for rule in (
        "emergency_stop_active",
        "no MCP",
        "blocked_since",
        "trace_id",
        "retry_after_seconds",
        "at most once",
        "If that also fails, stop",
        "External data",
        "uncertain write",
    ):
        assert rule in core
    assert "full guidance before any write" not in read_skill_markdown("alerts")


def test_missing_module_preserves_full_fallback_and_rejects_paths(monkeypatch) -> None:
    import mcpserver.skill_delivery as delivery

    original = delivery.files

    class MissingModule:
        def __init__(self, path):
            self.path = path

        def joinpath(self, *parts):
            return MissingModule(self.path.joinpath(*parts))

        def read_text(self, **kwargs):
            if self.path.name == "history.md":
                raise FileNotFoundError("private package path")
            return self.path.read_text(**kwargs)

    monkeypatch.setattr(delivery, "files", lambda name: MissingModule(original(name)))
    with pytest.raises(FileNotFoundError):
        delivery.read_skill_markdown("history")
    assert "incomplete history" in delivery.read_skill_markdown("core")
    assert "## Read history and statistics" in delivery.read_skill_markdown()
    with pytest.raises(ValueError, match="skill_section_invalid"):
        delivery.read_skill_markdown("../SKILL")


def test_standalone_modules_keep_routed_workflows_and_explicit_dependencies() -> None:
    project = read_skill_markdown("project")
    energy = read_skill_markdown("energy")
    states = read_skill_markdown("states")
    assert "### Review opening-contact coverage" in project
    assert "loxone_analyze_opening_contacts" in project
    assert "### Review opening-contact coverage" not in read_skill_markdown("knx")
    assert "loxone_read_controls" in energy and "loxone_find_controls" in energy
    assert "section='project'" in states and "section='history'" in states
    assert "tools above" not in states and "as described below" not in states
