# Tool schema reference

FastMCP derives each tool's input and output JSON Schemas from the registered Python function and Pydantic result model. MCP clients obtain the tool surface enabled for a concrete installation through `tools/list`; that response is authoritative for calls to that installation. The integrated Tool Explorer reads and visualizes the same response.

The plugin package also contains a static reference for the complete tool contract supported by its release:

- `tool-schema-reference.html` is the human-readable reference linked from **Help** and the Tool Explorer.
- `tool-schema-reference.json` is the equivalent machine-readable catalog.

`python tools/generate_schema_reference.py --output-root <directory>` generates both files from the FastMCP registry. The package builder invokes the same generator functions directly and passes the validated release version explicitly. Build-time verification with the project dependencies rejects stale output; the dependency-free publication job subsequently protects the downloaded package through its exact manifest and checksum. Do not maintain separate hand-written request or response schemas.

The static catalog is version-specific and configuration-independent. Optional tools can therefore appear there even when an installation does not publish them. Use `tools/list` whenever the exact installed surface matters.
