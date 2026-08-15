# ADR 0003: Phase-2 Controlled Switch Operations

- **Status:** Superseded by ADR 0005
- **Date:** 2026-08-04
- **Accepted:** 2026-08-06
- **Release:** `0.2.0-alpha.1`

## Context

Phase 1 provides six stable read-only Loxone tools. Phase 2 adds the first
state-changing capability without creating a generic command surface or
widening LoxBerry authorization. The write path must remain disabled by
default, user-bound, rate-limited and understandable to MCP clients.

## Decision

### Tool contract

`loxone_operate_control` accepts only a visible Loxone control UUID and the
enum action `on` or `off`. Phase 2 supports only Gen. 1 controls whose normalized
type is exactly `Switch`, with an `action` UUID and an `active` state UUID.
There is no free command, name-based target, bulk operation or expected-state
parameter.

The result reports the target, action, command acceptance, state confirmation
and the observed state `on`, `off` or `unknown`. The server waits at most three
seconds for a newer matching state event. An accepted command without a state
event remains successful with a warning and `confirmed=false`. A transport
failure after dispatch returns `outcome_unknown`; it is never retried.

The tool annotations are `readOnlyHint=false`, `destructiveHint=true`,
`idempotentHint=true` and `openWorldHint=false`.

### Authorization and activation

The supported scope sets are `loxone:read` and `loxone:read loxone:control`.
Control alone is invalid. Existing sessions remain read-only and refresh never
adds a scope. Protected resource metadata advertises control only while it is
enabled, without making it mandatory for the MCP endpoint. The consent page
shows required read access and lets the user explicitly add or omit requested
control access. All server-owned login, consent and error messages use the same
responsive dialog presentation; the registered client's callback page remains
client-owned.

Configuration adds `tools.loxone_control_enabled`, default `false`, and
`limits.control_requests_per_minute`, default `10` with range `1` to `60`,
without changing `schema_version: 1`. The write tool is registered only while
control is enabled. Disabling it revokes control-scoped families. Enabling
control for HTTPS/Gen. 2 endpoints is rejected; Gen. 2 write support requires a
later, separate opt-in decision and evidence.

Loxone permissions are the only control allowlist. The server resolves the
target in the structure delivered for the authenticated Loxone identity and
requires the Miniserver-provided action UUID. It does not add a second UUID or
client allowlist.

### Runtime and logging

Each command uses a short-lived authenticated WebSocket so its response cannot
race the persistent state event stream. Gen. 1 commands use Loxone Command
Encryption and the stored identity-bound JWT. Each OAuth family has at most one
control call in progress and at most the configured number per minute.

There is no separate audit database or UI. Every accepted operation writes one
compact INFO record to the existing service log. Rejected or uncertain calls
write WARN records, with identical failures limited to one record per identity
and error code per minute. Records contain a trace ID, pseudonymized client and
identity, target UUID, action and outcome; they contain no names, values,
payloads or secrets.

## Verification boundary

The deterministic gate proves schemas, scope preservation, configuration
compatibility, command construction, primary authorization failures and unknown
outcomes. There is no coverage target and no requirement to mirror every
defensive branch in a test.

Manual acceptance is limited to the changed UI at the primary desktop and
mobile viewports plus one native upgrade and one approved non-critical Gen. 1
Switch toggled on and off, restoring its initial state. Gen. 2, external access,
fresh installation, uninstall and exhaustive negative paths are outside this
acceptance run.

The required real Switch operation and the complete control-client flow were
confirmed on 2026-08-06. The sanitized evidence and remaining boundaries are
summarized in the [current evidence](../../evidence/current-evidence.md).
