# KNX page performance evidence

Issue #522 targets at most five seconds from opening or refreshing the native
KNX page until every requested section is loaded. A green functional test run
or an isolated CPU improvement does not establish that end-to-end target.
The owner accepted closing this optimization iteration after snapshot work,
review and functional live acceptance on 2026-10-18, even if the five-second
target remains unmet. Record achieved times explicitly; closure is not evidence
of a five-second result.

## Request boundaries

For the authenticated read actions `knx_page`, `knx_read_page` and
`knx_project_page`, the CGI exposes numeric, allowlisted `Server-Timing` values.
`X-KNX-Helper-Response-Bytes` reports the bounded helper JSON size, not compressed
network bytes. No token, identity, project content, arbitrary diagnostic text or
new JSON response field is included.

The spans are nested; do not add all header values. Use this hierarchy:

- Browser request: CGI total plus Apache/network/browser remainder.
- CGI total: module compilation, setup, spawn/input, helper pipe drain,
  response decoding/encoding and small surrounding work.
- Helper pipe drain: shell/Python/package bootstrap, module imports/definitions,
  input/dispatch/serialization and process shutdown.
- Helper dispatch: local configuration/proof, loopback send/header/read/decode
  and action dispatch overhead.
- Loopback header wait: outer middleware/transport plus bridge handler.
- Bridge handler: helper-key/proof/body handling, access-token verification,
  admission/preparation, analysis runner, final fresh authorization and response.

Runtime phases use each process's monotonic clock. The existing shell-to-Python
handoff and module-startup spans use bounded wall-clock timestamps.
Cross-process start timestamps are never subtracted. The browser request and
rendered section state must both be checked. A document response alone does not
prove that catalog, session restoration or remembered comparison has completed.

## Native baseline on 2026-10-18

An instrumented warm refresh on reserved Loxberry-Test measured 8.153 s overall.
The project request took 6.821 s; its analysis runner took 4.130 s. The residual
was therefore 2.691 s in this sample, rather than the earlier 4.067 s observation.
System load and parallel initial requests vary; these are individual samples,
not p50/p95 estimates or a five-second acceptance result.

Selected spans from that same request:

| Span | Milliseconds |
| --- | ---: |
| CGI compilation | 526.586 |
| Python/package bootstrap | 446.262 |
| Admin module imports | 343.904 |
| CGI response decode, 64,210 helper bytes | 486.562 |
| CGI response encode | 58.897 |
| Helper configuration read | 97.005 |
| Helper proof creation | 55.654 |
| Bridge access-token verification | 91.483 |
| Bridge helper-key read | 23.871 |
| Bridge post-runner processing/fresh check | 50.093 |
| Loopback header wait minus bridge handler | 99.230 |

A separate native module-load probe attributed approximately 171 ms to unused
`HTTP::Tiny`. The response decoding and startup spans were prioritized. Duplicate
token verification remains in place: its measured cost did not justify changing
security boundaries in this iteration.

A synthetic native decoder check with 69,422 ASCII helper bytes preserved complete
value equality in all three pairs. Original decode durations were 526.8/509.4/504.9
ms; accelerated durations were 15.5/2.5/2.5 ms, including optional module loading
in the first accelerated sample. Native CGI compilation and bounded concurrent
pipe checks passed. A fresh helper import loaded neither `importlib.metadata`
nor `asyncio`. These checks do not establish whole-page acceptance.

## Implementation constraints and checks

The snapshot follow-up combines part-local KNX format checks into one attribute
pass and rejects an unsupported root boundary before scanning the part. Exact
document/type/version multiplicity requirements remain unchanged. A valid-shape
synthetic profile measured about 28% less CPU in this format-check subphase;
this is neither the whole graph phase nor a native page-loading result.

Short overlapping LZ4 matches of at most 65,536 bytes use one bounded copy
instead of setting up the chunk loop. Larger matches retain the existing loop;
non-overlapping matches, length/reference checks and final checksum validation
remain unchanged. Alternating-order synthetic CPU samples showed about 17% less
CPU for distance-one, length-16 copies. This does not reproduce the native
compressed-match distribution and must not be projected onto total decode time.

Two parser candidates were rejected after repeated CPU measurements: sharing
attribute-name strings reduced graph IPC size by about 3% but increased parsing
CPU, and a special closing-tag path showed no reliable benefit. Worker model
serialization was also profiled; existing graph reducers already cover the
dominant object types, so no additional reducer complexity was introduced.

