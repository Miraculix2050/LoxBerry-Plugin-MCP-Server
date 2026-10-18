# Tool schema reference

## Cross-source project identity (#218)

Project node summaries and descriptions add `source_project_node_ids` (at most
32 physical occurrence IDs) and optional `logical_identity`. Its classification
is `single_source`, `equivalent`, `complementary`, or `ambiguous`; `reason` is a
fixed diagnostic code. `candidate_project_node_ids` lists at most 32 candidates,
with `candidates_omitted` counting omitted references. These are source references,
never authorization evidence. Existing mapping statuses remain unchanged.

Project model version 15 resolves verified cross-source UUID groups for `SysVar`,
`DigitalIn`, `Actor`, `Online`, `Mode`, and `VoltageOut`. All occurrences require
the same type and attributes except `Title`/`Desc`; UUID/reference spelling is
normalized. Equal topology or disjoint explicit connectors may complement each
other. Conflicts, repeated source IDs, unknown topology or unresolved references
prevent the entire group from merging. Raw graphs and physical IDs remain
available. Description and trace aggregate occurrences within existing limits.
Exact `source_id` filters check stored spellings across every represented occurrence.
Text search also checks every represented physical node ID and source ID.
Existing KNX identity rules are retained. This establishes static graph evidence,
not physical behavior, causality or permission. No new tool or store is added.

## Native PV-production forecast reads (#439)

Existing state readers optionally decode exact `PvProductionForecast` fields.
Semantics add energy/predicted_pv_energy with kWh; source-native timestamps use the
2009 epoch. Missing companions and unavailable sentinels retain explicit status.
The full control description adds optional `capabilities.model.pv_forecast` with
documented and missing state names, forecast origin and time basis. No new tool,
control action or change to read authorization is introduced. Local solar sampling
is an independent default-off Admin setting in shared SQLite V9. See
[source and storage contract](solar-recording.md). Skill revision 97.

## KNX correction draft descriptions and retention (#524)

`loxberry_prepare_knx_corrections` adds optional `metadata` in prepare mode only:
`title` and `source_chat` are limited to 160 characters; `summary` to 1024.
Unknown keys, blank supplied values and invalid types are rejected without
echoing submitted text. Omission preserves existing clients and existing metadata
on updates. Chat title is supplied descriptive provenance, never an OAuth
identity, permission or trusted instruction. There is no new MCP tool.

Read summaries add metadata, last-edit timestamp, archive state and decision
counts. New drafts remain for 30 days; existing stored expiry is preserved.
Admin-only extension and archive management do not refresh source evidence or
permissions. Archived drafts cannot be applied or exported; reopening resets
decisions. Local writes and experimental ETS downloads retain their separate
confirmation, ownership, revision and fresh project-authorization checks.
Compact-summary migration is additive and preserves legacy drafts. Skill revision 95.

## Qualified local irradiance forecasts (#440)

`loxone_get_weather` adds `forecast_sources` and `solar_windows`, keeping original
modes and defaults. Local file probes require independent live `loxberry:read`
approval and enabled local reads. Without that approval, discovery reports
`local_read_not_authorized` without probing the file. The fixed Weather4Lox
VisualCrossing hourly source is independently off by default; a LoxBerry Admin
must review and confirm its installation association. No caller URL/path or
cloud API request is accepted. Discovery is not exhaustive project discovery.

`solar_windows` requires strict `future_options`: source ID, offset-aware future
start/end, IANA timezone, duration_hours 1–24, nonnegative minimum sample threshold,
and optional `include_samples`. No cursors/history_options are accepted; future
options are invalid on other modes. At most 31 touched local days, 768 source
points, 16 examples and 16 bounded diagnostics fit within 64 KiB. Rank hourly
point sequences by sample mean, then earliest sample; no interpolation or energy
integration. JSON numeric precision is checked before ranking. Source changes,
revocation, stale publication and unknown native constraints remain explicit.
See [source and method contract](local-solar-forecast-method.md) and
[user guidance](../user/local-solar-forecast.en.md). Skill revision 87.

