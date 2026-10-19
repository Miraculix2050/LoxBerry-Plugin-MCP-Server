## Lighting and presence

Load core rules first. Resolve the exact visible control with the states module.
For a LightControllerV2, use `loxone_describe_control(view="lighting_context")`
to read source-proven mood IDs and names from its cached `moodList`. This is a
bounded read of the existing state, not an active device probe. Retain its exact
source-state reference, observation time and freshness in the answer.

Set `include_outputs=true` on that view only when exact runtime output references
are needed. `outputs` projects bounded, visible direct Switch/Dimmer/ColorPicker
children from normalized `subControls`, with parent identity and structure version.
The default leaves `outputs=null`. Runtime child keys remain exact, including any
suffix; never derive a connector from that suffix. State references have no values.
Respect output omissions, unsupported types, name and state limits. A valid empty
projection does not prove no configured lighting. Connector identity is unresolved
and physical configuration completeness is not assessable. A color picker and
default Kelvin bounds do not prove installed tunable-white fixtures.

Distinguish `unsupported`, `missing_reference`, `missing_value`, `invalid` and
`source_limit` from a valid empty list. `total` counts validated source entries;
it does not establish complete configured inventory. Respect `truncated`,
`omitted`, `name_truncated_indices` and `names_complete`. Unknown names remain
unknown. The complete view envelope is capped at 64 KiB; respect
`response_too_large` if retained control metadata prevents that bound. Do not silently replace omitted entries with guessed scene names.
Use existing full descriptions and bounded state reads only if their details
are required, and count those reads in workflow measurements.

For a presence/light relationship, first establish the exact visible source and
controller IDs with the user or independent source evidence. Names, room and
category do not assign a presence role. Load project guidance and inspect
`loxone_get_project_status` for mapping/source coverage. Find and describe the
exact project objects, then use `loxone_trace_project_logic` in the relevant
direction with `include_internal_flow_gaps=true`. Keep raw signal/reference paths
separate from reviewed internal `semantic_edges`. `internal_flow_not_modeled`
means no reviewed internal flow applies to that reached occurrence, not that
the configuration is broken or has no internal flow. A rule catalog entry alone
does not prove coverage; emitted reference rules and State contracts also count.
An absent gap does not establish complete block behavior. An ambiguous connector
parent stays `internal_flow_parent_ambiguous`. Neither diagnostic adds a path.
Do not jump across an unknown central block to invent a presence association.
Retain exact child `runtime_target_mapping` separately from its parent topology,
unmapped/ambiguous source evidence and every trace/response limit. A bounded
missing path does not prove the physical relationship is absent.

Read the project module for configured structural paths and operations before
writes. A mood ID/name never grants operation permission. Existing operations
still require their exact current allowlist and human-requested target/action.
Visible moods, names, rooms and controller capabilities do not prove physical
luminaires, presence associations, scene intent or a professional lighting
assessment. An integrated lighting analyzer is a separate subsequent delivery.
