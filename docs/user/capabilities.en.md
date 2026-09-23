# Capabilities and limits

[Deutsch](capabilities.de.md)

## Supported scope

The server reads visible rooms, categories, controls and states. Optional bounded history, statistics, masked LoxBerry diagnostics and documented type-specific actions for visible Gen. 1 controls are available.

When enabled by an administrator, selected state UUIDs can additionally be recorded locally as bounded event history. This supplements native Loxone history for short-lived transitions and never grants access beyond the caller's current visible structure.

`loxone_get_project_status`, `loxone_find_project_objects`,
`loxone_describe_project_object`, `loxone_trace_project_logic`, and
`loxone_analyze_project` provide bounded,
read-only Project Intelligence for a project that the bound Loxone identity can load. They expose
graph evidence rather than raw XML: a signal or reference trace describes structural influence,
not an observed historical cause. Results are limited and explicitly report truncation; unknown
block types and unresolved relationships remain visible without invented semantics. A trace caps
its unresolved-relationship entries independently and reports that with `unresolved_truncated`.
Confirmed KNX/EIB project objects add bounded source-backed metadata for bus lines, endpoints and
KNX logic blocks. Endpoint direction is `bus_to_loxone` or `loxone_to_bus`; it is not a claim
about the physical device role. Group addresses retain their original text and only expose a
canonical form when it is valid. `EIBType` remains an unresolved source code, not an inferred DPT.
Equal group addresses do not create a graph relationship or prove causality. Find and trace return
only a compact KNX summary; use `loxone_describe_project_object` for the original value, segments,
names, and raw DPT code. Project find pages and traces are additionally limited to 64 KiB and
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
`loxone_analyze_project` version 3 summarizes bounded project-local KNX evidence: address and
source-name patterns, raw datatype reuse, reviewed signal-use differences, exact runtime-mapping
context, local peer and graph outliers, path counts, and endpoints without an observed project
relationship. Runtime names and control types are used only for exact UUID mappings; names never
establish a mapping. Findings are review facts, not quality ratings. Fixed
limitation codes show when normalized DPTs, semantic domains, reviewed usage, or runtime mappings
are unavailable. The tool does not claim DPT compatibility, ETS coverage, bus activity, or physical
device use; use a returned project-node ID with describe or trace to inspect its evidence.
`loxone_analyze_observability` separately assesses a bounded, explicitly requested
time range for a project target. It combines exact UUID-mapped structural reachability,
current-state availability, advertised native statistic series, and local event-history
coverage. Reachability is not proof of a historical cause; configured statistic series are
reported as not time-checked, and absent or partial local coverage never proves that a state
did not occur. At most 20 statistic series per control are returned; omitted metadata is marked
by `native_statistics_truncated`. State names are capped at 200 UTF-8 bytes and
`state_names_truncated` marks omitted text. Control names and types use the same cap;
`control_metadata_truncated` marks omitted text.
For each state without complete local coverage, `recommendations` suggests
native statistics, local on-change recording, or `undetermined` from observable
value and control metadata. Existing native series are preferred, but their
mapping to a particular state and coverage of the requested period must be
checked. Partial local recording is reported as a coverage gap, not a request
to add another source. Native sampling advice has no fixed interval without
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

For initial orientation, this replaces separate calls to `loxone_list_rooms`,
`loxone_list_categories`, and an unfiltered `loxone_find_controls` request just
to learn their aggregate distribution. For example, a client can make one
overview call to see that its authorized visible structure has 18 controls in
four rooms and three categories, then use `loxone_find_controls` only for the
chosen room, category, or type. It does not replace those targeted calls when a
client needs individual controls, descriptions, or current states.

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
