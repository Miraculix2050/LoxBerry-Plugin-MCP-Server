# Connect Claude Desktop

This guide connects Claude Desktop on Windows to the LoxBerry MCP Server. Claude
starts a small local bridge named `mcp-remote` on the computer. The connection
to the LoxBerry stays on the local network instead of using a Claude cloud
connector.

## Preparation

### 1. Prepare the plugin and MCP address

- The plugin is configured and enabled, and its connection test succeeds.
- Use the **LoxBerry** HTTPS address entered in the plugin, not the Miniserver
  address. Append `/plugins/mcpserver/mcp`, for example:

  ```text
  https://loxberry.example/plugins/mcpserver/mcp
  ```

- Do not publish this address on the Internet. The computer running Claude only
  needs to reach the LoxBerry on the local network.
- User names, passwords, and tokens do not belong in the MCP address or Claude
  configuration. Authentication takes place securely in the browser later.

### 2. Install Node.js and npx

`mcp-remote` is a Node.js program. `npx` is included with npm and starts such a
program without requiring you to locate its installation directory yourself.

1. Download the current **LTS release** from [Node.js](https://nodejs.org/).
2. Run the Windows installer with the suggested components and keep the option
   to add Node.js to `PATH` enabled. npm and `npx` are installed with Node.js;
   `npx` is not a separate download.
3. Close any open PowerShell windows. Open PowerShell again and verify the
   installation:

   ```powershell
   node --version
   npm.cmd --version
   npx.cmd --version
   ```

The `.cmd` form avoids possible PowerShell execution-policy errors involving the
also installed `.ps1` launchers. All three commands must print a version. On
first use by Claude, `npx` downloads
the pinned `mcp-remote@0.1.38` release once from the npm registry into the local
npm cache, which is normally reused for later starts.
The direct Node method described below is intended for deliberately permanent
offline preparation instead.

### 3. Find the correct npx path

The short `npx` command normally works in Claude. If Claude later reports that
`npx` was not found, obtain the complete path in PowerShell:

```powershell
where.exe npx
```

Use the returned line ending in `npx.cmd`. A typical result is
`C:\Program Files\nodejs\npx.cmd`. In JSON, each backslash in a complete Windows
path must be written twice:

```json
"command": "C:\\Program Files\\nodejs\\npx.cmd"
```

A Codex runtime path visible in a prepared test installation is **not** a
general Node.js path and must not be copied.

## Set up the read-only connection

1. In Claude Desktop, open **Settings → Developer** and select **Edit Config**.
   Always use this menu item so the Microsoft Store edition also opens its
   active file.
2. Add the `loxberry-mcp` entry. Replace only the example address with your
   complete MCP address:

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
         ],
         "env": {
           "NODE_USE_SYSTEM_CA": "1"
         }
       }
     }
   }
   ```

   `-y` answers the one-time npm prompt automatically. `NODE_USE_SYSTEM_CA`
   allows a current Node.js release to additionally use certificates trusted by
   Windows. It does not disable certificate validation.

   Keep any existing MCP server entries and add only the new block and required
   comma.
3. Save the file and quit Claude Desktop completely. Then open Claude again.
4. On the first connection, authentication opens in your browser. Sign in with
   the dedicated Loxone user and approve access.
5. In a Claude chat, open **+ → Connectors**. `loxberry-mcp` and its tools must
   be available. Status and MCP logs are also under **Settings → Developer**.

### Scope for read-only access

The six read tools do not require a scope in the Claude configuration. Without
an explicit value, the bridge requests only `loxone:read`. Verify this scope on
the browser consent page before approving access.

## Optional Loxone control

> **Experimental and not yet accepted with Claude:** The following workflow
> describes the expected setup, but a complete Claude test of registration,
> consent, and tool availability has not yet confirmed it. Read-only remains the
> documented and tested default.

This section applies only when **Read and switch** was deliberately selected
under **Miniserver access through the MCP server** in the plugin UI. It is
unnecessary for normal read access.

Control always requires both scopes:

```text
loxone:read loxone:control
```

`loxone:control` alone is invalid. Existing read-only sessions never receive the
additional scope automatically.

1. Select **Read and switch** in the plugin and save the configuration.
2. Create the local folder `C:\Users\Public\LoxBerryMCP` and add
   `loxberry-oauth-client.json` with this content:

   ```json
   {
     "scope": "loxone:read loxone:control"
   }
   ```

   The file contains no credentials but must still remain local.
3. At the end of the existing `args` list, after `"http-only"`, add:

   ```json
   "--static-oauth-client-metadata",
   "@C:\\Users\\Public\\LoxBerryMCP\\loxberry-oauth-client.json"
   ```

   The complete section then reads:

   ```json
   "args": [
     "-y",
     "mcp-remote@0.1.38",
     "https://loxberry.example/plugins/mcpserver/mcp",
     "--transport",
     "http-only",
     "--static-oauth-client-metadata",
     "@C:\\Users\\Public\\LoxBerryMCP\\loxberry-oauth-client.json"
   ]
   ```

4. Revoke the existing Claude session in the plugin UI. Quit Claude completely
   and start it again.
5. Sign in again. The consent page shows required **Read access** and optional
   **Loxone control**. Select the control checkbox only when this extension is
   intended. If the option is missing, do not use control and stay with the
   tested read-only setup.

If **Read only** is later selected in the plugin, sessions with
`loxone:control` are revoked. To return to read-only access, remove the two
metadata arguments and reconnect Claude.

## Why a prepared configuration may look different

A prepared or offline test installation may directly start a particular
`node.exe` and an already installed `proxy.js`. This is the same bridge without
package resolution through `npx`:

```text
npx mcp-remote@0.1.38 ...
        or
node.exe <local path to proxy.js> ...
```

After preparation, the direct method starts the bridge entirely from local
files, but it needs a separately installed package directory and permanently
valid absolute paths. For normal users, `npx` is therefore the simpler default.
Never copy user-specific Node, Codex, or project paths from another computer.

## Troubleshooting

- **`npx` was not found:** Check the three version commands and then use the
  complete `npx.cmd` path reported by `where.exe npx`.
- **The server is missing:** Open the configuration through Claude again. Check
  spelling, commas, and brackets, then restart every Claude process.
- **Certificate error:** The LoxBerry certificate must be valid for the address
  and trusted by Windows. `NODE_USE_SYSTEM_CA` bypasses neither expiry nor a
  hostname mismatch.
- **No login or connection:** Check the MCP address and service status in the
  plugin UI. Publish addresses and logs only after masking them.
- **Control tool is missing:** Check plugin activation, the metadata file, the
  control permission selected in the OAuth dialog, and revocation of the
  previous read-only session.

Tested versions and known limitations are listed in the
[support matrix](../development/support-matrix.md).

Further reading: [Claude documentation for local MCP servers](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop),
[npm documentation for `npx`](https://docs.npmjs.com/cli/commands/npx/), and
[`mcp-remote`](https://github.com/geelen/mcp-remote).
