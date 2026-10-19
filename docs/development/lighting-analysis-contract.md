# Lighting analysis contract

Status: contract for review before the next implementation PR in the
[delivery plan](lighting-review-delivery-plan.md). The relationship PR does not
publish an analyzer yet. This extends `loxone_analyze_project`, never a new tool,
profile document, persistent store or independent project graph.

## Selection and existing behavior

Add `scope="lighting"`, `lighting_selection` and optional `lighting_context`.
KNX/Modbus defaults, existing analysis names, ETS options and wire behavior retain
their contracts. Reject lighting-only arguments outside the lighting scope and
ETS-only options in the lighting scope. No omitted selection means whole-house
analysis: lighting requires exactly one selection form:

- `controller_uuids`: 1–16 unique exact visible runtime controller IDs; or
- `room_uuid`: one exact visible room ID, never its name. Select visible
  LightControllerV2 controls deterministically, at most 16; report excluded count
  and partial selection if that room contains more controllers.

Keep multiple controllers per room and repeated names across rooms distinct.
Report unsupported selected control types without interpreting them as an empty
configuration. Runtime IDs retain exact suffixes; profile reference models keep
their existing UUID contract. Bound trace work per selected controller to 200 nodes,
16 levels, default depth 6. Findings use existing limit/cursor pagination, max 50 per
page, and the existing response-byte guard. Emit omissions and partial coverage.

## Request-local context

`lighting_context` has discriminator `version="lighting_analysis_context.v1"`,
forbids unknown fields, and is at most 64 KiB when serialized. Optional arrays:

- `scenes` (max 100): exactly one `controller_uuid` or existing `binding_id`,
  exact `mood_id`, optional plain `role` (max 64 characters), explicit `origin`
  (`user_confirmed` or `scenario_assumption`) and `rationale` (max 256 characters).
- `presence_sources` (max 16): exactly one `control_uuid` or existing `binding_id`,
  explicit origin and rationale. This declares the source's presence role, not
  an association with any controller. Only configured graph evidence can prove
  the inspected structural path; missing or unmapped paths remain unresolved.
- `rooms` (max 16): exact selected `room_uuid`, optional `usage` and `intent`
  (max 256 characters each), optional `tunable_white_installed` boolean and
  `zones` (max 16 plain labels of max 80 characters), explicit origin and rationale.
- `naming_rules` (max 16): exactly one selected `controller_uuid` or `room_uuid`,
  `kind="prefix"`, nonempty literal `value` (max 80 characters), explicit origin
  and rationale. No regex or natural-language instructions are executed.

Reject contradictory/duplicate resolved scene declarations and declarations for
unselected/inaccessible sources. Source identity and declaration origin remain
separate: a confirmed source binding cannot upgrade a hypothetical scene role,
fixture or room-use declaration into a confirmation. Text is data, never policy.

Use `read_profile_bindings` only when explicit references are supplied, with
`resolve_source_association` with expected role `lighting_intent` for scene
references and `room_sensor` for presence-source references. Profiles are
optional source reuse. The existing profile stores source confirmations and
rationale; it has no structured scene-role/room-use/fixture schema. Do not parse
rationale as such metadata or migrate it. Those meanings require the typed
request declarations above. Keep current installation, revision, source usability
and visibility checks. Native controller+mood membership is checked separately
against fresh visible `moodList`; neither another state nor a reference identifies
a scene role. A scene identity is always exact controller plus mood ID. A saved
room-sensor binding does not establish presence semantics: keep the explicit
presence-role declaration and its origin separate from source confirmation.

## Findings and provenance

Lighting checks are `inventory`, `naming_consistency`, `presence_relationships`,
`scene_roles` and `planning_context`; omitted analyses select these bounded checks.
Naming collisions, prefix differences and declared-role naming variation are
review candidates, never inferred faults or physical duplicates. Truncated or
unknown names do not establish complete naming comparisons. No role is inferred
from names, room, category, colors, Kelvin defaults or adjacent energy semantics.

Inventory uses the existing mood/output projections. Relationship evidence uses
the existing project mapping, find/describe/trace and opt-in internal-flow gaps;
unknown central flow never creates a path. Explicitly chosen source roles stay
declarations unless independently proven. Unmapped/ambiguous sensors, parent
anchors, source provenance and target-local coverage remain visible. No new
connector rules or energy-origin values are required.

Findings retain room/controller/scene references, supporting source/version,
observation freshness, graph references, stable code and bounded evidence.
Distinguish technical facts, confirmed declarations, assumptions and conditional
advice. Missing usage/intent/fixtures/zones/roles stays missing context. Report
controller capability separately from installed luminaire claims. An overall
review is conditional and limited to the selected visible evidence, never a
complete professional or physical lighting audit or operating permission.

## Authorization and publication

Acquire fresh caller-visible runtime/project sources on every page through the
existing access paths. Use `SourceSnapshot.capture/validate`, and re-read referenced
bindings before publication, including same-revision content/companion changes.
Lighting additionally guards selected mood projections and room metadata, because
those are not all covered by the shared control signature. On change, reject a
stale cursor/result rather than returning a mixed revision.

Bind the existing signed cursor/result cache to caller family, exact selection,
analyses, normalized context, project/runtime source versions, selected mood/room
digests and referenced profile revision/content. Reauthorize on every page;
cache hits do not establish authorization. No new store or persistent confirmation
is created. No Miniserver, profile, recorder or configuration writes, induced
events or bulk operations are part of analysis or acceptance.
