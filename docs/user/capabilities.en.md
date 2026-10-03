# Capabilities and limits

[Deutsch](capabilities.de.md)

## Supported scope

`loxone_get_state_semantics` reads semantic evidence and cached values for one
visible control with `loxone:read`, using a fresh visibility check. Select 1–100
unique exact `state_names`, or omit them and page all normalized states with
`offset` and `limit` (default/maximum 100). Follow `next_offset` with the same
selection. Unknown selections fail together; hidden controls are excluded.

Each item separates the original `value`, optional `semantic_value`, observation
`quality` and `semantics`. `known` means the interpretation is supported by the
identified existing decoder rule; `partial`, `unknown` and `invalid` preserve
gaps, absent companions and invalid source coding. A current value can have
unknown meaning, and a stale value can still have a known interpretation.
Missing document or firmware versions remain null. Per-field sources identify
Structure metadata, companion runtime states or decoder rules; Structure
modification times are not firmware. Formats longer than 64 characters are omitted
with original/returned lengths and explicit truncation instead of altered text.

V1 covers existing Irrigation/AlarmClock decoders, `value` display formats for
InfoOnlyAnalog/UpDownAnalog/Slider, UpDownAnalog ranges and position-bound
StatusMonitor `inputStates` configured tuple mapping and status-count semantics. Formats do not prove units,
precision or direction; configured labels do not prove severity or household roles.
Encoding and position lists retain at most 100 entries, sources at most eight,
with counts and completeness. Page completeness is independent of semantic and
metadata completeness. No project join, documentation-content download, hidden
diagnosis, alarm acknowledgement or installation-wide semantic coverage is provided.
Other energy, meter or controller meanings can remain unknown. This coverage is
fixture-tested; it does not establish new hardware or firmware compatibility.


For WindowMonitor controls, the full description retains the first 100 configured
positions in list or mapping source order, including malformed placeholders.
`capabilities.model.window_monitor_summary` reports `total`, `returned`, `omitted`,
and `truncated`; only retained explicit references can additionally expose internal
controls for reading. Explicit independent user links retain their existing authorization;
the monitor-only read restriction does not override them or other read-only restrictions.
Missing/null collections are empty. Unsupported collection shapes report
`invalid_window_monitor_collection`, with unknown (`null`) total and
omitted counts. Match `windowStates` by the original zero-based item index; omitted
positions are not evidence of missing contacts. These fields are absent from compact
views. Complete configured representation does not establish physical opening coverage.

Each retained item exposes a sorted, fixed-code `diagnostics` list without rejected
source values. Codes distinguish malformed entries (`invalid_window_monitor_entry`),
invalid fields (`invalid_name`, `invalid_install_place`, `invalid_control_reference`,
`invalid_room_reference`), missing references (`missing_control_reference`,
`missing_room_reference`), unavailable visible references (`control_reference_unavailable`,
`room_reference_unavailable`), and explicit room conflicts (`room_reference_mismatch`).
Absent optional names/install places are valid; invalid present values, including null,
are diagnosed. A rejected reference without a valid fallback can also be missing.
A valid mapping-key fallback remains usable even when the explicit UUID is invalid.

`resolution_status` is `resolved` when both the control and item room resolve,
`partially_resolved` when exactly one resolves, otherwise `unresolved`. The summary
counts these statuses over retained positions only; their sum equals `returned`.
`room_consistency` is separately `match`, `mismatch`, or `unknown`, comparing only
explicit UUIDs when both rooms and the control are visible. A mismatch does not
change resolution status. Hidden and unknown targets are both unavailable; names
never establish identity, contact roles, or physical correctness.

### Opening-contact assignment review

