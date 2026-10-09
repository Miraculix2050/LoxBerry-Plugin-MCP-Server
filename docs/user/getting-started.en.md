# Getting started

[Deutsch](getting-started.de.md)

## Requirements

- LoxBerry 4.0.0 or later.
- A dedicated Loxone user with the smallest practical rights.
- Gen. 1 through a local HTTP address; Gen. 2 through HTTPS with a trusted certificate.
- No credentials in URLs; HTTP Basic authentication is unsupported.

Loxone sockets disable automatic WebSocket transport pings and retain the Loxone
application keepalive with its timeout handling. On the investigated Gen. 1
target, transport pings triggered an unexpected gzip HTML file. Unexpected
structure files remain errors; they are neither decoded nor skipped. This finding
does not establish compatibility with other firmware or Miniserver generations.

## Installation and first connection

1. Install the release ZIP with the LoxBerry Plugin Manager.
2. Open **LoxBerry MCP Server** and enter the local LoxBerry HTTPS origin.
3. Select a configured Miniserver or enter its canonical endpoint.
4. Test the connection, enable **MCP access** and save the MCP configuration.
5. Connect a client to `https://<loxberry>/plugins/mcpserver/mcp` and complete OAuth login.

The HTTPS address must match the web-server certificate. **MCP access & HTTPS** provides copyable hostname and IP addresses.

Next: [Configuration](configuration.en.md) and [client setup](../clients/README.md).