## Structured weather archive (#439)

`loxone_get_weather` retains `actual` and `forecast` reads and adds `mode="history"`.
This branch requires `loxone:read`, `loxone:history`, global history activation and
an exact configured weather UUID/mode visible in the caller's fresh structure.
`history_options` selects that UUID, `stored_mode`, offset-aware past `start`/`end`
on the delivery reception axis (at most 31 days), and optional `include_raw`.
It is invalid on the original modes. Recording remains a separate, disabled-by-default
LoxBerry Admin option in the shared SQLite archive; configuring a source does not enable it.

Pages contain at most 96 source points and 128 explicit capture phases, with
truncation and an identity/source/content-generation-bound cursor. Raw fields are
omitted by default. Source point time, local reception and reported update remain
separate; `point_predates_capture` establishes no earlier capture coverage.
Forecast points remain forecasts and unknown units remain unknown. The whole response
is limited to 64 KiB; readers retain their history admission through worker completion
and recheck access and relevant configuration before publishing.

## Compact historical calculations (#438)

`operation="comparable_days"` offers an explicit `method="numerical"` with registered
`source_kind="solar_observation"` selectors, confirmed hourly production and optional
self-consumption/export bindings. Tolerances can only become stricter than 15%,
3 °C and 30 days. The output adds provenance, source coverage, metric pairs/groups,
negative deviations, separate previously captured native forecast context and
missing-source setup guidance. The generic Explorer form and JSON editor use the
same generated unions. See [numerical contract](../user/comparable-days.en.md).

The unchanged default is the compact qualitative class branch. Select one
deduplicated `source_kind="structured_weather"`, exact `state_uuid` and
`stored_mode="actual"`, or a confirmed actual-weather `binding_id` for
`solar_radiation`. Scalar selector contracts remain unchanged. Strict
`comparable_day_options` requires `reference_day`, uses
`method="radiation_classes"` and whole `start_hour`/`end_hour` (0/24 defaults),
with `maximum_seasonal_days` at most 30. Raw/cursor requests are rejected for this
branch. `data.weather_sources` carries the separate source/provenance summary;
`data.comparable_days` carries fixed positions, class origin, peers and exclusions.
The native 0-3 mapping is an explicitly owner-approved assumption of 2026-10-13,
not technically verified encoding. No irradiance energy, 15-percent tolerance,
temperature matching or normalized-yield claim is exposed. See the
[qualitative method](../user/comparable-days.en.md).

`loxone_analyze_history` requires `loxone:read` and `loxone:history`.
`operation` is `temperature_summary`, `energy`, `state_duration`,
`consumer_ranking`, `pv_load_overlap`, `operating_phases`, `baseload`,
`retrospective_shift` or the class
branch above. For the scalar operations, each of
1–16 `sources` selects exact control plus series/state IDs or a currently
confirmed `binding_id`. These selector forms cannot be mixed. Statistic selectors
have granularity; state history remains raw. UTC-normalized half-open RFC3339
`start`/`end` instants require explicit IANA `timezone` and a past, nonempty
interval touching at most 31 local days. Seven raw statistic days, 100,000 total
input points, 30 seconds, two concurrent analyses and 64 KiB output apply.

`data.sources` identifies source, status, unit, method/version, metrics, usable
intervals and limitations. Unsupported/unverified semantics produce
`insufficient_evidence`; partial observations are not complete periods.
`data.raw` is empty unless `include_raw=true`; then it has at most 100 items
and identity/request/content-bound `next_cursor`. Each page reauthorizes visibility.
Comparison operations additionally expose bounded `data.comparison` with status,
method/version, per-metric units, usable intervals and explicit limitations.
Optional strict `comparison_options` carries the caller's
`comparable_boundaries_confirmed` assertion (default false) and whole local
`night_start_hour`/`night_end_hour` (defaults 0/5, ranges 0–23/1–24). Options are
invalid on the original three operations and participate in cursor proofs.
Ranking and production/load roles use currently confirmed profile bindings;
declared compatibility does not become technical topology proof or permission.
See [architecture and contract decision](history-analysis.md).

