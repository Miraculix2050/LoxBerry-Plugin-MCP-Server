# Operation

[Deutsch](operation.de.md)

## Updates

The Plugin Manager discovers regular updates through the stable release source. Prereleases are offered only when explicitly allowed there. Keep a working earlier package before updating a prerelease so that you have a recovery path.

## Sessions and approvals

Under **Clients and sessions**, administrators can inspect and revoke sessions and local diagnostic or operate approvals. On narrow screens, all fields and actions appear together under each session or approval. While a revocation is running, the affected row is dimmed. Revoking an approval ends matching sessions. Disconnecting the Tool Explorer revokes only its OAuth session; its local approval can reactivate for the same Loxone identity and Miniserver until the displayed deadline. The inactive retention is configurable from 1 to 720 hours and defaults to 72 hours.

Session revocation blocks MCP access immediately. Loxone token cleanup then runs in the background. The section shows aggregate warnings when cleanup is pending, the Miniserver blocks sign-ins, or remote revocation remains unconfirmed after bounded attempts. For an unconfirmed result, an administrator can inspect Loxone user management; the warning does not identify a user.

The emergency-stop option list loads directly from the Miniserver using the credentials configured in LoxBerry. This can take several seconds. If a Miniserver sign-in block prevents the options from loading, the page shows the earliest retry time. **Try again** becomes available afterward and makes at most one coordinated sign-in attempt. Loading errors preserve the saved emergency-stop selection.
If another sign-in is merely in progress, the page instead shows a short retry time. The server-rendered fallback also displays aggregate cleanup warnings.

## Diagnostics and logs

The service log remains directly available under **Diagnostics and logs**. The LoxBerry LogManager lists native plugin logs after an actual Admin event has been recorded and registered. The Admin page distinguishes an empty LogManager list from an unavailable LogManager and a failed refresh request. Opening the log list does not create a log entry.

## Tool Explorer

The [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) is a local administrative test client. It signs in with a Loxone user and receives no rights from the LoxBerry admin session. Replace `loxberry` in the link with your installation's hostname when necessary. Mutating calls require confirmation before sending.
After sign-in, the connection card shows which OAuth scopes the session actually granted. Scopes marked **Not granted** were not granted to this session; local LoxBerry approvals and other authorization checks remain separate. The list clears when the session ends.
The connection card starts open so sign-in is immediately available. It can be collapsed after sign-in to make more room for the tool workspace. Its OAuth scope list starts collapsed, and the setup and schema-reference links remain visible above the card. Both disclosure choices persist across reloads and new tabs in the same browser.
RFC-3339 time fields are shown as local date/time fields and sent as UTC.
Time-range shortcuts and references from earlier results simplify common queries;
technical page parameters are available under **Advanced options**.
Search the available tools by name or description and combine the search with
one or more groups in the expandable filter. **All** clears the group selection.
Filtering is local and keeps the selected tool and
its unsent draft.
For the selected tool, the Explorer shows its read/write classification and
explicit MCP hints. Incomplete or contradictory metadata is conservatively
marked **May write**. Hints are not a safety guarantee; the complete annotations
are available under **Technical MCP metadata**.
The summary also lists required OAuth scopes for known tools. The scopes actually
granted to this session remain visible in the connection card. Long tool
descriptions can be expanded from the compact summary.
Results and history entries appear as an expandable tree. Large branches show
100 entries at a time; **Show more** loads the next batch. The disclosure arrow
opens a branch, while the separate value button reuses its unchanged value and path.
The complete response remains available under **JSON** and through **Copy JSON**.

MCP clients receive the tool descriptions published by the specific installation, including their input and output schemas, through the MCP method `tools/list`. The Tool Explorer reads and visualizes that exact response. **Help** also provides a static HTML reference for the complete tool contract of this plugin version and the same data as a JSON download.

Next: [Troubleshooting](troubleshooting.en.md).
