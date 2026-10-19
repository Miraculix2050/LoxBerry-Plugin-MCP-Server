Load core rules first.

## Read history and statistics

For direct self-consumption, an accumulated native EFM `totalSelfConsumption`
StatisticV2 channel with exact Wh/kWh format can supply hourly difference sums.
Confirm plant association separately; the EFM computes this value, it is not an
independent physical meter. Do not infer the role from a control name, substitute
another EFM output, or add a storage balance. Missing weather still prevents
weather-peer acceptance even when this energy source is usable.

For `comparable_days`, optional `analysis_context.day_context` declares one
confirmed `site` whose timezone equals the tool timezone. Map existing `sources`
by `source_index`; choose one `weather` source per quantity, never by name or
averaging. Numerical weather retains registered solar observations; qualitative
radiation retains the actual structured source. Forecasts remain forecasts.
Declare `assets` and confirmed `production` coverage as a disjoint partition;
never combine an aggregate with included meters. Distinct statistic series on one
control may supply distinct energy roles; exact-source or same-role reuse is
invalid. A single PV source retains the confirmed PV-minus-export balance.
Multiple PV sources require
confirmed common supply and contribute only qualified complete hours present in
every source. Radiation alongside PV requires confirmed independence; it cannot
come from the evaluated PV control. Production, direct self-consumption and
export require confirmed associations, while units, quantities, native EFM
membership and balance boundaries still need technical evidence. A profile is
optional for exact statistic selectors. Report echoed site/coverage as owner
confirmations, not independently verified physical facts. Separate independent
sites into separate calls. Preserve #439/#509 positive acceptance requirements.

For compact historical calculations prefer `loxone_analyze_history` with exact
advertised series/state IDs or currently confirmed visible profile bindings.
Inspect the schema, select `temperature_summary`, `energy` or `state_duration`,
use explicit RFC3339 half-open start/end instants and an IANA timezone. Check
each source's status, unit, method, usable evidence and limitations. A sample
mean is not time-weighted. Counter decreases need reset/rollover evidence;
partial energy intervals are never divided proportionally. State duration is
not measured energy. Capture gaps and unknown initial values remain unknown.
Do not infer quantities from profile roles or names. Legacy clock conversion
remains unverified. Limit requests to 16 sources/31 local days/100,000 input
points; raw statistic limits can be stricter. Request `include_raw=true` only
when the task needs raw evidence; follow its 100-item pages, which reauthorize
visibility and invalidate cursors if the source content changes. Deadline/bound
errors are not complete results. Do not poll unchanged analysis results.

Use `consumer_ranking` only with confirmed consumer bindings, matching energy
representations/windows and distinct declared boundaries. Ask the user to confirm
their comparability and exclude parent/child overlap before asserting
`comparison_options.comparable_boundaries_confirmed=true`; the server cannot prove
chat confirmation or physical independence. Individual counters are never summed.
`pv_load_overlap` needs confirmed production and consumer/house bindings; add one
binary state source only to retain whole hours inside known active phases. Hourly
coincidence and its energy upper bound are not measured solar self-consumption,
exact attribution or causation. Zero generation leaves attribution undefined.
`operating_phases` associates one state history with one numeric source: whole
active energy hours or unweighted active temperature samples, preserving gaps.
`baseload` uses the local 00:00-05:00 window by default, overridable with whole
`night_start_hour`/`night_end_hour` options. It reports a time-weighted median of
hourly mean powers derived from verified Wh/hour intervals; raw power samples
cannot establish durations. The 24-hour extrapolation is a labelled estimate for
the selected channel, not proven whole-installation base load. Respect ambiguous
local-window errors and the separate native EFM balance gate.

Read `coverage_evidence`: UTC intervals are half-open internally, while existing
public history/statistic time filters remain inclusive. Sample timestamps prove
points only. Only documented hourly difference records expose exact energy
intervals; never interpolate missing intervals or divide uncertain interval
energy proportionally. `truncated` describes the returned evidence page.
Event `capture_intervals` contain a persisted observed initial value only for
new capture phases. It applies at that phase's start, not the requested window
start; replay intervening transitions before treating it as a boundary value.
Legacy phases and retention-truncated phases may lack an initial value. Capture
without transitions does not establish inactivity, and reconnect gaps stay gaps.
Local calendar analysis needs an explicit IANA timezone; DST days may have 23 or
25 hours. Legacy Miniserver local-clock values require independently confirmed
Miniserver timezone evidence; the compatible public timestamp shape alone is not
UTC proof. Native Control History remains a separate event source.

Inspect each series' `semantics` in the existing description/observability and
statistic response. `cumulative_counter` requires an explicit accumulated flag;
aggregated accumulated reads use `interval_difference_sum`. Raw values otherwise
remain samples, not time averages or energy intervals. Exact Meter channel units
are source-declared, not physical calibration proof. Preserve unknown direction,
measurement boundary/method, rollover and unexplained counter decreases.
Meter subtype `sign_convention` describes the normalized output, independently
of physical direction/boundary. It requires a compatible StatisticV2 accumulated
flag: instantaneous `actual` is not an accumulated reading. Never use a subtype
rule as evidence of historical input configuration or native EFM semantics. Legacy
local-clock conversion and aggregated timestamp positions may remain unverified.
Use profile `semantic_reference` only as a versioned resolver reference; review
affected bindings when evidence changes. No extra discovery per metric is needed.

