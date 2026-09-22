# Operation

[Deutsch](operation.de.md)

## Updates

The Plugin Manager discovers regular updates through the stable release source. Prereleases are offered only when explicitly allowed there. Keep a working earlier package before updating a prerelease so that you have a recovery path.

## Sessions and approvals

Under **Clients and sessions**, administrators can inspect and revoke sessions and local diagnostic or operate approvals. Revoking an approval ends matching sessions. Disconnecting the Tool Explorer revokes only its OAuth session; its local approval can reactivate for the same Loxone identity and Miniserver until the displayed deadline. The inactive retention is configurable from 1 to 720 hours and defaults to 72 hours.

Session revocation blocks MCP access immediately. Loxone token cleanup then runs in the background. The section shows aggregate warnings when cleanup is pending, the Miniserver blocks sign-ins, or remote revocation remains unconfirmed after bounded attempts. For an unconfirmed result, an administrator can inspect Loxone user management; the warning does not identify a user.

If a Miniserver sign-in block prevents emergency-stop options from loading, the page shows the earliest retry time. **Try again** becomes available afterward and makes at most one coordinated sign-in attempt. Loading errors preserve the saved emergency-stop selection.

## Tool Explorer

The [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) is a local administrative test client. It signs in with a Loxone user and receives no rights from the LoxBerry admin session. Replace `loxberry` in the link with your installation's hostname when necessary. Mutating calls require confirmation before sending.
RFC-3339 time fields are shown as local date/time fields and sent as UTC.
Time-range shortcuts and references from earlier results simplify common queries;
technical page parameters are available under **Advanced options**.

MCP clients receive the tool descriptions published by the specific installation, including their input and output schemas, through the MCP method `tools/list`. The Tool Explorer reads and visualizes that exact response. **Help** also provides a static HTML reference for the complete tool contract of this plugin version and the same data as a JSON download.

Next: [Troubleshooting](troubleshooting.en.md).
