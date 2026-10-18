# KNX page performance evidence

Issue #522 targets at most five seconds from opening or refreshing the native
KNX page until every requested section is loaded. A green functional test run
or an isolated CPU improvement does not satisfy that end-to-end gate.

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

Every duration is measured within its own process using a monotonic clock, except
that existing shell-to-Python bootstrap uses bounded wall-clock timestamps.
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

The optional platform `JSON::XS` accelerator handles only bounded ASCII helper
responses. Request payload parsing remains unchanged. Non-ASCII responses,
unavailable accelerators and accelerator errors use the original `JSON::PP`
decoder. Boolean/null/number/string handling, malformed/trailing JSON, surrogate
fallback and depth limits are tested against the original decoder. No dependency
is installed automatically.

Package version metadata is resolved on first public `__version__` access and
then cached as the same string. Installed distribution metadata remains
authoritative; the release fallback literal and public import forms remain.
KNX helper imports do not load version metadata or unrelated async machinery.

Helper stdout and stderr are drained concurrently with fixed size limits and
the existing timeout/child cleanup. This prevents timing diagnostics from
blocking a helper while the CGI waits for stdout EOF.

Record final-head cold/warm browser samples, section completion, target file
hashes, configuration/catalog integrity, service health and reservation release
with each native acceptance run. Preserve independent downloads, fresh visibility,
final marker authentication, authorization and revision checks. Do not use cached
private results or omit remembered sections to claim the five-second target.