`loxone_analyze_opening_contacts` joins monitor references and exact consumer paths
in one bounded read-only call (`loxone:read`). Select `scope_type=monitor|room|contact|consumer`
and an exact visible `scope_uuid`. Additional candidates are at most 100 unique
visible `candidate_contact_uuids`; their physical contact role is not confirmed.
`include_current_state=false` is the default. Trace limits default to depth 6 and
100 nodes/edges, with maxima of 16 and 200. Each call inspects at most 100 monitors,
100 contact candidates, 100 consumers and 200 trace starts; responses stay within
65,536 bytes. At most 200 connections and 200 findings are materialized; additional
records are counted separately and prevent a complete result. Check separate monitor,
mapping, graph and state completeness, warnings and omission counts.
Each directed evidence trace adds up to 20 `gaps`, with at most 200 across the call.
A gap identifies the reached opaque project node, direction, safe technical block type
and connector key, fixed reason, connector-rule version and available rule references.
Invalid or overlong technical tokens are null; names and raw attributes are omitted.
`gaps_omitted` counts omitted cases per trace; `max_gap_evidence` preserves incomplete
graph evidence. `parent_boundary_incomplete` describes the existing conservative
parent check; it does not prove which adjacent port matters or a configuration defect.
The existing `unmodeled_internal_flow` warning remains unchanged.
Counts cover inspected retained positions, not the
entire installation. Duplicates use identical reference UUIDs. Without project
access, monitor findings remain available. Requested states expose original indices,
vector length and separate state freshness; `state_value` is an uninterpreted numeric
source token. State time is Unix time, independent of the analysis timestamp and
verified project marker.

The first consumer rule is exactly `AutoJalousie.Window`; `Dwc` is not assumed to be
an alias. `Or.I1/I2 -> Q` and projection of a resolved explicit `InputRef` reference
onto a unique `AQ` are marked derived rules. Bounded trace starts retain every
exactly identified occurrence of a logical KNX contact across internal model sources;
reaching that bound prevents a complete graph claim. Intermediate logic, lockout sources
and connector context remain visible in evidence. Unknown semantics, ambiguity
and reached limits prevent negative connection conclusions.
Connected inputs or outputs outside the reviewed connector rules also mark the
block's evidence incomplete; disconnected additional connectors do not.
A `cross_assignment_review_candidate` compares a proven feeding contact with another
non-feeding same-room candidate; it does not determine physical assignment.
`physical_opening_coverage` remains `not_assessable`. Monitor scope inspects retained
entries; room scope selects monitors by monitor/item room and candidates by exact
item/control rooms. Contact scope finds direct or explicitly linked monitor membership;
consumer scope uses its room for monitor context. Room and consumer scopes also
restrict consumers; monitor and contact scopes compare visible supported consumers.

The canonical skill separates monitor coverage, configured consumer wiring and
physical opening coverage. Find exact visible `WindowMonitor` controls, follow
discovery pages, and use `loxone_describe_control(view="full")`. Keep direct item
references separate from `relationships.linked_controls` (including links from
aggregate objects), exact Project Intelligence paths and name-only/shared-room
review candidates. A direct item reference is normalized and may originate from
an explicit UUID or a mapping-key fallback; resolution alone does not identify
the source. Describe each resolved referenced control separately with
`loxone_describe_control(control_uuid=..., view="full")` before inspecting its
`relationships.linked_controls`; the monitor embeds only compact item references.
An explicit link is indirectly linked evidence, not direct
monitor membership. Use diagnostics and original indices; malformed, unavailable,
room-mismatched and omitted entries limit conclusions. `partially_resolved` may
mean only the room resolved. Resolution counts cover retained positions only.
If current state matters, read `windowStates` and report index/vector discrepancies.

For correct-assignment questions, check `loxone_get_project_status`, resolve exact
contacts and consumers with `loxone_describe_project_object`, trace contacts
downstream with `loxone_trace_project_logic`, and trace the exact consumer
connector upstream, initially `AutoJalousie.Window`. Locate the connector through
returned child node IDs and their descriptions; compare exact graph node IDs and
edge endpoints. Preserve `InputRef`, `Or`, lockout controls and connector names.
Containment and shared reachability are not signal flow; do not invent internal
edges through unmodeled blocks. Check mapping ambiguity, `truncated_fields`,
trace truncation, unresolved relationships and freshness. Missing paths in
incomplete evidence do not prove missing wiring. This manual workflow supplements
the analyzer evidence and helps refine incomplete results.

Generic example: `roof-window contact -> InputRef -> Or with a lockout switch ->
blind named window.Window`, while another same-room window contact is monitored.
If complete relevant traces show that the latter does not feed that connector,
report a `cross_assignment_review_candidate` with the exact evidence. Wrong
contact wiring and misleading consumer naming are both possible; neither names
nor monitor membership justify a physical correction. If only separate segments
are available, report the gap. Use explicit wording such as "unresolved" and
"indirectly linked". Without an authoritative inventory and exact identity links,
physical completeness is `not_assessable`. Never infer one opening per blind or
contact roles from names, categories or room counts.

