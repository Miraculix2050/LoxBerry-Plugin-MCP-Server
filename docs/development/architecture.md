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

The Tool Explorer ships as ordered, same-origin static scripts. Its DOM-free core
handles schemas, redaction and generic value transfer; the static adapter registry
adds optional presentation hints. A tab-local state module owns drafts, results,
history and transcript transitions. The auth module handles discovery, PKCE and
the server-side Explorer session, while the MCP client owns fixed-path JSON-RPC
requests and accepts short-lived access tokens only from auth. Bounded views
render state and report user actions to the app controller. The controller owns
event wiring, mutation confirmation and session cleanup. New script assets are
listed in the Explorer template, the package manifest and the changed-test map;
their load order is part of the frontend integration contract.

## Authorization and data flow

Loxone authorization is evaluated with the signed-in Loxone user. LoxBerry authorization is independent: `loxberry:read` and `loxberry:operate` require matching local approval bound to client, Loxone identity and Miniserver. `loxone:control` additionally requires a global feature switch, OAuth consent, a visible operable Gen.-1 target and a typed allowlist.

The server loads the user-filtered structure at connection start and refreshes it only after a bounded version-marker check. State data is held in runtime snapshots; statistics use a bounded RAM cache. No arbitrary files, shell commands or target URLs are accepted from MCP input.

Per-family connection and control locks exist only while a holder or waiter uses
them, including cancelled and failed calls. Disconnect waits for connection
establishment before removing its record and never acquires a control lock;
control calls acquire connection locks through `snapshot()`. OAuth revocation and
family expiry use this same disconnect path after ending OAuth authorization.
The server supplies the runtime with the same authoritative OAuth access check
used by ProjectService. Queued read/history calls recheck it after obtaining
global concurrency; snapshots recheck before using a record, inside the
connection lock and after connection establishment. A connection that outlives
revocation is closed before publication. The encrypted Loxone token can remain
available to the remote-revocation worker without allowing a delayed OAuth call
to reconnect. No unbounded process-local revoked-family tombstones are needed.
Ended OAuth authorization is a permission failure; queued control/history calls
return `permission_denied` rather than a retryable availability error.
The normal, control and history rate windows survive disconnect and revocation
until their last timestamp expires after 60 seconds. Subsequent rate-limited calls
or disconnects sweep expired family keys, including families without connection
records. Cleanup is lazy: an inactive process can retain its last window, but
continued family churn does not retain all historical family keys. The active
session limit bounds connection records, not the number of families admitted
within one rate window.

Runtime session establishment shares the configured connection timeout between
local authentication coordination and network login. The in-process coordinator
lock and nonblocking interprocess file lock serialize authentication only, not
session lifetime or all reads. The file lock and endpoint-profile-bound breaker
are shared with service-owned emergency stop, Event History and Admin discovery;
MCP reads retain their own client token and fresh filtered structure. Admission
and family/refresh locks remain separate from authentication coordination and
remote session limits. The outer connection timeout bounds both local lock queues;
the interprocess lock has no strict FIFO fairness guarantee. Cancellation releases
locks without retrying login. A refresh and initial connection recheck OAuth access
and shutdown immediately before login after waiting.
These preflight checks also precede an active breaker cooldown's suppression;
ended OAuth access remains a permission failure without altering breaker state
or recording a network attempt.
Cancellation during authentication aborts the underlying transport immediately;
it does not start a new graceful-close budget. Cancellation during authentication
error cleanup also aborts the transport before propagating.

## Persistence and lifecycle

The same coordinator maintains an independent preventive authentication-rejection
guard in its existing private JSON file and under the same process lock. Typed
401 rejections use two separate three-in-five-minute budgets: public OAuth
getjwt password failures affect only public sign-ins; configured service getjwt
and all authwithtoken failures share the trusted budget. Public sign-ins observe
both budgets before any network probe; trusted reconnects and remote revocations
ignore the public password budget. Confirmed IP blocking remains global. A 60-second
pause doubles on rejected probes up to one hour; network failure and cancellation
restart the current pause without escalating it. Success outside recovery does
not erase recent failures. Fresh token acquisition and session authentication
share one atomic coordinator attempt; recovery succeeds only after both phases.
Public sign-ins reserve only the public guard before getjwt, then durably add
the trusted guard immediately before authwithtoken without releasing the lock.
A crashed public password phase therefore cannot pause trusted reconnects. Durable preflight reservations cover the maximum one-hour pause so an unsaved
outcome cannot lose protection in another process, and bound crash recovery;
the source-IP policy's initial or next escalated delay extends this reservation when stronger.
unreadable or unwritable protection state denies new authentication. Existing
authenticated sessions are not closed. A separate explicit native Admin action
allows an early probe no more often than once per minute; background retry flags
never grant this exception. Confirmed source-IP blocking retains priority.
Diagnostics retain the trusted guard fields and add public_failure_guard_state,
public_failure_count and next_public_login_at. next_auth_attempt_at covers trusted
authentication and IP blocking; next_public_login_at additionally covers the public
password pause. Existing source-IP breaker fields keep their meaning. Remote revocations defer without
consuming their network-attempt budget when the trusted guard or global IP gate is active.

