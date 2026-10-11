# Message Center source contract

Issue #366, experimental adapter v1. Source verification: 11 October 2026,
configured test Miniserver firmware **17.2.8.28**, Gen. 1 encrypted WebSocket.
No compatibility claim for another firmware or Gen. 2 device.

The official installed web app supplies these contracts:

| Source | Verified behavior | SHA-256 |
| --- | --- | --- |
| `MessageCenterHelper.js` | Severity 1 info, 2 warning, 3 important, 4 critical; action 1005 acknowledgement | `09334c36fe861dd9d482660d471d97fdfb734ac27e59cecc98db14ddbb66378b` |
| `AppHub.js`, MessageCenterExt | Fresh `messageCenter[centerKey].uuidAction`, `getEntries/2`, JSON in LL.value | `dd7cd47df998c4e94f4a402d08eeccfbcec5f57e5615933294cb4144315b5e29` |
| `scripts4.js`, Commands | `jdev/sps/io/<center>/getEntries/2`; action/read/delete are separate commands | `64e36fbc462f808c3373f21cc822264d4dd493199569bc8c568ec9a7fc1e7245` |
| `shared-app.js`, MsPermission | `SYSTEM_MESSAGES=131072`; action detail independently checks requiredPermissions | `641e1241a305b477834f2b9989f2bfc48ae77286ba75203bab3e049c39b7c9de` |

A read-only source probe returned 15 retained entries. Observed entry fields:
entryUuid, eventId, sourceUuid, affectedUuids, severity, affectedName, title,
roomUuid, installationPlace, isHistoric, setHistoricAt, confirmedAt, timestamps,
readAt, isVisuLocked, actions, desc, helpLink. Timestamps are Unix seconds.
Native UUIDs use 8-4-4-16 hex groups. Probe and structure serials differ only in
MAC presentation. The implementation compares canonical validated MACs.
Private records and vendor bundles remain outside the repository; tests use
synthetic records. No acknowledgement/read/delete action was sent.

Require a fresh caller-filtered structure, the explicit permission bit and exactly
one valid Message Center. Reject unsupported firmware and source shape, oversized
sources (2 MiB/2000 entries), malformed/duplicate identifiers and malformed times.
Page at most 50 records and 64 KiB, with field truncation and identity/target/query/
source-revision authenticated cursors. No service-owned collector or persistent
history is introduced. Retained history has unknown retention coverage.
Historical modes also require `loxone:history` and administrator History activation.
The native response includes all retained entries; current-only calls filter historic
records before returning from the runtime. `source_total` describes the source collection.
The real structure uses a dictionary of centers, not a direct center object;
only one advertised dictionary entry is accepted. No first-of-many selection.
Known credential assignments and URLs are omitted from source text; text remains
untrusted evidence and is never logged. No HTML or action links are executed.

The official app's historical flag and historic timestamp are preserved separately
from confirmation and read timestamps. Do not synthesize missing lifecycle times.
The read adapter reports available acknowledgement metadata but performs no action.
Actual confirmation requires a separately reviewed capability and safe test entry.

For #367, the official app's NotificationExt reads `globalStates.notifications`
text events. Its history is client memory, cleared/rebuilt by connection lifecycle;
native push history belongs to the device. Neither establishes readable retained
upstream history. The fresh test structure advertises the notification state.
Notification source implementation needs a separate bounded latest-event contract;
never turn missing events into an empty exhaustive history.

## Controlled manual Okay comparison

On 11 October 2026 the owner clicked Okay for exactly the supplied test warning,
manual event 1121 / severity 2 / native action 1003. Before: isHistoric=false,
setHistoricAt=null, confirmedAt=null. After: the same entry remained retained,
isHistoric=true, setHistoricAt was set, confirmedAt remained null. This proves
historization for that observed contract, not acknowledgement, removal or a repair.
The native UI opens details with a separate readEntry command; readAt changes are
not an effect of our readers. A native automation warning of the same severity
advertised action 1005 instead, so severity does not determine the action.
The writer allowlist therefore covers 1005 and only the verified 1121 warning/1003.
Other manually triggered levels are not generalized from the warning observation.

Writer approval binds a bounded, expiring single-use preview to family, identity,
target, center, firmware and the raw selected entry metadata (excluding readAt).
Fresh enablement, OAuth scope, source permission and action-specific permission
checks precede dispatch in the same authenticated caller session. Post-action reads
return only the selected entry's lifecycle, not unrelated history. The audit uses
hashed identity/entry references and a correlation ID, never source text or credentials.
