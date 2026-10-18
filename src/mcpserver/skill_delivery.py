"""MCP delivery surfaces for the bundled agent skill."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Final, Literal, get_args

from mcp.server.fastmcp import FastMCP

SKILL_NAME: Final = "using-loxberry-mcp"
SKILL_REVISION: Final = 95
SKILL_MIME_TYPE: Final = "text/markdown"
SKILL_RESOURCE_URI: Final = f"skill://{SKILL_NAME}/SKILL.md"
SERVER_INSTRUCTIONS: Final = (
    "Inspect current schemas. Read using-loxberry-mcp core first via "
    "loxone_get_skill_guide(section='core') or skill://using-loxberry-mcp/core.md. "
    "Its task index selects states, history, project, knx, modbus, lighting, energy, "
    "operations, diagnostics or alerts; load only needed modules. Before any write "
    "load core, operations and the relevant read module. If module retrieval is "
    "unavailable use loxone_get_skill_guide() or "
    f"{SKILL_RESOURCE_URI}; if both fail stop the affected workflow. "
    "Never retry uncertain writes."
)
SkillSection = Literal[
    "full",
    "core",
    "states",
    "history",
    "project",
    "knx",
    "modbus",
    "lighting",
    "energy",
    "operations",
    "diagnostics",
    "alerts",
]
SKILL_MODULES: Final = tuple(section for section in get_args(SkillSection) if section != "full")


@lru_cache(maxsize=12)
def read_skill_markdown(section: SkillSection = "full") -> str:
    """Read fixed packaged files without runtime, project or caller data access."""
    root = files("mcpserver").joinpath("skills", SKILL_NAME)
    if section == "full":
        return root.joinpath("SKILL.md").read_text(encoding="utf-8")
    if section not in SKILL_MODULES:
        raise ValueError("skill_section_invalid")
    return root.joinpath("modules", f"{section}.md").read_text(encoding="utf-8")


def render_full_guide() -> str:
    """Build the compatibility artifact from the canonical module sources."""
    root = files("mcpserver").joinpath("skills", SKILL_NAME)
    header = root.joinpath("frontmatter.txt").read_text(encoding="utf-8").strip()
    return (
        header
        + "\n\n"
        + "\n\n".join(read_skill_markdown(section).strip() for section in SKILL_MODULES)
        + "\n"
    )


def register_skill_resource(server: FastMCP) -> None:
    """Register legacy and fixed, discoverable module resources."""
    server.resource(
        SKILL_RESOURCE_URI,
        name=SKILL_NAME,
        title="Using LoxBerry MCP",
        description="Complete compatibility guide; core and task modules are also available.",
        mime_type=SKILL_MIME_TYPE,
    )(lambda: read_skill_markdown())

    def register(section: SkillSection) -> None:
        def resource() -> str:
            return read_skill_markdown(section)

        server.resource(
            f"skill://{SKILL_NAME}/{section}.md",
            name=f"{SKILL_NAME}-{section}",
            description=f"{section} guidance; read core first. No project data.",
            mime_type=SKILL_MIME_TYPE,
        )(resource)

    for section in SKILL_MODULES:
        register(section)
