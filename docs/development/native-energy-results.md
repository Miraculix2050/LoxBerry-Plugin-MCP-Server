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

## Delivery and limits

Only `actual/day/week/month/year/lifetime` are accepted. Native values never enter
the state cache. One typed `native_result` accompanies the existing control
identity, empty values and zero state counts; semantics is omitted only in native
mode. Field delivery, semantics and freshness remain independent. Four observed
actual fields and optional/unobserved Rest are named explicitly; period fields
retain Export/Import/Production/Charge/Discharge/Consumption/Income. No aliases,
unit/sign inference, balance or self-consumption calculation is performed.

## Partial report components

The native transport rule remains `native_efm_17_2_8_28.v1`. Results now use
`native_efm_result.v2`; its additive semantic fields and widened `unit` enum
explicitly distinguish known W/kW from null. The pure rule
`native_efm_actual_semantics_17_2_8_28.v1` is based on the official
[Structure File 17.1, pages 64–67](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=64).

| Native component | Proven meaning | Remaining gaps |
| --- | --- | --- |
| Actual Gpwr/Ppwr/Spwr | Grid/production/storage power; W or kW only from the same EFM's complete `details.actualFormat` | Sign direction, boundary, observation time |
| Actual Cpwr | Load power | Unit, sign direction, boundary, observation time |
| Actual Rest | No supported interpretation | Quantity, unit and boundary |
| Native calendar/lifetime fields | Source names and current native view | Units, currency, boundaries/reset and historical date selection |
| Historical report components | Existing independently evidenced StatisticV2/Event History path | Coverage and component-specific semantics must pass that path's gates |
| EnergyManager / EnergyManager2 | Separate documented generation context below | No positive target-device evidence; no shared EFM algorithm |

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

### Real-device evidence disposition — 2026-10-18

The reserved, read-only [#533 investigation](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/533)
on Loxberry-Test, firmware 17.2.8.28, established fresh caller administration
and independently matching source identity. The caller-authenticated raw structure,
its normalized visible controls and HTTP-MCP `loxone_find_controls` agreed:

| Family | Availability in this caller's visible structure | Real-device context acceptance |
| --- | --- | --- |
| EnergyManager | Not available in the inspected scope | Unverified |
| EnergyManager2 | Not available in the inspected scope | Unverified |

Both HTTP-MCP discovery responses were successful, non-stale and complete without
a continuation cursor. Fresh post-read visibility and authorization were checked.
This does not establish absence from inaccessible controls, Config or other
installations. No real manager metadata/state specimen, positive `energy_context`
result, load observation or manager Browser acceptance was possible. Documented
contracts and synthetic tests remain separate from these missing device proofs;
neither generation is declared compatible or defective by this disposition.

Installed package 0.4.0b4 used Python 3.13.5. Six inspected source files (manager
decoder, models, structure, semantics, runtime and client) matched master
`56aac1f430aac678add9bb1507507a50f7e1e6ae`. The pre-existing `tools.py` matched
`eb97a8a7` instead; this was a mixed installed revision, not an exact-master
acceptance. Private evidence retains full file hashes and source identity.
Configuration hash, inspected source hashes, service PID/active state and loopback
health remained unchanged; the private runtime was closed and reservation released.
No deployment, restart, configuration, permission or control changes were made.