The optional platform `JSON::XS` accelerator handles only bounded ASCII helper
responses. Request payload parsing remains unchanged. Non-ASCII responses,
unavailable accelerators and accelerator errors use the original `JSON::PP`
decoder. Boolean/null/number/string handling, malformed/trailing JSON, surrogate
fallback and depth limits are tested against the original decoder. No dependency
is installed automatically.

Package version metadata is resolved on first public `__version__` access and
then cached as the same string. Installed distribution metadata remains
authoritative; the release fallback literal and public import forms remain.
KNX helper imports do not resolve the plugin version or load unrelated async
machinery. Required Solar configuration validation may load Python metadata for
Pydantic's own plugin discovery; this is separate from a plugin-version lookup.
Solar observation analysis models load only when observations are actually
constructed. Source models remain imported before the configuration lock;
configured sources use the same authoritative validator even with recording
disabled. Avoid moving cold model imports inside the shared configuration lock.
Session phase logs are restricted to an active project certificate scope for the
same endpoint. Ordinary sessions and inherited tasks after scope exit emit no
project timings; each session still connects and authenticates independently.

Helper stdout and stderr are drained concurrently with fixed size limits and
the existing timeout/child cleanup. This prevents timing diagnostics from
blocking a helper while the CGI waits for stdout EOF.

Record final-head cold/warm browser samples, section completion, target file
hashes, configuration/catalog integrity, service health and reservation release
with each native acceptance run. Preserve independent downloads, fresh visibility,
final marker authentication, authorization and revision checks. Do not use cached
private results or omit remembered sections to claim the five-second target.

## Same-functionality follow-up (#552)

The historical 18.283 s and 21.459 s service-cold observations used different
functional baselines. Cross-source identity/provenance and Solar configuration
validation were integrated between them. The measured post-graph identity and
diagnostic span grew by 1.591 s, helper imports by 0.947 s; graph construction fell
by 0.417 s. These nested observations are attribution clues, not a controlled
causal comparison or proof that every remaining difference is measurement noise.

A Performance-Analyzer compared pre-#536 snapshot modules from `16a8ae3a` with
the current implementation while retaining identical model-15 identity semantics,
project input and snapshot fields. Eight alternating fresh-process pairs on the
development host measured median snapshot construction of 979.71 -> 446.26 ms
(CPU 968.75 -> 437.50 ms). Every field, including private lookup dictionaries,
was canonically identical independently of pickle reducers. This bounds the
finding to snapshot CPU for that input; it is not native whole-page acceptance.

Two local caches were rejected: attribute and UUID memoization slowed the actual
saved project despite positive synthetic cases. Reusing the identical compiled
UUID pattern and returning early for empty UUIDs retained all conservative
identity checks and reduced local identity time from 87.97 to 78.85 ms across
24 alternating pairs with identical results. No new cache or model version is
required because interpretations remain unchanged. When every block UUID has
one occurrence, topology indexes are unused by existing identity decisions.
A fast path retains the complete UUID/local-duplicate pass and the existing
single-source or ambiguous/duplicate-source evidence, including connector
collisions. Multi-occurrence groups retain the complete existing topology path.
Twelve alternating local pairs reduced identity time from 79.51 to 16.90 ms;
equivalent duplicate groups and groups over the source limit retained equal
results and comparable fallback times.

An initially tested source-model lazy import was rejected. On reserved
Loxberry-Test, eight alternating fresh-process probes loaded the same three
Solar sources and measured combined import/validation of 1162.78 -> 825.61 ms,
with equal parsed documents. However, actual parallel initial CGI requests moved
cold source-model imports into the shared configuration lock: project forwarding
configuration time grew from about 24 ms to 897-1492 ms. The whole-page pilot did
not improve reliably. The retained change defers only observation analysis,
leaving source-model imports outside the configuration lock. A standalone CPU
improvement is insufficient when it introduces contention in the real page path.

For whole-page comparison, alternate the unchanged master reference `6704f6e0`
with only the two optimized runtime files. Keep project/configuration, shared
OAuth session, remembered comparison, periodic polling and all security checks
unchanged. A cold sample means restarting the plugin service, not clearing OS or
browser caches. Record initial response completion and separately verify rendered
rows/loading indicators. Do not call this a precise paint timestamp or p95.
