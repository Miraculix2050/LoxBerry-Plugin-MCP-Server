Load core rules first.

### Confirmed installation profile

Weather bindings are a separate `source_kind="weather"` with exact
`weather_state_uuid`, `mode="actual"|"forecast"`, allowlisted `field` and
`role="weather_context"`; never invent a control UUID. Formats do not verify units.
Current values are not automatically observations, forecasts are not past weather
and `solar_radiation` encoding remains unknown. Structured weather history requires
explicitly configured local recording sources; it never backfills old days.
The qualitative comparable-day branch uses an explicitly owner-assumed native
class mapping, never verified radiation energy. Inspect its diagnostics/warnings.
Production bindings may include user-declared `pv_parameters`; only a currently
confirmed valid binding makes them usable. Profile mutation confirmation rules are in operations. Missing geometry is unknown, not a reason
to invent orientation or reject every simple comparison. Arrays share a source;
do not infer individual yields or sum completeness. MCP replacement/deletion checks
old and new source visibility. Use a smaller profile page after `response_too_large`.

Use `loxone_get_installation_profile(view="summary")` to select confirmed
source roles. Summary retains exact source identities, statuses, provenance and
usability limitations after fresh authorization and reference cleanup. Request
`view="full"` for the relevant page when rationale, display names or complete
PV/load parameters are needed; omitted summary fields are not absent declarations. Follow `next_offset` only as far as needed; every page requires
fresh caller visibility. Roles, measurement boundaries and directions are user
declarations, not verified technical units, aggregation or physical topology.
Use only bindings with `status="confirmed"`; drafts, invalid sources and
`needs_review` bindings require Admin review. Do not infer missing equipment
from omitted bindings. Installation changes never inherit old confirmed roles.

### Native energy reads

   Resolve one exact currently visible EFM with `loxone_find_controls` and current
   description references; never infer a target from its name. Call
   `loxone_read_controls` with `targets=[{control_uuid: ...}]` and
   `native_result_view` (`actual`, `day`, `week`,
   `month`, `year`, `lifetime`) with one exact target, no `state_names`, and
   `include_semantics=false`. This first slice requires a freshly verified Loxone
   administrator on exact firmware 17.2.8.28; a LoxBerry login does not grant it.
   Period views also require `loxone:history` and administrator-enabled history.
   `native_result` is separate from cached states: `values=[]`, zero state counts,
   state semantics omitted. In `native_efm_result.v2`, only Gpwr/Ppwr/Spwr gain
   metadata-bound W/kW units and documented power roles; Cpwr is load power with
   unknown unit and Rest stays unknown. Check rule/provenance and metadata status:
   changed/missing/invalid/unsupported metadata never supplies units. Check field delivery
   separately from unknown scale, signs, currency, observation freshness and
   period boundaries. `semantic_complete` remains false. Calendar views
   describe current running periods, not yesterday or arbitrary historic dates.
   Missing `Rest` is not zero. Do not calculate a balance, infer self-consumption,
   self-sufficiency or aliases, or retry native reads automatically. Omit/null
   `native_result_view` retains the existing cached-state workflow without probes.
   For dated energy components use confirmed bindings and the existing
   `loxone_analyze_history(operation="energy")` with source semantics and coverage;
   keep their time windows separate from current native power snapshots. Native
   fields are not synthetic statistic/state selectors. Check `report_applicability`
   and `report_limitations`; missing self-consumption/storage/residual components
   remain unknown.
   For native EnergyManager/EnergyManager2 context, use the opt-in
   `loxone_describe_control(view="energy_context")` on one exact visible manager.
   This plugin disclosure policy requires a freshly verified Loxone administrator
   and rejects hidden diagnosis. It is not a claimed Loxone permission rule.
   Check generation, advertised/missing capabilities, metadata status and each
   cached state's observation quality separately. Gen-1 fresh names/minOnTime
   are not joined to old cached load IDs; zero minOnTime means no trigger, not
   confirmed flexibility. Gen-2 editing locks concern MinSoc/MaxSpwr parameters,
   not general load locks. `hasActual` may be digital feedback; false means a
   manager assumption, not measured load power. Load pwr/ppwr units and priority
   direction remain unknown. Only documented Gen-2 global powers have kW and
   Ssoc/MinSoc have percent; preserve unknown signs and physical boundaries.
   Output activation is not a measured physical cycle. Gen-1 activeUntil timezone
   is unknown; Gen-2 minimumActiveUntil uses documented UTC seconds since 2009.
   Do not infer historical locks, schedule loads, follow internal load UUIDs as
   authorized controls or reconstruct the manager algorithm. Detailed cached
   loads are also decoded through the existing semantic surfaces only after the
   same fresh administrator check. Raw/legacy reads retain their existing contract.
   Source-shape fixtures do not prove device or firmware compatibility.

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

