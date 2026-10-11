"""Shared registration and reference for data-free, user-selected task starters."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Prompt


def register_prompt_surface(server: FastMCP) -> None:
    """Register recipes only; rendering never reads a project or grants access."""
    from mcpserver.knx.prompts import knx_prompts

    for prompt in knx_prompts():
        server.add_prompt(prompt)


def prompt_reference(prompt: Prompt) -> dict[str, Any]:
    """Match prompts/list without expanding a recipe or performing any I/O."""
    return {
        "name": prompt.name,
        "title": prompt.title,
        "description": prompt.description,
        "arguments": [item.model_dump(exclude_none=True) for item in prompt.arguments or []],
    }
