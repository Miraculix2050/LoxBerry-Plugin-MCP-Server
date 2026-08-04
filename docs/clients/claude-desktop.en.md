# Connect Claude Desktop

This guide connects Claude Desktop on Windows to the LoxBerry MCP Server. Claude
uses a small local bridge, so the connection to the LoxBerry stays on the local
network instead of using a Claude cloud connector.

## Before you start

- The plugin is configured and enabled, and its connection test succeeds.
- Claude Desktop is installed.
- Node.js with `npx` is installed. If needed, open PowerShell and run
  `npx --version`. If the command is unavailable, install a current LTS release
  of [Node.js](https://nodejs.org/) first. On first use, `npx` downloads the
  pinned bridge version once from the npm registry.
- Have the LoxBerry HTTPS address entered in the plugin ready. Append
  `/plugins/mcpserver/mcp` to obtain the MCP address. The LoxBerry does not need
  to be published on the Internet for this setup.

User names, passwords, and tokens do **not** belong in the configuration file.
Authentication takes place securely in the browser later.

## Add the MCP server

1. In Claude Desktop, open **Settings → Developer** and select **Edit Config**.
2. Add the `loxberry-mcp` entry to the file that Claude opens. Replace only the
   example address with your complete MCP address:

   ```json
   {
     "mcpServers": {
       "loxberry-mcp": {
         "command": "npx",
         "args": [
           "-y",
           "mcp-remote@0.1.38",
           "https://loxberry.example/plugins/mcpserver/mcp",
           "--transport",
           "http-only"
         ]
       }
     }
   }
   ```

   Keep any existing MCP server entries and add only the new block. Make sure
   the result is valid JSON with the required commas.
3. Save the file and quit Claude Desktop completely. Then open Claude again.
4. On the first connection, authentication opens in your browser. Sign in with
   the dedicated Loxone user and approve access.
5. In a Claude chat, open **+ → Connectors**. `loxberry-mcp` and its tools must
   be available there. Connection status and MCP logs are also available under
   **Settings → Developer**.

## Troubleshooting

- **`npx` was not found:** Install Node.js and restart Claude afterwards.
- **The server is missing:** Open the configuration through Claude again. Check
  spelling, commas, and brackets. Then quit every Claude window before
  restarting the app.
- **Microsoft Store version:** Always use **Edit Config** in Claude. This version
  may store its active file in a Store profile instead of the classic
  `%APPDATA%` directory.
- **No login or connection:** Check that the MCP address reaches the LoxBerry in
  a browser and that the service is enabled in the plugin UI. Do not publish the
  address or error details without masking them.
- **Grant access again:** Revoke the affected session in the plugin UI and
  reconnect Claude.

Tested versions and known limitations are listed in the
[support matrix](../development/support-matrix.md).

Further reading: [Claude documentation for local MCP servers](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
and [`mcp-remote`](https://github.com/geelen/mcp-remote).
