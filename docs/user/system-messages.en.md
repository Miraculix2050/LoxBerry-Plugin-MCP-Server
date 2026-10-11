# System Messages

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