`retrospective_shift` uses one confirmed grid_export statistic with explicit
export direction, matching declared consumer boundaries and explicit
comparable_boundaries_confirmed=true. Add up to seven confirmed consumer/binary
operating-state pairs with usable load constraints; energy granularity hour and
state granularity raw. Distinct physical sources and complete owner-confirmed
cycles/hourly energy profiles are required. comparison.retrospective_shift is
bounded to 16 conditional examples and 128 hourly allocations with one shared
export budget, profile revision, search/output limits and excluded-cycle count.
Every example has admissibility=not_proven, native_lock_status=not_checked and
blocking condition historical_native_lock_coverage_missing. No admissible
schedule, measured self-consumption, PV attribution or saving is claimed.
See [user workflow](../user/retrospective-shift.en.md).

## Shared history time and coverage evidence (#437)

`loxone_get_statistics.data.coverage_evidence` and local Event History's
`coverage_evidence` use `history_evidence.v1`: UTC and half-open internal
intervals, source evidence kind, bounded intervals/point count and endpoints, limitations
and explicit truncation. Existing inclusive filters and cursors remain unchanged.
Statistics metadata describes the returned page only; samples establish points,
not continuity. Documented hourly difference records establish their one-hour
intervals; other aggregate positions and legacy local-clock conversion can remain
unverified. No interpolation or guessed sampling rate is introduced.

Event History adds at most 128 `capture_intervals` with phase start/end and an
optional persisted initial value/observation timestamp. The value applies at
phase start, not query start; later transitions must be replayed. Every read/page
requires fresh caller visibility. Schema 6 migrates additively to 7 without
backfilling initial values. Reconnects start new phases. Retention or size eviction
invalidates obsolete initial evidence. More than 128 overlapping phases reports
truncation/partial coverage rather than complete coverage.

Pure source-time helpers require explicit IANA zones for local calendar boundaries
and reject ambiguous/nonexistent local timestamps. The legacy public timestamp
shape remains compatible and explicitly unverified. Supported LoxBerry runtimes
use installed system IANA data; pinned `tzdata` is a development fallback for
Windows tests. This is not a separate history cache or native Control History
decoder.

## Bounded native-series semantics (#435)

`capabilities.statistics[].semantics`, observability `native_statistics[].semantics`
and `loxone_get_statistics.data.semantics` use the existing pure resolver without
additional discovery. `value_meaning` distinguishes cumulative readings, raw
samples and the existing adapter's interval difference sums. Nonaccumulated
aggregates retain unknown aggregation; no average/min/max is inferred. V2 UTC
timestamps and the documented hourly difference start convention are separate
from unverified day/month/year positions and legacy local-clock conversion.
Exact Meter actual/total/totalNeg channels may carry source-declared W/kW/Wh/kWh
units (`unit_origin=structure_declared`); names or generic analog formats do not.
Exact IRCv2 temperature series retain actual/target roles and explicit temperature
formats; conflicting channel units remain unknown. Direction, measurement method,
physical boundary, rollover and reset correction remain unknown. A supported
reset-to-zero command is not evidence that a decrease was a valid reset.

Profile bindings add nullable `semantic_reference` to resolver rule versions.
Persisted old bindings remain readable. New evidence or changed references marks
affected bindings `needs_review`; unrelated names do not. A rule reference does
not establish a value, semantic completeness or user-declared technical truth.
State references identify the applicable shared or family-specific ruleset for
value-dependent companion branches. Decoder changes must bump that applicable
reference even when structure metadata is unchanged. New manager families retain
the references of unchanged legacy families. A technical rule reference never
authorizes disclosure or decoding.

## Native Energy Manager context (#436)

`loxone_describe_control(view="energy_context")` is an opt-in typed
`energy_context.v1` view for exact `EnergyManager` and `EnergyManager2` controls.
It requires freshly visible, non-hidden structure and strict current Loxone
administrator evidence. Unsupported families return `unsupported_source`.
Legacy views retain their existing fields and network behavior.