### Runtime and project capabilities

The server reads visible rooms, categories, controls and states. Optional bounded history, statistics, masked LoxBerry diagnostics and documented type-specific actions for visible Gen. 1 controls are available.

For known visible UUIDs, prefer `loxone_read_controls` for identity and current values in one call, as described below. For reference-only selection, explicit hidden diagnosis or servers without that tool, use `loxone_describe_control(view="state_refs")` after discovery. It returns only control identity, visibility and the complete normalized `states` list of names and UUIDs, without room/category context, capabilities, statistics, history, presentation or relationships. The view reloads the user-filtered structure and returns an error rather than cached references if the refresh fails. `stale` marks a disconnected event stream; `observed_at` timestamps the description, not a state value. Select only needed UUIDs, deduplicate them and call `loxone_get_states` in batches of at most 100; make no value-read call for an empty selection. Preserve explicit `include_hidden=true` for hidden-control diagnosis and its value reads. Use `history_targets` for history/statistic selection, `operation_targets` for operation preparation, and `full` for additional diagnosis.

After locating a control with `loxone_find_controls`, `loxone_describe_control` can use `view="history_targets"` to return only its identity, state names and UUIDs, advertised native control-history flag, and statistic series IDs and metadata. The default `view="full"` retains the detailed response. `native_statistics_truncated=true` in the compact view means more than 128 valid StatisticV2 series were found and some are omitted. A listed target does not establish that local event history is recorded or that native history or statistics cover a requested period; check the respective history response.

For a control operation, use `view="operation_targets"` immediately before calling `loxone_operate_control`. It returns only the control identity, visible allowed actions, and action-specific targets needed to form parameters: radio outputs, scene IDs, analog range, override modes, mood-list state reference, and color temperature bounds when applicable. Empty target fields mean that the control does not advertise those choices. Tool-schema bounds still apply to numeric operation parameters. This view omits state lists, statistics, history, relationships, and presentation metadata; `full` remains available for diagnosis. This view reloads the current user-filtered structure; if the refresh fails, no cached operation targets are returned.

When enabled by an administrator, selected state UUIDs can additionally be recorded locally as bounded event history. This supplements native Loxone history for short-lived transitions and never grants access beyond the caller's current visible structure.

`loxone_list_event_history_sources` lists active and retained removed sources only when the caller can currently see their exact control and state. It needs `loxone:read` and `loxone:history`; an unavailable current Loxone view returns an error. `loxberry_list_event_history_sources` gives the complete source inventory with the same paged response and additionally requires either enabled `loxberry:read` with exact local read approval or enabled `loxberry:operate` with exact local operate approval. The scopes and approvals are independent. Both lists report `recording_status` and a known `recording_ended_at`; follow `next_cursor` to retrieve every source. Listing never grants source changes: add, remove and purge retain their operate requirements.

Removing an event-history source stops recording but leaves retained events readable while the control and state remain currently visible to the caller. `loxone_get_event_history` reports `recording_status`, `recording_ended_at`, `recording_notice`, and the requested period's `coverage` separately. `active` means configured for recording, while only `coverage` establishes capture for the requested period. A gap after removal is never treated as continuous recording. Global age and database-size limits still apply. An approved client can permanently delete one inactive source's events and coverage with `loxberry_purge_event_history_source` and `confirm=true`. A purge with an unknown outcome, including a timeout or post-commit maintenance failure, must not be retried automatically.

If a removal reports that its metadata outcome is unknown, inspect the source list and history before a manual retry. A repeated removal can repair the retained-source marker; `recording_ended_at` stays empty when the original end time cannot be confirmed.

