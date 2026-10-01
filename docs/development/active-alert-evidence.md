# Active visible alert evidence gate (#167)

Source: [official Structure File 17.1, dated 6 August 2026](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf).

| Family | Evidence and decision | Automated evidence |
| --- | --- | --- |
| AalEmergency | Page 26 explicitly defines status 0/1/2/3; only 1 is an active alarm. Approved for V1; no companion, acknowledgement or severity claim. | Table-driven synthetic contract fixtures for all codes, malformed and unavailable/stale observations. |
| SmokeAlarm | Pages 125–126 define active levels 1/2, test alarm and signal suppression, but do not explicitly establish inactive level 0 in the examined section. Deferred pending complete inactive/test/acknowledgement evidence. | No adapter compatibility claim. |
| StatusMonitor | Pages 130–131 define comma-separated position-bound IDs and configured priorities, not an alarm predicate. Deferred. | Existing metadata tests do not establish alert activity. |
| WindowMonitor | Pages 152–153 define opening bitmasks; an open window is not inherently an alarm. Deferred. | Existing contact analysis does not establish alert activity. |
| AalSmartAlarm, Alarm, AlarmChain | Known candidates outside the first reviewed adapter. Explicit unsupported coverage. | No adapter compatibility claim. |

Document version is provenance, not the connected firmware version. No new
hardware/control-family support claim follows from synthetic fixtures. The
read-only target smoke verifies deployment/catalog/integration; no real alarm is
triggered and active values remain fixture evidence unless independently observed.

The old #167 suggestion to begin with StatusMonitor is superseded by this gate.
#166 and #168 are implemented foundations; #123 is closed as not planned.
