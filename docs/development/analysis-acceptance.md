# Analysis scenario acceptance

The versioned catalog in `tests/fixtures/analysis/scenarios.json` preserves the
six lighting, seven basic/history and twelve solar questions collected in the
research chat (#433, #445). Each row names source requirements, a baseline read
workflow, completeness conditions, valid insufficient-evidence answers and
prohibited claims. Tool sequences are routing candidates, not proof that a source
exists. The catalog is not a promise to implement every roadmap workstream here.

Two KNX workflows from #457 extend this original 25-question matrix to 27 cases:
`knx-01` inventory review and `knx-02` exact address explanation with explicit
project variant. Both allow qualified answers for missing discovery, permissions,
imports or associations; different names and DPT declarations prove no defect,
topology, bus activity, causality or unused address. Separately approved local
catalog reads are conditional, not inferred from project permission.

For each KNX run record prompt-list and recipe byte sizes separately in
protected evidence, including observed model/client versions, optional token telemetry, and whether the
client invokes prompts or uses the normal-tool fallback. Measure relevant guide
sections, read call counts, bounded coverage and independently judged answer
quality. Prompt expansion does no source access: zero downloads/SQLite work are
valid only for that expansion, not the later workflow. Captures may use the
read-only method labels `prompts.list` and `prompts.get`; arguments and recipe or
answer content stay outside the value-free capture. Missing client/billing token
telemetry is optional supplementary evidence, never substituted with character counts.

`tests/fixtures/analysis/reference.json` contains installation-independent
numeric reference data for the delivered analysis core. A sample mean of 21 °C
does not establish a time-weighted mean. Event durations and numeric energy remain
different evidence types. Fixtures are neither hardware acceptance nor model
workflow measurements. The catalog's current support labels are conditional
source requirements; they do not certify an installed target.

## Three independent gates

1. Deterministic source/semantic/quantity calculations use reference fixtures and
   explicit tolerances. Numeric tolerances are absolute in the stated unit.
2. Workflow acceptance checks source selection and answer boundaries against each
   catalog row. A justified qualified answer can pass when data is absent. The
   reviewer must adjudicate the answer; the capture validator does not grade text.
3. Matching live SSH/browser/MCP evidence proves only the tested platform boundary.
   No test installation is required to contain every optional device or meter.

Weather-adjusted comparisons (#439), load-shifting/future planning (#440), and
specialized lighting review (#441) remain external dependencies. Native energy
results (#436) retain the #357/#363/#364 evidence gates. Record unavailable
capabilities explicitly instead of fabricating roles or introducing a balance
engine to fill them.

## Observable acceptance criteria (owner decision, 2026-10-18)

#485 makes UTF-8 bytes, complete-task call/page/retry/fallback counts, matched
cold/warm MCP timings and independent scenario correctness binding. Actual tokens
and tokenizer identity are optional supplementary evidence. There is no mandatory
20% token target and no replacement universal 20% byte/call target. Bytes do not
establish tokens, model-context consumption or monetary savings.

The owner retained a maximum of **50 answer records**. The reduced original matrix
is 25 questions with one independent initial/warm pair each: 25 sessions, 50
records, without a claim of three-session replication. Keep the two KNX extensions
separate. The historical scenario catalog and its three-run reference metadata
remain unchanged; declare the reduced execution plan explicitly in capture v2.
Missing original cases remain incomplete even if a declared subset is complete.
The producer must enforce the answer-generation budget across the campaign;
separate baseline/final files do not authorize 50 new answers each. Existing
45-record captures retain their original uneven eight-question coverage. Do not
relabel them as complete new captures or count copied records as new executions.

## Offline measurement capture

Run `python tools/analysis_acceptance.py` for the catalog identity; without actual
workflow captures it exits 2 (`incomplete`). `--capture FILE` validates a capture;
`--baseline FILE` additionally compares matched captures. This offline tool makes
no network requests, model calls, target accesses or writes. Keep captures and
private source inventories outside the public repository.

New collection uses **version 2**. Version 1 remains readable as a historical
contract with its original token requirements; it must not be used to judge the
new criteria. Mixed-version comparisons are rejected. No missing measurement is
silently converted to zero or inferred from a previous capture.

A v2 object has exactly `version`, `identity`, `plan`, `catalog_reads`, and `runs`:

- `identity` retains the v1 label fields `client`, `client_version`, `model`,
  `tokenizer`, `tokenizer_version`, `guide_revision`, `environment`,
  `tool_catalog_sha256`, `catalog_sha256`, and adds `runtime`, `workload_sha256`,
  `serialization`, `measurement_boundary`, `cold_conditions`, `warm_conditions`.
  Labels are non-secret version/method descriptions of at most 256 characters.
  Use `unavailable` for unobservable model/client/tokenizer identifiers. Optional
  tokenizer identity and token counters do not block v2 completeness. Missing
  mandatory execution labels (client/version, model, guide revision, environment,
  runtime, boundary and cold/warm conditions) remain incomplete; they cannot
  establish matched execution. Unavailable identity-field names are disclosed
  without echoing the private labels. Digests are SHA-256 of
  canonical ASCII JSON (sorted keys, compact separators). The private workload
  digest binds caller authorization identity, source selection, period and data
  fingerprints; report only the combined identity digest publicly. Baseline/final
  must use the same client/model, runtime, environment, workload, boundary,
  serialization and cold/warm definitions. Guide/catalog identities may change.
- `plan` has `case_ids` (unique catalog IDs), `runs_per_case` (1–3), and
  `record_limit` (at most 50). Planned initial/warm records must fit the limit.
  For the current original matrix use all 25 original IDs, one run, limit 50.
- `catalog_reads` lists every actual tools/list retrieval separately, each with
  `response_bytes`, `description_bytes`, `schema_bytes`, `duration_ms`, `status`,
  `page`, `retry`, `fallback_reason`, and `task`. Status/count labels follow the
  call rules below. `task` is `{case_id, run, phase}` for retrievals within that
  task, or `null` only for a measured setup retrieval outside all task intervals.
  Unobserved client retrievals must be disclosed as a capture gap, not silently
  classified as absent or setup. Missing numeric values are `null`, not zero. Do not assume an unobserved client cache or equate offered
  tool metadata with content inserted into model context.
- Each run contains `case_id`, `run`, `phase` (`cold`/`warm`), independently
  adjudicated `outcome` (`pass`/`fail`/`incomplete`), `calls`, `optional_metrics`.
  Outcomes require reviewing authorized source selection, domain arithmetic and
  tolerance, completeness, justified qualifications and prohibited claims. A
  smaller insufficient-evidence answer is not efficiency evidence against a
  successful complete analysis. The validator does not adjudicate answer text.
- Each actual call has exactly `tool`, `status` (`ok`/`error`/`timeout`),
  `duration_ms`, `response_bytes`, `guide_section`, `guide_module_bytes`, `page`,
  `retry`, `fallback_reason`. Calls must be released read-only tools or the
  read-only prompt methods `prompts.list`/`prompts.get`. Include every subsequent
  detail read, all pages, failures, retries and fallbacks. Boolean `page` means a
  continuation/page request; `retry` means an actual repeated failed attempt.
  Fallback reasons are `source_unavailable`, `unsupported`, `permission_denied`,
  `rate_limit`, `incomplete_coverage`, `tool_error`, `other`, or `null` (none).
  They categorize the request without private values. Guide section labels and
  module bytes apply only to actual `loxone_get_skill_guide` calls; other calls
  use `null` for both. Repeated guide fetches count each time. A failed guide
  response may have no extractable module bytes; retain `null` and the gap.
- `optional_metrics` contains `authorization_ms`, `download_count`, `sqlite_ms`,
  `calculation_ms`, `peak_bytes`, `tool_result_tokens`, `input_tokens`,
  `output_tokens`. Unobservable values are `null` and do not block acceptance.
  Retain already available phase data; do not build extensive instrumentation or
  obtain alternative API credentials solely to populate optional fields.

### Reproducible byte and timing boundary

Set `serialization` to `canonical_json_utf8_v1`. For each actually received MCP
JSON-RPC response serialize the whole response object with
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
and count its UTF-8 encoded bytes. Include both text and structured content when
returned. This is a normalized serialized-response measurement, **not** compressed
HTTP/TLS wire size. Error responses count too. A timeout with no response may
record zero received bytes only when absence was observed; an unavailable size is
`null`. Never substitute a CLI event's internal result wrapper for the documented
MCP response boundary without declaring a different, non-comparable method.

For tools/list, also serialize the ordered list of tool-description strings and
separately the ordered list of objects with `inputSchema` and `outputSchema`
(`null` when absent), using the same JSON convention. Those extraction sizes are
components reported separately, not additional traffic to add to response bytes.
For a fetched guide module, count the actual decoded module text's UTF-8 bytes;
its enclosing MCP response is already included in response traffic. The report
separates guide responses from other results to avoid double-counting. Per-task
`response_bytes` excludes catalog traffic, `catalog_response_bytes` reports the
assigned catalog responses, and `total_response_bytes` combines them once.
Task call counts/duration sums include assigned catalog retrievals, including
failures, pages, retries and fallbacks. Unassigned setup catalog calls remain
visible separately in `setup_catalog_call_totals`; all catalog calls are also
reported together without adding description/schema component sizes as traffic.

Measure each MCP call from dispatch to complete response/error/timeout using a
monotonic clock. `mcp_sum_ms` is the sum of these measured durations, **not** wall
elapsed time: overlapping calls remain separate summands. Model generation and
user waiting are excluded. State whether transport/client overhead is included
in `measurement_boundary`; use exactly the same boundary in baseline/final.
A new AI session is not proof of cold server caches. Declare connection state and
relevant runtime/cache state in `cold_conditions`/`warm_conditions`, while
retaining fresh authorization, visibility, identity binding, limits and admission
and cancellation protections.

Reports expose absolute values and percentage changes, complete-task traffic,
call/page/retry/fallback counts, error/timeout rates and per-case/phase sample
counts, p50, descriptive nearest-rank p95 and min/max. A single observation does
not establish variability or stable p95. Small-sample percentiles remain expressly
descriptive. No automatic performance or efficiency acceptance is produced:
independently verify equal answer scope/quality and investigate noise before
applying the unchanged-read >10% regression gate. Do not omit required safety,
approval or verification reads to reduce counts.

Capture fields reject response text, arguments, addresses, credentials and
unrecognized extras. Version labels and counters must be sanitized by the
producer; schema validation alone cannot establish that their content is safe.
No raw payloads or caller/workload identifiers belong in public reports.

## Delivery gates

Changed checks run during iteration; final Full CI on the final PR revision is the
merge gate. Independent phase reviews repeat at most three times. Runtime PRs
also require reserved, rollback-safe Loxberry-Test deployment and affected
browser/MCP/SSH acceptance. This catalog/harness PR changes no installed behavior
and requires no hot-swap. Update the support matrix as later PRs supply evidence.

## Foundation closeout snapshot (PR 9)

The original 25 questions now retain baseline fields and add `final_acceptance`:
released read-workflow candidates, DE/EN answer boundaries, reference category,
support status and explicitly incomplete independent-AI-run status. The two KNX
extension rows remain separate. Public [German](../user/analysis-support.de.md)
and [English](../user/analysis-support.en.md) matrices mirror those 25 rows.
Neither a routing contract nor a catalog validator adjudicates generated prose.

The five original numeric datasets are executed against the delivered core in
`test_original_numeric_references_against_delivered_core`: 21 degC unweighted
sample mean, 3 kWh observed counter difference, 3/2 kWh consumer rank, 3600 s
whole-hour PV/load/enable overlap and 100 W night median with 2.4 kWh labelled
daily estimate. The synthetic held-power intervals are converted into whole-hour
energy only by the acceptance fixture; no production sample-hold decoder exists.
Numeric tolerances remain in the versioned catalog. Scenario-contract rows have
no invented numeric reference or tolerance.

| Boundary | Deterministic evidence | Installed evidence and limitation |
| --- | --- | --- |
| Optional/missing consumer and several bindings | `test_installation_profile*`, `test_history_analysis_tools` | Temporary profiles save/read/delete/revision/approval denial tested in PRs 2/3/5; native production/consumer roles absent. |
| Unit/quantity contradictions and reset | `test_state_semantics`, `test_history_analysis`, `test_history_comparison` | Native meter format remains unverified; real analysis returns insufficient evidence. |
| Separate meters, overlapping boundaries, storage and unmetered rest | ranking/comparison role, boundary and method gates; catalog solar-15/18/24 | Ranking requires user confirmation; no inferred storage/rest accounting or native EFM balance. External #436 stays open. |
| DST, partial intervals, unknown initial value and capture gaps | `test_history_evidence`, `test_history_analysis`, `test_history_comparison`, Event History store tests | Schema 6 to 7 without invented baselines, real known/unknown phase display, isolated SQLite predecessor/reconnect fixture. |
| Revoked/hidden visibility and cursor changes | profile, history adapter and runtime security tests | Primary/restricted MCP, unauthenticated denial and fresh raw continuation accepted; no hidden IDs in public evidence. |
| Bounded mixed calculations | original numeric reference test and comparison/adapter suites | Positive installed isolated fixtures; native mixed results are qualified insufficient evidence, not positive device-family certification. |

Target acceptance in PRs 2–8 used Loxberry-Test (aarch64, Python 3.13.5,
plugin 0.4.0-beta.4), guarded backups/hash/permission checks, service `/healthz`,
authorized native MCP and DE/EN Explorer/Admin workflows at CSS 1280x800 and
390x844 (extra viewports for shared layout). Scope-specific records are in
[historical analysis](history-analysis.md), [semantic evidence](analysis-semantic-evidence.md)
and the individual reviewed PRs. No Gen. 2/Compact promise is added. Installer
compatibility is not inferred from file hot-swap. Shared authorization, recording
and unrelated configuration are retained; no Loxone control commands were used.

## Historical performance and token measurements (pre-revision snapshot)

The following historical observations retain their original evidence limits. They
do not establish current byte/workflow/performance acceptance.

Per the user's measurement constraint at that time, the client is the configured Codex desktop
and model identifier is `gpt-6.1-sol`. Exact client version, tokenizer/version,
independent session token usage and per-answer model telemetry are unavailable.
Guide revision is 76. The current complete release catalog SHA-256 is
`b025206d93c65a4ae35ad7636c5629727cf5ae4d5080076d89957f1c3fb7b004`
(canonical ASCII JSON, sorted keys and compact separators).

| Observation | Initial baseline | Integrated runtime after PR 8 |
| --- | --- | --- |
| Complete static tool count / catalog bytes | 36 / 287233 | 46 / 382121 |
| Full guide bytes | 55117 | 77572 |
| Static registry, three runs, p50 / nearest-rank p95 ms | 1279.53 / 1343.50 | 1776.98 / 1878.02 |
| Static registry peak bytes, observed range | 2962760–3769763 | 3428524–5765583 |
| Native compact one-hour energy, three observations ms | no matched PR-1 live baseline | 2234.67 / 1809.61 / 1820.62 |
| Same native compact energy response / raw reader bytes | unavailable | 2230 / 6425 |
| Native new comparison calls ms | unavailable | night 3083.55; rank 2359.67; PV/load 2042.98; mixed phase 1958.69 |
| Client tokens, tokenizer, 75 independent AI workflows | unavailable | incomplete |

Static construction used local Python 3.13.15, not the target's request path.
Concurrent KNX, alerts and system-message changes enlarged the catalog as well;
these figures are not an unchanged-read performance comparison. The foundation
adds four tools (profile read/save/delete and one shared analysis tool), rather
than one tool per question. The measured catalog growth is a cost, not a token
saving. Compact native responses are approximately 65% smaller in bytes than the
matched raw reader, but the result is qualified insufficient evidence and bytes
are not tokens. No 20% token-savings acceptance is claimed.

The three compact request observations have p50 1820.62 ms and nearest-rank p95
2234.67 ms; they are not independent AI workflows or a statistically robust
latency benchmark. Authorization, download count, SQLite phase, calculation,
request peak memory and model input/output tokens are not complete matched
baseline/final measurements. No confirmed 10% unchanged-read regression or pass
is asserted from these samples. The bounded core, cache isolation, worker
admission and event-loop responsiveness have deterministic tests; they do not
substitute for unavailable matched performance telemetry.

All delivered foundation contracts can be reviewed and reproduced. AI/token and
matched-performance acceptance remains explicitly **incomplete** under the
available-metrics constraint, without API credentials or fabricated counters.
External weather (#439), scheduling (#440), lighting (#441), and native EFM
(#436/#363/#364) workstreams remain outside this closeout.

## Final integrated target verification

PR 9 changes documentation, the offline catalog and acceptance tests only; it
keeps the PR-8 runtime and guide 76 unchanged. A separate reserved final read-only
probe made 21 native MCP tool calls, verified guide 76, energy, state duration and the four comparison
operations across compact/source workflows, raw continuation, source errors,
restricted visibility and unauthenticated denial. Five installed runtime/guide
hashes, preserved file modes, history schema 7, active service and `/healthz`
passed. The existing caller's profile remained empty. No hot-swap was needed for
this non-rendered documentation/test delta.

The final DE Explorer full-guide request displayed revision 76; the EN profile
read completed against fresh caller visibility. Both languages were inspected
at CSS 1280x800 and 390x844, without horizontal overflow or console warnings/errors.
These final smoke checks complement the per-feature PR 2–8 evidence. They do not
represent 25 independent model answers or token acceptance. #445 therefore remains
open for the missing independent AI/token and matched-performance gates.


## Modular-guidance and compact-read accounting (#442/#443)

V2 also accepts `resources.read` for published fixed guide resources. The collector
verifies the URI/section association; the value-free capture stores the section,
UTF-8 module bytes and actual response bytes, never a private URI or arguments.
Tool and resource guide reads use the same guide-fetch counters; actual parity or
fallback reads count separately. Do not silently omit resource traffic.

Use profile summaries for source selection and lighting_context for source moods.
Fetch full PV/load parameters or raw/detail history only when the task needs them;
include every such extra read, page, retry and fallback in complete-workflow totals.
Existing analysis/comparison summaries and include_raw detail paths are retained.
The original scenario questions, numeric references and prohibitions are unchanged.
Lighting routing supports only source mood names, not the specialized #441 review.

Reuse existing v2 separation of metric availability and independent quality review.
Missing token telemetry stays null and optional-unavailable; bytes/calls/times do
not establish token or cost savings. Protocol sessions, fixtures, native source
coverage and independently judged AI answers remain distinct evidence boundaries.
