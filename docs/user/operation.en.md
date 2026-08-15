# Operation

[Deutsch](operation.de.md)

## Updates

The Plugin Manager discovers regular updates through the stable release source. Prereleases are offered only when explicitly allowed there. Keep a working earlier package before updating a prerelease so that you have a recovery path.

## Sessions and approvals

Under **Clients and sessions**, administrators can inspect and revoke sessions and local diagnostic or operate approvals. Revocation ends matching sessions.

## Tool Explorer

The [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) is a local administrative test client. It signs in with a Loxone user and receives no rights from the LoxBerry admin session. Replace `loxberry` in the link with your installation's hostname when necessary. Mutating calls require confirmation before sending.
RFC-3339 time fields are shown as local date/time fields and sent as UTC.
Time-range shortcuts and references from earlier results simplify common queries;
technical page parameters are available under **Advanced options**.

MCP clients receive the tool descriptions published by the specific installation, including their input and output schemas, through the MCP method `tools/list`. The Tool Explorer reads and visualizes that exact response. **Help** also provides a static HTML reference for the complete tool contract of this plugin version and the same data as a JSON download.

Next: [Troubleshooting](troubleshooting.en.md).
