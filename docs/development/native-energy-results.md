# Native energy results

The first #436 runtime slice extends `loxone_read_controls`; it adds no MCP tool.
`native_result_view=null` retains the released cached-state path and causes no
native requests, administrative gate or firmware probe. A non-null view requires
one exact target, no state selector and disabled semantic enrichment.

## Evidence and authorization

The initial contract is limited to EFM and firmware 17.2.8.28, matching the
[reviewed read contract](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/436#issuecomment-6113527821).
A freshly authenticated caller-owned request session loads the filtered
structure. Strict boolean `currentUser.isAdmin=true`, visible EFM and independent
firmware/serial agreement are mandatory. Missing/malformed administration is
unknown and denied; display names, token permission bits and LoxBerry permissions
are not substitutes. OAuth revocation is checked before reading and publication;
a post-read structure must still prove visibility, administration and identity.
Non-admin aggregate disclosure remains an open evidence gate.

Actual requires read scope; other views require read/history scopes and existing
history activation. Authentication uses existing coordination and token-health
confirmation, without automatic retries. Sessions and ephemeral tokens are
closed/destroyed on completion, rejection, timeout and cancellation.

### Non-admin evidence disposition (#535)

Final disposition for [#535](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/535),
reviewed and merged in [#592](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/592)
on 2026-10-26: **insufficient evidence; retain admin-only**.
No non-admin implementation or disclosure policy is introduced.

The owner-authorized read-only inventory on 2026-10-26 used two existing distinct
Restricted/Explorer identities on the reserved test target. Each loaded two fresh
filtered structures in its own authenticated session. Caller UUID equality,
Miniserver serial agreement and post-read OAuth admission were verified without
retaining private identities or participant data in this summary. The restricted
caller was strictly non-admin, with no visible EFM in either structure and no
history scope. The other caller was strictly admin, with one visible EFM and
history scope. History was enabled. No native aggregate request was made.

| Required case, for both actual and day | Evidence and remaining gap |
| --- | --- |
| Non-admin EFM visible; all relevant participants accessible | Unavailable among the two inspected eligible identities. No participant-access proof or own-session actual/day specimen. |
| Same non-admin EFM visible; a specific participant explicitly denied | Unavailable. No independently established participant relationship, explicit effective denial or intended aggregate-disclosure/filtering policy. |
| EFM denied or absent from caller visibility | Fresh restricted-caller non-visibility observed twice. This establishes neither explicit denial nor physical absence. Native denial and actual/day behavior remain untested; day additionally lacks history scope. |
| Revocation during an admitted read, including post-read release | Unavailable. Stable pre/post admission does not prove revocation handling on a real device. Existing synthetic regression tests do not replace this evidence. |

Observed firmware was **17.2.10.21**. The inventory does not satisfy the issue's
fixed **17.2.8.28** actual/day matrix or establish compatibility for either firmware.
No concrete non-admin product use case was supplied beyond investigating support.
Existing-session authorization permits this inventory; it does not establish a
vendor disclosure policy or authorize creating users, changing rights or inducing
revocation. The sampled runtime/client/structure source hashes, configuration hash,
service PID and active state were unchanged, and the private runtime was closed
before reservation release.

The reviewed decision concludes this bounded investigation with these unavailable
cases and retains admin-only. Any later non-admin support still needs
an explicit reviewed contract and separate implementation approval, preserving
own-session authorization, pre/post checks, scopes, bounds and no fallback/cache.

## Delivery and limits

Only `actual/day/week/month/year/lifetime` are accepted. Native values never enter
the state cache. One typed `native_result` accompanies the existing control
identity, empty values and zero state counts; semantics is omitted only in native
mode. Field delivery, semantics and freshness remain independent. Four observed
actual fields and optional/unobserved Rest are named explicitly; period fields
retain Export/Import/Production/Charge/Discharge/Consumption/Income. No aliases,
unit/sign inference, balance or self-consumption calculation is performed.

## Partial report components

The versioned [EFM semantic evidence matrix](efm-semantic-matrix.v1.md)
records the #534 documentation/KB investigation, per-field decisions and exact
missing prerequisites for firmware 17.2.8.28. The baseline confirmed the existing
subset; the follow-up adds only Cpwr's declared display-unit binding. Node/meter
direction rules alone do not establish aggregate inclusion formulas.

The native transport rule remains `native_efm_17_2_8_28.v1`. Results now use
`native_efm_result.v2`; its additive semantic fields and widened `unit` enum
explicitly distinguish known W/kW from null. The pure rule
`native_efm_actual_semantics_17_2_8_28.v2` is based on the official
[Structure File 17.1, pages 64–67](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=64).

| Native component | Proven meaning | Remaining gaps |
| --- | --- | --- |
| Actual Gpwr/Ppwr/Spwr | Grid/production/storage power; W or kW only from the same EFM's complete `details.actualFormat` | Sign direction, boundary, observation time |
| Actual Cpwr | Load power; declared W/kW from the same EFM's stable `actualFormat`, including its documented consumed-power applicability | Sign direction, boundary, observation time, source calibration |
| Actual Rest | KB block output means calculated remaining power of the top group; no native-field enrichment yet | Native field/output binding, unit, direction and boundary |
| Native calendar/lifetime fields | Source names and current native view | Units, currency, boundaries/reset and historical date selection |
| Historical report components | Existing independently evidenced StatisticV2/Event History path | Coverage and component-specific semantics must pass that path's gates |
| EnergyManager / EnergyManager2 | Separate documented generation context below | No positive target-device evidence; no shared EFM algorithm |

An enriched native field adds nullable `unit_origin`, currently only
`configured_display_format` for the exact Gpwr/Ppwr/Spwr/Cpwr W/kW rule.
The originating source is the same EFM's stable, bounded `details.actualFormat`;
provenance lists both unit and origin. This is declared presentation metadata,
not a measurement calibration, scale factor or proof of source-unit consistency.
No unit conversion, new admitted format or extra request is introduced. Missing,
invalid, unsupported or changed metadata leaves unit and origin null.
Native Rest and period fields receive no unit-origin inference. The
[read-only follow-up](efm-rest-display-observations.md) records the independent
Cpwr source chain, current comparisons and separate missing native Rest result.
Earlier semantic rule v1 remains accepted when reading retained old results;
new enrichment emits v2. No transport/schema version changes are needed.

The [EFM KB](https://www.loxone.com/dede/kb/energieflussmonitor/) defines Rest's
block function and explains unmetered downstream loads and measurement
differences. The general residual meaning is known even while native mapping
is pending. Tolerances, asynchronous updates and display rounding prevent an
exact zero-balance requirement; never clamp residuals, reconstruct native Rest
from displayed rounded values, double count metered parents and their children,
or infer an unmetered consumer from a residual alone. The owner's screenshots
establish presentation examples only; they do not prove native-field binding or
that EFM arithmetic ignores unit configuration. No fresh device acceptance is
claimed by this clarification.

Only a bounded, fully retained format with one numeric `%…f` followed by literal
`W` or `kW` is accepted. Formats are never executed and values are never scaled.
Generic Control formats, participant formats and `totalFormat` are not substitutes.
Both already required structures must advertise identical format metadata. A
change retains raw values but drops unit enrichment and reports
`source_metadata_changed`; no retry or additional source request is made.
Absent metadata is `missing`; rejected types, bounds or encoding are `invalid`.
A retained format outside this rule's allowlist is `unsupported`, not evidence
of a source defect. These statuses never supply units.
Quantity, unit, field delivery, freshness and `semantic_complete=false` remain
independent. Provenance records rule, firmware, document pages and metadata path.

For a report, request `native_result_view="actual"` for current partial power
components. Resolve confirmed historic bindings and use the existing
`loxone_analyze_history(operation="energy")` with its source semantics and coverage
for dated energy components. Preserve those time windows separately; this is no
temporal join between a current snapshot and historical totals. Native fields are
not valid synthetic statistic/state selectors. Missing self-consumption, storage
or residual components remain unknown. `report_applicability`,
`historical_date_selection_supported=false` and `report_limitations` make these
constraints explicit in the compact result.

Calendar views are running native periods. Start/end/timezone and physical
observation freshness remain unknown; retrieval time is response receipt time.
Lifetime start/reset is unknown. Historical reports require independently proven
historical series and cannot read yesterday through `get/day`.

The complete operation is bounded by 30 seconds; transport phases use the smaller
of ten seconds and the configured timeout. Native outer payload is at most 32 KiB,
LL.value JSON text at most 16 KiB, flat object at most 16 properties, and final
structured envelope at most 64 KiB. Duplicate/nested/nonfinite content is rejected;
known wrong scalar fields are invalid without coercion. Unknown field names are
not published. Missing fields are not zero. No native-result cache is added.

Pure source projection, session transport, runtime policy and tool serialization
remain separate. Tests cover their boundaries; fixtures do not establish device
or broader firmware compatibility. Reserved Browser/MCP/SSH acceptance and matched
performance measurements are separate required delivery evidence.

## Energy Manager context

`loxone_describe_control(view="energy_context")` returns `energy_context.v1` for
one exact visible EnergyManager or EnergyManager2. It requires a fresh caller
structure and strict boolean Loxone administration; `include_hidden=true` is
rejected. This conservative plugin disclosure policy is not a claimed native
permission requirement. LoxBerry administration does not substitute. Legacy
descriptions retain their fields and reads. No new tool, endpoint, session, cache,
algorithm or action is added.

The [official Structure File 17.1 pp.61–63](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=61)
provides distinct generation contracts:

| Family | Documented context | Unverified context |
| --- | --- | --- |
| EnergyManager | Fresh load ID/name/minOnTime seconds; zero means no trigger. Cached output/preparing/manual-wait/permanent flags; activeUntil seconds since 2009 | Metadata/state temporal association, timezone, priority direction, global power units and physical cycles |
| EnergyManager2 | Parameter edit locks, connected/valid inputs; global Gpwr/Spwr/Ppwr/MaxSpwr kW and Ssoc/MinSoc percent; last-delivered load identities/status; minimumActiveUntil UTC seconds since 2009 | Load pwr/ppwr units, meter feedback, priority direction, signs, boundaries, general/historical load locks and physical cycles |

Each result separates documented, advertised and missing states. These are
source-shape capabilities, not device compatibility proof. Unsupported families
are rejected; installed fixtures remain distinct from real-device acceptance.
Fresh Gen-1 metadata is never joined to cached IDs: a load can be reconfigured
after its last state delivery. Gen-2 payload names/UUIDs remain last-delivered
source facts; references never authorize another control read or implicit join.

`hasActual=true` may be digital feedback; false labels a manager assumption and
absence stays unknown. Editing locks are not general load locks. Output activation
does not prove a physical cycle; current states do not establish historical native
constraints. State observation quality remains separate, including stale records.
Existing semantic surfaces share the pure decoder but newly decoded loads require
the same fresh administrator check. Existing raw reads remain unchanged.

Retained metadata and payloads are bounded to 100 loads. Load JSON is at most
16 KiB, with unique keys/IDs and Gen-2 provided opaque UUIDs, at most 16 flat scalar
properties per load, strict types and finite numbers. Text is UTF-8 bounded; no
format, icon or reference is executed. The final envelope is at most 64 KiB;
oversized output returns an error without partial metadata. New family-specific
technical rulesets version source fingerprints independently of disclosure rights,
preserving unchanged legacy families. Rule references alone establish neither
semantic completeness, present administration nor physical truth.

### Real-device evidence disposition

The [#533 read-only investigation](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/533#issuecomment-6243892031)
recorded the following scoped dispositions on firmware 17.2.8.28:

| Family | Availability in this caller's visible structure | Real-device context acceptance |
| --- | --- | --- |
| EnergyManager | Not available in the inspected scope | Unverified |
| EnergyManager2 | Not available in the inspected scope | Unverified |

This does not establish absence from inaccessible controls, Config or other
installations. No real manager metadata/state specimen, positive `energy_context`
result, load observation or manager Browser acceptance was possible. Documented
contracts and synthetic tests remain separate from these missing device proofs;
neither generation is declared compatible or defective by this disposition.
