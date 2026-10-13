# Confirmed load constraints and observed cycles (PR 7)

Predecessor: merged PR #505 / 226db035. Parent: #440. This stage describes
historical cycles and stores explicit owner declarations; it operates no load
and supplies no future scheduling or financial saving claim.

## Profile contract

Add optional `load_flexibility` to a consumer binding in the current profile.
Existing bindings remain valid. Confirm the whole binding again after any change.
The constraints contain an IANA timezone, at most 16 local weekly windows,
latest completion, expected duration, interruptibility, minimum run/off times,
and the exact linked operating-state binding. Weekdays are Monday=0..Sunday=6.
Windows and completion have an explicit 0/1 next-day offset, avoiding implicit
midnight interpretation. No empty/inverted/>24-hour window qualifies. Ambiguous
or nonexistent DST boundaries must be excluded by the later scheduling adapter.

Energy-profile provenance is either `observed_intervals` (the confirmed consumer
source must independently qualify complete measured intervals) or `user_declared`
(a positive finite declared Wh value, never treated as measured energy). A role,
origin string or declaration cannot establish quantity/unit/interval semantics.
The rationale is bounded plain text, never an instruction or authorization.
`native_lock_policy=never_override` is fixed; unknown native locks are not clear.

Only a currently confirmed consumer and currently visible, confirmed binary
operating-state association make the constraints usable as declarations. Hidden,
invalid, changed or unconfirmed linked sources cannot qualify. Do not reveal a
hidden companion's identifiers in the consumer projection. This does not by
itself make a load schedulable or establish a native lock observation.

## Historical cycle evidence

Extend the existing `operating_phases` analysis to describe cycles when the two
confirmed profile sources explicitly associate a consumer and its operating
state. Keep the default calculation for existing callers. Use the existing fresh
history context, deduplicated reads, current scalar semantics and common bounds.

A complete cycle requires a decoded false-to-true-to-false sequence within one
continuous capture phase, strictly inside the requested interval. Repeated
identical active values may be coalesced within the same capture phase. Initial
active values, query-edge truncation, capture restarts, gaps and unknown states
cannot establish both boundaries. Preserve incomplete episode diagnostics rather
than asserting missing cycles or inventing durations.

Associate energy only when the existing scalar rule establishes nonnegative,
complete hourly Wh/kWh interval energies and those intervals tile the entire
observed cycle. No interpolation, fractional allocation, cumulative-counter
conversion or class/lux-derived energy is introduced. Whole-cycle energy and
profile completeness remain separate from duration or state coverage.

Results include observed bounds, duration, energy availability, declared-profile
origin, constraint discrepancies and limitations. A complete energy profile is
evidence for a later counterfactual, never permission to operate or proof of
shiftability. Native locks remain unverified unless an independent reviewed
adapter establishes them. PR 8 must preserve this gate.

Bound output to 16 described episodes and 128 energy intervals in total, with
counts and truncation. Preserve the existing 31 local days, 100,000 input points,
30-second deadline, two analyses and 64-KiB result ceiling. The target acceptance
distinguishes isolated installed fixtures from genuine available source evidence.

## Delivery gate

This draft begins with typed constraints and the method contract. Profile/store
projection, Admin DE/EN UI, historical cycle runtime, schema/guide, tests and
focused target acceptance are required before merge. #501 is separate and excluded.