`loxone_get_project_status`, `loxone_find_project_objects`,
`loxone_describe_project_object`, `loxone_trace_project_logic`, and
`loxone_analyze_project` provide bounded,
read-only Project Intelligence for a project that the bound Loxone identity can load. They expose
graph evidence rather than raw XML: a signal or reference trace describes structural influence,
not an observed historical cause. Results are limited and explicitly report truncation; unknown
block types and unresolved relationships remain visible without invented semantics. A trace caps
its unresolved-relationship entries independently and reports that with `unresolved_truncated`.
Exact `ModbusASensor` objects add optional read-only `modbus` evidence to project search and
describe. Search remains by `block_type`, without a new technology filter.
The allowlist is `ModbusAddress`, `ModbusCmd`, `ModbusDataType`, `ModbusPollingCycle`,
`SourceValHigh`, `DestValHigh`; observed `ModbusDev` ancestors expose raw configured `Channel`,
`ModbusServer` exposes `Timeout`, and `Comm485` exposes `RxTimeout`, `Baudrate`, `Databits`,
`Parity`, `Pause`, `Protocol`. Comm485 is reported only as an observed source type in this
ancestry, never classified as Modbus by itself. `source_read` derives from the exact sensor
type; containment is hierarchy, not signal causality. Existing connector and relationship
evidence remains available in describe.

