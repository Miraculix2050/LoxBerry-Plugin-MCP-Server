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
| Installation profile | Bounded, versioned user declarations linked to exact currently visible sources |

The transport uses a server-local output-validator cache for the pinned MCP SDK.
Each tool output schema with unchanged JSON serialization is checked once against
its meta-schema; order-only object changes may trigger another safe check. Keys
retain JSON boolean/number distinctions without per-call object sorting. Every
structured response still undergoes complete instance validation. Independent
schema snapshots detect replacement and in-place edits, and tool removal clears
the corresponding entry. In-flight calls retain the validator for their original
registration. Pydantic argument validation, authorization and cancellation remain
in the existing SDK and policy paths. This removes repeated schema checking; it
does not establish a measured latency improvement (#529).

The installation profile stores metadata in `installation-profile.json` in the
plugin data directory. Its strict schema, cross-process lock, atomic replacement
and monotonically increasing revision protect concurrent Admin edits and restart
recovery. Deletion retains an empty revision tombstone. The local Admin adapter
uses fresh service-owned visibility; the read-only MCP adapter obtains fresh
visibility for the signed-in client on every page. Neither adapter treats a user
declared role as verified measurement semantics. Source fingerprints ignore
display names and flag technical changes for review. Hidden controls are omitted;
retired source identities are removed from invalid binding projections.
The MCP summary is a pure typed projection of that already authorized, cleaned
full result. It performs no storage/source access and preserves all identity,
status and usability evidence; the snapshot context rechecks authorization before
publishing either view. Display names, rationale and full PV/load declarations
remain in the default full view. Both use the same pagination and output budget.


MCP profile mutations use a separate policy/orchestration adapter. It requires
general local operation approval plus a default-disabled exact client/identity/
Miniserver profile capability. It rechecks local policy at the persistence boundary,
uses fresh caller visibility and expected revisions, and rejects whole-profile
deletion containing hidden bindings. A bounded worker remains admitted until it
finishes after a deadline or caller cancellation. The server audits the client's
confirmation assertion without claiming to verify chat content. Pure profile
storage remains independent from OAuth, MCP and technical decoders.

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

Lighting presentation reuses those adapters, drafts and bounded generic result
inspection. An exact visible LightControllerV2 result row can prepare a lighting
analyzer draft only when the current tool schema advertises that scope; it never
autoruns a request. Scope changes remove incompatible ETS/lighting arguments,
checks and cursors. Text-only page summaries preserve selection/naming coverage
and conditional evidence boundaries. No browser profile store or resolver is added.

## Authorization and data flow

An opened runtime session remains owned by connection setup until its maintainer
actually starts. Cancellation, protocol/normalization failure and initial-stream
failure close unpublished sessions without replacing the original diagnostic.
Failed families without retained records release their cache state; owned
disconnected records keep stale values until normal eviction/disconnect. Shutdown
also drains orphan cache subjects through per-subject cleanup.

Transport jsonschema instance mismatches return a fixed diagnostic without jsonschema
source values, property names or schema fragments. Full instance traversal and
validation remain enabled; invalid output is discarded. This intentionally
sanitizes the SDK's detailed invalid-output text while preserving valid wire
responses and unrelated input-validation behavior.

Project text search tests raw/source, uniquely mapped runtime and KNX/imported
metadata predicates before building response summaries or Modbus projections.
The result cache and exact total/order/pagination contracts remain unchanged;
independent project receipt and current authorization still precede result reuse.

Statistics cache entries, including empty results, are capped at 1,024 by default.
Retained key/tuple and conservative Python-object overhead count toward its byte
budget. Incremental point/byte totals and a separate monotonic insertion/refresh
expiry order avoid full-cache recounts without changing access-based LRU, TTL or
caller/source keys. Every hit still follows fresh History authorization. These
internal accounting limits are not a total service-RSS guarantee.

ProjectQueryIndex retains immutable incoming/outgoing positions for non-containment
raw edges followed by semantic edges. Descriptions merge raw positions in original
order, retaining duplicate edge occurrences and limiting response projection;
traces/semantic observations visit only indexed adjacency with their existing
API and direction rules. Containment remains separately indexed. Position integers,
tuples, maps and proxies count toward the existing 64 MiB shared view/index cache
budget. Cold index construction costs more time and RAM; oversized indices remain
uncached rather than bypassing the budget. No new persistent or unbounded cache,
download shortcut or authorization change is introduced.

Index construction retains singleton adjacency tuples directly and allocates
temporary lists only at junctions. Tuple storage is charged conservatively from
known group/link counts; the largest possible position bounds every retained
integer. Shared singleton tuples may be charged twice, preserving the existing
budget without walking each stored position for accounting. Indices remain eager,
immutable and independent of caller authorization; no lazy cache state is added.

Loxone authorization is evaluated with the signed-in Loxone user. LoxBerry authorization is independent: `loxberry:read` and `loxberry:operate` require matching local approval bound to client, Loxone identity and Miniserver. `loxone:control` additionally requires a global feature switch, OAuth consent, a visible operable Gen.-1 target and a typed allowlist.

The server loads the user-filtered structure at connection start and refreshes it only after a bounded version-marker check. State data is held in runtime snapshots; statistics use a bounded RAM cache. No arbitrary files, shell commands or target URLs are accepted from MCP input.

Structure JSON decoding, normalization and exact-response hashing run in admitted
threads. Runtime-owner lookups and publication remain on the event loop. Each
caller still receives its own complete filtered response before immutable reuse;
the username, target namespace and resource limits are part of the reuse context.
Cancellation, including repeated cancellation, retains admission until worker
exit and never publishes the cancelled result. This improves responsiveness;
it does not promise lower normalization CPU time. The synthetic
`tools/benchmark_structure_responsiveness.py` probe compares cold, changed and
warm response wall time and heartbeat lag against an explicit Git baseline.

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

Healthy existing records bypass a currently occupied connection-admission lock;
they reserve no new capacity and still recheck current access, shutdown and
publication authorization, and perform the requested visibility refresh. Other
requests retain serialized admission and the existing family-lock/pruning order.
Pruning skipped by this contended live-record path remains with the admission
owner and subsequent ordinary reads. New connections remain serialized, so no
additional in-flight capacity pool or authentication parallelism is introduced.
`tools/benchmark_warm_snapshot.py` compares warm-read latency against an explicit
Git baseline with a separate synthetic delayed connection and with no contention.

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

Runtime containment mapping (`explicit_runtime_parent_v1`) is a separate overlay
on the immutable graph. Legacy mapping status and node keys remain unchanged;
derived records carry parent/ancestor references without adding graph nodes or
connector semantics. The rule version and explicit parent relationships enter
the runtime fingerprint. Parent lookup is bounded to 16 steps, including conflict
and cycle detection. Authorization and independent project downloads still precede
immutable mapping reuse. Project-status inventory cursors bind the caller family,
project/runtime fingerprints and filters; response trimming preserves continuation
without skipping records. Observability keeps exact-only counters and emits the
selected derived child's evidence separately from parent topology.

Project trace optionally reports `include_internal_flow_gaps` in the existing
bounded `semantic_gaps` projection. Unmodeled reached occurrences and ambiguous connector
parents are diagnostics only: traversal, graph identity, mapping definitions and
default responses remain unchanged. Diagnostic references share retained-node and
response-byte limits. No lighting graph or connector interpretation is introduced.
Coverage uses emitted internal edges, including reference projections, and the
existing State contracts; catalog rules alone never establish port coverage.

The additive `lighting` scope of the existing project analyzer selects at most
16 exact visible controls or one exact room and runs its bounded checks in the
existing isolated analysis worker. It reuses the runner's result cache, cursor
leases, pagination, byte fitter and project graph. The default remains KNX.
`lighting_analysis` owns typed request-local declarations and normalization;
`read_profile_bindings`, `resolve_source_association` and `SourceSnapshot` remain
the shared source/profile authority checks. There is no new profile or store.
Each page reacquires caller-visible project/runtime sources. Both cache keys bind
caller identity, normalized selection/context, source/profile content and mood/room
signatures. Before publication another fresh project/runtime acquisition and
profile read reject revocation or mixed revisions, including same-revision changes.
Publication re-reads optional profile bindings before the final fresh runtime/
project acquisition; source validation and return then contain no further await.
Operational profile failures remain source unavailability, not malformed input.
Referenced profiles additionally carry a bounded content checksum from before
resolution through the final synchronous publication guard. It detects replacement,
deletion and same-revision changes across later awaits, including file identity
changes during checksum reading; it parses no bindings and creates no store.
The final read is capped at the existing profile document limit and takes no lock
or further await. Direct-only lighting uses an explicit source-only mode of the
same `SourceSnapshot`: endpoint/native metadata are guarded without constructing
a profile identity. Existing callers keep the strict profile-identity default;
references cannot select the source-only mode. Fresh authorization remains separate.
Presence declarations are separate from configured reachability; unknown central
flow, child parent anchors and bounded missing paths never prove causation.
The [lighting contract](lighting-analysis-contract.md) defines the reviewed scope.

## KNX metadata administration


`knx.file_comparison` is an admin-only consumer of the same XML/CSV parsers and
duplicate selection rules. It compares explicit files or streams the current
import catalog in a revision-checked read transaction. Numeric address keys,
exact text, normalized DPT sets and missing/empty/false states drive source
changes; format-bound group identities and manual sources remain separate.
It returns at most 50 changes per page and has no import-application or MCP
read-path role. Two comparison draft slots share the existing session/target/
revision/expiry and size limits; loading or clearing them retains the separate
import slot. Legacy drafts without a slot remain import drafts. Comparison
drafts cannot enter the import preview/application path. There is no persistent
comparison history and no graph, live signal or ETS deletion inference.

`knx.project_comparison` compares imported address keys with the existing
authorized `ProjectQueryIndex.knx_by_address` reverse index. The explicit
`ets_project_comparison` analysis does not change default analysis selection or
build another graph. A temporary indexed SQLite table holds project address
keys in a read transaction; only bounded numeric observations are cached.
An additive partial index of imported target/address keys avoids fetching JSON
for import-only observations. Its membership follows source updates; creating
the index on existing schema-v3 stores leaves records and revisions unchanged.
Counts and a bounded JSON array of keys are selected without materializing a
full comparison table or allocating one Python/SQLite row per import-only key.
Source JSON is inspected only for addresses shared with the project. Internal
numeric observations carry address, relation and comparison flags; complete
finding objects and source values are constructed only for a delivered page.
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


Experimental ETS correction XML is a separate admin-only serializer and temporary
`xml_export` draft purpose. It performs indexed batch reads of up to 50 selected
addresses and their required parents; it does not enter MCP read paths. Provenance
requires XML address and group source records from the latest import timestamp
and document digest. Older source records remain readable/importable but require
reimport for correction export. Root attributes, selected-address attributes and
required parent attributes are carried through unchanged except explicit names
or nonempty descriptions; unsafe reconstruction is rejected. Leading document
comments retain their exact positions; other interior positions block v1.
Preview and download check their ASCII-escaped JSON size against a 20 MiB budget
before creating a draft, leaving room below the CGI's 24 MiB helper-response limit.
Download rechecks the same budget; oversized payloads return the normal file-limit
error rather than a CGI internal error, without evicting another draft.

The project comparison browser bridge reauthorizes the existing read-only
comparison request before preview/download and checks project fingerprint/model,
page evidence, OAuth session and target/catalog revision. Admin payload text is
always an explicitly chosen local candidate, never a Loxone authorization grant.
The serializer never accesses Loxone or edits catalog/overrides. Draft download is
session/target/revision-bound and requires the visible experimental confirmation.
An actual ETS project-copy import remains an external acceptance gate for #419.


## Canonical task guidance (#442)

Fixed packaged Markdown modules own workflow rules. The core task index selects
only needed modules; guidance retrieval never reads project or runtime data.
`tools/generate_skill_guide.py` composes the checked-in legacy full guide from
these sources; regression tests reject drift. Resources and the existing guide
tool share the same module loader, revision and allowlisted section type.
Clients fall back to the full guide if a module is unavailable and stop the
affected workflow if both retrieval paths fail. Core and operations are required
before writes and contain all mandatory mutation prerequisites, including KNX
draft/apply and event-source management. Read modules are loaded only for needed
source evidence; they add no independent universal pre-write loading requirement.


The opt-in `include_outputs` lighting view projects explicit normalized direct
runtime children without deriving connector semantics from keys or names. Bounds
and unknown physical completeness are separate from the mood-source status.
This projection reuses the existing parser and introduces no independent graph.

The existing mood operation validator and the compact lighting read share one
source-row/ID validator in `loxone/lighting.py`. Its pure, bounded projection
retains only source IDs/names and explicit omission evidence; it has no runtime,
policy or command dependency. The MCP adapter obtains fresh caller visibility
before accessing the cached state and adds observation/source metadata. Read-only
input/name/output bounds do not alter the released operation-ID contract. No new
service, dispatcher or physical/scene interpretation is introduced.

Admission tracking counts both holders and queued connection waiters. Healthy warm
reads bypass the connection queue even during the fair-lock release handoff; cold
capacity remains serialized. Cancellation removes the counter in a non-awaiting
finally block. Ordinary uncontended reads retain normal pruning.

The sequential attention overview reuses only endpoint-bound public certificate bytes within one call, with fixed `attention_load` timing labels. Each source retains its own session, authentication, authorization, rate admission and download; the final access check remains mandatory. The scope is cleared on failure and cancellation.

State-cache permission pruning can reuse only the same exact built-in frozenset
supplied by the current structure generation. Every incoming event still passes
membership checking. Changed snapshots and mutable/general containers re-prune
retained states, and connection/disconnect/clear resets the optimization. This
avoids repeated full-cache walks without using a marker as authorization.

State-cache ingestion enforces conservative 16 MiB per-family and 64 MiB global
retained-byte estimates in addition to state-count limits. Estimates include
Python value storage and entry overhead, not process RSS or temporary wire/decoder
allocations. Text sizing is constant-time; decoder trees are bounded to 65,536
visited objects and depth 32. Oversized/unaccountable replacements discard the old
observation. Byte eviction removes oldest ingested entries, including stale values,
without promoting reads. Removed states become unknown while connected and
unavailable while disconnected; other retained values keep their freshness.
Permission pruning, count eviction, replacement and lifecycle cleanup share one
accounting path; cached membership never authorizes a new event.


State-cache byte capacity is shared by stable `(Miniserver ID, Loxone identity ID)`
from the freshly authorized connection setup, never by display names. Values and
permissions remain family-isolated. All families of one identity share the same
16 MiB upper bound, and each registered identity receives an equal share of the
64 MiB global budget (whichever is smaller). A new actual identity can reduce
per-identity capacity, but additional OAuth families of the same identity cannot
reduce another identity's share. Eviction stays within each identity's ingestion
order; no global oldest-victim eviction remains. Clearing its last family releases
an identity's share. Missing identity evidence remains family-isolated rather than
being inferred. The fixed entry estimate includes the extra accounting indexes.