Use `loxone_describe_control` first. Call `loxone_get_control_history` only when
`has_history` is true, and call `loxone_get_statistics` only with a `series_id`
advertised under `capabilities.statistics`.

For comparisons, operating phases and retrospective shifts, optional
`analysis_context` uses `history_analysis_context.v1`: each association references
one existing `sources` entry by zero-based `source_index`. Keep independent
supplies in separate requests; native EFM membership remains server-verified.
Profiles are optional. References retain confirmed roles, boundaries and cycle
constraints; direct sources require explicit associations and fresh visibility.
`observed` loads need complete measured cycles and exact operating associations.
Declared real cycles are confirmed models; hypothetical cycles have no native
identity. Keep all cycle timezones equal to the explicit analysis timezone.
The export association must itself be user-confirmed before it establishes a
measured budget. Any operating feedback supplied by a profile-backed declared
real model must match its saved companion; do not substitute an unrelated state.
Inspect `comparison.context_analysis` for associations, measured episodes and
conditional allocations against one shared measured export budget. A declared
allocation has no observed original cycle and proves no historical improvement,
measured saving, PV attribution or operating permission. Never backfill missing
phases, source semantics or energy measurements, or auto-save a declaration.
For history-target selection, use `view="history_targets"` to receive only the
control identity, state UUIDs, native control-history flag, and advertised
statistic series. The default `view="full"` remains available when control
model, presentation, actions, or relationships are needed. Check
`capabilities.native_statistics_truncated`; if true, the normalized StatisticV2
list stopped at 128 series and an absent series is not evidence it does not
exist. The compact view does not establish local event recording or time coverage.
For `source: legacy`, use `raw`
granularity only and no more than seven days; StatisticV2 also supports aggregated
granularities. Follow `next_cursor` with
the same query arguments. History and statistic cursors use signed continuation
anchors, so a changed live result does not duplicate prior entries. Do not invent
a series ID or interpret a cache hit as newer than its response metadata. A hidden
control is readable only with the same explicit `include_hidden=true` mode.
`loxone_get_control_history` accepts optional inclusive RFC-3339 `start` and `end`
filters; they narrow its returned bounded result but do not expand the Miniserver
history fetch.

`loxone_get_event_history` is separate plugin-owned event history. It reports
capture and coverage evidence, so `not_recorded` and `partial_coverage` are not
evidence that a state did not occur. Use exact `control_uuid` and `state_uuid`
from current discovery. Keep runtime subcontrol suffixes in `control_uuid` exactly
as discovered, including case; `state_uuid` remains a plain UUID. History uses
only that child/state pair and never falls back to parent or sibling records. `loxone_list_event_history_sources` lists active and
retained removed sources whose exact control and state are currently visible;
it requires `loxone:read` and `loxone:history`. The complete, cursor-paged
`loxberry_list_event_history_sources` additionally requires either enabled
`loxberry:read` with its exact local approval or enabled `loxberry:operate`
with its exact local approval. Neither LoxBerry scope implies the other.
Capture changes are separate approved writes described in operations. Removed
and re-added sources leave coverage gaps; keep `recording_status` separate from
requested-period coverage when interpreting retained observations.

For a time-bounded diagnostic question about one known project target, use
`loxone_analyze_observability` with the exact target identity, a structural
direction, and the requested RFC-3339 range. It returns only exact UUID-mapped
reachable controls, current-state availability, advertised statistic-series
metadata, and local event-history coverage. A project path is not a historical
cause; `temporal_coverage: not_checked` means statistics were not retrieved;
`native_statistics_truncated` marks omitted statistic metadata;
`state_names_truncated` marks omitted state-name text;
`control_metadata_truncated` marks omitted control-name and type text; and
`not_recorded` or `partial_coverage` never proves that a state did not occur.
The per-state `recommendations` explain how to close incomplete history gaps.
They use observable value and control metadata, not signal names. An
documented digital state with observed 0/1 value can support on-change recording
without an `is_analog` flag; conflicting metadata or values remain uncertain.
Documented `value` states of `InfoOnlyAnalog`, `UpDownAnalog`,
`LeftRightAnalog`, and `Slider` supply analog evidence without that flag; a
small range is not proof of a digital state. An explicit contradictory flag
keeps the recommendation uncertain.
For `Daytimer`, the analog flag applies only to `value`, and local event-history
sources are unsupported. A native series is
recommended for reuse only when its output maps to the state; disabled series
are ignored, and an unmapped legacy output remains uncertain. Verify the requested
period before claiming coverage. A partial local recording needs more capture
time; a configured native series takes precedence without creating a duplicate
source. `undetermined` means the available metadata does
not establish continuous or discrete behavior. Native sampling intervals are
qualitative advice based on the diagnostic need, not promised rates. Use
`loxone_get_statistics` only when an advertised series needs direct evidence
for the same period. Do not add history sources automatically.
