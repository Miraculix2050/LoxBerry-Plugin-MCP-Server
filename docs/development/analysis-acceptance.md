# Analysis scenario acceptance

The versioned catalog in `tests/fixtures/analysis/scenarios.json` preserves the
six lighting, seven basic/history and twelve solar questions collected in the
research chat (#433, #445). Each row names source requirements, a baseline read
workflow, completeness conditions, valid insufficient-evidence answers and
prohibited claims. Tool sequences are routing candidates, not proof that a source
exists. The catalog is not a promise to implement every roadmap workstream here.

`tests/fixtures/analysis/reference.json` contains installation-independent
numeric reference data for the upcoming analysis core. A sample mean of 21 °C
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
  cold initial workflow and a warm repeat; this yields 150 records for 25 cases.
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
