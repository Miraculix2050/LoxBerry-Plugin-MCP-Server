# ADR 0002: Phase-1 Read-only Alpha

- **Status:** Accepted
- **Date:** 2026-08-03
- **Release:** `0.1.0-alpha.1`

## Context

Phase 0 established the Python 3.13, MCP 2025-11-25, OAuth 2.1, Apache and
Loxone protocol boundaries. Phase 1 turns that foundation into a native,
installable LoxBerry 4 plugin without widening the authorization surface.

The implementation follows the LoxBerry documentation for
[plugin development](https://wiki.loxberry.de/entwickler/plugin_fur_den_loxberry_entwickeln_ab_version_1x/start),
[Python plugins](https://wiki.loxberry.de/entwickler/python_develop_plugins_with_python/start),
[web UI development](https://wiki.loxberry.de/entwickler/web_ui_development_in_loxberry/start),
[developer tips](https://wiki.loxberry.de/entwickler/entwicker_tipps_und_tricks/start)
and the [V4 sample plugin](https://github.com/mschlenstedt/LoxBerry-Plugin-SamplePlugin-V4).

## Decision

### Identity and layout

The immutable identity is `NAME=mcpserver`, `FOLDER=mcpserver`, title
`LoxBerry MCP Server`, Plugin Interface 2.0 and minimum LoxBerry 4.0.0. Hooks
use LoxBerry's `$LBP*` paths and argument `$3`; a suffixed installation folder
therefore remains valid. Installed text files use LF line endings.

Persistent files are contracts:

- `LBPCONFIG/mcpserver.json`: authoritative `schema_version: 1` configuration;
- `LBPDATA/auth/sessions.json`: OAuth clients, hashed credentials and families;
- `LBPDATA/auth/loxone-tokens.json.enc`: AES-GCM protected Loxone JWT records;
- `LBPDATA/auth/install.key`: root-created 256-bit installation key.

The key is never packaged or exported. Configuration and sessions survive an
upgrade. Uninstall removes only external files bearing the plugin marker.

### Runtime and service

The package contains a complete arm64 wheelhouse and creates a plugin-owned
Python 3.13 virtual environment with `--no-index --no-deps`. It does not import
the LoxBerry Python SDK. The service runs as `loxberry`, applies `UMask=0077`
and systemd sandboxing, and binds only `127.0.0.1:8765`. Apache publishes only
the exact MCP, OAuth and metadata paths. Port or foreign-file conflicts abort
installation rather than overwrite another owner.

The configuration is disabled by default. In that state only the loopback
health endpoint remains available; MCP, OAuth and metadata routes fail closed
with HTTP 503. Validation precedes atomic replace; only a successful write is
followed by a bounded service restart. The last valid file remains after a failed write.
Runtime caches and connections are
separated by immutable OAuth family, Miniserver and Loxone identity. Cache
values have the explicit freshness states `current`, `stale`, `unknown` and
`unavailable`.

### Authentication and transports

Only scope `loxone:read` exists. OAuth access, refresh and authorization values
are stored only as SHA-256 digests. The store limits file size, total clients,
total active families, families per client and age. Refresh replay revokes the
whole family. Administrative revocation attempts Loxone `killtoken`, then
removes the encrypted JWT even when the Miniserver is unavailable.

Gen. 1 accepts only canonical private literal HTTP addresses and uses WS plus
Loxone Command Encryption. Gen. 2 accepts only canonical HTTPS origins and uses
WSS with the HTTP and WebSocket libraries' hostname and certificate validation.
A TLS error never selects HTTP/WS as a fallback. Gen. 2 remains experimental
until an independent complete report exists.

### MCP contracts

The stable read-only inventory is exactly:

1. `loxone_get_system_status`
2. `loxone_list_rooms`
3. `loxone_list_categories`
4. `loxone_find_controls`
5. `loxone_describe_control`
6. `loxone_get_states`

All tools declare `readOnlyHint=true` and `destructiveHint=false`. Their common
envelope contains `ok`, `data`, `warnings`, `observed_at`, `stale` and
`trace_id`. Lists use signed opaque cursors with limit 50 by default and 100 at
most. State requests contain 1–100 unique, visible state UUIDs. Normalization
excludes controls restricted to internal references and only returns rooms and
categories referenced by visible controls.

### Administration UI

Perl is only the authenticated native LoxBerry integration layer. It uses
`LoxBerry::System`, `LoxBerry::Web`, `LoxBerry::Log` and `HTML::Template` in
`nojqm` mode. All validation, storage, probing and revocation run through the
narrow Python JSON stdin/stdout helper.

The first layer is server rendered and supports save, connection test and
revocation with POST/Redirect/Get and no JavaScript. Responsive layout, visible
focus and touch-sized actions are mandatory from this layer. JavaScript then
progressively enhances status, connection test and revocation using the same
CGI and Python handlers. There is no SPA, jQuery Mobile, configuration write via
`ajax-generic.php`, mandatory polling or AJAX-only navigation.

## Consequences and verification boundary

This change requires the complete deterministic gate, package inspection,
disabled-JavaScript UI checks, the full responsive viewport matrix and native
LoxBerry lifecycle tests. Gen. 1 needs a real restricted-user run for all six
tools, reconnect and revocation. Automated tests can prove the Gen. 2 negative
TLS boundary but cannot promote real hardware compatibility.
