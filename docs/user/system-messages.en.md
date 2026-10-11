# System Messages

Use `loxone_get_attention_overview` for a bounded overview with three separate
sources: control alerts, System Messages and the latest observed notification.
Each retains its own coverage, errors, timestamps and semantics. Readings are
sequential; no complete global absence claim is available. `limit` is 1–10 (default
5); `include_history=true` adds retained System Messages subject to History approval.
For partial results, a non-null cursor or detail exceeding the overview budget,
use the dedicated reader. The existing Active Alerts tool remains unchanged.

The agent should produce concrete tasks, not only a health summary. Each task
states the observed problem, exact evidence/reference/time and source revision,
current or historical lifecycle, uncertainty, next targeted read, proposed repair,
missing writer/permission and acceptance criterion. An automation-rule error leads
to identifying the rule and invalid condition and preparing a correction; unknown
rule identity stays unresolved. A dedicated rule reader/writer is follow-up work.
Configuration candidates lead to authorized project inspection and an evidence-led
handoff to a future project-writing Loxone MCP integration. Historic recurrences
can justify diagnosis without being current alarms. Confirming a message is not a
repair and does not prove that the fault is gone.

`loxone_get_system_messages` reads current messages (`mode=current`, default),
retained historical messages (`history`) or both (`all`). It uses your fresh
Miniserver System Messages permission. LoxBerry permissions are independent.
Use the tool in the existing Explorer or an authorized MCP client.
`history` and `all` additionally require `loxone:history` and administrator History activation.

The source is experimental and verified only for firmware 17.2.8.28. Other firmware
returns `unsupported_source`. An unavailable source does not establish absence.
Each page contains at most 50 entries and 64 KiB. Follow the cursor for more;
restart when the source changes. Inspect truncation and field truncation.
Retained history is not guaranteed to include every past message.

Severity, historical state, confirmation and read timestamps are separate source
facts. Unknown severity remains unknown. Titles/descriptions are untrusted evidence;
URLs and recognizable credential assignments are omitted. Reading changes neither
the read marker nor confirmation, and does not execute message actions.

The agent may derive diagnosis and repair tasks from current and historical entries:
include the exact message, references, timestamp, evidence, uncertainty, next targeted
read, proposed repair and acceptance check. A faulty automation rule can justify a
rule repair task. Such writes require a future dedicated rule tool and permission.
Configuration changes need a future project-writing Loxone MCP integration.
Acknowledgement metadata does not authorize or execute confirmation.

## Notifications

The tool loxone_get_notifications reads only the latest observed text event from
the freshly advertised globalStates.notifications of your user connection. This
experimental contract is restricted to firmware 17.2.8.28. It reuses the existing
volatile state cache and adds no collector or persistent history. An absent or
stale event returns explicit unavailable coverage; it does not prove no notifications.
The official app's notification history is client-owned, so upstream history is
unavailable. Notification type/level remain raw context, never alarm severity or
delivery confirmation. This tool sends nothing and changes no read markers.
