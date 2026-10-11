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
Public password outcomes never charge or reserve the trusted rejection budget.
A separate source_ip_pending_until reservation covers an unrecorded 4003 outcome
in any authentication phase. It uses the existing initial/next IP recovery delay,
clears on every durably recorded outcome and does not increment rejection counts.
After a crash or failed outcome write it temporarily gates all new authentication. Durable preflight reservations cover the maximum one-hour pause so an unsaved
outcome cannot lose protection in another process, and bound crash recovery;
the source-IP policy's initial or next escalated delay extends this reservation when stronger.
unreadable or unwritable protection state denies new authentication. Existing
authenticated sessions are not closed. A separate explicit native Admin action
allows an early probe no more often than once per minute; background retry flags
never grant this exception. Confirmed source-IP blocking retains priority.
Diagnostics retain the trusted guard fields and add public_failure_guard_state,
public_failure_count and next_public_login_at. next_auth_attempt_at covers trusted
authentication and IP blocking; next_public_login_at additionally covers the public
password pause. recovery_guard_state separately reports an unknown in-flight or
interrupted outcome; both effective times include this global recovery reservation.
Existing source-IP breaker fields keep their meaning. Remote revocations defer without
consuming their network-attempt budget when the trusted guard, global recovery reservation or confirmed IP gate is active.
An issued OAuth token whose sign-in or consent cannot finish is encrypted with its remote
revocation marker in one existing token-store write. If that write fails, the
login transaction retains it and blocks new issuance until cleanup can be queued.
Consent denial and expiration use this same durable queue rather than opening a
separate foreground cleanup connection; an authentication pause cannot discard
the only token copy. Without a token store, failed cleanup retains the transaction
and a separate temporary token copy is used for the remote attempt.

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

## KNX metadata administration

`knx.project_comparison` compares imported address keys with the existing
authorized `ProjectQueryIndex.knx_by_address` reverse index. The explicit
`ets_project_comparison` analysis does not change default analysis selection or
build another graph. Temporary indexed SQLite tables hold project address/name
observations in a read transaction; only bounded compact findings are cached.
An additive partial index of imported target/address keys avoids fetching JSON
for import-only observations. Its membership follows source updates; creating
the index on existing schema-v3 stores leaves records and revisions unchanged.
Counts and bounded keys are selected without materializing a full comparison
table. Source JSON is inspected only for addresses shared with the project.
Returned pages hydrate at most 50 address records in one metadata lookup and
at most 20 project objects per address, with omitted counts. No per-hit queries
or full source-document decoding occurs. A bounded worker lease remains held
until threaded work actually ends, including cancellation; the existing shared
analysis deadline also bounds SQLite operations. Target/revision-bound cursors
and fresh authorization guard every response. The KNX page uses the existing
Explorer OAuth/transport components with a new read-only grant; existing
Explorer defaults are preserved. Neither browser login nor metadata access
grants LoxBerry administration rights.

`knx.read_model` provides local query validation, literal Unicode substring matching
and bounded source/DPT projections. Indexed target selection precedes SQLite text
filters; the process materializes only the selected page, with fixed query count
and no query per result. No complete catalog cache or second project graph is
introduced. Schema version 3 stores a derived casefolded search
document per address; an atomic migration preserves original source fields and revision.
Insert/update triggers maintain it in the same transaction for manual, JSON and ETS
changes. NUL separators prevent matches across field boundaries; validated queries
cannot contain NUL. SQLite performs literal substring scans within the indexed target
without per-row Python callbacks or JSON decoding. MCP search reads a covering
target/search-document/address index without fetching metadata rows.
Page queries and JSON exports bind optional
filters to the expected KNX revision and target. Source projections distinguish
absent, empty and override values; DPT normalization establishes identifier syntax
only, not type-registry membership, assignment role or Loxone EIBType equivalence.

`knx.project_metadata` supplies authorized project tools with revisioned, indexed
batch reads for at most one output page. A service-owned LRU, including negative
lookups, stores immutable serialized projections below 16 MiB with conservative
owned-memory accounting. Decoding returned pages isolates mutable caller values.
Each request
checks the current revision before cache reuse; cache entries never authorize access.
The native unit sets validated `MCPSERVER_KNX_STORE` to the same persistent database
used by CGI; the server passes this optional path into tool registration explicitly.
CGI `LBPDATA` is not assumed to exist in systemd. All SQLite work runs in a thread. Search returns numeric address keys from target-bound
SQL filtering, never a materialized metadata catalog; only returned items are enriched.
The existing `ProjectQueryIndex` owns the reusable node-to-numeric-address index without
a second graph. Edge variants remain in original Loxone fields. Search/result/cursor
identities include the target and KNX revision; analysis identities include that revision
and effective selected labels. Manual prefix labels override imported labels by exact
format and prefix. Fresh project authorization remains required after enrichment and
on cache hits. Storage failure is explicit, not an empty metadata result.

Public `knx.metadata` separates imported/manual fields, source identifiers, deviations
and all raw/normalized DPT declarations with syntax status. Loxone titles, descriptions
and EIBType remain unchanged; `normalized_dpt_evidence` retains its existing meaning.
Explorer builds source disclosures lazily and uses text nodes; imported names never
become primary result captions. The existing response-size/page/worker bounds remain.