The result separates generation-specific metadata, advertised and missing state
capabilities, and cached state semantics with independent observation quality.
Generation 1 metadata is not joined to load events by names or numeric IDs.
Generation 2 editing locks are not load blocking states. Its documented global
states add `power`/`percentage` quantities and specific roles; load power units,
priority direction and physical cycle evidence remain unknown.

Load JSON accepts at most 100 flat entries within 16 KiB, rejects duplicate keys,
ambiguous identifiers, nested values and non-finite numbers, and does not expose
undocumented fields in the decoded value. Raw states retain their legacy form.
Manager context and semantic envelopes reject output exceeding 64 KiB using
`response_too_large`; no partial raw/decoded payload is returned. Source rules
identify generation and state independently of disclosure rights. Structure
contract evidence is not device acceptance or historical native lock evidence.

## Temperature and binary measurement semantics (#435)

The shared state-semantic descriptor adds nullable `measurement_quantity` and
`measurement_role`. Exact `IRoomControllerV2.tempActual`/`tempTarget` return
`semantic_value={kind:"temperature", role, value, unit}`; the unit remains null
without complete explicit Celsius/Fahrenheit evidence. Exact
`InfoOnlyDigital.active`/`Hourcounter.active` return
`{kind:"binary_state", active, role}` for numeric zero/one. Existing raw value,
quality, authorization and paging contracts remain unchanged. The semantics
tool and optional compact enrichment use the same pure resolver. The legacy
raw-state reader retains its existing decoding contract.
See the [source/version matrix](analysis-semantic-evidence.md). No historical
availability, physical-device role or energy inference is added.

## Locally approved installation-profile maintenance (#434)

`loxone_get_installation_profile(offset=0, limit=100, view="full")` adds
`view="summary"` for source selection. Both views use the same fresh snapshot,
visibility filtering, reference cleanup and post-read authorization recheck.
Summary retains profile status/revision, binding ID/role, exact state/statistic/
weather source identity, confirmation/review status, provenance and usability
limitations. It omits control display names, rationale and full PV/load parameters;
fetch the relevant full page before using those details or confirming mutations.
Pagination, page limits, warnings, errors and the 64 KiB envelope bound apply to
both views. Only summary adds `view="summary"`; the full default shape is retained.
No storage format or mutation contract changes.

Profile reads/writes add a discriminated weather binding alongside unchanged
state/statistic inputs: `source_kind="weather"`, `role="weather_context"`, exact
`weather_state_uuid`, `mode="actual"|"forecast"`, one fixed WeatherPointData field,
rationale and explicit confirmation. No control selector is accepted for weather.
Reads return a separate typed weather branch, null unit, source presentation format,
`history_status="unavailable"` and distinct current-source/forecast origin.
Production bindings add optional `pv_parameters`: bounded finite installed kWp,
paired coordinates and up to 16 unique arrays with optional capacity, north-zero
clockwise azimuth, tilt and qualitative shading. These are declarations, not source
semantics. `pv_parameters_usable` requires a valid currently confirmed binding.
Complete profile envelopes are capped at 64 KiB; smaller pages remain available.
Version-1 documents are strictly validated before read-only in-memory migration;
revision writes persist v2. Rollback to older code requires the prior profile backup.

`loxberry_save_installation_profile(binding, expected_revision, confirm=false)`
and `loxberry_delete_installation_profile(expected_revision, binding_id=null,
confirm=false)` require `loxone:read`, `loxone:history`, `loxberry:operate`, an
active general operation approval and a separate locally enabled approval for
the exact client, identity and Miniserver. Neither approval is implied by the
other. The profile capability defaults to disabled.

The caller must obtain explicit human confirmation in the conversation and send
`confirm=true`; the server cannot independently verify conversation content.
Both tools return only the new revision and affected binding ID. All affected
bindings need current visibility, including whole-profile deletion. Revision
conflicts require rereading; an uncertain write result must not be retried
automatically. Both tools are non-idempotent mutations; deletion additionally
advertises the destructive annotation. A single bounded worker, admission rate
limit and 30-second deadline protect the persistence path. The deadline is
checked under the profile lock before persistence starts; a write already
started can have an uncertain outcome after timeout or cancellation.

