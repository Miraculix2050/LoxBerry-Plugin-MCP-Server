# Native EFM semantic evidence matrix v1

- Evidence version: `efm_semantic_matrix.17_2_8_28.v1`, documentation review 2026-10-18;
  installation-observation follow-up 2026-10-19.
- Scope: #534; exact EFM firmware `17.2.8.28`, existing native aggregate views only.
- Decision: **no new runtime semantic rule**. Retain `native_efm_result.v2` and
  `native_efm_actual_semantics_17_2_8_28.v1` unchanged. Documented block behavior,
  observed wire shape and an accepted aggregate decoder are separate evidence.

## Sources and applicability

| ID | Primary source | Version/date and locator | Applicability |
| --- | --- | --- | --- |
| D1 | [Structure File](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf) | 17.1, 2026-08-06, physical PDF pp.64–67 | EFM details, node meanings, states and aggregate commands. Local retained official PDF hash reverified on 2026-10-18; online PDF retrieval failed. |
| K1 | [Energieflussmonitor](https://www.loxone.com/dede/kb/energieflussmonitor/) / [Energy Flow Monitor](https://www.loxone.com/enen/kb/energy-flow-monitor/) | Retrieved 2026-10-18; outputs and application example; no publication date or firmware bound stated | Block outputs and display/configuration explanation; not a version-bound wire mapping. |
| K2 | [Bidirectional meter](https://www.loxone.com/dede/kb/zaehler-bidirektional/) | Retrieved 2026-10-18; outputs, properties, meter reading/units; undated | Meter input direction is configurable; output Pf describes consumption/delivery. Does not identify aggregate EFM sign encoding. |
| K3 | [Storage meter](https://www.loxone.com/dede/kb/zaehler-speicher/) / [Meter & Storage](https://www.loxone.com/enus/kb/meter-storage/) | Retrieved 2026-10-18; English outputs/properties rechecked 2026-10-19; undated | Output Pf is positive for discharge and negative for charge; the direction property concerns the physical value at input Pf. Input direction and units are configurable. Not an aggregate Spwr decoder. |
| K4 | [Meter](https://www.loxone.com/dede/kb/zaehler/) | Retrieved 2026-10-18; inputs and meter reading/units; undated | Power/flow and readings depend on configured medium, units and connected inputs. Not proof of an EFM period unit. |
| E1 | [Original sanitized matrix](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/436#issuecomment-6109313546) | Browser capture 2026-10-11, exact firmware 17.2.8.28 | Owner-authenticated read-only same-origin requests; fresh structure and independent firmware lookup. Browser identity equality with the MCP caller was not established. |
| E2 | [Delivered semantics and acceptance](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/492) | Recorded acceptance on candidate `12ac66b2ffd99f960b6178dc425ffb6b31bbbc69`; merged as `c5daa493f1061e518c97b68446ee6c79da736bfb` | Separate fresh caller-owned admin session and installed MCP handler, all six views; actual/day also through HTTP-MCP/Explorer. Existing semantics only. |
| E3 | Caller-authorized linked-storage comparisons, #534 follow-up | Read-only device observations 2026-10-19, exact firmware 17.2.8.28; private provenance retained | Native actual.Spwr compared with the explicitly referenced storage meter and verified participant-state binding on one installation; negative, zero and positive cases observed. No universal sign or input-inversion contract. |

D1 SHA-256:
`97bbc5ec79c8479c0f2f561a55780a764a518fe420d11fd2fc26979fc41e5f23`.
The EFM command table on p.67 was also rendered and visually checked. Adjacent
Fronius/Energy Monitor units on that page belong to another control family.
KB statements have no independently established 17.2.8.28 applicability for a
new aggregate interpretation; their review date is not a source version.

E1 establishes the JSON-string wire shape and numeric fields in the tables
below. E2 separately establishes the existing format rule through a fresh
caller-owned administrator session. Both concern firmware 17.2.8.28 and remain
historical evidence, not confirmation of today's configuration or permission.
Detailed sanitized capture provenance, receipt times, acquisition limitations
and artifact digests are retained in the private project-data evidence store.
The original documentation review made no new device requests. The later E3
follow-up adds installation observations only and accepts no new runtime rule.

## Actual field decisions

“Confirmed existing” applies only to the stated released subset. Every remaining
unknown has an insufficient-evidence disposition; no row authorizes a new decoder.
`unit=null`, `sign_convention=null`, `scale=null`, `currency=null` and
`semantic_complete=false` retain their released meanings.

| Exact aggregate field | Documentation | Observed raw evidence | Supported encoding / decision | Precise missing prerequisite |
| --- | --- | --- | --- | --- |
| actual.Gpwr | D1 pp.66–67: grid power; block-setting unit. K1: grid-power output. D1 p.65 signs apply to node.actual. | E1 numeric; E2 own EFM format retained | **Confirmed existing:** power/grid_power, W/kW only through the unchanged exact actualFormat rule. Sign and boundary unknown. | Explicit aggregate sign contract plus independent configuration linking grid direction and physical measurement boundary to this aggregate field. |
| actual.Ppwr | D1 pp.66–67: production power; block-setting unit. K1: production-power output. | E1 numeric; E2 own EFM format retained | **Confirmed existing:** power/production_power, same W/kW rule. Sign and boundary unknown. | Explicit aggregate direction contract and configuration proving which production sources, reverse flows and measurement boundary the aggregate includes. |
| actual.Spwr | D1 pp.66–67: storage power; block-setting unit. K3 signs describe meter.Pf, D1 p.65 describes node.actual. | E1 numeric; E2 own EFM format retained; E3 agrees with linked meter-output signs for negative, zero and positive cases on one installation | **Confirmed existing:** power/storage_power, same W/kW rule. E3 supports installation-level correspondence with K3; general charge/discharge sign contract and boundary remain unknown. | Aggregate Spwr sign contract and independent storage configuration/boundary evidence beyond E3's explicit references. Input-direction encoding remains unknown but is not required to interpret the meter's normalized output. |
| actual.Cpwr | D1 p.67: load power; K1 calls the block output consumption power. No explicit aggregate unit binding. | E1 numeric; no independent Cpwr format | **Confirmed existing:** power/load_power, unit/sign/boundary unknown. No extension. | Explicit applicability of a unit source to aggregate Cpwr, plus direction and configured load/measurement-boundary evidence. The neighboring fields' actualFormat rule cannot be widened by analogy. |
| actual.Rest | D1 p.67 lists Rest without defining its quantity. K1 describes the block output as calculated remaining power of the top group; distribution-board residuals represent unmetered downstream devices and may include measurement differences. | Absent in E1; root display flags/names/icons are metadata, not a numeric Rest specimen | **Insufficient evidence:** native quantity/role/unit/sign/boundary remain unknown. Missing is not zero. | Caller-authenticated native Rest specimen and independent top-group/configuration evidence linking it to the documented output; explicit unit/direction applicability. No residual arithmetic or synthetic meter. |

The released actualFormat rule accepts only the same EFM's complete bounded
single numeric `%…f` format followed by literal W/kW, unchanged across the two
already required structures. Values are never scaled. Missing, invalid,
unsupported and changed metadata remain distinct; changed metadata drops unit
enrichment while retaining raw values. Generic control, participant, storage and
total formats are not fallback evidence.

### Installation-level Spwr follow-up

E3 resolves the missing positive native observation for the tested installation:
three positive `get/actual.Spwr` responses each matched at least one adjacent
storage-meter `actual` value. The meter and its explicitly bound EFM participant
were exactly equal in both reads bracketing each native request. Cached EFM
`Spwr` was also positive. Earlier E3 rounds observed matching negative and zero
signs. Selection used fresh control references and the verified firmware-bound
participant mapping, not display names or matching numbers.

This supports correspondence with K3's normalized **output** convention on that
installation. It does not identify the incoming physical value or prove an
inversion: the Config direction setting and source-field encoding remain
unverified. Sequential software observations also do not establish a physical
measurement instant, continuous sign transition, multiple-storage behavior or
a general aggregate boundary. The runtime `sign_convention` remains null.
Detailed values, identities, acquisition times, traces and preservation hashes
remain in the private evidence store; they are not public product examples.

## Meter-output prerequisite resolved separately

The 2026-10-19 analytical follow-up combines D1 physical pp.105–106
(`Meter.details.type`, its explicit missing-field default, and advertised state
channels) with the meter KB output tables. The implementation now exposes the
[documented meter output rules](meter-output-semantics.md) for unidirectional,
bidirectional and storage subtypes. `PwrN`/`powerName` is a power/flow display
label. The configurable direction on absolute Bi/storage meters concerns input
Pf; its unknown XML encoding does not block the fixed output convention.

This closes the meter-output question, not the native aggregate questions below.
The runtime subtype also does not prove the historical configuration, physical
medium, source wiring or measurement time. Native EFM and meter output rules
retain separate source references. No new aggregate decoder is authorized.

## Period field decisions

The following seven rows apply **independently to each** of day, week, month,
year and lifetime: 35 aggregate field/view combinations. All were numeric in E1.
D1 p.67 lists the fields and current-period selectors but does not bind a
quantity, unit, direction or currency to each aggregate field. K1's named block
outputs and formulas are contextual documentation, not native field aliases.

| Field in each period view | Documentation / independently observed metadata | Supported encoding / decision | Precise missing prerequisite |
| --- | --- | --- | --- |
| Export | D1 lists Export; K1 documents Ed, a daily block output. E2 totalFormat exists. | **Insufficient evidence:** raw numeric Export; quantity/unit/direction unknown. | Explicit aggregate Export quantity/unit and export-boundary contract tied to configured sources. No Ed alias or totalNeg mapping established. |
| Import | D1 lists Import; K1 documents Id. E2 totalFormat exists. | **Insufficient evidence:** raw numeric Import; quantity/unit/direction unknown. | Explicit aggregate Import quantity/unit and import-boundary contract tied to configured sources. No Id alias or total mapping established. |
| Production | D1 lists Production; K1 documents Pd. | **Insufficient evidence:** raw numeric Production; quantity/unit/direction unknown. | Aggregate quantity/unit and included production/reverse-flow boundary for each view; no Pd alias. |
| Charge | D1 lists Charge; K3 documents storage meter channels. | **Insufficient evidence:** raw numeric Charge; quantity/unit/direction unknown. | Aggregate charge quantity/unit/direction and configured storage boundary; no transfer from a meter's reading or totalNeg. |
| Discharge | D1 lists Discharge; K3 documents storage meter channels. | **Insufficient evidence:** raw numeric Discharge; quantity/unit/direction unknown. | Aggregate discharge quantity/unit/direction and configured storage boundary; no transfer from a meter's reading or total. |
| Consumption | D1 lists Consumption; K1 documents Cd. | **Insufficient evidence:** raw numeric Consumption; quantity/unit/direction unknown. | Aggregate quantity/unit and consumption boundary, including residual/storage treatment; no Cd alias or balance formula. |
| Income | D1 lists Income; K1 describes Yd and export/import price parameters. | **Insufficient evidence:** raw numeric Income; quantity/unit/currency unknown. | Explicit native Income meaning, currency source and applicability, time accumulation and tariff/source linkage. Income=Yd=OYt is not established. No tariff reconstruction. |

`totalFormat` is documented for `total/totalNeg` (D1 p.64). Its retained format in E2
does not prove that the seven aggregate period fields use that unit. Meter KB
examples also allow different media and independently configured power/reading
units; they do not supply the missing aggregate mapping.

### View, boundary and completion decisions

These decisions qualify all seven fields in the corresponding view. They do not
promote any field to a known quantity or unit.

| View | Documented selector / observed shape | Confirmed existing encoding | Unknown / precise missing prerequisite |
| --- | --- | --- | --- |
| day | D1 p.67: current day; E1/E2 seven fields | current_calendar_period; period_completion=running | Start/end/timezone and reset require an explicit aggregate clock/boundary contract and matching source/configuration evidence. Not yesterday. |
| week | D1 p.67: current week; E1/E2 seven fields | current_calendar_period; period_completion=running | Same clock/reset evidence; week start and calendar convention not independently established. |
| month | D1 p.67: current month; E1/E2 seven fields | current_calendar_period; period_completion=running | Explicit month/timezone/reset contract and matching evidence absent. |
| year | D1 p.67: current year; E1/E2 seven fields | current_calendar_period; period_completion=running | Explicit year/timezone/reset contract and matching evidence absent. |
| lifetime | D1 p.67: total/lifetime; E1/E2 seven fields | lifetime_accumulator; period_completion=unknown | Initial epoch, reset/reconfiguration and inclusion rules need a firmware-bound contract and independent source/configuration evidence. Not guaranteed since installation. |

For every period: `period_start=null`, `period_end=null`, `timezone=null`,
`period_boundaries=unknown`. “Running” identifies the current native calendar
view; it does not prove continuous recording, full coverage or a common physical
measurement instant. No historic date selector is introduced.

## Measurement timestamp and freshness decision

**Insufficient evidence** for every view: no independently proven physical
measurement timestamp was retained. D1's aggregate command table provides no
timestamp mapping. E1 response receipt and E2 `retrieved_at` prove retrieval
only. Keep `observation_freshness=unknown`, `retrieval_freshness=current` and
the physical-observation-time limitation. A configuration modification marker,
transport receipt, successful request or plausible value is not a measurement
timestamp. A new interpretation requires an explicit source timestamp/clock
contract and caller-authenticated evidence tying it to these exact aggregates.

## Result and verification boundary

The fixed matrix is complete with confirmed-existing and insufficient-evidence
decisions. There is no proven additive extension. Raw values, missing-field
handling, schemas, Explorer, bundled skill, authorization, source request counts,
timeouts and transport budgets remain unchanged. Node signs, meter KB meanings
and residual display configuration are recorded as research context, not decoded
into aggregate fields. No new target, firmware or compatibility claim is made.

This documentation-only result needs consistency review and CI, not deployment,
browser acceptance or new device acceptance under the change-driven test
strategy. E1/E2 remain historical source evidence. If later evidence permits a
behavioral extension, it requires its own narrow reviewed change, regression and
negative tests, synchronized contract/documentation and matching device acceptance.
Broader topology/transformations remain #357; manager acceptance #533, optional
non-admin disclosure #535, weather/PV planning #509/#510 and performance #501
remain separate.
