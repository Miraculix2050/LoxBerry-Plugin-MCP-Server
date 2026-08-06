# Set up the ChatGPT/Codex desktop app

The ChatGPT desktop app can use the LoxBerry MCP Server directly through
Streamable HTTP and OAuth. Unlike Claude Desktop, this setup needs neither
Node.js nor `npx` nor a local bridge.

## Preparation

Before setup, you need:

- an installed, configured, and enabled LoxBerry MCP Server plugin;
- the HTTPS address of your LoxBerry, reachable from the computer;
- an HTTPS certificate that the computer trusts;
- the complete MCP address. It combines the LoxBerry address and the fixed
  `/plugins/mcpserver/mcp` path, for example:

  ```text
  https://loxberry.local/plugins/mcpserver/mcp
  ```

Use the address of the **LoxBerry**, not the Loxone Miniserver address. Never put
credentials in the URL.

Also decide which permissions are needed before authentication:

- When **Read only** is selected in the plugin, the server offers only
  `loxone:read`.
- When **Read and switch** is selected, the server also advertises
  `loxone:control`. The desktop app prefers the server-advertised scopes and
  therefore requests both permissions during a new login.

## Add the MCP server

1. Open **Settings** in the ChatGPT desktop app.
2. Open **Plugins > MCP**. Depending on the app version, this section may be
   named **MCP servers** directly.
3. Select **Add MCP server**.
4. Enter a clear name, for example `LoxBerry MCP Server`.
5. Explicitly select **Streamable HTTP** as the type.
6. Enter the complete MCP address, for example:

   ```text
   https://loxberry.local/plugins/mcpserver/mcp
   ```

7. Select **Save**.
8. When the app has found the server, select **Authenticate**.
9. The LoxBerry MCP Server consent page opens in the browser. Check the displayed
   permissions and approve the login only when they match your intended access.
10. Return to the desktop app. If the app offers or requires a restart, perform
    it.

The server should then appear as connected. Use `/mcp` in the desktop app to
inspect connected MCP servers.

## Understand read and write access

When **Read and switch** is selected in the plugin, the desktop app requests
both scopes during authentication:

```text
loxone:read loxone:control
```

The consent dialog shows required **Read access** and optional **Loxone
control** as a checkbox. Only when control is selected and confirmed are the six
read tools and the narrowly limited control tool available. The write tool can
only operate permitted, visible Gen. 1 controls with actions advertised by
`loxone_describe_control`. The authenticated
Loxone user's permissions further restrict what is actually possible.

Write access is not silently added later: it must be selected and approved on
the browser consent page. For read-only access, leave the optional checkbox
clear.

If the setting is later changed to **Read only**, the plugin revokes existing
control sessions. Authenticate the desktop app again to obtain a read-only
session.

## Troubleshooting

- **Server is not found:** Check that **Streamable HTTP** is selected and that
  the complete URL ends with `/plugins/mcpserver/mcp`.
- **Certificate error:** Open the LoxBerry address in a browser and resolve the
  certificate warning first. Never disable certificate validation.
- **Authenticate is missing:** Check that the server is saved and reachable,
  then open its entry again.
- **Unexpected write access:** Revoke the session and authenticate again without
  selecting the optional control permission.
- **Connection remains pending:** Restart the desktop app and then inspect the
  server through `/mcp`.

Further reading: [Official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
