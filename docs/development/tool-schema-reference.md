# Tool schema reference

`loxone_analyze_opening_contacts` publishes a bounded read-only join of retained
WindowMonitor references, exact runtime mappings and reviewed `AutoJalousie.Window`
paths. Its schema separates monitor/item diagnostics, direct/link/caller provenance,
connections, neutral findings, directed graph evidence, per-dimension completeness,
omissions and optional state alignment. Unknown internal flow and bounded evidence
never establish an absent connection; physical coverage is always `not_assessable`.

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


## Availability errors

Runtime availability failures retain `error="temporarily_unavailable"` and existing
fixed safe messages. The notes read preserves its released `rate_limited` category
when wrapping local budget rejection, including the same diagnostic and retry fields. Additive `availability_phase` and `retry_after_seconds` are
nullable. `diagnostic_code` is one of `local_rate_limit`,
`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token`, `structure_refresh_timeout`, `structure_refresh_unknown`,
or `availability_unknown`. These codes describe established exception categories,
not the ultimate network/authentication cause. Token-store errors and missing
tokens share `structure_refresh_token`; it does not claim that every token error
means a missing token. Other existing source-processing codes remain compatible.

Refresh phases are `token_lookup`, `session_establishment`, `structure_version`,
`structure_load`, or `session_close`. Local budget rejection uses `local_budget`;
other unclassified runtime failures use `unknown`. If cleanup itself fails, the
reported failure belongs to `session_close`. Unknown exception categories stay
`structure_refresh_unknown`; cancellation continues to propagate.

Only `local_rate_limit` can include an integer `retry_after_seconds` in 1..60,
and only when admission is calculable for a positive local budget:
ceil(60 + oldest timestamp whose expiration admits the next call - monotonic now),
bounded to 1..60. The timestamps belong exclusively to this OAuth family's local
rolling budget. No capacity, occupancy, identity, or other family's state is
exposed. This observation does not reserve capacity; later calls can consume it.
All other availability failures have a null retry delay and no automatic retry promise.
Limits, authorization, per-request fresh visibility and write uncertainty stay intact.

The envelope's `trace_id` correlates the tool failure with sanitized service events.
Events add allowlisted `diagnostic_code` and `availability_phase`; arbitrary values
are omitted. Warning suppression is scoped to category and phase for 60 seconds.
Repeated responses keep their own fields and trace IDs even when no new warning
is emitted; deduplicated event counts are not request counts.

Historical evidence for #328 identifies one structure-refresh failure, but does
not recover its underlying exception or the second original response. The earlier
trace/time queries found no matching cause evidence. These additions cannot
retrospectively attribute those failures. A healthy service/state stream and
`stale=false` on a failed envelope do not prove a successful fresh structure read.
