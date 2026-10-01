# Development-only chart browser measurements

This routine continues #297 without changing production assets, dependencies or
performance architecture. The existing backend measurements and their revision
attribution in [chart preparation measurements](event-history-chart-measurement.md)
remain unchanged. An authenticated target-browser run is still outstanding.

## Reproduction

Use an existing Playwright browser page, with Node.js and the repository checkout.
The harness does not install or launch a browser and adds no Playwright package.
For local fixtures, start `node tools/browser/chart-fixture.cjs 8766`, then open
`http://127.0.0.1:8766/?case=sparse&count=2` in an isolated context. Replace
`sparse` with `dense`; `count` accepts one through four sources. Close the context
and server after the run. The fixture serves the shipped chart scripts and uPlot
from this checkout and accepts only chart-read actions. It never seeds a target
history or connects to a Miniserver.

With an existing `page` and Node access:

```javascript
const {measure} = require('./tools/browser/measure-chart.cjs');
const report = await measure(page, {width: 390, height: 844, timeout: 30000});
console.log(JSON.stringify(report));
```

For browser providers whose code sandbox has no `require`, generate an import-free
function into a local development file:

```javascript
const fs = require('node:fs');
const {bundle} = require('./tools/browser/measure-chart.cjs');
fs.writeFileSync('local-chart-runner.js', bundle(), 'utf8');
```

Pass that file to the provider's Playwright code runner (`filename`), or its
contents as the function to execute with the existing page. Keep generated
runners and numeric raw reports outside the tracked checkout. Reloading is part
of each measurement. Use a fresh context per fixture sample; for target samples,
retain the authorized authenticated context and record the warm-run policy.

For LoxBerry-Test, first acquire the normal shared test reservation, use an
already authorized Admin browser page with one to four selected sources, and
record deployed revision, browser version, source count and sparse/dense selection
policy without source identities. Run this read-only routine against that page.
Do not export authentication state or URLs containing credentials. Do not create,
alter or delete histories for this measurement. Release the reservation afterward.
The harness clicks Zoom in and Previous once; it leaves that page at the resulting
range. Restore the intended range manually after measuring.

## Meaning and acceptance

- Requests include only the three fixed same-origin chart CGI actions. Numeric
  `headers_ms` ends at fetch resolution; `body_ms` includes reading and JSON
  parsing through the original response. These are browser-observed request
  durations, not DNS/TLS/server phase breakdowns. Pending long polls remain
  visible in the report and are excluded from readiness. Failed requests are not
  discarded. Request rows are capped at 512, with an explicit dropped count.
- First content is the first uPlot draw with a finite numeric sample inside the
  current X range and a visible, connected chart intersecting the viewport,
  followed by two animation frames and another visibility check. It measures
  the first chart, not completion of every selected series. `first_content_ms`
  uses the navigation time origin; `first_content_from_probe_ms` starts at probe
  installation. This is a reproducible rendering proxy, not compositor or
  physical-display paint proof; no screenshot or trace is collected.
- Pan/zoom latency runs from a trusted toolbar click to a changed-range visible
  draw plus two animation frames. The driver also waits for chart requests to
  settle before the next click. Render latency and request completion are
  separate measurements. Drag, wheel and touch gestures are not covered.
- Requested size is verified against actual inner and visual viewport width,
  height and visual scale. The report also includes document client dimensions
  and device pixel ratio. Chromium mobile metrics override avoids desktop
  scrollbar shrinkage at 390 CSS pixels. This emulation is viewport evidence,
  not physical phone or touch compatibility evidence. Without CDP, actual
  viewport verification still applies and a mismatch rejects the sample.
- CDP `Performance.enable` uses `threadTicks` when supported. Only then is
  `TaskDuration` delta exported as `renderer_thread_cpu_ms`, from
  DOMContentLoaded to the end. Wall-clock fallback never becomes CPU evidence.
  Heap values are V8 isolate used/total bytes at the end, without forced GC.
  They include instrumentation overhead and are neither process RSS nor a heap
  leak diagnosis. Unsupported or failed metrics are `null`. Metric semantics
  follow the [Chromium implementation](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/inspector/inspector_performance_agent.cc).
- Long-task counts/duration are optional browser observations, not CPU usage.
  Service CPU/RSS, worker/GPU/process CPU, heap snapshots and raw DevTools traces
  are outside this harness.

An accepted sample requires first content, clear chart status, exact viewport,
two completed trusted visible interactions, successful non-long-poll requests
and no dropped request rows. Bounded timeouts remain failed/unaccepted evidence;
there is no invented latency or successful empty chart. Setup/navigation failures
reject the runner promise rather than producing a successful report.

The report exports fixed labels, numeric measurements and booleans only; it does
not export source UUIDs, names, endpoints, tokens, request/response bodies, project
values, error text, screenshots, traces or authentication state. The probe adds
observation overhead; comparisons must use the same instrumented routine.

## Local fixture evidence, 2026-10-01

Four accepted local runs used Chromium 154.0.8037.93, two synthetic sources and
fresh isolated contexts, at an actual inner/client/visual viewport of 390×844,
visual scale 1 and DPR 1. Each row is one reload with Zoom in then Previous.
These are harness verification samples, not LoxBerry or Miniserver benchmarks.
The shipped assets were from master `cd7e4ac4e2f94925f8388a5a225d2720027dc1df`;
the development probe/driver were the new files delivered with this document.

| Fixture / sample | First content ms | Zoom ms | Pan ms | Renderer thread CPU ms | End used heap bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sparse 1 | 98.8 | 26.3 | 27.2 | 74.6 | 4368564 |
| Sparse 2 | 74.4 | 24.6 | 26.7 | 74.0 | 4374784 |
| Dense 1 | 138.7 | 32.3 | 46.2 | 125.6 | 7694068 |
| Dense 2 | 99.4 | 25.4 | 78.9 | 151.9 | 7621544 |

Sparse fixtures contain 24 events per source across two days (24 returned events
across two sources in the initial day). Dense fixtures model 100000 events per
source over two days but return at most 2000 evenly sampled events per source,
with `reduced=true`. They exercise the existing bounded frontend reduction and
reload path, not a large SQLite database or backend history preparation.
Sparse samples made one prepare and one query (body/parse 2.7–5.4 ms); dense
samples made one prepare and four queries (6.6–32.7 ms). Each also retained a
pending long poll. With only two samples per case, no distribution or comparative
performance claim is justified. A preliminary desktop-scrollbar sample was
rejected because the visual viewport was 375 pixels wide.

No authenticated target Admin browser session was available for this task.
Live sparse/dense histories, service resources, physical device paint, gestures,
longer CPU/heap observation and end-to-end target measurements remain open in
#297. The earlier 48 backend samples retain their original instrumented revision.

## Verification

`node --test tests/js/chart-measurement.test.cjs` covers deterministic clocks,
draw visibility/range gating, delayed JSON completion, privacy sentinels, fixture
limits/read-only routing, exact viewport acceptance and absent/failing/thread-CPU
metrics. `python tools/test.py --profile changed` includes this suite through
`tests/test_chart_measurement.py`. Full CI remains the final project gate.
