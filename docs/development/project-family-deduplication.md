# Authorized project-content reuse across OAuth families (#379)

- Status: implemented; Gen. 1 acceptance recorded below.
- Scope: OAuth-family `sps.LoxCC` content. Service-identity discovery in #239 remains separate.
- [German version](project-family-deduplication.de.md)

## Authorization before reuse

Every project request, including warm cache hits and pagination continuations,
downloads the project with the requesting family's own Loxone token. A marker,
a visible structure or another family's cached graph cannot prove current
project-read permission. No reliable smaller permission probe is established.

The tool/runtime path still validates OAuth scope, the current access token and
family, token confirmation and freshly fetched caller-visible structure.
`ProjectService` rechecks access after the download, after parsing or reuse, and
after the final authenticated marker check. Permission denial, marker failure,
project changes during verification, cancellation and revocation fail closed.
Service credentials never authorize an OAuth-family request.

The owner accepted the extra download and marker-check cost of warm calls and
continuations. This is a deliberate authorization change, not a warm-latency
optimization. Cold-load time and retained graph memory are the comparison targets;
the architecture change is the primary objective.

## Bounded immutable content and separate family views

Only after its own successful download may a family reuse parsed content with
the same Miniserver identity, SHA-256 of exact response bytes, parser/cache epoch,
project model version and processing limits. The bundle fingerprint is a different
hash domain and is not substituted for response-byte equality. Changed bytes with
an unchanged marker rebuild that family's snapshot and view.

The existing load semaphore serializes downloads and parsing. Two successful
identical downloads can therefore share one completed parse; downloads and
authorization are never coalesced. There is no shared parse task for a revoked
waiter to cancel.

Project-backed MCP calls use a separate admission gate before acquiring shared
read slots: one active call, no waiting queue, and at most twelve calls per
rolling minute across all families on this runtime/Miniserver. Excess calls
return the existing temporary-unavailability envelope with a local rate-limit
diagnostic. Normal family and history limits still apply.
The global budget is charged only after family/history admission and current
access validation succeed; rejected or cancelled admission cannot consume
another family's project allowance. Admitted work remains charged on failure.
This also covers project-backed opening analysis and history/observability queries. Unrelated
reads keep their shared slots available during a project-call burst.

Family references remain keyed by Miniserver, identity and family. Visible
structures, mappings, queries, cursors, tokens and rate limits remain separate.
The content index contains keys only; graphs live in the existing family/view
caches. No raw bytes or graph store is persisted. Private snapshot lookup tables
are built once and treated as read-only by all consumers.

Family references remain bounded to eight entries. The 128 MiB graph allowance
counts each unique retained snapshot once. Views/queries retain their separate
eight-entry, 64 MiB conservative allowance. Eviction drops the family reference,
content key and views together. Existing active requests may retain their returned
snapshots; cache accounting is not a measurement or hard bound of process RSS.

Revocation cancels only that family's loads and immediately drops its references.
Another valid family must still download and authorize its next request.
Shutdown clears all references; restart cannot reuse previous process memory.
A different Miniserver, parser/cache epoch or processing limit cannot reuse an
incompatible graph. Family identity changes cannot reuse old family views.

## Deterministic verification

`tests/test_project_family_baseline.py` covers independent downloads for the same
and different identities, Miniserver isolation, overlapping loads, denied cold
and warm reads, caller-view isolation, unchanged-marker response changes,
revocation after download, cancelled queued loads, processing-limit and parser
epoch changes, bounded reference eviction and shutdown cleanup.
The existing worker/tool tests retain marker-change, token, fresh-visibility,
mapping, query and cursor checks.

The synthetic-only benchmark exercises the real disposable worker with mocked
authorization and download. Run with Python 3.13 and repository dependencies:

```powershell
$env:PYTHONPATH = 'src'
python tools/benchmark_project_families.py --nodes 1000 --families 2 --samples 3 --warm-calls 3
```

It reports cold/warm download and worker counts, worker wall time, traced parent
allocations, family references, unique content entries and conservative graph
accounting. Tracing distorts timing; worker wall time includes startup and IPC.
It does not prove real OAuth validation, permission changes, RSS or target latency.

## Target evidence and remaining gates

The unchanged Gen. 1 path was measured using two existing grants of one identity,
each with its own authorized download and freshly fetched structure. Response
hashes were identical and parsing produced separate snapshots. This direct
family-token harness is not MCP access-token acceptance. Evidence retains only
anonymous labels, hashes, byte counts and numeric measurements.

Matched before/after runs must use the same workload, graph/model version,
sampling and contention; separate structure, download, parse, memory and total
time. Report cold, warm and concurrent cases and unsuccessful samples.
Do not automatically retry an uncertain authentication failure.

On 2026-10-10, three successful Gen. 1 samples per revision compared baseline
`962be53` with runtime `ace8b46`, model 13, two grants of one identity and
858,414-byte responses. A recorded response-byte SHA-256 agrees across the
baseline and candidate runs. The harness fetches fresh structure before each
request but measures snapshot loading, not the full MCP/query path.

| Measurement (mean unless noted) | Baseline | Shared content |
| --- | ---: | ---: |
| First-family cold request | 24.31 s | 24.45 s |
| Second-family cold request | 24.82 s | 6.15 s |
| Both cold requests together | 49.12 s | 30.60 s |
| Retained unique graphs | 2 | 1 |
| Conservative graph accounting | 74,108,432 B | 37,054,216 B |
| Harness parent RSS | 118,797,653 B | 103,383,040 B |
| Harness parent peak RSS | 125,246,123 B | 107,029,845 B |
| Parser worker wall time, both families | 36.90 s | 18.26 s |
| Own downloads, two cold plus two warm calls | 2 | 4 |

