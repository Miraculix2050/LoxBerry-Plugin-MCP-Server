# Support matrix

- **Status:** Current pre-release support statement.
- **Evidence:** [Current evidence](../evidence/current-evidence.md) distinguishes implemented, automated and hardware-confirmed behavior.

## Platforms and Miniservers

Structured weather history is independently opt-in and uses the shared SQLite v8
store/subscription. Current and forecast provenance, reception time and point time
remain separate. Numeric weather units/radiation encoding are unverified;
recording does not prove continuous observation, backfill, comparable days or a
PV forecast. A separate [qualitative comparable-day method](../user/comparable-days.en.md)
uses an explicitly owner-assumed class mapping and does not qualify numerical
irradiance, normalized yield or self-consumption. See [weather history](../user/weather-history.en.md) for read limits
and the v7 backup required for rollback to older code. Device evidence is scoped
to the corresponding recorded target acceptance; fixtures are not device proof.

| Component | Status | Scope |
| --- | --- | --- |
| LoxBerry 4.0.0.14, Debian 13, aarch64 | hardware confirmed | native package, service, HTTPS transport and offline wheels |
| LoxBerry 3 and older Debian bases | unsupported | outside the supported baseline |
| Gen. 1, firmware 17.1.7.27 | hardware confirmed | local HTTP/WS, token authentication, visibility and states |
| Older Gen. 1 firmware | experimental | no compatibility promise |
| Gen. 2 / Compact | experimental | HTTPS/WSS fail-closed behavior is automated; real compatibility needs an independent report |

## MCP clients

| Client | Status | Known limit |
| --- | --- | --- |
| Claude Desktop `1.24012.9` with `mcp-remote` `0.1.38` | hardware confirmed | local bridge behavior only |
| Codex CLI `0.146.0` | hardware confirmed | client refresh and logout limitations do not weaken server audience or revocation rules |

## Product limits

- Local solar windows support only the explicitly confirmed Weather4Lox
  VisualCrossing v1.0 hourly point source with independent LoxBerry read approval.
  No arbitrary providers, Lux conversion, irradiance-energy integration, PV yield,
  surplus or admissible load schedule are qualified. Automated source fixtures
  establish adapter behavior; production read-only source inspection is distinct
  from test-target/browser acceptance and does not establish all installations.

- `loxone_get_system_messages` is experimental and version-bound to firmware
  17.2.8.28. Its source contract was observed on Gen. 1; plugin/browser acceptance
  must be recorded separately. No Gen. 2 or exhaustive retained-history promise.

- One Miniserver target is supported.
- External or cloud-hosted MCP access is unsupported.
- Read-only tools are available within the signed-in Loxone user's visibility.
- `loxone_get_state_semantics` adds fixture-tested exact-state evidence for
  existing Irrigation/AlarmClock decoders, `value` format metadata on
  InfoOnlyAnalog/UpDownAnalog/Slider, UpDownAnalog ranges and StatusMonitor
  `inputStates` position-stable tuple decoding and configured-state counts. Other meanings remain unknown;
  this does not establish new firmware or control-family hardware compatibility.
- History, diagnostics and cache operation require their documented scopes and local approvals.
- Normalized `Meter` output conventions are fixture-tested for documented
  unidirectional, bidirectional and storage subtypes (including the documented
  missing-subtype default). State and compatible StatisticV2 series share the
  rules; unknown/legacy metadata remains unenriched. See
  [meter output semantics](meter-output-semantics.md). This establishes no new
  target compatibility or native EFM aggregate contract.
- Control is Gen.-1-only, default-disabled, type-specific and limited to visible operable controls.
- Only actions explicitly identified as hardware confirmed in the user capability documentation are hardware promises; other implemented actions remain unverified.

See [Gen. 2 compatibility testing](gen2-compatibility-test.md) and the [user capability overview](../user/capabilities.en.md).

- `loxone_get_active_alerts` evaluates documented, fixture-tested AalEmergency,
  AalSmartAlarm, AlarmChain and SmokeAlarm rules (Structure File 17.1), plus Alarm.level
  stages (Structure File 17.0) with owner-approved zero-as-inactive assumption
  (#346, 11 October 2026); SmokeAlarm zero uses the owner-approved assumption
  from #347. No active case has
  hardware observation evidence. This adds no hardware-family or firmware compatibility promise. Known
  unsupported monitor/alarm families make coverage partial; this is no safety
  certification or alarm notification service.


- Confirmed load constraints and observed-cycle descriptions (#440): additive
  profile/Admin declarations and historical operating_phases detail. Complete
  activity edges and interval-energy profiles are separate from user-confirmed
  program identity, native lock observation and future scheduling. Unknown locks
  are never inferred clear; no operation permission or saving claim is added.

- Conditional retrospective shifts (#440): existing history analysis checks
  complete cycles/hourly energy and declared windows against one shared measured
  export budget. Missing historical native locks remain a blocking qualification
  condition in every example. Automated fixtures establish arithmetic/contract
  gates only; no admissible device schedule, PV attribution or saving claim.

- Accepted KNX Admin project-bound application and ETS preview handoff (#458):
  independently authenticated Admin helper and fresh authorized project evidence,
  with cancellation-safe bounded workers. Fixture coverage is not installed-device
  acceptance or actual ETS import evidence. No new firmware compatibility claim.

- Native PVPF (#510): typed hourly energy and state semantics follow Structure File
  17.1 pp.115–116. Availability and prediction age are explicit; automated fixtures
  do not establish an available real Weather Service or forecast accuracy.

- Conditional future planning (#510): native PVPF hours, confirmed complete cycles,
  explicit base/storage scenarios and shared hourly budget. Unknown future native
  constraints remain conditions. Automated evidence is separate from positive
  source/device acceptance and measured forecast accuracy.


- Request-local energy context (#556): one budget per request; up to four
  explicitly confirmed disjoint PVPFs; optional profile references or declared
  real/hypothetical cycles. Native membership is server-derived and physical
  boundaries remain explicit. Multiple independent plant fixtures establish
  isolation/arithmetic only, not real multi-plant or new firmware compatibility.
  On 25 October 2026 the owner approved #510 software/technical closeout, including
  a real native PVPF read with 72 available hours on Loxberry-Test. The comparison
  with three production intervals measured after forecast capture and real
  single/competing-consumer planning were not performed and are no longer closeout
  gates. Runtime qualification and conditional semantics remain unchanged;
  empirical forecast accuracy, measured savings and operating permission are not
  established. #440 retains its separate retrospective technical closeout.


### EFM self-consumption statistics

The exact accumulated StatisticV2 `totalSelfConsumption` Wh/kWh channel has a
bounded hourly decoder and regression coverage. Plant association remains an
explicit owner declaration; output is a native EFM calculation, not independent
physical metering. Unknown EFM channels, units and legacy clocks remain unqualified.
A representative native hourly source read does not establish positive real
weather-peer, all-firmware or multi-installation acceptance. The owner-approved
#439/#509 technical closeout combines source-read evidence and model tests; it
does not claim empirical plant validation (see [criteria](solar-history-acceptance.en.md)).