The dedicated authenticated KNX CGI uses narrow local admin actions. Small prefix labels remain in the atomic configuration; per-target address records are indexed by numeric KNX address in `data/plugins/mcpserver/knx/metadata.sqlite3`. Database transactions and expected revisions reject concurrent updates. Metadata never changes Loxone names or authorizes project access. JSON exchange is separate from ETS file adapters.

`knx.catalog_service` orchestrates bounded XML/CSV parsing, canonical identity/conflict selection, preview and explicit application. `xml_adapter` preserves address attributes, root attributes once and group attributes once with parent-prefix references. `csv_adapter` uses the standard strict CSV reader with bounded physical lines and explicit positional 3/1 or 3/3 headers; only tab separation and modern Description/DatapointType headers are accepted. Blank optional cells are unknown, not explicit empty values. Both adapters share lossless decoding and source-field normalization, preserving ordered DPT declarations without choosing a preferred type. Resolved file format is bound into each draft; changing the UI file-format selection invalidates its preview. CSV source evidence cannot establish an original XML hierarchy for export. Schema version 2 adds source evidence and selected groups without changing existing address/configuration contracts. Idempotent migrations preserve version-1 manual records. Import addresses, group metadata and group-label selection commit in one SQLite transaction; manual prefix changes retain their separately named configuration transaction. Config-store serialization binds preview/application to both target and manual-label state.

Short-lived drafts use a separate `knx/drafts.sqlite3`, a native authenticated-admin browser cookie bound to the web account, ten-minute expiry, at most eight drafts and 32 MiB of logical content. No session material enters catalog records, exchange documents or logs. Draft lookup verifies session, target and expected catalog revision; a refreshed preview rotates its confirmation token. A failed parse/replacement preserves the previous valid draft. Import processing runs in the bounded CGI helper process (60-second execution bound), outside the MCP event loop. No importer is added to the MCP read path.

Catalog comparison streams existing requested rows through one temporary-ID join instead of loading every description or issuing queries per address. Preview retains at most 50 change/group rows and five conflicts (up to 16 candidates each) per response. Full replacement removes absent import source fields while retaining all manual records and override values. The UI defaults to retaining a missing manual name from the former additional ETS name, shows that choice and its values in the preview, and preserves an explicitly changed policy. The service still requires a source-preservation decision before applying; no former ETS name silently becomes manual data. Source provenance is distinct from local display format. JSON restoration clears ETS reconstruction evidence for affected addresses, since exchange files cannot establish an original ETS hierarchy.

## Service-owned Admin discovery (#239)

Admin Event History selection/validation and emergency-stop option discovery use
one lazy, dedicated service-owned connection. Recorder and emergency-stop event
subscriptions retain their separate sockets; MCP tools retain their own OAuth
family's Loxone identity. The fixed loopback-only `POST /internal/admin-discovery`
requires an installation-secret-derived local helper key, a fresh configuration/
credential binding and a fixed selection or display projection. Apache does not proxy it.
It never returns raw structure, credentials, project content or arbitrary commands.

Event History and explicit emergency-option refresh requests send a complete new
`data/LoxAPP3.json` request. The separate `emergency_stop_display` projection checks
`jdev/sps/LoxAPPversion3`, the same change marker used by Project Intelligence.
It may reuse the private emergency-option display cache only with matching
credentials/endpoint, a nonempty matching marker and a last successful result.
Changed/missing markers and old or stale cache entries require a complete load.
The loaded structure's `lastModified` binds the replacement list to its version.
This is a display cache, never a fresh visibility or operation authorization proof.
A single receiver starts after authentication, with one pending fixed marker or
file request and no response queue. Marker replies require an exact command match;
unrelated files/text remain terminal. CGI alone owns the atomic cache write lock.

The UI first checks the display projection in the background on configuration
hydration and only then displays the matching cache or freshly rebuilt list.
It checks again at the configured structure-refresh
interval (minimum 60 seconds) while visible. Successful checks schedule the next
check; failures stop automatic attempts until a new page load or explicit retry.
The no-JavaScript fallback checks before server-side display. The initial normal
HTML shell remains local and nonblocking. The manual button always forces a complete structure read. Saved and unsaved
signal selections survive hydration, concurrent configuration changes and errors.
Valid state tables and keepalives have frame/byte/time budgets; unexpected text,
unsolicited files and binary/Gzip files terminate the connection. No Gzip payload
is assumed to be a structure response. Cancellation, timeout, provider failure,
disconnect, identity/configuration change and service shutdown discard the affected
connection and result. A failed request never reconnects automatically or returns
an old snapshot. A later explicit request can establish a new guarded connection.
Existing discovery deadlines remain projection-specific: 35 seconds for Event
History and 90 seconds for emergency options, including coordinator/queue wait.
The local helper allows one additional second for delivery.
Idle expiry is 60 seconds (checked every five seconds); absolute reuse is at most
five minutes. Current credentials and configuration are checked before and after
each load; source-IP blocking also prevents warm reuse. New authentication uses
the shared rejection/coordinator protections from #408.

**Accepted residual risk:** a partial permission change might leave an
uninterrupted Miniserver session able to return previously visible objects until
disconnect or bounded replacement. A complete structure download, a keepalive and
an unchanged project marker do not prove universal permission freshness. The owner
accepted this uncertainty for this internal Admin path. The 2026-10-10 full-access
withdrawal test closed a held OAuth-identity socket with code 4004 and rejected its
old token with 401 without an operator-triggered reboot. It did not test partial
changes or the configured service identity and is not a firmware-wide guarantee.
