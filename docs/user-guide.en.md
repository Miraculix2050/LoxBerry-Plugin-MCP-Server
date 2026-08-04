# LoxBerry MCP Server 0.2.0-alpha.1

## Requirements

- LoxBerry 4.0.0 or newer; the reference target is 4.0.0.14 on Debian 13/arm64.
- A dedicated Loxone user with the smallest practical read permissions and,
  when needed, narrowly assigned Switch permissions.
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

For Claude Desktop, follow the short
[step-by-step guide](clients/claude-desktop.en.md), which includes a ready-to-use
configuration example and troubleshooting help.

For the ChatGPT/Codex desktop app, the
[direct Streamable HTTP guide](clients/chatgpt-codex-desktop.en.md) explains URL
setup, browser authentication, and the requested read or write permissions. It
does not require a local Node.js bridge.

The six read-only Loxone data tools and the read-only skill-guide tool remain
enabled by default. Under **Miniserver access through the MCP server**, select
**Read and switch** to additionally operate Gen. 1 Switches. A new OAuth grant
with `loxone:control` is then required. Switching back to **Read only** revokes
existing control sessions while read-only sessions remain valid. **Read and
switch** cannot be enabled for a Gen. 2/HTTPS target.

## Agent Skill

The server delivers the
[`using-loxberry-mcp`](../src/mcpserver/skills/using-loxberry-mcp/SKILL.md)
Agent Skill directly through MCP. It describes the safe workflow for discovery,
pagination, state reads, ambiguous names and explicitly requested Switch
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

Claude users can find the required scope configuration under
[Optional Loxone control](clients/claude-desktop.en.md#optional-loxone-control).

Save, connection test and session revocation remain usable without JavaScript.
With JavaScript, status, test and revocation update without a page navigation.

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
Tokens, drafts, results and the history bounded to 50 calls remain in tab memory
and disappear on reload or close.
**Disconnect and revoke** also clears them immediately.

The permissions dropdown defaults to **Read only**. **Read and control** is
selectable only when Loxone control is globally enabled and requires fresh consent for
`loxone:control`. Every state-changing call displays its tool and arguments
again and requires confirmation immediately before dispatch. **Disconnect and
revoke** ends the explorer session; after a browser crash it can still be revoked
under **Clients and sessions**.

## Scope and operation

The alpha publishes six documented Loxone data tools, the read-only
`loxone_get_skill_guide`, and optionally `loxone_operate_control`. The control
tool accepts only a visible `Switch`
control UUID and the action `on` or `off`. It provides no name-, room-, bulk- or
free-form commands. History, LoxBerry tools and Basic Auth remain excluded.
Results and actions are limited to the authenticated Loxone user's permissions.

The English healthcheck never repairs the system:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Logs appear in the LoxBerry log viewer. Diagnostic export contains only the
version, service state, transport kind and masked counts. Sessions can be
revoked individually or together; an available Miniserver also receives a
best-effort `killtoken`.

Every control attempt creates one compact masked record in the existing service
log. Repeated identical rejections are limited; no separate audit file is
created.

## Rollback

Disable the service in the UI first. If a prerelease is faulty, reinstall the
previous plugin ZIP through Plugin Manager. Configuration and sessions survive
upgrades together with encrypted Loxone tokens and the local installation key,
so a still-valid session can continue without another login. Uninstall removes
the service, Apache rule and narrow sudoers rule only when their plugin
ownership marker matches.
