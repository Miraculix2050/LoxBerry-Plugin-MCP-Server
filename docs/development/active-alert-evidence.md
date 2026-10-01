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
| StatusMonitor.inputStates | Comma-separated position-bound configured IDs. | Deferred: IDs/name/priority/color provide no source alarm predicate. No configurable selection policy. [#348](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/348). | 17.1 pp.130–131; existing metadata tests do not prove alert activity. |
| WindowMonitor.windowStates | Comma-separated opening/locking bitmasks, offline/unknown. | Deferred: open/tilted/unlocked are not intrinsically alarms. [#349](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/349). | 17.1 pp.152–153; contact analysis is not an alarm rule. |

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