### Confirmed flexible loads and observed activity cycles

Read the current installation profile first. Only confirmed consumer bindings
with load_constraints_usable=true provide declared windows/deadlines, duration,
interruptibility, minimum run/off times and exact operating-state association.
Hidden/unconfirmed/changed companions cannot qualify; do not invent IDs or native
lock observations. Profile mutation safeguards are in operations.

Use operating_phases with this confirmed consumer statistic at hour granularity
and its confirmed binary operating-state binding at raw granularity. Inspect
comparison.load_cycles, profile_revision, boundaries_complete, energy_profile_complete,
discrepancies, limits and both truncation flags. Initial active states, query
edges, capture restarts/gaps and missing hours are incomplete evidence. State
edges describe local observed activity, not native appliance/program identity.
active_episode_only is the default; user_confirmed_cycle is an explicit owner
assertion. Declared Wh values never become measured interval energy. Unknown
native locks remain not_checked, planning not_evaluated. Never infer shiftability,
a cleared lock, operation authorization, self-consumption or financial savings.
A profile-change failure requires a fresh read and review, not blind retry.

### Conditional retrospective load shifts

For retrospective_shift, read the current profile and use one confirmed
grid_export statistic with explicit export direction and the same declared
measurement boundary as every consumer. Select at most seven distinct confirmed
consumer/operating-state pairs with usable constraints; energy granularity hour,
state granularity raw. Explicit comparable_boundaries_confirmed=true is required;
check the declaration and exclude duplicate/overlapping consumer counters.
Use complete user_confirmed_cycle activity episodes with matching duration and
complete observed hourly energy profiles. Declared totals, missing hours,
capture gaps/restarts and non-hourly aggregates never invent measured profiles.

Inspect comparison.retrospective_shift, profile_revision, excluded_cycles,
limitations, examples_truncated and each example's blocking_conditions. The
shared export budget is allocated across all loads without counting the same
energy twice. Declared original-date windows/completion, DST, continuous
inactive coverage and minimum off time are checked; cycles remain contiguous.
Missing historical native locks explicitly block admissibility: every example
is conditional_only, admissibility=not_proven and native_lock_status=not_checked.
Explain this condition to the user. Never recommend it as an allowed device
operation, measured self-consumption, proven solar attribution, net saving or
financial benefit. Storage, other load responses and sub-hour dynamics remain
unknown. No future planning or device write is authorized. Search exhaustion
returns no allocation from a partial search; truncation is not global optimality.

### Native PV-production forecasts and local observations

For an exact visible `PvProductionForecast`, reuse control description and named
state reads with semantics. `period`, `today`, `tomorrow` and `after` are forecast
kWh, not observed production. Check `ready`, `errorInfo`, prediction timestamp and
cycle bounds together; zero timestamps and -1 energy are unavailable. Time states
use the native 2009 epoch. Current cache observations do not prove a recently
issued forecast; inspect prediction/cycle times separately. No subdaily forecast
distribution or inverter-limit validation follows from these aggregate values.

LoxBerry Admin can explicitly confirm and enable bounded irradiance/temperature
sampling or complete settled PVPF snapshots in the existing history store.
Administrator source contracts are declarations, not native decoder guarantees
or physical calibration. Never qualify sources by names, units in display text
alone, or a caller-supplied analysis rule. Irradiance derived from the assessed PV
yield is a circular baseline and must be excluded. Samples establish observations
of source states, not continuous physical measurements. Recording starts now and
never backfills history. Forecast snapshots retain forecast origin.

### Qualitative weather peers

For qualitative weather peers use `loxone_analyze_history(operation="comparable_days")`
with one exact configured actual structured-weather UUID or a confirmed actual
weather binding for `solar_radiation`, explicit past bounds/timezone and
`comparable_day_options` containing `reference_day` and a fixed local-hour window.
Read the `comparable_days.radiation_classes.v1` method and its classification
origin: native 0-3 mapping is an explicitly owner-approved assumption, not a
verified decoder. Only the same class sequence at the same completed source-point
positions qualifies a peer; never shrink missing positions, use forecasts as
observations, or infer continuous coverage. No raw pages, 15-percent radiation
tolerance, temperature selection, radiation energy, normalized yield, PV anomaly
diagnosis or self-consumption result is provided by this class branch. Lux cannot
be converted universally to irradiance. Numerical source/method gates remain open. Unexpected values stay in the archive
and in bounded point-time/raw-value/reason diagnostics with a trace-correlated
sanitized log. Tell the user when the tool warns about mapping/data incompatibility;
do not call it a proven device fault or silently treat those values as valid classes.
