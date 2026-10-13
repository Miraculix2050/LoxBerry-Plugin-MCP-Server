# Comparable days method review (PR 6 draft)

Status: PR 6 draft with an owner-approved qualitative runtime branch; final review and target acceptance pending.
Predecessor: PR #496, merged as a9f499df. The runtime adapter and acceptance remain
required before this package can merge. Parent issue: #439.

The pure method accepts adapter-produced hourly evidence for one to 31 contiguous
local days. Callers cannot assert evidence-rule identifiers. A reference day and
all candidates use a fixed local-hour window; a running reference uses only its
completed hours. Incomplete candidates are excluded rather than shrinking the
window per pair. Ambiguous/nonexistent DST boundaries are excluded explicitly.

Maximum seasonal separation is 30 days, radiation-energy deviation 15 percent,
and temperature deviation 3 degrees Celsius. Stricter caller options are allowed
and echoed. Radiation must be qualified interval energy in Wh/m²; temperature
must use the same qualified observation position. Source generation, installation
and evidence rules must remain compatible. Reception and capture intervals do
not establish source-time measurement coverage. Forecasts cannot become observations.

Candidates sort by normalized weather distance, seasonal distance and local date.
Each qualified PV pair can report a signed difference. A group requires at least
three complete PV candidates and a qualified reference. The median defines the
comparison baseline. A difference strictly below -20 percent only flags a check
candidate; it is not a defect diagnosis. Zero radiation or zero median cannot
establish normalized yield or savings. House energy is not isolated PV energy.

The runtime integration must preserve one fresh history authorization context,
one admitted worker, 16 sources, 100000 points, 31 touched days, 30 seconds, two
analyses and 64 KiB output. Read each source/range once; any new source-time query
requires an index and explicit budget. Recheck authorization/configuration before
output and preserve cancellation admission. Existing exact scalar AnalysisSource
contracts cannot be relaxed to represent structured weather.

The installed recorder currently has no reviewed numerical solar-radiation rule.
Its raw numerical field, presentation formats and user-declared profile roles
cannot qualify radiation interval energy. The integration must return explicit
insufficient_evidence for such sources. Positive method fixtures do not prove
real-source qualification or compatibility. Define and review the actual adapter
qualification rules before claiming usable numerical comparisons.

59 numerical reference/contract cases cover thresholds, fixed windows, missing evidence,
source changes, DST, zero/invalid/overflow values, group completeness and deadline
checks. Runtime/schema/Explorer/DE-EN documentation and target acceptance are still
pending. #501 is independent, excluded from this chat and not declared passed.

## First method review corrections

Only closed RadiationRule, TemperatureRule and PVRule enum objects qualify
internal adapter evidence. Nonempty raw strings, serialized enum values and
profile roles are rejected. Source generation and installation identity are
mandatory. No current recorder adapter is granted qualification by these types;
an adapter must establish each documented quantity/unit/time/interval predicate.

Differences and ratios use the decimal representation of finite source summaries
before conversion to output floats. Inclusive 15-percent/3-degree bounds and the
strict -20-percent advisory threshold are tested with fractional decimal inputs
and representable values immediately beyond their boundaries. No broad tolerance
or approximate equality widens the accepted thresholds.

Primary weather documentation distinguishes absolute irradiance in W/m²,
relative irradiance in percent and radiation classes. It does not by itself
identify the archived binary solar_radiation field or establish a continuous
observed interval: https://www.loxone.com/enen/kb/weather-service/ . Do not infer
that mapping from related weather-service outputs.


## Owner method adjustment (2026-10-13)

The owner approved an initial qualitative radiation-class comparison while the
numerical 15-percent/radiation-energy method remains unavailable without a
qualified historical source. The owner separately approved treating binary
solarRadiation integer values 0-3 as risk classes as an explicitly labelled
assumption. The later owner instruction requires preserving unexpected values:
they stay in the archive and appear as bounded diagnostics with point time, raw
numerical value and reason. They are not used as valid classes. A tool warning
tells the AI to inform the user, and a sanitized warning log correlates via trace
ID without logging source identifiers or raw values. This indicates mapping/data
incompatibility, not a proven device fault. At most 16 diagnostics are included;
the total count and truncation are explicit. Nonfinite values use fixed textual
representations compatible with JSON rather than nonfinite JSON numbers.

The assumption supersedes neither unknown numerical units nor missing native
encoding proof. classification_origin is owner_assumed_risk_class_0_3 with an
explicit unverified-mapping limitation. The qualitative method uses one actual
source, exact hour-start source points, a fixed completed-hour window and an
identical class sequence. It applies no temperature/PV comparison and provides
no radiation energy or normalized yield. Valid peers may still be selected when
unexpected values occur outside the selected hour positions; the diagnostics
remain visible. Missing/invalid required positions never shrink the window.

One bounded read uses the existing reception index; reception and source point
must both be inside the query interval. Latest point versions replace earlier
versions without summation; every row consumes the input budget. There is no new
source-time query, persistent schema or backfill. Forecasts and points predating
capture are excluded from comparison. The existing admission and final caller
authorization/configuration checks remain required.

The local V17.0 communication specification page 21 describes solarRadiation as
an integer only. The archived Structure File is V16.0, not the V17.1 source used
by other rules, and supplies no class mapping. Weather Service documentation
supplies the class descriptions. They are not combined into a claimed verified
binary decoder. Lux is separate context; no conversion to W/m2 is introduced.
