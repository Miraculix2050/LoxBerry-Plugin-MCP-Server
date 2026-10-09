# Authorized project-content reuse across OAuth families (#379)

- Status: implementation under review; target acceptance is incomplete.
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

Acceptance also needs real different-user grants with differing visibility,
controlled project-read permission loss on warm calls and continuations, and
a controlled project update. These are not established by equal bytes from
two grants of one user or by deterministic mocks. Test-control operations in
room/category MCP-Test do not themselves authorize user-rights administration.
No Gen. 2 claim follows from Gen. 1 evidence.

Merge/issue closure requires completed target gates, green final CI, ordinary
review and the separate security audit with no relevant unresolved findings.
