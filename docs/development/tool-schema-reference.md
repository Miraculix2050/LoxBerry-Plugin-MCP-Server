# Tool schema reference

The full `loxone_describe_control` schema includes additive
`capabilities.model.window_monitor_summary` collection counts and fixed diagnostics.
Its `returned` count includes malformed retained positions; `total` and `omitted`
are null for invalid collection shapes. Compact views omit this metadata.
Each retained item adds fixed `diagnostics`, `resolution_status`, and
`room_consistency`. Summary `resolved`, `partially_resolved`, and `unresolved`
counts sum to `returned`, excluding omitted positions. Resolution checks the
control and item room independently; room mismatch is a separate UUID-based
consistency result. Unavailable references never distinguish hidden from unknown.

FastMCP derives each tool's input and output JSON Schemas from the registered Python function and Pydantic result model. MCP clients obtain the tool surface enabled for a concrete installation through `tools/list`; that response is authoritative for calls to that installation. The integrated Tool Explorer reads and visualizes the same response.

For `loxone_describe_control`, the generated schema lists `view="full"` as the default. `history_targets` is the compact history/statistics transfer view; `operation_targets` returns allowed actions and only their selectable targets or ranges, without statistics, state lists, relationships, or presentation. `state_refs` returns only identity, visibility and complete normalized state-name/UUID references from a freshly loaded user-filtered structure; it omits room/category context, capabilities, presentation and relationships. Existing full/default fields remain compatible; additive metadata is documented above.

The two event-history source-list tools share a cursor-paged response (`sources`, `next_cursor`). Each source includes `recording_status` and a known `recording_ended_at`. `loxone_list_event_history_sources` returns only currently visible control/state pairs; `loxberry_list_event_history_sources` returns the complete inventory after an independently approved local read or operate grant. Their authorization requirements are described in the tool descriptions and permissions guide.

The plugin package also contains a static reference for the complete tool contract supported by its release:

- `tool-schema-reference.html` is the human-readable reference linked from **Help** and the Tool Explorer.
- `tool-schema-reference.json` is the equivalent machine-readable catalog.

`python tools/generate_schema_reference.py --output-root <directory>` generates both files from the FastMCP registry. The package builder invokes the same generator functions directly and passes the validated release version explicitly. Build-time verification with the project dependencies rejects stale output; the dependency-free publication job subsequently protects the downloaded package through its exact manifest and checksum. Do not maintain separate hand-written request or response schemas.

The static catalog is version-specific and configuration-independent. Optional tools can therefore appear there even when an installation does not publish them. Use `tools/list` whenever the exact installed surface matters.
