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

The server always advertises every known OAuth scope. The checkboxes in the
plugin configuration do not change this list; they are global capability gates.
The permissions actually granted to a sign-in are selected only in the OAuth
consent dialog after Loxone authentication.

The currently known ChatGPT/Codex desktop app prefers the server-advertised
scopes and may therefore request all five during a new sign-in:

```text
loxone:read loxone:history loxone:control loxberry:read loxberry:operate
```

This does not mean that every permission is granted or administratively
enabled. Review the browser selection during every new sign-in; exact client
behavior may change with an app version.

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

## Understand permissions and administrator approval

The consent dialog shows required `loxone:read`. Every other scope is an
optional checkbox:

| Scope | Effect | Additional approval |
| --- | --- | --- |
| `loxone:read` | Read visible Loxone structure and current states | always active |
| `loxone:history` | Read history and statistics | global administrator checkbox |
| `loxone:control` | Operate supported visible controls with bounded actions | global administrator checkbox |
| `loxberry:read` | Read LoxBerry and plugin diagnostics | global and local administrator approval |
| `loxberry:operate` | Clear the plugin-owned statistics cache | `loxone:history` plus global and local administrator approval |

`loxberry:operate` can be confirmed only together with `loxone:history`. For
read-only access, leave every optional checkbox clear.

OAuth consent and administrator approval are separate checks: an optional scope
may already be present in the token while its capability has not yet been
enabled in the plugin configuration or locally approved. The affected tool then
fails closed with `permission_denied`. No additional permission selection in
the desktop app or Tool Explorer is required.

Loxone control remains restricted by visible controls, documented actions, and
the authenticated Loxone user's permissions. LoxBerry approvals are bound to
the exact OAuth client, Loxone identity, and Miniserver. Disabling an optional
global capability revokes matching sessions; a new permission is never silently
added to an existing session.

## Troubleshooting

- **Server is not found:** Check that **Streamable HTTP** is selected and that
  the complete URL ends with `/plugins/mcpserver/mcp`.
- **Certificate error:** Open the LoxBerry address in a browser and resolve the
  certificate warning first. Never disable certificate validation.
- **Authenticate is missing:** Check that the server is saved and reachable,
  then open its entry again.
- **Unexpected write access:** Revoke the session and authenticate again without
  selecting `loxone:control` or `loxberry:operate`.
- **`permission_denied` despite a confirmed scope:** Enable the corresponding
  global capability. For `loxberry:read` and `loxberry:operate`, the
  administrator must also approve the exact sign-in locally.
- **Connection remains pending:** Restart the desktop app and then inspect the
  server through `/mcp`.

Further reading: [Official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
