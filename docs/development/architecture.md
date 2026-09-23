# Architecture

- **Purpose:** Current implementation architecture and operational boundaries.
- **Audience:** Maintainers, reviewers and contributors.
- **Status:** Authoritative for the implemented system; ADRs record why significant decisions were made.

## System context

The plugin runs a local MCP server on LoxBerry. Apache publishes the fixed HTTPS MCP path and proxies only to a loopback service. The plugin has no project cloud service and supports one configured Miniserver.

```text
MCP client -- HTTPS/OAuth --> LoxBerry Apache -- loopback --> mcpserver service
                                                        |--> Loxone HTTP/WebSocket adapter
                                                        |--> LoxBerry read adapters
                                                        `--> configuration, sessions and bounded caches
```

## Components and contracts

| Component | Responsibility |
| --- | --- |
| MCP transport and registry | Streamable HTTP, stable tool schemas, validation and structured errors |
| OAuth and policy | PKCE, scopes, client binding, consent, revocation and per-call authorization |
| Loxone adapter | Token authentication, filtered structure, states, history and bounded control transport |
| Control registry | Explicit actions and value ranges per supported control type |
| LoxBerry adapters | Masked diagnostics and the limited plugin-owned cache operation |
| Admin UI and Explorer | Local configuration, session management and a separate OAuth test client |

## Authorization and data flow

Loxone authorization is evaluated with the signed-in Loxone user. LoxBerry authorization is independent: `loxberry:read` and `loxberry:operate` require matching local approval bound to client, Loxone identity and Miniserver. `loxone:control` additionally requires a global feature switch, OAuth consent, a visible operable Gen.-1 target and a typed allowlist.

The server loads the user-filtered structure at connection start and refreshes it only after a bounded version-marker check. State data is held in runtime snapshots; statistics use a bounded RAM cache. No arbitrary files, shell commands or target URLs are accepted from MCP input.

## Persistence and lifecycle

Configuration, encrypted sessions and plugin identity persist outside the package. Secrets are separated from ordinary configuration. Root lifecycle hooks consume service templates only from the current installer staging area, never from the installed plugin configuration or binary directories. The staging area's integrity remains a LoxBerry Core trust boundary because Core runs unprivileged lifecycle hooks before `postroot`; plugin code cannot make that shared staging area root-owned. Within the persistent LoxBerry tree, sensitive root operations use descriptor-relative traversal and reject symbolic links, non-regular files and path replacement. Install, upgrade and removal follow the native LoxBerry layout; upgrade preserves supported configuration and authentication state through idempotent migration. The service starts unprivileged, validates configuration and listens only on loopback.

Local OAuth revocation is immediate. The service attempts remote Loxone `killtoken` through a persisted, profile-wide queue gate. Token-authentication rejection, confirmed remote kill, nominal expiry and unresolved failure are distinct outcomes; unresolved records stop after five network attempts. An atomically replaced, permission-restricted sidecar stores only aggregate status and anonymous expiring outcome markers. Cleanup never probes an open Miniserver authentication breaker.
Anonymous random receipt acknowledgements remain in the sidecar only while their terminal token-store records await deletion. They are not returned to the Admin UI; display tombstones expire independently, and the acknowledgements are pruned after record removal so a delayed cross-file recovery cannot recount an outcome.

## Security and observability

Gen. 1 uses local HTTP/WS plus Loxone command encryption; Gen. 2 requires validated HTTPS/WSS and never falls back to cleartext. Logs and diagnostic exports are structured and sanitized: no credentials, tokens, private keys, full structures or arbitrary raw logs. Writes are audited without secrets and are never retried after an uncertain outcome.

The authenticated Admin UI sends no-store cache directives, a same-origin Content
Security Policy, frame denial, a no-referrer policy and MIME sniffing protection
for page, AJAX, diagnostic-download and redirect responses.

## Related documents

- [Implementation guidelines](implementation-guidelines.md)
- [Architecture decisions](adr/README.md)
- [Test strategy](test-strategy.md)
- [Support matrix](support-matrix.md)

## Internal project source

ProjectService is attached to the Loxone runtime lifecycle but performs no eager
fetches. Every Project Intelligence call validates the current OAuth identity and
read scope, uses its existing token for the fixed encrypted HTTP project endpoint,
and rechecks authorization before releasing data. ZIP processing is bounded and
memory-only. The public projection offers status, search, description, and bounded
  signal/reference traces, and deterministic analysis; it never returns raw XML
  and does not add a scope. Analysis version 3 consumes the immutable project
  view and exact UUID mappings only. It can report source-name patterns, local
  peer or graph outliers, and mapped runtime context, but names never create a
  mapping and missing normalized DPT or semantic-domain data is exposed as an
  explicit limitation rather than inferred.
Confirmed KNX/EIB nodes add an allowlisted semantic projection to those same
responses. It preserves source-backed bus direction and bounded group-address
facts without deriving physical roles, DPT meanings, or graph edges from equal
addresses. A small reviewed registry may add separate derived internal connector
edges for exact block types and connector keys; unknown pairs never receive an
edge. Trace reports those derived edges separately from raw wiring and only
classifies KNX/Loxone boundary paths whose endpoints are exact KNX endpoints or
exact runtime mappings. Search and trace use compact node projections and
enforce a 64-KiB envelope limit with explicit response-size truncation; describe
is the detailed per-object evidence projection.