The first cold mean differs by 0.6%; three timing samples do not establish a
small first-load regression or a universal latency guarantee. The two-family
cold total drops by approximately 38%, graph accounting by 50%, and measured
parent RSS by approximately 13%. Worker startup/IPC remain part of cold timing.
Parent peak RSS excludes child-worker peaks; worker wall time includes startup
and IPC and is not a separate CPU-time measurement.
Warm snapshot requests increase from approximately 2.6 s to 6.1 s as explicitly
accepted: every candidate warm request downloads independently, without parsing
again. Failed earlier measurements are retained separately and excluded from
these successful-sample means.

After the focused Hotswap, two real MCP grants independently returned current
project status with the same fingerprint/model and `stale=false`; the second
grant took 6.09 s. A real concurrent MCP probe admitted one project request,
rejected the second with `local_rate_limit`, and completed an unrelated fresh
structure overview while the admitted project call was active. Final source CI,
ordinary re-review and the separate security re-review on `ace8b46` are green;
the original admission finding is addressed and its GitHub thread resolved.

An additional direct-family-token probe used two real identities with different
visibility. Both independently downloaded identical bytes and shared one graph,
while their query instances and views remained separate: 402 versus 60 root
controls, with different runtime-mapping counts. This probe does not replace
MCP access-token acceptance.

The Restricted Explorer grant also completed real MCP cold/warm project status
and first/continuation object pages while its temporary project-read right was
present. Applying the controlled right withdrawal required a Miniserver reboot;
the LoxBerry MCP service remained running with its warm family cache. Calls with
the original grant and prepared cursor failed closed afterwards. Ordinary
structure reads also failed and the grant required renewed authentication, so
this phase establishes fail-closed behavior across the reboot, not an isolated
project-permission denial with otherwise valid authentication. After the user
reauthenticated, the Restricted grant could read current structure, while its
project status and object-page requests returned `permission_denied`. Its
structure overview contained 67 controls, versus 456 for the primary reader.
Same-marker warm and
continuation permission denial is covered deterministically, not claimed as a
live unchanged-marker observation.

The independently authorized primary MCP grant then loaded the changed project
with a new fingerprint and unchanged mapping counts; the result was current.
With the same Restricted token, the authenticated `jdev/sps/LoxAPPversion3`
marker remained available while downloading `sps.LoxCC` returned
`project_permission_denied`. This live counterexample rules out using that
timestamp as proof of project-download permission.
Test-control operations in
room/category MCP-Test do not themselves authorize user-rights administration.
No Gen. 2 claim follows from Gen. 1 evidence.

Merge/issue closure requires completed target gates, green final CI, ordinary
review and the separate security audit with no relevant unresolved findings.

## Authorized analysis result reuse (#396)

Analysis results use a separate bounded in-memory cache: four entries, 64 MiB
in total and a five-minute TTL. Modbus results depend on the loader-bound
project content identity, model/analysis versions and selected analyses. KNX
also includes the complete visible runtime-mapping fingerprint and any applicable
address taxonomy. Different KNX mappings never share completed results.

Every request, including a hit or continuation, independently downloads the
project with its own grant and refreshes visible structure. Authorization is
checked again after computing or retrieving the result. Shared computation is
serialized per result key; cancelled or unauthorized producers publish nothing.

Cursor leases remain family/identity/view-bound, are limited to four entries,
and contain no results or authorization. A random lease generation prevents an
expired or evicted cursor from becoming valid when another family recreates the
same result. Expiry and result eviction invalidate dependent leases. Neither
results nor leases are persisted. Public schemas and analysis versions stay
unchanged. Additional search/relationship index caches are outside this change.

The loader binds the private content identity to exact downloaded response bytes,
Miniserver, parser epoch/model and processing limits, including graphs too large
for the graph cache. A marker alone cannot prove authorization or identify bytes.

## Shared query topology (#398)

ProjectQuery separates a read-only ProjectQueryIndex (nodes and containment
parents/children) from family-visible mappings and control names. Queries may
borrow an index only for the exact same graph object after their independent
authorized load. The same family can keep topology when visible structure changes
and the graph survives. Missing-child reads do not grow the shared mappings.

Existing bounded view/query references own the indexes; there is no additional
global pool, persistence or worker serialization. The eight-entry / 64 MiB view
cache charges shared owned index containers once, plus separate family mapping/
query estimates. Eviction, revocation and close remove the respective references.
A valid result can remain uncached if it exceeds these retention limits.

Construction/allocation measurements are separate from network downloads and
whole-service RSS. Gen. 1 assessment used two independent loads of the one
available full grant; distinct-family and changed-view sharing is also covered
deterministically. The existing Restricted grant remains a live negative gate.

## Shared search results (#399)

A bounded ProjectResultCache owns shared search/analysis values separately from
private cursor leases. Search keys include the Miniserver, exact project content
identity, model/search version, complete visible mapping fingerprint (including
names), and normalized filters. Limit and cursor affect pagination only. Search
results are limited to eight entries / 64 MiB / 300 seconds; family/identity/view
leases have a separate eight-entry limit and random generations. Analysis retains
its four-entry / four-lease bounds using the same owner primitive.

Every search still independently loads authorized project and current visibility,
then authorizes again before publishing or returning cached values. Failed or
cancelled authorization publishes no result. Response models copy retained data.
An authorized in-flight hit restores its borrowed result after concurrent eviction
within the same bounds and original TTL before returning its own cursor.
Expiry, eviction and changed input invalidate dependent cursor leases; recreating
a result cannot resurrect an old cursor. There is no persistence or authorization
in the cache primitive.