Configuration, encrypted sessions and plugin identity persist outside the package. Secrets are separated from ordinary configuration. Root lifecycle hooks consume service templates only from the current installer staging area, never from the installed plugin configuration or binary directories. The staging area's integrity remains a LoxBerry Core trust boundary because Core runs unprivileged lifecycle hooks before `postroot`; plugin code cannot make that shared staging area root-owned. Within the persistent LoxBerry tree, sensitive root operations use descriptor-relative traversal and reject symbolic links, non-regular files and path replacement. Install, upgrade and removal follow the native LoxBerry layout; upgrade preserves supported configuration and authentication state through idempotent migration. The service starts unprivileged, validates configuration and listens only on loopback.

Local OAuth revocation is immediate. The service attempts remote Loxone `killtoken` through a persisted, profile-wide queue gate. Token-authentication rejection, confirmed remote kill, nominal expiry and unresolved failure are distinct outcomes; unresolved records stop after five network attempts. An atomically replaced, permission-restricted sidecar stores only aggregate status and anonymous expiring outcome markers. Cleanup never probes an open Miniserver authentication breaker.
Anonymous random receipt acknowledgements remain in the sidecar only while their terminal token-store records await deletion. They are not returned to the Admin UI; display tombstones expire independently, and the acknowledgements are pruned after record removal so a delayed cross-file recovery cannot recount an outcome.

## Security and observability

Gen. 1 uses local HTTP/WS plus Loxone command encryption; Gen. 2 requires validated HTTPS/WSS and never falls back to cleartext. Logs and diagnostic exports are structured and sanitized: no credentials, tokens, private keys, full structures or arbitrary raw logs. Writes are audited without secrets and are never retried after an uncertain outcome.

The authenticated Admin UI sends no-store cache directives, a same-origin Content
Security Policy, frame denial, a no-referrer policy and MIME sniffing protection
for page, AJAX, diagnostic-download and redirect responses.

Admin and Event History CGI actions require a POST with an Origin matching the
request scheme, host and effective port. A shared Perl guard uses server-side
`HTTPS` (`on`/`1`, `off`/`0`) and `REQUEST_SCHEME` (`http`/`https`); invalid or
contradictory metadata is rejected. If both variables are absent, native Apache's
cleartext HTTP convention applies. DNS host comparison is case-insensitive;
IPv4 and bracketed IPv6 are supported. Omitted ports mean 80 for HTTP and 443 for
HTTPS. Missing/null or malformed Origins are rejected before helper execution.
The guard never infers the scheme from a port or the configured MCP public origin.
It ignores `Forwarded` and `X-Forwarded-*` headers. A TLS-terminating reverse proxy
must sanitize incoming forwarding headers and provide the external host/port in
`HTTP_HOST` and consistent external scheme metadata through an explicitly trusted
webserver configuration, overwriting backend TLS metadata where necessary. This
does not introduce plugin-managed proxy trust or establish deployment-specific
proxy compatibility.

## Related documents

- [Implementation guidelines](implementation-guidelines.md)
- [Architecture decisions](adr/README.md)
- [Test strategy](test-strategy.md)
- [Support matrix](support-matrix.md)

## Internal project source

ProjectService is attached to the Loxone runtime lifecycle but performs no eager
fetches. Every Project Intelligence call validates the current OAuth identity and
read scope, loads the current user-filtered structure through a newly authenticated
session, uses its project marker, and rechecks authorization before releasing data.
A changed marker triggers a new download through the fixed encrypted HTTP project
endpoint; a matching marker reuses the identity-bound, memory-bounded graph. A
verification failure invalidates the cache. ZIP processing is bounded and
memory-only. Mapped views and queries are reused while the marker and freshly
loaded visible structure match. Project search and analysis results use separate
bounded, five-minute in-memory caches keyed by identity, graph, visible structure,
model version, filters, and selected analyses.
Marker session establishment uses the runtime's shared Miniserver authentication
coordinator, including its source-IP block suppression.

The public projection offers status, search, description, bounded signal/reference
traces, and deterministic analysis; it never returns raw XML and does not add a
scope. Analysis version 7 consumes the immutable project view and exact UUID
mappings only. It can report source-name patterns, local peer or graph outliers,
and mapped runtime context, but names never create a mapping. Missing normalized
DPT or semantic-domain data is exposed as an explicit limitation rather than inferred.

Native History reads continue to establish a fresh authenticated session and
load the visible structure before returning data. Debug logs separate authorization,
connection, structure, visibility, remote fetch, and parse timings without
recording tokens, project content, or history values. Marker-only History
visibility remains unverified for a History-capable control; the tested rights
changes did not exercise that case.
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
