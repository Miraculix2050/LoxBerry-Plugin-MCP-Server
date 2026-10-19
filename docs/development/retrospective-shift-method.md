# Conditional retrospective export absorption (PR 8)

Predecessor: merged #506 / 6e8f170f. Parent: #440. Extend the existing
`loxone_analyze_history` operation contract; do not add an operating tool.
The owner explicitly approved conditional examples when native lock evidence
is absent. Such examples are not admissible schedules or recommendations to
operate a device. Unknown locks never become clear.

## Evidence and scope

Use one freshly authorized historical context, deduplicated reads and the
existing 16-source / 31-local-day / 100,000-point / 30-second / two-worker /
64-KiB bounds. Require one confirmed grid-export binding with an explicit
export direction and measurement boundary, and confirmed consumer/operating
binding pairs with current usable load constraints. The caller must explicitly
confirm comparable boundaries; this remains a declaration, not verified wiring.
Reject duplicate consumer/operating associations and missing or conflicting
boundaries rather than counting the same appliance twice.

Use only complete observed episodes with owner-confirmed cycle identity,
matching declared duration, no constraint discrepancies, and fully tiled native
hourly Wh/kWh energies. Declared cycle totals cannot invent an hourly shape.
Native day/month/year sums, counters, partial hours, state gaps, query-edge
episodes and capture restarts cannot establish complete input profiles.

## Conditional examples

Keep each whole cycle contiguous, even when interruption is permitted. Move it
only within windows anchored to its original local start date, with explicit
next-day offsets and latest completion. Exclude ambiguous/nonexistent DST
boundaries; use elapsed UTC duration and require the entire interval inside
the local window and requested past interval. No future time validation is
introduced here.

Require continuous observed inactive coverage for the alternative interval and
the declared minimum off time on both sides, within one capture phase. Do not
overlap the original episode or other observed activity. Every shifted energy
interval must match a complete measured export interval exactly. No prorating,
interpolation, lux conversion or risk-class-derived energy.

For each hour, the conditional absorption is the minimum of cycle energy and
remaining measured export. All loads share one export budget. Select the highest
remaining conditional absorption, then earliest start, then binding and original
episode start; recompute after each allocation. Select at most one alternative
per original episode, prevent overlapping hypothetical cycles of the same load,
and publish at most 16 allocations / 128 hourly allocations. Bound evaluated
alternatives and return an explicit budget limitation rather than silently
choosing from a truncated search.

The result must label values as conditional export-absorption upper bounds in
Wh, not measured self-consumption, PV attribution, net savings or financial
benefit. Storage interaction, other load responses and sub-hour dynamics remain
unknown. The owner-approved absence of native lock information is an explicit
blocking qualification condition in every example. Do not claim that a control
without an exposed lock state has no locks, or use current locks as historical
coverage. The documented `jLocked` text state and Switch `lockedOn` do not by
themselves establish complete appliance constraints or historical lock coverage.

## Delivery

Review this typed method before runtime integration. Preserve profile-revision,
source visibility/fingerprint, final-access, raw pagination and admission gates.
Update schemas, Explorer help, skill guidance, paired DE/EN docs, support matrix
and changelog with the behavioral PR. Keep installed fixtures separate from
real available source acceptance. #501 remains excluded and unclaimed.
