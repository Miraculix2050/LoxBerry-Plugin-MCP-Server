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
| EnergyManager / EnergyManager2 | Separate families, outside this slice | No positive target-device evidence |

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