## Task-scoped KNX guidance (#455)

`loxone_get_skill_guide(section="core"|"states"|"history"|"project"|"knx"|"modbus"|"lighting"|"energy"|"operations"|"diagnostics"|"alerts"|"full")` adds optional task selection;
omitted selection remains the full guide. Static task-module resources expose the
same canonical content, derived from the bundled full document without project
access. Schema help distinguishes local/imported deviations from Loxone/ETS
name comparison and explicitly limits DPT validation to syntax. Existing tool
names and analysis defaults remain unchanged. See the [KNX workflow](../user/knx-mcp.en.md).

## Explicit ETS/Loxone project comparison (#417)

`loxone_analyze_project(scope="knx", analyses=["ets_project_comparison"])`
adds a bounded read-only comparison to analysis version 12; omitted selection
retains the existing default set. Each comparison finding has a numeric
`address_id`, relation (`common`, `import_only`, `observed_project_only`),
separate name-comparison/ambiguity/completeness flags, optional local metadata
and at most 20 project objects with an omitted count. Objects preserve primary
Loxone names, original address/style/variant, project fields and truncation.
The summary identifies target/revision, latest input declaration, full address
counts and bounded source coverage. Installation coverage and bus usage remain
unassessed; a naming deviation does not establish an error. Existing cursors,
authorization, response bounds and source diagnostics still apply.

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

## Raw Modbus analog-endpoint evidence

Project search/describe node schemas now include optional `modbus: ProjectModbusData`
only for exact `ModbusASensor` and `ModbusAActor` objects. `ProjectModbusFieldData` retains allowlisted
source-field evidence statuses and bounded raw occurrences; `ProjectModbusAncestorData`
retains part-local containment and configured fields without decoded semantics.
Search uses a one-ancestor bound, describe uses `min(limit, 16)`. Invalid strings are
value-free publicly, retained internally. Missing values remain absent. See the
synchronized capability guides and issues #352/#381 for the raw projection boundary.
Actor fields are bounded at eight; `configured_write` describes configuration only.
An observed `ActorCaption` ancestor preserves its containment identity with no fields.
Sensor fields and ancestry bounds remain unchanged. The V1 analyzer remains sensor-only.
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
Optional `native_result_view` adds one native EFM read. Its fixed view allowlist,
admin-first authorization, empty state rows, independent source quality and
budgets are documented in [Native energy results](native-energy-results.md).
`native_efm_result.v2` adds versioned partial semantics, provenance and report
applicability; actual Gpwr/Ppwr/Spwr allow metadata-bound `W`/`kW` units. Other
units, signs and physical boundaries remain unknown. Historical components keep
the existing independently evidenced history contract.
Omission/null keeps the contract below unchanged and does not fetch native data.
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
`structure_refresh_auth_busy`, `structure_refresh_auth_cooldown`,
`structure_refresh_source_ip_suppressed`,
`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token`, `structure_refresh_timeout`, `structure_refresh_unknown`,
or `availability_unknown`. These codes describe established exception categories,
not the ultimate network/authentication cause. Token-store errors and missing
tokens share `structure_refresh_token`; it does not claim that every token error
means a missing token. Other existing source-processing codes remain compatible.

`structure_refresh_auth_busy` identifies exhausted local authentication coordination
before network login; `structure_refresh_auth_cooldown` identifies the preventive
rejection pause or uncertain protection persistence before network access.
`structure_refresh_source_ip_suppressed` identifies the
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


The active-alert agent workflow checks freshness, coverage and truncation before
reporting current status, then uses exact source references for focused state
reads and runtime-to-project mapping. Describe/trace provide static input/output
evidence, not a proven cause. Report observations, facts, hypotheses and
optimization candidates separately. The project analyzer has KNX/Modbus scopes,
not an alarm scope; no arming inference, acknowledgement or test command follows.

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

