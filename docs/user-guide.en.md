# LoxBerry MCP Server 0.2.0-alpha.1

## Requirements

- LoxBerry 4.0.0 or newer; the reference target is 4.0.0.14 on Debian 13/arm64.
- A dedicated Loxone user with the smallest practical read permissions and,
  when needed, narrowly assigned permissions for the supported controls.
- Gen. 1: a private local HTTP address. Gen. 2: a valid HTTPS address with a
  trusted certificate; currently experimental.
- Never put credentials in URLs. Basic Auth is unsupported.

## Installation and setup

Install the ZIP through the normal LoxBerry Plugin Manager. The package contains
all Python wheels for offline installation. Then open **LoxBerry MCP Server**:

1. Enter the LoxBerry's local HTTPS origin, for example
   `https://loxberry.local`.
2. Select one of the Miniservers configured in LoxBerry. Alternatively, select
   “Enter endpoint manually”; the canonical endpoint field is shown only in
   that mode. Use `http://192.168.1.20` for Gen. 1, or HTTPS only for Gen. 2.
   The selection does not copy credentials
   stored by LoxBerry.
3. Test the connection, enable the service and save.
4. Connect Codex CLI or Claude Desktop to
   `https://loxberry.local/plugins/mcpserver/mcp` and complete OAuth login.

The plugin UI help shows the complete MCP address once with the current
LoxBerry hostname and once with its local IP address. Both can be copied
directly. The hostname address is recommended because some MCP clients do not
accept a private IP address as an OAuth server. In every case, the web server
certificate must exactly match the address in use.

For Claude Desktop, follow the short
[step-by-step guide](clients/claude-desktop.en.md), which includes a ready-to-use
configuration example and troubleshooting help.

For the ChatGPT/Codex desktop app, the
[direct Streamable HTTP guide](clients/chatgpt-codex-desktop.en.md) explains URL
setup, browser authentication, and the requested read or write permissions. It
does not require a local Node.js bridge.

The six read-only Loxone data tools and the read-only skill-guide tool remain
enabled by default. Under **Miniserver access through the MCP server**, select
**Read and switch** to additionally operate supported Gen. 1 controls. A new
OAuth grant with `loxone:control` is then required. Switching back to **Read only** revokes
existing control sessions while read-only sessions remain valid. **Read and
switch** cannot be enabled for a Gen. 2/HTTPS target.

## Agent Skill

The server delivers the
[`using-loxberry-mcp`](../src/mcpserver/skills/using-loxberry-mcp/SKILL.md)
Agent Skill directly through MCP. It describes the safe workflow for discovery,
pagination, state reads, ambiguous names and explicitly requested control
operations. Machine-readable JSON schemas remain part of the MCP tools and are
not duplicated in the skill.

During connection setup, the server's MCP instructions point the client to
`skill://using-loxberry-mcp/SKILL.md`. Resource-capable clients can retrieve the
guide on demand. Clients that do not consume MCP resources can retrieve the same
document through the always-read-only `loxone_get_skill_guide` tool. This is
automatic delivery and discovery, not a silent client-side installation or
permanent prompt injection.

Local installation is optional. It lets Codex, Claude Code and other
Agent-Skills-compatible clients activate the skill natively from its
description, even before an MCP connection exists:

```bash
npx skills add Miraculix2050/LoxBerry-Plugin-MCP-Server --skill using-loxberry-mcp
```

Alternatively, copy the `using-loxberry-mcp` folder to
`~/.agents/skills/using-loxberry-mcp` for Codex or
`~/.claude/skills/using-loxberry-mcp` for Claude Code. In Claude Desktop and
Claude.ai, upload the same skill folder as a ZIP under **Customize > Skills**.
After local installation, the client automatically selects the skill for
matching LoxBerry or Loxone requests; `$using-loxberry-mcp` activates it
explicitly.

The consistent OAuth dialog shows required read access and, when requested by
the client and enabled in the plugin, optional Loxone control as a separate
choice. If control is not selected, only `loxone:read` is granted. After
confirmation, the LoxBerry hands off to the MCP client's registered callback.
The final message shown there belongs to the client, such as Claude Code, not
to the plugin.

Under **Clients and sessions**, the application name supplied by the client is
shown together with a short client instance identifier. This makes Codex,
Claude and the MCP Tool Explorer as well as multiple registrations of the same
application distinguishable. The application name is display-only metadata
supplied by the client; the client ID remains authoritative for technical
association and authorization.

