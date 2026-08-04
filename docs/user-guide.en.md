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
2. Enter the canonical Miniserver endpoint: for example
   `http://192.168.1.20` for Gen. 1, or HTTPS only for Gen. 2.
3. Test the connection, enable the service and save.
4. Connect Codex CLI or Claude Desktop to
   `https://loxberry.local/plugins/mcpserver/mcp` and complete OAuth login.

For Claude Desktop, follow the short
[step-by-step guide](clients/claude-desktop.en.md), which includes a ready-to-use
configuration example and troubleshooting help.

The six read tools remain enabled by default. To operate Gen. 1 switches,
additionally enable **Loxone control**. A new OAuth grant with `loxone:control`
is then required. Disabling control revokes existing control sessions while
read-only sessions remain valid. Control cannot be enabled for a Gen. 2/HTTPS
target.
Claude users can find the required scope configuration under
[Optional Loxone control](clients/claude-desktop.en.md#optional-loxone-control).

Save, connection test and session revocation remain usable without JavaScript.
With JavaScript, status, test and revocation update without a page navigation.

## Scope and operation

The alpha publishes six documented `loxone_*` read tools and optionally
`loxone_operate_control`. The control tool accepts only a visible `Switch`
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
