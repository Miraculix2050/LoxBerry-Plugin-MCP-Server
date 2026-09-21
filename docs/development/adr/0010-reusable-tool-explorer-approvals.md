# ADR 0010: Reusable Tool Explorer approvals

- **Status:** Accepted
- **Date:** 2026-09-22

## Decision

The fixed local Tool Explorer uses the server-defined application identity
`tool-explorer-v1` for local `loxberry:read` and `loxberry:operate` approvals.
The identity is assigned only after the existing exact client name, callback
path and allowed-origin validation. Its approval remains additionally bound by
an installation-local HMAC to the Loxone identity, Miniserver and capability.

OAuth registration, PKCE, consent, family and token lifetimes remain unchanged.
A later validated Explorer login can reactivate its application approval while
receiving a new dynamic client identifier, family and credentials. Other
dynamic clients retain the existing exact-client binding.

Explorer approvals are versioned configuration records containing only their
pseudonymous binding and bounded lifecycle timestamps. Once no matching family
is active, they remain reusable for 72 hours by default; administrators may
configure 1 to 720 hours. Cleanup runs at service startup and every minute, and
authorization also rejects an expired record before physical cleanup.

Existing opaque approval hashes are not converted. They remain visible as
legacy approvals and individually revocable. Revoking an approval removes it
and revokes matching families. Explorer disconnect remains an OAuth-session
action and does not remove the longer-lived local approval.

## Consequences

- OAuth credentials are never retained to preserve a local approval.
- A different identity, Miniserver, capability, origin or third-party client
  cannot reuse an Explorer approval.
- The Admin UI distinguishes active, login-required and legacy inactive rows
  and shows the scheduled removal time for reusable inactive approvals.
