"""MCP delivery surfaces for the bundled agent skill."""

from __future__ import annotations

from importlib.resources import files
from typing import Final

from mcp.server.fastmcp import FastMCP

SKILL_NAME: Final = "using-loxberry-mcp"
SKILL_REVISION: Final = 18
SKILL_MIME_TYPE: Final = "text/markdown"
SKILL_RESOURCE_URI: Final = f"skill://{SKILL_NAME}/SKILL.md"
SERVER_INSTRUCTIONS: Final = (
    "For Loxone queries, history, LoxBerry diagnostics, ambiguous control names, "
    "stale or unconfirmed states, "
    "and before any control operation, retrieve the using-loxberry-mcp guide from "
    f"{SKILL_RESOURCE_URI} or call loxone_get_skill_guide. Never retry uncertain writes."
)


def read_skill_markdown() -> str:
    """Read the canonical skill bundled in the installed Python package."""
    resource = files("mcpserver").joinpath("skills", SKILL_NAME, "SKILL.md")
    return resource.read_text(encoding="utf-8")


def register_skill_resource(server: FastMCP) -> None:
    """Publish the bundled skill as a static MCP resource."""

    @server.resource(
        SKILL_RESOURCE_URI,
        name=SKILL_NAME,
        title="Using LoxBerry MCP",
        description=(
            "Agent workflow for safe Loxone discovery, operations, and LoxBerry diagnostics."
        ),
        mime_type=SKILL_MIME_TYPE,
    )
    def skill_resource() -> str:
        return read_skill_markdown()
