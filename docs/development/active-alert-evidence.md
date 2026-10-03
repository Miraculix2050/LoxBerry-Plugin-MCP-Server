# Active visible alert evidence gate (#167, #344)

Source: [official Structure File 17.1, dated 6 August 2026](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf).
The full 168-page PDF was retrieved and the listed sections checked for #344;
17.0 pages 26–29 were compared with 17.1 pages 26–30.

| Exact family/state | Raw format and activity | Context and gate decision | Evidence |
| --- | --- | --- | --- |
| AalEmergency.status | Integral numeric 0/1/2/3; only 1 active. Boolean/string/other codes invalid. | Existing support; no test/acknowledgement/suppression inference. | 17.1 p.26; all codes and invalid/current/stale fixtures. |
| AalSmartAlarm.alarmLevel | Integral numeric 0 inactive, 1 immediate, 2 delayed. Boolean/string/other codes invalid. | Approved. No required companion. Optional isLocked/isLeaveActive (Boolean or numeric 0/1) and disableEndTime (finite nonnegative timestamp, capped at year 9999) never override level. startDrill/confirm commands expose no readable test/acknowledgement state: context remains unknown. alarmCause is last-cause text, not an activity predicate, and is not fetched. | 17.1 p.27, compared with 17.0 pp.26–27; all enum codes, invalid and optional-context fixtures. |
| AlarmChain.activeAlarmType | Integral numeric bitmap 0–15. Active iff any bit 2/4/8 set; bit 1 denotes acknowledgement. Zero and acknowledgement alone inactive. Boolean/string/fractional/unknown bits invalid. | Approved. No companion needed. Preserve active bits alongside acknowledgement; no guessed priority/danger. No readable test/suppression status. | 17.1 pp.29–30, compared with 17.0 p.29; exhaustive 16 combinations and invalid-format fixtures. |
| Alarm.level | Active levels 1–6 documented. Inactive level not explicitly defined. | Deferred: no complete inactive/acknowledgement mapping. armed, nextLevelAt, startTime are insufficient. [#346](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/346). | 17.1 pp.27–29; no adapter claim. |
| SmokeAlarm.level | Active levels 1/2 documented; inactive level absent. testAlarm is numeric 0/1; areAlarmSignalsOff concerns signal suppression. | Deferred: no complete inactive mapping. acousticAlarm=0 is not no alarm. [#347](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/347). | 17.1 pp.125–127 and official Fire/Water Alarm function description; no adapter claim. |
| StatusMonitor.inputStates | Comma-separated position-bound configured IDs. | Unsupported for alerts: configurable aggregation defines no intrinsic alarm predicate. [#348](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/348). | 17.1 pp.130–131; position-stable tuple/count decoding supports ordinary state reading, not alert activity. |
| WindowMonitor.windowStates | Comma-separated, position-bound integer bitmasks: 1 closed, 2 tilted, 4 open, 8 locked, 16 unlocked; no bits means unknown/offline. | Deferred: no source alarm activity predicate or test/reset/acknowledgement mapping established. Open/tilted/unlocked are not intrinsically alarms. [#349](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/349). | 17.1 pp.152–153; see the bounded source review below. |

All deferred candidates retain unsupported_family coverage and are not read by
this tool. Document version is provenance, not connected firmware compatibility.
No active cases have hardware-observation evidence. Read-only target smoke proves
deployment/catalog/integration only; no real alarm or drill is triggered.

Optional context records retain raw value and freshness even when unavailable,
stale or invalid; such values are not interpreted. Missing optional references
are omitted; corresponding decoded fields remain null. Primary-state quality
alone controls activity coverage for currently approved families. Active test
alarms, where the source reports them, remain visible and counted; absence of a
readable test state never means a confirmed non-test alarm.

The old #167 StatusMonitor-first suggestion is superseded by this gate.
#166 and #168 are implemented foundations; #123 is closed as not planned.

## WindowMonitor source review (#349)

Historical alarm-adapter review: #349 was reclassified on 2026-10-03 as ordinary
contact-state presentation. The missing alarm predicate blocks only an Active
Alerts adapter, not shared contact-state decoding or completion of #349. The
implemented read path uses these documented bits with separate observation and
mapping quality; the historical review below remains unchanged.

Checked on 2026-10-03 against master `0cf9240`. The official Structure File
17.1 (6 August 2026, 168 pages) was downloaded from the source URL above;
printed pages 152–153 and the immediately adjacent section boundaries were
checked. Download SHA-256:
`97bbc5ec79c8479c0f2f561a55780a764a518fe420d11fd2fc26979fc41e5f23`.
This review covers the WindowMonitor section, not the entire PDF.

| Source/field | Established evidence | Remaining alarm-semantic gap |
| --- | --- | --- |
| Structure File 17.1 pp.152–153: exact `WindowMonitor.windowStates` | A string of comma-separated integer bitmasks, indexed by `details.windows`. Bits describe opening and locking as listed above. The source describes no bits as unknown/offline but does not separately specify its textual encoding. | No active/inactive alarm predicate, alarm test state, reset or acknowledgement semantics documented in this section. |
| Structure File 17.1 p.153: `numOpen`, `numClosed`, `numTilted`, `numOffline`, `numLocked`, `numUnlocked` | Counts by contact condition; combined conditions are assigned to the worse condition (closed plus unlocked counts as unlocked). | Count precedence is not an alarm rule. |
| Official [Window and Door Monitor function description](https://www.loxone.com/dede/kb/fenster-tuer-ueberwachung/), unversioned web page: Inputs, Outputs, Parameters, Properties, Basic programming | `Hpos` uses 0 unknown/offline, 1 closed, 2 tilted, 3 open, 4 closed/unsecured, 5 closed/secured. Digital inputs describe open, tilt and secured conditions; outputs include condition counts and sensor text. | No documented mapping of these inputs/outputs to `windowStates`; no source alarm activity or test/reset/acknowledgement mapping established. Do not substitute Hpos enum values for state bitmasks. |

The function page's directly linked [API Commands](https://updatefiles.loxone.com/KnowledgeBase/Online/Common/Documents/API_Commands.pdf)
(13 January 2026, pp.1–7, checked on the same date) describes generic connector
commands, not WindowMonitor alarm semantics. No commands were executed.

Result: the evidence gate remains unmet. `WindowMonitor` remains a candidate
outside `ALERT_FAMILIES`, yielding `unsupported_family` without state reads.
Static inspection of `test_visibility_and_unsupported_families` confirms generic
unsupported-family/no-read coverage using StatusMonitor; it is not a dedicated
WindowMonitor fixture or hardware observation. No runtime or test changes were
made for this documentation review.

Open, tilted, unlocked, offline, invalid, missing or stale contact evidence does
not establish alarm activity or alarm freedom. This bounded review does not prove
the absence of physical alarms or of evidence in other sources. Issue #349 remains
open; resolver implementation and hardware observation remain separate work.
