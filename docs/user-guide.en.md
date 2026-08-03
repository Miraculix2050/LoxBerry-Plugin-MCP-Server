# LoxBerry MCP Server 0.1.0-alpha.1

## Requirements

- LoxBerry 4.0.0 or newer; the reference target is 4.0.0.14 on Debian 13/arm64.
- A dedicated Loxone user with the smallest practical read permissions.
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

Save, connection test and session revocation remain usable without JavaScript.
With JavaScript, status, test and revocation update without a page navigation.

## Scope and operation

The alpha publishes only the six documented `loxone_*` read tools. It provides
no controls, history, LoxBerry tools, Basic Auth or generic commands. Results
are limited to the permissions of the authenticated Loxone user.

The English healthcheck never repairs the system:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Logs appear in the LoxBerry log viewer. Diagnostic export contains only the
version, service state, transport kind and masked counts. Sessions can be
revoked individually or together; an available Miniserver also receives a
best-effort `killtoken`.

## Rollback

Disable the service in the UI first. If a prerelease is faulty, reinstall the
previous plugin ZIP through Plugin Manager. Configuration and sessions survive
upgrades together with encrypted Loxone tokens and the local installation key,
so a still-valid session can continue without another login. Uninstall removes
the service, Apache rule and narrow sudoers rule only when their plugin
ownership marker matches.
