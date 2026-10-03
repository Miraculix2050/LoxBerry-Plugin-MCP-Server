# OAuth-family project deduplication preparation (#379)

- Status: investigation preparation; production behavior is unchanged.
- Scope: OAuth-family `sps.LoxCC` content. No dependency on implementing #239.
- Target evidence: none collected by this preparation.
- [German version](project-family-deduplication.de.md)

## Current path and reuse boundary

`LoxoneClient.download_project()` performs the fixed project request with the
requesting family's Loxone token and username, with bounded bytes, timeout,
redirect rejection and no automatic retry. It never substitutes service credentials.
`ProjectService._load()` validates scope, family and token confirmation, gets the
family token, and serializes loads through one semaphore. The cache key is
`(miniserver_id, identity_id, family_id)`; marker equality reuses only that entry.
On a miss it downloads, invokes the disposable `process_project()` subprocess,
rechecks authorization and checks the marker again before caching. The graph
cache is bounded to eight entries and 128 MiB of conservative accounting; separate
family views/queries are bounded to eight entries and 64 MiB.

`ProjectService.view()` requires the runtime subject to match the family; mapping
and query reuse additionally compare the caller's structure. Fresh visible
structure acquisition belongs to the tool/runtime path, not `load_snapshot()`.
Benchmarking that method alone cannot prove fresh visibility or MCP authorization.
Revocation cancels that family's loads and removes its cache/views; close removes
all retained content. Existing worker tests cover marker errors, project changes,
revocation and bounded caching. `test_project_family_baseline.py` adds two-family
download isolation (including overlapping calls), denied download, invalid warm
family access, independent revocation and view isolation.

No inspected code establishes a reliable independent project-read permission
proof without the project download. An authenticated program marker or visible
structure is not such a proof. Until target/protocol evidence establishes one,
each new family must perform its own authorized download before any proposed
shared parsed-content lookup. Existing cache-hit behavior is a baseline, not proof
that all future #379 permission gates are already satisfied.

## Reproducible offline baseline

Run from the repository with Python 3.13 and development dependencies:

```powershell
$env:PYTHONPATH = 'src'
python tools/benchmark_project_families.py --nodes 1000 --families 2 --samples 3 --warm-calls 3
```

The tool accepts counts only. It generates literal-only synthetic LoxCC in memory;
it does not read project files, credentials, configuration or the network and
prints only fixed labels, synthetic hash and numeric measurements.

- In-process parser measurements cover unpacking, decoding, graph construction,
  Python allocation peak/retained bytes, CPU and wall time. They exclude IPC and
  do not measure the disposable worker's peak RSS. Tracing adds timing overhead;
  compare only runs with the same tracing setup.
- Service phases exercise the unchanged real worker subprocess with mocked
  download, marker and authorization. Per-family cold/warm counts, bytes and
  worker wall time are recorded. A cold call includes one worker invocation;
  warm calls reuse that family's graph. Every new family still downloads/parses.
- Parent traced allocations include mocks, phase records, IPC and retained graphs;
  they are not process RSS. Cache-accounted bytes are conservative estimates,
  not measured object size. Worker wall time includes startup and serialization;
  it is not parser CPU. No fresh structure, mapping, query or cursor is timed.
- This is a before baseline only. No synthetic result demonstrates actual byte
  equality across users, permission behavior, target latency or optimization benefit.

## Candidate design, subject to evidence and review

After each family's successful authorized download, hash exact response bytes and
look up immutable parsed content by Miniserver identity, SHA-256 and explicit
parser/model version. The existing bundle digest hashes sorted unpacked members;
it is a different domain and must not be silently substituted for response-byte
equality. Keep family authorization epoch/reference and visible structure, mapping,
query, cursors, rate limits and tokens separate. Do not retain raw bytes in a new
cache or persistent store.

Bound content entries/bytes and account for graphs retained by views and active
requests. Coalesce parsing only after each family independently downloads and
validates; do not coalesce family authorization or downloads. A cancelled/revoked
waiter must not cancel another valid family's work or acquire a new reference.
Recheck the requesting family and version after waiting and before returning.
Remove its reference immediately on revocation; clear all references on shutdown.
Version/identity changes and failed fresh proof cannot fall back to stale content.
No shared cache, permission probe or production instrumentation is shipped here.

## Target measurement protocol (pending)

Use explicitly authorized test grants and controlled permission/project changes.
Reserve the target and record code revision, parser version, anonymous case labels,
sample counts, workload size, warm-up, cache state and contention. Never retain or
publish project bytes, usernames, tokens, URLs or installation identifiers.

Compare two grants of one user and grants of different users, before and after a
controlled visibility change, project-read denial and project update. Record only
sanitized hashes, byte counts and numeric timings/counters. Separate fresh visible
structure validation, authorized project download, parsing CPU/wall time,
mapping/query, end-to-end latency and parent/worker memory. Collect matched cold,
warm and concurrent repetitions; report failures as well as successful samples.
Do not retry an uncertain authorization failure automatically.

First measure the unchanged service. A later experimental implementation needs
the same workload, identity permissions, revisions, sampling and contention for a
before/after comparison. Agree a material benefit threshold before evaluating that
experiment; no threshold or positive target result is asserted here.

## Security and lifecycle matrix

| Case | Required evidence before productive sharing |
| --- | --- |
| Two families, identical bytes and marker | Each downloads with its own authorization; only parsing/content may be shared afterward |
| Same marker, visibility removed | Fresh caller structure hides removed controls; own mapping/query/cursor cannot use another family's visibility |
| Same marker, project-read denied | Denied family cannot obtain content from another reference; prove permission handling on cache hits too |
| Revocation during download/parse/wait | No result/reference for revoked family; another valid family remains independent |
| Project changes during verification | Reject inconsistent version; no stale fallback |
| Identity or Miniserver changes | No reference, view or cursor crosses the changed boundary |
| Marker/structure failure, confirmation required, auth busy, source-IP suppression | Fail closed; preserve existing bounded coordinator/rate-limit behavior |
| Concurrent identical/different content | Independent authorized downloads; bounded parse coalescing and queue/backpressure |
| Cancellation, eviction, active views | No leaked references, unauthorized delivery or unaccounted retained content |
| Restart/stop/parser version change | Clear memory-only references; no persistent project data or incompatible parsed reuse |
| MCP cache hit and pagination continuation | Recheck caller scope, family, token confirmation, project permission and fresh visibility |

The added tests establish selected **current isolation baselines**, not acceptance
of a future shared cache. Remaining cases require deterministic candidate tests
and matching live authorization/lifecycle evidence. Implement #379 only if those
gates and matched target benefit measurements pass. #239 retains its separate
service-identity transport and discovery gates; neither issue proves the other.
