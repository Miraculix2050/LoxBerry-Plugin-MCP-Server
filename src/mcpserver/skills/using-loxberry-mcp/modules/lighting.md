## Lighting and presence

Load core rules first. Resolve the exact visible control with the states module.
For a LightControllerV2, use `loxone_describe_control(view="lighting_context")`
to read source-proven mood IDs and names from its cached `moodList`. This is a
bounded read of the existing state, not an active device probe. Retain its exact
source-state reference, observation time and freshness in the answer.

An active mood or its name does not prove any output is switched on or off.
For current output claims read exact child states with semantic evidence and
apply the states module's activity rules; unsupported colors/positions remain
uninterpreted for activity. An unresolved child prevents an exhaustive all-off
claim, even when discovery and value delivery are complete.

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
assessment.

For a bounded combined review, call `loxone_analyze_project(scope="lighting")`
with `lighting_selection` containing exactly one `controller_uuids` list (1–16
exact visible IDs) or one exact `room_uuid`. A room selects at most 16 visible
LightControllerV2 controls, with exclusions. Optional `max_depth` (default 6,
maximum 16) and `max_nodes` (maximum/default 200) bound each controller's trace.
Checks are inventory, naming_consistency, presence_relationships, scene_roles and
planning_context; omit analyses for these defaults. KNX/Modbus behavior is separate.
Follow signed cursors with identical selection, checks and context, at most 50
findings/page; source/profile/room/mood changes require a new analysis.

Use optional typed `lighting_context` only for explicit request-local declarations,
with `schema_version="lighting_analysis_context.v1"`. Scenes select exact
controller+mood or existing lighting_intent binding+mood identities. Presence
sources select exact visible controls or room_sensor bindings, independently of
the selected room/controllers. Their presence role never proves an association.
Rooms independently declare usage, intent, installed tunable-white and each zone
with its own value/origin/rationale. Naming rules are literal prefixes, not regex
or instructions. All declarations retain user_confirmed or scenario_assumption;
a confirmed source cannot upgrade a hypothetical role or physical claim.
Duplicate resolved identities and overlapping room/controller prefixes are errors.
Use the existing bounded binding-ID grammar; malformed references are invalid
inputs. A selected scene without a role remains missing context. Naming checks
exclude noncurrent mood names and report freshness gaps even without inventory.
Retry unavailable profile reads rather than inventing substitute declarations.
Direct-only reviews require no profile/installation serial; explicit references
retain strict installation and content-change guards. Keep selected target child
mapping provenance and `unresolved_truncated` beside retained unresolved counts.
No profile migration, saved context, control, configuration or recorder writes.

Inventory findings retain 20 moods/outputs per controller and explicit omissions;
use the existing describe view for further detail. Respect naming comparison
completeness, current mood membership and all trace/response limits. Findings
retain room/controller/scene references and distinguish technical observations,
review candidates, missing context and conditional advice. Never label naming
candidates as faults or use controller Kelvin defaults as installed fixture proof.

The Explorer can transfer a complete visible LightControllerV2 find-result row
into an exact-controller lighting draft, without running it. Its lighting form
shows only matching arguments; changing scope removes incompatible fields,
checks and cursors. JSON scope changes retain explicit compatible checks after
structural validation; malformed types remain errors. Page summaries distinguish observations, review candidates,
context gaps and conditional guidance. Read naming completeness independently
from selected-controller coverage and retain the generic evidence/JSON details.
Use the six lighting scenarios in the DE/EN support matrix as bounded workflows;
unknown source/role/fixture evidence remains partial, never a fabricated pass.
