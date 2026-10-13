# Comparable days method review (PR 6 draft)

Status: proposed method and typed result contracts; not a registered MCP operation.
Predecessor: PR #496, merged as a9f499df. The runtime adapter and acceptance remain
required before this package can merge. Parent issue: #439.

The pure method accepts adapter-produced hourly evidence for one to 31 contiguous
local days. Callers cannot assert evidence-rule identifiers. A reference day and
all candidates use a fixed local-hour window; a running reference uses only its
completed hours. Incomplete candidates are excluded rather than shrinking the
window per pair. Ambiguous/nonexistent DST boundaries are excluded explicitly.

Maximum seasonal separation is 30 days, radiation-energy deviation 15 percent,
and temperature deviation 3 degrees Celsius. Stricter caller options are allowed
and echoed. Radiation must be qualified interval energy in Wh/mÂ²; temperature
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

58 reference/contract cases cover thresholds, fixed windows, missing evidence,
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
