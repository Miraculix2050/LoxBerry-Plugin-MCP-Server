# Message Center source contract

Issue #366, experimental adapter v1. Source verification: 11 October 2026,
configured test Miniserver firmware **17.2.8.28**, Gen. 1 encrypted WebSocket.
No compatibility claim for another firmware or Gen. 2 device.

The official installed web app supplies these contracts:

| Source | Verified behavior | SHA-256 |
| --- | --- | --- |
| `MessageCenterHelper.js` | Severity 1 info, 2 warning, 3 important, 4 critical; action 1005 acknowledgement | `09334c36fe861dd9d482660d471d97fdfb734ac27e59cecc98db14ddbb66378b` |
| `AppHub.js`, MessageCenterExt | Fresh `messageCenter.uuidAction`, `getEntries/2`, JSON in LL.value | `dd7cd47df998c4e94f4a402d08eeccfbcec5f57e5615933294cb4144315b5e29` |
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
