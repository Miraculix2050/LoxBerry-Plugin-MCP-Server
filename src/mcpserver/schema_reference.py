"""Generate the versioned static reference for the complete MCP tool surface."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Final, cast

from mcp.server.fastmcp import FastMCP

from mcpserver.loxone.runtime import LoxoneRuntime
from mcpserver.tools import (
    LoxBerryOperateRuntime,
    LoxBerryReadRuntime,
    register_tool_surface,
)

REFERENCE_HTML_PATH: Final = "webfrontend/htmlauth/tool-schema-reference.html"
REFERENCE_JSON_PATH: Final = "webfrontend/htmlauth/tool-schema-reference.json"


def tool_schema_catalog(version: str) -> dict[str, Any]:
    """Return every supported release tool using FastMCP's canonical schemas."""
    server = FastMCP("LoxBerry MCP Server schema reference")
    placeholder = object()
    register_tool_surface(
        server,
        runtime=cast(LoxoneRuntime, placeholder),
        loxberry_runtime=cast(LoxBerryReadRuntime, placeholder),
        loxberry_operate_runtime=cast(LoxBerryOperateRuntime, placeholder),
        control_enabled=True,
    )

    tools = []
    for tool in sorted(server._tool_manager.list_tools(), key=lambda item: item.name):
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "annotations": (
                    tool.annotations.model_dump(by_alias=True, exclude_none=True)
                    if tool.annotations is not None
                    else {}
                ),
                "inputSchema": tool.parameters,
                "outputSchema": tool.output_schema,
            }
        )
    return {
        "title": "LoxBerry MCP Server tool schema reference",
        "version": version,
        "scope": "Complete tool contract supported by this plugin release",
        "liveDiscovery": (
            "MCP clients receive the tools enabled for an installation via tools/list."
        ),
        "tools": tools,
    }


def schema_reference_json(version: str) -> bytes:
    """Render the canonical machine-readable catalog."""
    return (json.dumps(tool_schema_catalog(version), indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def schema_reference_html(version: str) -> bytes:
    """Render a standalone human-readable reference from the canonical catalog."""
    catalog = tool_schema_catalog(version)
    sections: list[str] = []
    for tool in catalog["tools"]:
        name = html.escape(tool["name"])
        description = html.escape(tool["description"])
        annotations = html.escape(json.dumps(tool["annotations"], indent=2, ensure_ascii=False))
        input_schema = html.escape(json.dumps(tool["inputSchema"], indent=2, ensure_ascii=False))
        output_schema = html.escape(json.dumps(tool["outputSchema"], indent=2, ensure_ascii=False))
        sections.append(
            f"""<article id="{name}" class="tool">
  <h2><code>{name}</code></h2>
  <p>{description}</p>
  <details><summary>Annotations</summary><pre>{annotations}</pre></details>
  <details><summary>Input schema</summary><pre>{input_schema}</pre></details>
  <details><summary>Output schema</summary><pre>{output_schema}</pre></details>
</article>"""
        )
    content = "\n".join(sections)
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(catalog["title"])} {html.escape(catalog["version"])}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ max-width: 78rem; margin: 0 auto; padding: 1rem; line-height: 1.5; }}
    nav {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: 1rem 0; }}
    .tool {{ margin: 1rem 0; padding: 1rem; border: 1px solid #8888; border-radius: .4rem; }}
    summary {{ cursor: pointer; font-weight: 600; padding: .5rem 0; }}
    pre {{ max-height: 32rem; overflow: auto; padding: .75rem; background: #7772;
      white-space: pre-wrap; overflow-wrap: anywhere; }}
    a {{ color: inherit; }}
    :focus-visible {{ outline: 3px solid #1261a0; outline-offset: 2px; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(catalog["title"])}</h1>
    <p>Plugin version <strong>{html.escape(catalog["version"])}</strong>.
      This static page documents the complete tool contract supported by this release.</p>
    <p>MCP clients obtain the tools enabled for a specific installation, including their
      input and output schemas, through <code>tools/list</code>. The Tool Explorer
      visualizes that live response.</p>
    <nav aria-label="Reference links">
      <a href="explorer.cgi">Open Tool Explorer</a>
      <a href="tool-schema-reference.json" download>Download JSON reference</a>
    </nav>
  </header>
  <main>{content}</main>
</body>
</html>
"""
    return document.encode("utf-8")


def write_schema_reference(output_root: Path, version: str) -> tuple[Path, Path]:
    """Write both generated reference formats below an output root."""
    html_path = output_root / REFERENCE_HTML_PATH
    json_path = output_root / REFERENCE_JSON_PATH
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_bytes(schema_reference_html(version))
    json_path.write_bytes(schema_reference_json(version))
    return html_path, json_path
