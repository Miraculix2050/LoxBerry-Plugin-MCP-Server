# ADR 0006: Phase-3 LoxBerry Read-only Diagnostics

- **Status:** Accepted
- **Date:** 2026-08-07

## Decision

Phase 3 adds three optional, read-only MCP tools: `loxberry_get_system_status`,
`loxberry_get_plugin_status`, and `loxberry_get_service_health`. They have no
input parameters, use the established result envelope, and are annotated as
read-only, non-destructive and closed-world. Public errors are limited to
`permission_denied`, `temporarily_unavailable`, and masked `internal_error`.

`loxberry:read` is advertised and the tools are registered only while
`tools.loxberry_read_enabled` is true (default false). `loxone:read` remains
required. The canonical scope order is `loxone:read`, `loxone:control`, then
`loxberry:read`; refresh tokens preserve, never extend, their scopes.

An administrator approves a pending OAuth family that includes `loxone:read` and
may also include `loxone:control`. The approval is
the installation-bound HMAC pseudonym of exact client, identity, and
Miniserver identifiers. It is stored in `policies.loxberry_read_bindings`, not
as raw identifiers. A client may request `loxberry:read` before local approval.
After the user confirms it, the server records a pending request and issues the
confirmed diagnostic scope. Until local approval, every diagnostic tool call is
denied; the same connection gains access once the binding is approved. Refresh
never extends scopes. Every tool call rechecks scope and the
live binding. Revoking a binding ends every matching OAuth family; global
disable ends diagnostic-scoped families but retains approvals.

The adapter reads only `Base.Version` from the bounded LoxBerry general config,
fixed bounded `/proc` sources, `os.cpu_count`, `statvfs(LBHOMEDIR)`, and a
fixed-property, three-second `/bin/systemctl show` for this service. It uses no
shell, dynamic paths, foreign services, logs, PIDs, network data, environment
values, or write operations. A stopped MCP service cannot report itself through
MCP.

## Consequences

The admin UI exposes global activation, the diagnostic rate limit, approved
pseudonym fingerprints, the related client name and connection fingerprint,
approval from pending sessions (including control sessions), and revocation.
The Tool Explorer retains one tab-and-origin client registration across scope
changes. Documentation and the `using-loxberry-mcp` skill describe the local
approval flow and never recommend repair, restart, or permission bypass.
