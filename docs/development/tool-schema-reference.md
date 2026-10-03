# Tool schema reference

## WindowMonitor contact-state decoding

Exact `WindowMonitor.windowStates` values share one decoder in state reads,
state semantics, optional compact-read semantics and opening-contact analysis.
`semantic_value.kind=window_contact_states` supplies at most 100 indexed contacts
with raw tokens (up to 200 characters, explicit token truncation), bitmasks,
all documented state labels, retained metadata, and independent decoding/mapping
statuses. Provenance identifies the monitor/state and Structure File 17.1 pp.152–153.
Bits 1/2/4/8/16 mean closed/tilted/open/locked/unlocked; zero means
`unknown_or_offline`, not confirmed offline. All documented-bit combinations are
preserved without priority or alarm inference; unknown bits are invalid.
ASCII decimal tokens of 1–10 digits accept surrounding ASCII whitespace.

Inputs above 65,536 characters are rejected before splitting; nested semantic
enrichment is bounded to 16 KiB independently of raw-value response limits.
`values_total`, `positions_total`, `positions_returned`, `alignment`, `truncated`,
`metadata_complete`, `decoding_complete` and `mapping_complete` expose coverage.
Missing or duplicate positions and malformed metadata never shift the join.
Freshness and observation time remain in the existing outer state quality fields.
Opening analysis adds optional `decoded_state` per retained item and optional
decoding/mapping/truncation flags in monitor state; its existing nonnumeric raw-token
redaction remains intact. Ordinary state readers retain their original raw values.

History readers are unchanged. Native `has_history` and actual Event History source
inventory/coverage govern availability; current state readability is not retention
evidence. Historical values are not joined to today's metadata automatically.
WindowMonitor remains unsupported in Active Alerts.

## Structure overview counts

`loxone_get_structure_overview` counts the authorized visible discovery corpus,
including normalized subcontrols and excluding hidden controls. `counts.controls`
counts controls; `counts.control_types` counts distinct types with no synthetic
unassigned type bucket. `counts.rooms` and `counts.categories` count visible
definitions referenced by the normalized corpus, excluding the synthetic
`unassigned` bucket. `rooms.total` and `categories.total` include that bucket
if any controls have missing or unresolvable references within the visible
structure. Empty Config definitions and definitions referenced only by hidden
controls are excluded.

For each group, `total = definitions_count + (unassigned_bucket_present ? 1 : 0)`.
With two assigned rooms and no unassigned controls, `counts.rooms=2` and
`rooms.total=2`; with unassigned controls, `counts.rooms=2` and `rooms.total=3`.
The same examples apply to categories. Type `total` equals `counts.control_types`.

`returned` equals `len(items)`; totals remain unchanged under the 50-item or
64-KiB envelope limit, even if the unassigned bucket itself is omitted.
`complete` means `returned == total`; `truncated` means `returned < total`.
These describe delivery, not freshness or installation coverage. Complete
`control_count` sums equal `counts.controls`; truncated sums may be smaller.
Assigned UUIDs identify visible definitions; names are not unique identifiers.
The synthetic bucket has `assignment="unassigned"`, `uuid=null`, and `name=null`.

## Raw Modbus analog-sensor evidence

Project search/describe node schemas now include optional `modbus: ProjectModbusData`
only for exact `ModbusASensor` objects. `ProjectModbusFieldData` retains allowlisted
source-field evidence statuses and bounded raw occurrences; `ProjectModbusAncestorData`
retains part-local containment and configured fields without decoded semantics.
Search uses a one-ancestor bound, describe uses `min(limit, 16)`. Invalid strings are
value-free publicly, retained internally. Missing values remain absent. See the
synchronized capability guides and issue #352 for the narrow sensor-only boundary.
The generated HTML/JSON schema reference derives these definitions from the same
public Pydantic models; it is generated during packaging, not checked in separately.

## Modbus V1 project analysis (#358–#360)

`loxone_analyze_project(scope="modbus")` returns `ProjectModbusAnalysisData`
version 1 through the scope-discriminated success envelope. KNX remains the
default scope with version 8. Omitted Modbus selection executes `inventory`,
`configured_register_mappings`, `direct_consumers`, `configured_polling` and
`evidence_gaps`. Empty, duplicate and cross-scope selections are rejected before
project loading. The input schema's `x-analyses-by-scope` annotation also supplies
Explorer selection options; changing scope clears selection and cursor.
Comparison-exclusion findings retain their `blocked_check` and `reason_code`,
the implicated source field, its raw value/status and duplicate-pair evidence.
Unsupported explicit commands remain explicit evidence, not absent values or
invalid device configurations. Contradictory or reversed device/transport
containment cannot establish a comparison identity.