Claude users can find the required scope configuration under
[Optional Loxone control](clients/claude-desktop.en.md#optional-loxone-control).

Save, connection test and session revocation remain usable without JavaScript.
With JavaScript, status, test and revocation update without a page navigation.

## Web server certificate

The certificate diagnostic only reads the system-wide LoxBerry HTTPS
certificate. It shows the issuer, expiry, DNS and IP SAN counts, and match
results for the configured MCP origin and current LoxBerry hostname. Individual
SAN names and private addresses are not included in the diagnostic export or
logs.

When the certificate was issued by the local LoxBerry CA and the installed Core
supports the required scripts, **Reissue web server certificate** can renew it.
The action requires the SecurePIN and a separate confirmation. It accepts no
free-form SANs; instead, LoxBerry Core creates the certificate from the current
hostname, reverse-DNS name, local IP and its standard loopback entries. The
existing LoxBerry CA is retained, so an already imported `cacert.cer` remains
valid. Apache restarts briefly and interrupts existing HTTPS connections.

The action remains disabled for an externally issued certificate. Success or
failure is recorded in the LoxBerry system log without the SecurePIN, private
keys or SAN values. The automatic Core check renews a certificate when it
expires or the local IP changes, but currently does not detect a hostname-only
change; the manual reissue covers that case.

## MCP Tool Explorer

**Open MCP Tool Explorer** opens a separate, admin-only browser page for the
local MCP endpoint. It signs in with a Loxone user like every other MCP client
and does not inherit permissions from the LoxBerry admin session.

After sign-in, the explorer lists the currently published tools with their
description, schema and read/write classification. Arguments can be edited in
an automatically generated form or its synchronized JSON representation.
Responses are shown as a selectable tree and raw JSON; a selected value can be
reused only in a schema-compatible parameter of a new call.
A single state UUID reused with `loxone_get_states` is automatically wrapped in
a one-item list.

Lists return at most the number of entries requested by `limit`. A non-empty
`next_cursor` indicates another page. **Fetch next page** requests it directly
with the same filters and limit. Alternatively, **Reuse value** prioritizes
mapping `next_cursor` to the same tool's `cursor` field and preserves the
previous arguments. A cursor is an opaque continuation value that must not be
edited and is valid only for the same tool and filters. The `control_type`
filter compares the complete Loxone type case-insensitively, so `Switch` and
`switch` are equivalent.

The MCP transcript shows sanitized JSON-RPC messages, status and duration.
Authorization headers, OAuth values and secret-shaped arguments are never shown.
Access tokens, drafts, results and the history bounded to 50 calls remain only in
tab memory. The refresh token is kept in that tab's `sessionStorage` so a reload
can restore the sign-in and rotate the token immediately. A browser tab lock
prevents automatic reuse in a duplicated tab. Other pages on the same LoxBerry
admin origin are not a security boundary and must come from trusted plugins.
Closing the tab normally
discards that local value, but the browser cannot reliably revoke the server
session immediately. Explorer sessions therefore expire after eight hours at the
latest. **Disconnect and revoke** ends the session immediately and remains the
reliable sign-out path before closing the tab.
The public OAuth client registration is likewise limited to the tab and at most
eight hours; stale registrations from earlier plugin versions are discarded and
registered again automatically.

The permissions dropdown defaults to **Read only**. **Read and control** is
selectable only when Loxone control is globally enabled and requires fresh consent for
`loxone:control`. Every state-changing call displays its tool and arguments
again and requires confirmation immediately before dispatch.
The link on the plugin main page uses the same address through which the plugin
page was opened. Through either the local IP address or the LoxBerry hostname,
the complete explorer flow uses that current HTTPS address. HTTP and hosts that
are not locally allowlisted remain fail-closed and offer a link to the configured
HTTPS address.

**Disconnect and revoke** ends the explorer session; after a browser crash or closing without
revocation it can still be revoked under **Clients and sessions**.

## Scope and operation

The alpha publishes six documented Loxone data tools, the read-only
`loxone_get_skill_guide`, and optionally `loxone_operate_control`. The control
tool accepts only a visible control UUID and an action explicitly advertised by
`loxone_describe_control`. Supported types are `Switch`, `Dimmer`,
`LightController`, `LightControllerV2`, and `Jalousie`; automatic blind actions
are offered only when `details.isAutomatic=true`. Percentages are limited to 0
through 100, and lighting moods to documented scene IDs or currently visible
numeric `moodList` IDs. The server
provides no name-, room-, bulk-, free-form, learning, renaming, or expert
commands. History, LoxBerry tools and Basic Auth remain excluded.
Results and actions are limited to the authenticated Loxone user's permissions.

The English healthcheck never repairs the system:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

The service log can be opened directly from the status card in the LoxBerry log
viewer. It is bounded to the active file and two 512 KiB rotations, approximately
1.5 MB in total. Under **Diagnostics and logs**, **Warnings** is the default;
**Errors** and **Information** can be selected persistently. **Debug** can be
enabled for 15 or 60 minutes and automatically returns to the selected log level
without another restart. Normal HTTP access and successful read-only MCP calls
are not recorded individually outside debug.

Diagnostic export contains only the version, service state, transport kind and masked counts. Sessions can be
revoked individually or together; an available Miniserver also receives a
best-effort `killtoken`.

The admin status card refreshes the service state and PID automatically. An
inactive service offers **Start**; an active service offers **Stop** and
**Restart**. Stop and restart require confirmation and interrupt active MCP
connections. These actions change neither the stored plugin configuration nor
systemd auto-start. They control only the fixed
`loxberry-mcpserver.service` unit.

Service control is an administrative LoxBerry function and grants no Loxone or
MCP permissions. The sudoers file permits the `loxberry` user only the complete
`systemctl start`, `systemctl stop`, and `systemctl restart` commands for that
fixed unit; arbitrary subcommands, arguments, and other units are not allowed.
The action and result are recorded in the admin log without raw `systemctl`
output.

Every control attempt creates one compact masked record in the existing service
log. Repeated identical rejections are limited; no separate audit file is
created.

## Rollback

Stop the service in the UI first. If a prerelease is faulty, reinstall the
previous plugin ZIP through Plugin Manager. Configuration and sessions survive
upgrades together with encrypted Loxone tokens and the local installation key,
so a still-valid session can continue without another login. Uninstall removes
the service, Apache rule and narrow sudoers rule only when their plugin
ownership marker matches.
