# Normalized meter output semantics

Rule family: `Meter.output.<type>.<channel>.v1`. Reviewed 2026-10-19.

## Source-to-runtime chain

The official [Structure File 17.1](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf),
physical pp.105–106, defines runtime `Meter`, `details.type` values
`unidirectional`, `bidirectional`, `storage`, `legacy`, and explicitly makes a
missing type default to unidirectional. It binds `actualFormat` to `actual`,
lists `total` and the optional `totalNeg` and calendar reading channels.
`powerName` is explicitly a display name. The retained official PDF SHA-256 is
`97bbc5ec79c8479c0f2f561a55780a764a518fe420d11fd2fc26979fc41e5f23`.

The corresponding block-output contracts supply the normalized conventions:

| Runtime subtype | `actual` / block output Pf | Reading channels | Primary source |
| --- | --- | --- | --- |
| unidirectional | Nonnegative, including zero; no consumption/production role inferred | Nonnegative | [Meter](https://www.loxone.com/dede/kb/zaehler/), [Pulse Meter](https://www.loxone.com/dede/kb/impulszaehler/) |
| bidirectional | Positive consumption, negative delivery | Separate nonnegative readings | [Meter Bidirectional](https://www.loxone.com/dede/kb/zaehler-bidirektional/), [Pulse Meter Bidirectional](https://www.loxone.com/dede/kb/impulszaehler-bidirektional/) |
| storage | Positive discharge, negative charge | Separate nonnegative readings | [Meter & Storage](https://www.loxone.com/dede/kb/zaehler-speicher/), [Pulse Meter & Storage](https://www.loxone.com/dede/kb/impulszaehler-speicher/) |
| legacy | No new rule | No new rule | Structure File distinction; do not apply new-block KB by name |

KB review used the official indexed content where direct retrieval failed.
The fixed-value meter's nominal parameter is nonnegative, but its output table
lists an unrestricted range. No extra fixed-value-specific contract is invented;
only a documented runtime subtype can select these rules. Internal Config XML
type names are not runtime types and are not assigned to unobserved families.

## Boundaries and validation

The normalized `Meter` model retains only the documented subtype. Malformed,
unknown and contradictory unidirectional/negative-channel metadata loses this
enrichment. Source references distinguish the explicit and documented-default
cases and the exact subtype/output rule, invalidating affected profile bindings
when the rule changes. Resolver operation is pure and adds no source requests.
State rules require an advertised state; series rules require StatisticV2 with
compatible accumulation metadata and raw granularity. Difference sums do not
inherit a counter's nonnegative output rule: a decrease requires separate reset
evidence. Legacy series remain unchanged.

State `sign_convention` and optional series `sign_convention` describe normalized
outputs. State `semantic_value.kind=meter_output` reports the raw finite numeric
value, channel, subtype, and `output_direction` for `actual`. Counter channels
have no invented Mrc/Mrd alias or charge/delivery label. Boolean, string,
nonfinite, overflowing, or disallowed negative state values are invalid, without
clamping or rewriting the original value. Unit/quantity and physical boundary
remain separate; a sign rule does not prove energy, activity, physical operation,
continuous coverage or a source measurement timestamp.

The absolute Bi/storage blocks' direction property concerns the physical value
at **input** Pf. Their **output** conventions above are fixed. Thus unknown XML
encoding of that input setting is not a blocker to output interpretation. The
reference project's `PwrN` strings are power/flow labels, not polarity evidence.

## Relationship to #534

These rules close the meter-output prerequisite only. They do not modify
`native_efm_result.v2`, its sign convention, units, periods or transport. The
[EFM matrix](efm-semantic-matrix.v1.md) still independently qualifies aggregate
Gpwr/Ppwr/Spwr direction/boundary, Cpwr unit/boundary, native Rest applicability,
period quantity/currency/clock/reset and physical observation time. Existing
positive/negative/zero comparisons support the tested installation only.

## Verification

Tests cover normalization/default versus malformed/future/legacy metadata,
zero and both signed directions, nonnegative counters, invalid numbers, exact
channels, shared state/compact-read semantics, raw-value preservation, series
accumulation conflicts and profile source references. No new tool, write path,
project join or arbitrary format inference is introduced. Target access, if
used to inspect source metadata, remains read-only and separate from local rule
tests; no unrequested target deployment is implied.