Counts describe `(model_source_id, project_node_id)` occurrences and carry
`exact` or `lower_bound`. Source ingestion, candidate scanning, supported-type
coverage and presentation are separate; physical installation coverage is
always unknown. A successful loader consumes all admitted sources or fails;
bounded diagnostic presentation does not make ingestion incomplete.
Per-check occurrence counts include unsupported and unresolved inventory items;
hierarchy nodes without observed ancestry are excluded from the raw-field gap
check rather than represented as evaluated. `hierarchy_fields_not_inspected`
explains this prerequisite gap with bounded affected occurrences. Coverage carries
the same exclusions.
Global evaluated sensor coverage counts the distinct union evaluated by selected
non-gap checks. Gap-only inspection reports exactly zero in this global count,
while its own CheckStatus retains the inspected evidence domain.
Source-type and per-check occurrence counts use distinct identities even when a
candidate also has an observed ancestry role; role-group totals are not additive.
Raw field status counts include evaluated sensor fields and each observed ancestor's fields
once. Search/describe retain their existing ancestry limits; internal analysis
uses at most 32 hops and reports gaps instead of inferred physical identity.

The shared worker/cache/page path preserves authorization and binds cursors to
scope, scoped version, caller identity, project marker/fingerprint/model version,
structure fingerprint and selection. Findings use a separate `modbus:` ID namespace.
Construction quotas and presentation omissions follow #354. Pagination fits the
whole envelope into 65,536 UTF-8 bytes, retains count/check/limitation truth and
advances only over emitted findings. Static fixture evidence does not establish
live sensor acceptance. Mapping comparison requires unique observed project
transport/device ancestry, exact raw command `3` or `4`, and an explicit raw
address. Addresses retain their lexical spelling. Repeated mappings and differing
explicit raw attributes are review candidates; missing evidence is a gap.
Polling summaries retain explicit raw values with unknown units, including when
mapping prerequisites are unavailable. Direct consumers count raw signal edges
and distinct resolved consumer occurrences separately; references remain separate.
Zero observed consumers never establish non-use. No register width, overlap,
device validity, scaling, byte order, bus load or current measurement is evaluated.

## Compact control reads

`loxone_read_controls` is an additive `loxone:read` tool for known visible UUIDs.
`targets` contains 1–25 unique `{control_uuid, state_names?}` objects; identifiers
and exact state names are 1–128 characters. Each optional name list has 1–100
unique entries. Omission selects all normalized state references of that control.
The batch contains at most 100 named references, counting aliases separately to
bound output rows. Empty-state controls return an empty `values` list. Target and
name order is preserved. A single freshly authorized snapshot validates the entire
batch before cache reads; unknown, hidden and inaccessible targets share `not_found`.
Duplicate selections and excess named references return `invalid_input`; malformed
typed arguments fail MCP input validation. No `include_hidden` is provided.

Each item contains the existing `ControlSummaryData` as `identity` and named
`values` with original value, UUID, freshness and observation time. Default
`semantics` is null. `include_semantics=true` adds the exact item model of
`loxone_get_state_semantics` using its shared snapshot reader and resolver,
including only current documented companion values. This optional projection
duplicates raw values in its evidence items; it is not the smallest payload.
Neither mode expands relationships, notes, history, statistics, actions or project
data. `omitted_sections` explicitly identifies these sections and absent semantics.

`requested_controls/returned_controls` and `requested_states/returned_states`
count selected controls and named references. Successful `complete=true` and
`truncated=false` mean the requested projection is fully delivered, not that all
values are current, known or semantically interpreted. Each semantic descriptor
retains its own metadata completeness. Envelope `stale` reflects disconnection or
any non-current selected state. Responses exceeding 65,536 UTF-8 bytes of the
serialized structured envelope return `response_too_large` without partial values;
split targets or select fewer states. This limit does not count MCP transport
framing or the textual copy of structured output.

`loxone_get_state_semantics` is an additive `loxone:read` tool for one visible
control. Optional `state_names` select 1–100 unique exact names; otherwise page
the normalized references with `offset` and `limit` (default/maximum 100).
Unknown selected names fail atomically. `next_offset` continues the same
selection; `returned`, `total`, `truncated`, `complete` describe page coverage.
Each item separates the original `value`, optional `semantic_value`, observation
`quality` (`availability`, `freshness`, `observed_at`) and `semantics`.
Interpretation status is `known|partial|unknown|invalid` with a fixed `reason`.
Nullable descriptor fields cover value type, display format, unit, range, precision
and sign convention. `encoding` and position-bound `positions` have separate
returned/total/truncated/complete fields, capped at 100 entries each. At most eight
per-field sources identify a Structure field, exact companion runtime state or
stable existing decoder rule;
document and firmware versions stay null when unavailable. Structure modification
timestamps are not firmware versions. Sources describe the retained claim list,
not overall family coverage. Valid display formats exceeding 64 characters are
omitted unchanged, with original/returned lengths and explicit truncation and
completeness; this omission is not invalid coding.
No hidden-control option, documentation-content
pipeline, project join or name-based inference is provided. Static metadata can
remain useful when the value is unavailable; stale companions are not used to label
values. Format strings are not parsed into units or precision in V1. StatusMonitor
metadata is not a new value decoder or alert classification.