`Alarm.level` additionally accepts integral numeric codes 0–6: 1 silent, 2 acoustic,
3 optical, 4 internal, 5 external, 6 remote. Code 0 means no running alarm under
an explicit owner-approved assumption (#346, 11 October 2026), not a Loxone guarantee.
Rule `Alarm.level.v1` exposes separate provenance for Structure File 17.0 p.28
(stages) and the issue decision (zero/activity and accepted format), with
`reason=owner_approved_decoder`. If the assumption proves incorrect, it is a bug.
Stages are not danger ratings. Acknowledgement resets the digital alarm outputs
while retaining arming; the API level transition and test-mode mapping are not
specified. Test, acknowledgement and suppression context remains unknown; armed,
nextLevelAt and startTime do not override activity. Missing, invalid or stale
levels never establish inactivity.

SmokeAlarm.level accepts 0 (inactive), 1 (pre-alarm) and 2 (main alarm). Levels 1/2 and numeric testAlarm 0/1 use Structure File 17.1 p.126; level=0 is an owner-approved assumption from issue #347 (2026-10-11), separately identified in decoder provenance with reason=owner_approved_decoder. If disproven, it is a bug. Optional testAlarm never overrides activity; missing, stale or invalid test context remains unknown. Acknowledgement and signal suppression remain unknown; acousticAlarm=0 does not prove inactivity. No command-transition or hardware compatibility claim follows.

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
value or physical-role claim. `loxone_trace_project_logic` adds optional
`semantic_gaps` referencing retained project nodes. Derived State edges use
`configured_state_selection` with rule `state_table_aq_v3`. Opening connector
rule version 5 preserves the prior warning and gap limits. Unknown version/table,
row limits and unknown output payload contracts are fixed gap categories.

State rule v3 recognizes fixed operands for I1–I8, four AND conditions per row,
first-match priority and codes 1–9 plus omitted equality for the evidenced
17020828/274/178 source triple. Dependencies are conservative possible AQ
influences; no runtime evaluation or conversion is exposed. Tables are bounded
at 100 rows and text operands at 256 characters. Empty numeric results, unknown
operator encodings and variable comparison expressions remain explicit gaps.
Project model version is 13; KNX analysis stays at version 12 and Modbus analysis at version 1.

`loxone_describe_project_object` adds optional `include_state_table=false`.
Its additive `state_table` projection is restricted to exact visible runtime
mappings and preserves row/condition positions, fixed operands, AQ values and
literal TQ templates. The existing `limit` bounds row delivery; at most 100 rows
and 512 characters/template are retained, with explicit omission/truncation and
64 KiB response fitting. `complete` describes delivered table data, not complete
TQ substitution or OutputAPI payload semantics. Default describe/trace omit table content.
Sparse condition positions are supported by state_table_aq_v3; project model
version 13, KNX analysis version 12 and opening connector version 5 distinguish cached interpretations.

### API connector connection metadata

Project find/describe additionally expose optional `knx.metadata`: `revision`,
the original metadata `address` and `address_format`,
separate `imported`/`manual` fields, `import_info`, `deviations` and sourced
`dpt_details`. Missing fields remain unknown; empty values remain explicit.
DPT status recognizes identifier syntax only and does not replace raw Loxone EIBType
or establish assignment/registry validity. The versioned
`normalized_dpt_evidence` mapping is independent of these declarations.
Describe preserves raw EIBType; evidenced unique main types use
`system=dpt_main_type` and a main-only `normalized_code`. The separate evidence
contains format/Config/mapping versions, EIS, candidate main types and implicit
versus explicit provenance. ETS/manual subtypes remain in `metadata.dpt_details`;
no subtype or compatibility is inferred from main-type agreement. Search includes names and
descriptions by numeric address while retaining Loxone titles as primary. KNX
revision changes invalidate continuation cursors. No new MCP write/export tool exists.

Project model version 14, KNX analysis version 13 and Opening connector rules 5 apply.
The canonical skill introduced this metadata in revision 54. Exact stored connector keys `OutputAPI` and `API` expose
optional `api_connector` with `semantics=connection_metadata_only`,
`value_available=false` and `rule_id=api_connector_metadata_v1`. No aliases are added.

Explicit Co/In or Ref relationships touching such a port have kind
`api_connection` in describe/trace. Optional `api_connection` edge metadata names
`source_block_project_node_id` and `target_block_project_node_id`,
`semantics=block_communication_dependency`, `payload_semantics=unknown`,
`value_available=false` and the same rule ID. Describe exposes at most `limit`
(maximum 100) block-level `api_connections`, with `api_connections_truncated`.
Trace follows explicit edges, preserving existing bounds, unresolved evidence
and authorization. Link orientation is a project fact, not a protocol contract.
Signal-use/KNX/Opening analysis excludes these metadata edges. Containing blocks
appended for context do not introduce unrelated State scalar gaps. The legacy
State `output_api_complete=false` field still denotes unknown payload semantics.

Sources: [Loxone Status](https://www.loxone.com/dede/kb/status-baustein/),
[Loxone Status Monitor](https://www.loxone.com/dede/kb/status-monitor/), exact
project Co/K port evidence and the user's API-connector contract clarification.
Connected-edge tests are synthetic; no live wired API example is claimed.

Known API-only unresolved links use `api_connection_unresolved`, including ambiguous source candidates when all candidates are exact API ports. This evidence remains in generic describe/trace and aggregate unresolved counts, while scalar KNX/Opening/Modbus predicates and Modbus relationship budgets exclude it. Mixed/unknown source candidates keep the original unresolved category.

## EFM participant references (#363)

Full Describe exposes `capabilities.model.efm` for exact source type `EFM`.
Paths preserve ordered occurrences and parents, separate from causal wiring and
subcontrols. Associations resolve only against fresh caller visibility;
unavailable targets disclose no identity. Reused controls remain separate.
Titles, icons and rest metadata are presentation, never measured values.
Roles retain bounded source tokens and remain semantically unknown without a
matching version rule; numeric XML aliases are not decoded. Limits are 100
occurrences, eight levels and 32 KiB retained metadata. Omitted subtree roots
are counted; their unvisited descendants remain unknown. Topology, references
and roles have separate completeness. Compact views remain unchanged.
State bindings belong to separate #364; no values or remote node reads occur.

Field-shape evidence: sanitized firmware 17.2.8.28 capture,
[#363 provenance](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/363#issuecomment-6108309261),
SHA-256 `242d191e4cbd2efc82397bc3cfb2026ec3e287278527e74ed451addb741af310`.
Config application version remains unknown. All fixtures are independently
authored synthetic data. Flat fields reproduce observed types; nesting,
missing/malformed data, rest, repetition and bounds remain unobserved synthetic
cases. Automated tests do not establish device compatibility.

Resolved control display names/types are capped at 200/64 characters with a
truncation marker. The complete serialized EFM projection also fits 32 KiB.
`projection_omitted` counts normalized occurrences omitted from the DFS suffix
by that final budget; retained parents and source paths remain stable.

## EFM state reference bindings (#364)

Full EFM Describe adds `capabilities.model.efm_bindings`, keyed by the participant
occurrence path from #363. The only decoder joins explicit `actualEfmState`
UUID-form strings by exact equality to values in the same authorized monitor's
state-name/UUID map. It requires a fresh firmware probe of **17.2.8.28** whose
Miniserver identity matches the freshly authorized structure. Unknown/other
versions and failed or mismatched probes remain unsupported; there is no version
range, positional/actualN guess, name decoder or XML alias. Compact views perform
no additional probe. No numeric values or remote node reads are requested.

Source field, observed JSON type, encoding, exact source names and validated
state UUIDs remain separate from node/control identity. Status distinguishes
absent, malformed, unsupported encoding/version, missing reference, conflict,
partial and state-map limit. All aliases and contradictory source facts are
preserved within bounds; nested absence does not remove a participant. Reference
completeness does not imply semantics, units, observations or energy balances.
Config version remains unknown. Duplicate JSON property names are not checked;
synthetic contradictory normalized pairs do not prove duplicate-wire detection.

The source map is bounded to 1,000 entries, candidates to 100 across the monitor,
and the serialized binding projection to 32 KiB. Omitted candidates retain counts
and incomplete status. Structure File 17.1 documents a name reference; the
observed UUID wire form differs. Only the specimen's UUID encoding is implemented.
All negative/alias/nested/reordered/conflicting/name-form tests are explicitly
synthetic. Neither automated tests nor this rule establish general compatibility.

Bindings cover only participant paths emitted by the bounded #363 projection.
`projection_omitted` separately counts retained occurrences excluded there.
`firmware_verification` distinguishes verified version metadata, identity mismatch,
invalid version data, unavailable probes and unrequested/unknown applicability.

Source identity uses the existing strict MAC serial canonicalization (case and
colon/hyphen presentation only). Invalid identities remain `invalid_identity`;
no arbitrary string or installation-name equivalence grants applicability.


## Confirmed load declarations and cycle output

Consumer profile bindings optionally accept load_flexibility with explicit IANA
zone, bounded weekly windows/next-day offsets, completion, duration, interruption,
minimum run/off times, exact operating_binding_id and observed-versus-declared
energy provenance. Native locks may never be overridden. The default identity is
active_episode_only; user_confirmed_cycle remains a user assertion, not a native
measurement or operation authorization. Whole-binding confirmation is renewed.

Read projections expose declaration usability and withhold hidden companion
identifiers. Companion fingerprints are internal; reused binding IDs do not
retarget the load without renewed confirmation. MCP mutation checks include old
and new companions. Profile storage v3 validates/read-converts v1/v2 without
rewriting them; unknown schemas fail closed.

operating_phases may additionally return comparison.load_cycles with profile
revision, observed episode bounds, complete-edges/energy flags, source-provenance
and identity declarations, discrepancies and explicit not_checked native locks /
not_evaluated planning. Sixteen episodes and 128 energy intervals are separately
bounded/truncated; complete-hour measured energies never include partial allocation.
The existing scalar selector and aggregate comparison behavior remain intact.

Original companion control/state anchors are retained privately with the trusted
fingerprint. Old-source visibility checks use those original anchors, never a
reused current binding ID. Private references are withheld from every projection.


Routing descriptions identify purpose, decisive prerequisites and limitations.
Field help owns parameter selection and bounds; the canonical workflow modules
own longer recipes. Native values, supplemental calculations, statistic-series
reads, observability metadata and historical causation remain distinct. The
routing revision changes no tool names, defaults, bounds or authorization.


## Bounded lighting source context (#442/#443)

`loxone_describe_control(view="lighting_context")` adds a fresh-visibility read of
one visible LightControllerV2's cached `moodList`; full remains the default.
Only validated source IDs and names are returned. Status distinguishes available,
unsupported type, missing reference/value, invalid data and `source_limit`.
Source state reference, cached origin, observation time and freshness remain
explicit. `total`/`omitted` describe the validated source list, not complete
configuration. At most 100 moods, 200 characters per name and 32 KiB of normalized
mood-row JSON are retained; serialized input is limited to 1,048,576 characters.
`returned`, `truncated`, `name_truncated_indices` and `names_complete` distinguish
collection and name omissions; absent/invalid source counts remain null.
Unknown names remain null. The complete view envelope is capped at 64 KiB;
oversized retained control metadata returns `response_too_large` without changing
the legacy full view.
Explicit hidden diagnosis remains read-only. No scene roles, presence mapping,
physical fixture inventory, operation targets or new operation permission are
inferred. The shared released mood-ID validation and operation behavior remain
unchanged; source parsing limits for this read do not change operation validation.

Core plus operations supply the complete mandatory write guidance, including
profile, message, event-source and KNX draft/apply safeguards; source-specific
read modules are loaded only when their evidence is needed. This changes no
runtime permission, approval, confirmation or uncertainty contract.
