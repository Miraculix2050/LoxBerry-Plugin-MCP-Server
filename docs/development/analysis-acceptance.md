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

For each KNX run record prompt-list and recipe token/byte sizes separately in
protected evidence, including tokenizer/model/client versions and whether the
client invokes prompts or uses the normal-tool fallback. Measure relevant guide
sections, read call counts, bounded coverage and independently judged answer
quality. Prompt expansion does no source access: zero downloads/SQLite work are
valid only for that expansion, not the later workflow. Captures may use the
read-only method labels `prompts.list` and `prompts.get`; arguments and recipe or
answer content stay outside the value-free capture. Missing client/billing token
telemetry remains explicitly incomplete, not substituted with character counts.

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

## Offline measurement capture

Run `python tools/analysis_acceptance.py` to obtain the catalog identity. Without
workflow measurements it exits 2 (`incomplete`). Provide `--capture FILE` to
validate measurements, or additionally `--baseline FILE` for a like-for-like
comparison. No network requests, model calls or writes are performed by this tool.
Keep captures and private reference measurements outside the public repository.

A capture is an object with exactly `version` (1), `identity`, and `runs`:

- `identity` contains non-secret version labels: `client`, `client_version`,
  `model`, `tokenizer`, `tokenizer_version`, `guide_revision`, `environment`,
  `tool_catalog_sha256`, and `catalog_sha256`. Digests use SHA-256 of canonical
  JSON (sorted keys, ASCII escaping, compact separators). Use the actual observed
  model/versions; unavailable labels must explicitly say `unavailable`.
- Each run contains `case_id`, `run` (1–3), `phase` (`cold` or `warm`), independent
  reviewer `outcome` (`pass`, `fail`, `incomplete`), `calls` (read-only tool names),
  `guide_sections`, and every metric listed below. Each independent session has a
  cold initial workflow and a warm repeat; this yields 162 records for 27 cases.
- Metrics are `duration_ms`, `authorization_ms`, `download_count`, `sqlite_ms`,
  `calculation_ms`, `peak_bytes`, `output_bytes`, `tool_result_tokens`,
  `input_tokens`, and `output_tokens`. Counts, bytes and tokens are integers.
  Use JSON `null` for unobservable metrics; zero requires evidence of zero.

Do not include prompts, response text, arguments, installation identifiers,
addresses, credentials or token contents. Extra fields are rejected. Reports
include only case IDs, counters and identity digests. Labels are declared by the
capture producer, so payload rejection does not replace producer-side sanitation.

For this implementation, use the currently configured Codex model and client and
only metrics actually available there. Missing token or phase telemetry remains
`incomplete`; do not substitute character estimates or fabricated tokenizer counts.
Do not require API credentials as a workaround. The same measured client/model,
tokenizer and environment must be used for baseline and final comparison.

Output includes per-case/phase p50 and nearest-rank p95. Three observations are a
bounded workflow smoke, not a statistically robust latency distribution. Confirm
suspected performance regressions with a controlled matched measurement before
applying the 10% unchanged-read limit. Evaluate the 20% tool-result token reduction
only for workflows that actually replace raw data transfer. No performance result
is automatically accepted by the capture tool.

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

## Available performance and token measurements

Per the user's measurement constraint, the client is the configured Codex desktop
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