`loxone_analyze_opening_contacts` publishes a bounded read-only join of retained
WindowMonitor references, exact runtime mappings and reviewed `AutoJalousie.Window`
paths. Its schema separates monitor/item diagnostics, direct/link/caller provenance,
connections, neutral findings, directed graph evidence, per-dimension completeness,
omissions and optional state alignment. Unknown internal flow and bounded evidence
never establish an absent connection; physical coverage is always `not_assessable`.
Each directed trace includes additive `gaps` (20 per trace, 200 per call) and
`gaps_omitted`. Fixed reasons distinguish `block_reference_projection_unavailable`
from `parent_boundary_incomplete`. Gap node references refer to reached trace nodes;
block/connector tokens are restricted to 64 ASCII identifier characters or null.
Rule references describe available rules, not a resolution of the gap. No new
internal-flow semantics or connector aliases are introduced.

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
`structure_refresh_auth_busy`, `structure_refresh_source_ip_suppressed`,
`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token`, `structure_refresh_timeout`, `structure_refresh_unknown`,
or `availability_unknown`. These codes describe established exception categories,
not the ultimate network/authentication cause. Token-store errors and missing
tokens share `structure_refresh_token`; it does not claim that every token error
means a missing token. Other existing source-processing codes remain compatible.

`structure_refresh_auth_busy` identifies exhausted local authentication coordination
before network login; `structure_refresh_source_ip_suppressed` identifies the
source-IP breaker or explicit source-IP blocking (including code 4003). These are
distinct from transport failures, remote session limits and local rate admission.
Runtime coordination and login share the configured connection timeout. Cancellation
releases coordinator locks and closes a session cancelled during authentication.

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


`loxone_get_active_alerts` provides a bounded read-only overview from one freshly
authorized visible structure and captured cached observations. It evaluates
`AalEmergency.status` (0 normal, 1 alarm, 2 reset, 3 disabled),
`AalSmartAlarm.alarmLevel` (0 inactive, 1 immediate, 2 delayed), and
`AlarmChain.activeAlarmType` (bits 2/4/8 active alarm types; bit 1 acknowledgement).
Integral numeric values are accepted; booleans, strings and unknown codes are
invalid. AlarmChain combinations 0–15 are accepted; acknowledgement alone is
inactive, while acknowledgement never cancels active alarm bits. Rules use
Structure File 17.1, pages 26–30; document provenance is no firmware promise.
Only current, available primary states establish activity or inactivity.

`semantic_value` exposes decoded source levels/types and context without tool-side
reinterpretation. Active findings include optional `context`: `test_alarm`, `acknowledged` and
`signals_suppressed` are true/false/null; null means unknown or not exposed by
the source. AalSmartAlarm lock/leave/disable states are optional context sources
and never override an active level. `context.source_states` preserves captured
companion values, UUIDs, freshness and observation times; stale/invalid context
is not interpreted. No test or suppression state is inferred from a command.
Active test alarms and acknowledged active source states remain counted.

`limit` is 1–50 (default 50), without cursor or family filter. Traversal stops at
1,000 visible tree entries, reads at most 100 unique state UUIDs, examines at most
100 references per supported control, attempts at most 100 decodes, and retains
50 coverage reasons. Primary/required states across all sources are captured before
optional context, so companions cannot starve later primary states. The closed
candidate set is AalEmergency, AalSmartAlarm, Alarm, AlarmChain, SmokeAlarm,
StatusMonitor and WindowMonitor. Other types are outside the claimed scope.
Unsupported candidates, missing/invalid/stale states and budget limits make
`coverage.complete=false`. Hidden controls and their counts are excluded.
`candidate_controls` is null when the scan is incomplete; evaluated/unsupported/
unavailable counts cover only retained candidates. `known_active` counts established
findings; `total_active` is null when evaluation coverage is partial.

`returned`, `truncated` and top-level `complete` describe delivery as well as
coverage. Findings are ordered by control UUID. Output is capped at 65,536 UTF-8
bytes of the serialized structured envelope; trailing findings are removed while
identity and coverage are preserved. If metadata alone exceeds the cap, return
`response_too_large`. Coverage-reason truncation is separate. No simultaneous
measurement, polling, history, acknowledgement or notification service is promised.
Empty partial results never mean no alarms; even complete results apply only to
known candidate families, never the physical installation.

StatusMonitor ordinary readers share configured tuple/count decoding (Structure File 17.1
pp.130–131). Description includes optional status UUIDs and bounded input/status
coverage; semantic values preserve malformed/unmatched/missing positions and
separate mapping completeness from syntax and observation freshness. No new tool
or intrinsic alarm classification is introduced.

## State project semantics

`loxone_describe_project_object` adds optional `state_semantics`: sanitized
Config/XML/block versions, rule ID, AQ contract status, bounded AQ input keys and
a fixed unsupported reason. This is static configuration evidence, not a live
value or physical-role claim. `loxone_trace_project_signal` adds optional
`semantic_gaps` referencing retained project nodes. Derived State edges use
`configured_state_selection` with rule `state_i2_eq1_aq_v1`. Opening connector
rule version 2 preserves the prior warning and gap limits. Unknown version/table,
row limits and unknown output contracts are fixed gap categories.