Each field carries `explicit`, `absent`, `ambiguous` or `invalid` evidence, source field,
raw occurrences and opaque model-source/project-node provenance. Conflicting values have no
single `raw_value`; identical duplicate occurrences remain visible. Numeric source strings are
limited to 64 characters and eight occurrences per field, with `occurrences_omitted`.
Malformed or oversized strings remain internal source evidence; public occurrences mark them
invalid and omit their content. All units/enums and datatype semantics remain `unresolved`.
Channel is not a proven unit ID. No defaults, scaling formula, bit/word order, actor support,
runtime freshness or successful transactions are inferred. Configured polling is static evidence.
Search shows one ancestor at most; describe shows at most `min(limit, 16)`, with
`ancestry_status` and `ancestry_truncated`. Unsupported Modbus types receive a describe diagnostic.
`loxone_analyze_project(scope="modbus")` and Explorer provide Modbus version 1:
`inventory`, `configured_register_mappings`, `direct_consumers`,
`configured_polling` and `evidence_gaps`. Omission selects all five; KNX remains
the default scope (version 9). Changing Explorer scope clears selection and cursor.
Mapping review compares exact raw commands `3`/`4` and explicit lexical addresses
within uniquely observed project transport/device ancestry in one source.
Repeated mappings or differing explicit raw attributes are review candidates,
not defects.
Comparison exclusions preserve the specific reason, affected raw field, value
and evidence status. An explicit unknown command remains explicit; it is treated
as neither an absent value nor an invalid device configuration.
Polling values have unknown units and establish no achieved rate or
bus load. Direct signal edges and distinct consumers are counted separately;
references remain separate and no observed direct consumer does not prove non-use.
Inspect check status, coverage, gaps, omissions and pagination. These checks
create no bus traffic and establish no current measurement or device health.
Shared sensor/actor registers can be intentional. Register width, overlap,
device addressing, scaling and byte order require independent register documentation.
Describe carries bounded parser diagnostics for observed ancestors and caps the structured
envelope at 65,536 UTF-8 bytes: it shortens ancestry with an explicit truncation flag or returns
`response_too_large` if the remaining description cannot fit.
`coverage_complete=false` explicitly avoids an installation inventory claim; register numbers,
names and cross-part source IDs do not merge occurrences. Existing identity, authorization,
marker, cursor and response-byte checks still apply. The Explorer displays these optional typed
fields, including source-field array labels. Sanitized public historic RTU and vendor TCP fixtures
prove source shape only; live sensor/device compatibility is unverified (issues #350/#352).

Confirmed KNX/EIB project objects add bounded source-backed metadata for bus lines, endpoints and
KNX logic blocks. Endpoint direction is `bus_to_loxone` or `loxone_to_bus`; it is not a claim
about the physical device role. Group addresses retain their original text and only expose a
canonical form when it is valid. `EIBType` remains an unresolved source code, not an inferred DPT.
`EIBextsensor` and `EIBtextsensor` are bus-to-Loxone endpoints;
`EIBextactor` and `EIBtextactor` are Loxone-to-bus endpoints. Validated `:0` and
`:1` address variants remain distinct; the address reports whether it came from
`EibAddr` or, for `EIBextsensor` when that field is absent, `EibAddrPulse`.
Variants are supported only for the two external endpoint types. The suffix does not prove
which physical edge occurred. An exact variant search returns that variant;
searching the canonical base may return both.
Equal group addresses do not create a graph relationship or prove causality. Find and trace return
a compact KNX summary with original and canonical addresses, source field, and variant; use
`loxone_describe_project_object` for address segments, names, any raw datatype code,
and bounded connector IDs, keys, and incoming/outgoing signal counts. A missing
`EIBType` on the newly modeled families leaves the datatype unknown.
The `knx_group_address` filter accepts valid two- or three-level addresses and `:0`/`:1`
variants. Invalid syntax or numeric ranges return `invalid_input`; a valid address without
matches returns a successful empty search page. Valid original forms are still compared exactly
with original or canonical addresses.
Project find pages and traces are additionally limited to 64 KiB and
report a size trim through `truncated` and `truncation_reason`.
`project_parts` counts internally ingested model sources rather than Loxone Config projects.
Status exposes opaque `model_sources`; identical KNX source occurrences from separate model
sources are presented once as a logical object with `source_occurrence_count` and
`model_source_ids`. Equal titles or group addresses never cause such a merge.
Where an exact reviewed block and connector rule is available, describe also returns one or more
separate KNX signal-use observations, while trace returns separately marked derived connector edges
and bounded `knx_to_loxone`, `loxone_to_knx`, or `knx_to_knx` paths. Unknown block or connector
behaviour is not guessed. These are static project paths, not evidence that a bus telegram or
historical state change caused an action.
`loxone_analyze_project` version 9 summarizes bounded project-local KNX evidence: address and
source-name patterns, raw datatype reuse, reviewed signal-use differences, exact runtime-mapping
context, local peer and graph outliers, path counts, and endpoints without direct configured
wiring. Graph outliers identify raw edge degree and show signal, reference, and separately derived
semantic edges with bounded connector evidence. A connectivity finding distinguishes direct signal
wiring from references and identifies the inspected connectors. "No direct configured consumer
found" (or, for an output, "no direct configured input source found") refers only to static project
wiring; it does not mean a group address is unused or a device is inactive.
Runtime names and control types are used only for exact UUID mappings; names never
establish a mapping. Findings are review facts, not quality ratings. Fixed
limitation codes show when normalized DPTs, semantic domains, reviewed usage, or runtime mappings
are unavailable. The tool does not claim DPT compatibility, ETS coverage, bus activity, or physical
device use; use a returned project-node ID with describe or trace to inspect its evidence.
Project status and analysis also expose `coverage_by_source_type`. Raw source-object
counts are separate from logical endpoint, logic-block and line counts; additional
occurrences merged across model sources are counted explicitly. Unknown KNX-like
objects and omitted type groups make coverage incomplete. Object details identify
`EIBType` as raw Loxone Config evidence and report that normalized DPT evidence is
currently unavailable.
Select `address_hierarchy` to page through measured one-, two- and three-level
address prefixes. Each prefix fact separates logical endpoints, raw model-source
occurrences, canonical addresses and edge variants, and includes bounded original
address examples. Direct wiring means an observed project signal/reference
relationship; unresolved relationships remain separate. Pattern and outlier
candidates report a local peer baseline, not a configuration verdict. The
optional Admin-managed KNX address labels apply only to the configured Miniserver,
require an explicit two- or three-level format, appear as `admin_configured`
metadata, and do not change project facts.
For three-level group addresses, `3:6/2=Label` labels a middle group;
`2:6/2=Label` labels a complete two-level address instead. The Admin page can
export the current text as a UTF-8 file and load such a file into the text field.
Loading does not save labels; use “Save KNX address labels” to apply them. The
file contains only label text, without a Miniserver address. Names and
address shape never establish floors, functions, DPTs, ETS meaning or bus activity.
`loxone_analyze_observability` separately assesses a bounded, explicitly requested
time range for a project target. It combines exact UUID-mapped structural reachability,
current-state availability, advertised native statistic series, and local event-history
coverage. Reachability is not proof of a historical cause; configured statistic series are
reported as not time-checked, and absent or partial local coverage never proves that a state
did not occur. At most 20 statistic series per control are returned; omitted metadata is marked
by `native_statistics_truncated`. State names are capped at 200 UTF-8 bytes and
`state_names_truncated` marks omitted text. Control names and types use the same cap;
`control_metadata_truncated` marks omitted text.
The bundled `using-loxberry-mcp` guide combines these existing tools into a
diagnostic workflow: identify the target, check current observations and their
timestamps, verify historical coverage for the requested period, and distinguish
structural paths from evidence of events and possible causes. A value observed
after reconnect does not reveal when it changed while disconnected.
For each state without complete local coverage, `recommendations` suggests
native statistics, local on-change recording, or `undetermined` from observable
value and control metadata.
Documented digital states of `InfoOnlyDigital`, `Switch`, `Pushbutton`,
`PresenceDetector`, and other supported control types can be recommended for
on-change recording with observed 0/1 values even without `is_analog`.
The documented `value` state of `InfoOnlyAnalog`, `UpDownAnalog`,
`LeftRightAnalog`, and `Slider` is treated as analog even without
`details.analog`; a small value range does not make it a digital state.
An explicit conflicting `details.analog=false` leaves the recommendation
undetermined.
For a `Daytimer`, `is_analog` applies only to the `value` state, not its mode or
time values. Local recording is not recommended for `Daytimer` because local
event-history sources do not support this control type. An active native series is preferred only when its output maps to
the state. A legacy series without a state UUID leaves the recommendation
undetermined. Coverage of the requested period still needs checking. Partial local recording
is reported as a coverage gap, not a request to add another source. Native
sampling advice has no fixed interval without
evidence about signal dynamics; the tool never changes recording settings.
`source_diagnostics` reports bounded source gaps such as parser anomalies, invalid KNX fields
and unmodeled attributes. They are not configuration verdicts and never expose unknown source
values: only fixed codes, field names, value shapes and project-node references are returned.
If the project source cannot be processed at all, the normal error result includes a fixed,
value-free `diagnostic_code` that distinguishes invalid, unsupported, limited, timed-out and
otherwise failed source processing.

`loxone_get_structure_overview` returns a bounded initial map of the rooms,
categories and control types visible to the signed-in Loxone user. It contains
no current states, history, hidden-object counts or Config-project data; use the
targeted discovery tools for details. Each breakdown contains at most 50 items,
and the complete result envelope is limited to 64 KiB with explicit completeness
metadata.

`counts.rooms` and `counts.categories` count visible definitions referenced by
the normalized discovery corpus, excluding the synthetic `unassigned` bucket.
Each group's `total` includes one such bucket if controls have missing or
unresolvable references within the visible structure:
`total = definitions_count + (unassigned_bucket_present ? 1 : 0)`.
With two assigned rooms and no unassigned controls, `counts.rooms=2` and
`rooms.total=2`; with unassigned controls, `counts.rooms=2` and `rooms.total=3`.
The same applies to categories. Types have no synthetic unassigned bucket.
`returned` counts delivered items; totals remain unchanged under truncation,
even if the unassigned bucket is omitted. `complete` describes delivery, not
freshness or installation coverage. Complete `control_count` sums equal
`counts.controls`, including normalized subcontrols; truncated sums may be
smaller. Empty Config definitions and definitions referenced only by hidden
controls are excluded.

For initial orientation, this replaces separate calls to `loxone_list_rooms`,
`loxone_list_categories`, and an unfiltered `loxone_find_controls` request just
to learn their aggregate distribution. For example, a client can make one
overview call to see that its authorized visible structure has 18 controls in
four rooms and three categories, then use `loxone_find_controls` only for the
chosen room, category, or type. It does not replace those targeted calls when a
client needs individual controls, descriptions, or current states.

### StatusMonitor

StatusMonitor now decodes comma-separated `inputStates` into position-stable
per-input tuples: raw token, configured ID/text/color/priority/status UUID, input
reference and explicit mapping status. `loxone_describe_control` exposes bounded
definition/input totals and completeness; `loxone_get_state_semantics`,
`loxone_get_states` and semantic projections of `loxone_read_controls` share the
decoder. State reads require fresh visibility; a failed refresh does not fall
back to cached authorization. Enrichment retains at most 100 positions and 16 KiB;
empty, malformed, unmatched or missing
positions never shift later inputs. Check `decoding_complete`, `mapping_complete`
and `truncated` separately from observation freshness. Stale values are historical
mappings, not confirmed current status. IDs are configured output indexes, not
original input values. `numState0`–`numState9`/`numDef` are counts mapped to IDs
0–10; a positive count is not a monitor-wide status or alarm. Integrated-monitor
aggregation is identified only through an already-visible referenced StatusMonitor;
no reference expansion or state read is performed. There is no single inferred
current tuple for a multi-input monitor.

Use these source facts for contextual AI review of text/spelling, configured color
and value grouping and consistency. Missing statuses can only be assessed when
project logic and intended purpose provide evidence; visualization metadata does
not establish complete wiring or intent. Labels, priorities and colors never
establish an intrinsic alarm meaning. Source: Structure File 17.1, pp.130–131.

## Compact reads of known controls

Use `loxone_read_controls` when visible control UUIDs are already known; otherwise
discover them with `loxone_find_controls` first. For example:

```json
{"targets":[{"control_uuid":"<visible-control-uuid>","state_names":["value"]}]}
```

The response joins `identity` (name, type, visibility, room and category) with
named `values` (UUID, original value, freshness and observation time) in one call.
Omit `state_names` to read all states of the selected control. Exact names are
required. Select 1–25 unique controls and at most 100 named states in total;
identifiers/names are limited to 128 characters. Aliases count separately.
Hidden/unknown controls or unknown state names reject the whole batch.

`include_semantics=true` optionally adds the same evidence and observation-quality
model as `loxone_get_state_semantics`. No relationships, notes, history, statistics,
actions or project data are expanded. Existing detail tools remain available.
`complete` and requested/returned counts describe delivery of the selected data,
including unavailable or stale values; they do not prove freshness or complete
semantic knowledge. Semantic metadata has its own completeness fields.
The structured response is limited to 64 KiB; `response_too_large` returns no
partial values. Split the targets or select fewer states.

Compared with full descriptions this reduces payloads substantially for controls
with many relationships. For one small control, `describe_control(view="state_refs")`
plus `get_states` may use fewer bytes, but still needs two calls.

## Limits

- Exactly one Miniserver target is supported.
- External or cloud-hosted MCP access is outside supported operation.
- Gen. 2/Compact remains experimental until independent compatibility evidence exists.
- Unconfirmed control actions are not promised as hardware verified.
- No arbitrary commands, Loxone Config management or general LoxBerry system administration.

## Hardware-confirmed control

Only these Gen. 1 actions were confirmed on explicitly authorized harmless test
fixtures: `Switch.on`, `Switch.off`, `Dimmer.set_level`, `Dimmer.off`,
`TimedSwitch.on`, `TimedSwitch.off`, `LightControllerV2.set_mood`,
`Jalousie.open`, `Jalousie.set_position`, `Jalousie.enable_auto` and
`ColorPickerV2.set_color_hsv`. That evidence does not transfer to other
controls, actions or installations.

The current mapping of platforms, clients and evidence status is in the [support matrix](../development/support-matrix.md).


### Active visible alerts

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

Check `coverage.complete` independently of `truncated`/`complete`. Empty partial
results do not establish absence of alarms. The tool does not classify StatusMonitor or
WindowMonitor states as alarms. Use source control/state references for targeted
reads; do not infer danger, cause or severity from names or colors. This snapshot
is not an emergency notification service and never acknowledges alarms.
`limit` allows 1–50 findings (default 50), without cursor/family filter. Coverage
applies only to known candidate families, never the physical installation;
`total_active` remains null for partial evaluation.

### Version-bound State signal flow

Project traces and opening-contact analysis derive `State.I2 -> State.AQ` only
from the verified equality/default table encoding for ConfigVersion 17020828,
XML 274 and State revision 178. The ordered table must be complete and use only
the confirmed `I2 == 1` predicate and numeric results, with an unconditional
default; at most 100 rows are evaluated. Equal reachable numeric results or an
early unconditional row can establish AQ independence. Exact external wiring
and derived edges remain separate. A wired independent input does not invalidate
an upstream AQ path. Unknown versions, operators, malformed tables and
unsupported TQ/OutputAPI contracts retain explicit gaps. The earlier live State
version is not included. Describe exposes bounded `state_semantics` provenance;
trace exposes `semantic_gaps`, without exporting private table rows or texts.
