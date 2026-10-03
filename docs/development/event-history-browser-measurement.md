# Development-only chart browser measurements

This routine originated in #297, which is now closed as an ongoing measurement
task (not completed performance acceptance). It supports focused follow-up
measurements without changing production assets, dependencies or performance
architecture. The existing backend measurements and their revision
attribution in [chart preparation measurements](event-history-chart-measurement.md)
remain unchanged. The October 3 authenticated target pilots are recorded in #297;
they supersede
the earlier zero-sample status. They do not complete the former broad measurement
matrix or prove current performance.

## Focused cache-overflow comparison (#371)

`tools/browser/measure-chart-overflow.cjs` exports `bundle({charts, cache})` for an
existing Playwright page. Write its returned function to a local development file
and run that file with the browser provider. Omit the arguments for the working
checkout; supply the two scripts from the comparison revision for the baseline.
The runner creates and closes isolated sibling pages, fulfils only synthetic
fixture requests, and does not navigate or modify the caller's target page.

Each DE/EN and 1280x800/390x844 combination uses two sources, one initial load and
five updates. The primary source starts with 24 or exactly 4,000 events; every
update adds one event, while the second source remains unchanged. Pages contain
at most 500 events; a dense replacement returns a deterministic reduced subset.
This fixture is not the SQLite sampler: it tests bounded response handling with
the shipped controller, cache, styles and uPlot. Responses include a fixed 15 ms
synthetic delay. Toolbar interaction timings include Playwright dispatch, query
completion and two animation frames, not physical paint or touch latency.

The accepted October 4 comparison used baseline `c039b944` and the #371 working
revision. Values below pool the four language/viewport combinations; update
rows contain 20 observations, initial and interaction rows four. Times are
median (minimum–maximum), milliseconds.

| Scenario/measurement | Before | After |
| --- | ---: | ---: |
| Small: initial | 188 (177–225) | 177 (171–201) |
| Small: five updates | 67 (65–84) | 67.5 (65–95) |
| Small: zoom | 65 (65–65) | 64.5 (64–65) |
| Small: pan | 66.5 (66–67) | 66.5 (66–84) |
| Dense: initial | 424 (420–430) | 431 (412–462) |
| Dense: five updates | 68 (65–117) | 83 (66–116) |
| Dense: overflow update only | 107.5 (99–117) | 108.5 (100–116) |
| Dense: zoom to higher detail | 331 (315–332) | 331.5 (329–332) |
| Dense: pan | 117 (116–117) | 117.5 (99–133) |

Small initial loads used two requests/4,248 JSON bytes in both revisions;
each update used one request/600–601 bytes. Dense initial loads used nine
requests/278,057 bytes in both revisions. The overflow update used two requests
in both, but the replacement queried two sources before and one after: total
JSON bytes decreased from 19,868 to 18,038. Each of the four following updates
used one request/608 bytes. JSON byte counts exclude HTTP headers and compression.
The fixture envelopes are ASCII, so character and UTF-8 byte counts coincide.

The baseline destroyed both plot instances at overflow; the new controller
destroyed neither. Both revisions completed without JavaScript exceptions or
horizontal page overflow, and keyboard values remained accessible. The new
controller showed the DE/EN reduced-detail notice only on the affected source;
zooming to an exact shorter range removed it. No immediate recovery loop occurred.
The small-history request and transfer path was unchanged. The timing ranges
overlap; this is a correctness and transfer comparison, not a speedup claim.
These measurements do not establish current CGI/SQLite cost, service CPU/heap,
target-device overflow reproduction, or the retired broad #297 acceptance matrix.

The installed-path smoke on exclusively reserved LoxBerry-Test used the five
changed existing Chart View files, with baseline hash verification, retained
backups and post-deploy hashes. Service and `/healthz` passed before and after.
Authenticated sibling tabs at 1280x800 (DE) and 390x844 (EN) loaded three existing
sources with 276, 7 and 0 cached events, two populated plots, clear status, no
horizontal overflow or JavaScript exceptions, and the updated cache/controller
asset suffixes. Zoom worked without changing target histories. This confirms
the installed path only: no suitable 4,000-event history was present in the
inspected selection, so overflow reproduction remains synthetic.

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
runners and numeric raw reports outside the tracked checkout. The driver opens
a disposable sibling page in the same authenticated browser context, measures
one navigation to the caller's exact URL, and closes that page on success or
failure, including redirects. It never installs scripts on the caller's page.
Cross-origin redirects reject the measurement with a fixed error before sampling.
Use a fresh context per fixture sample; for target samples retain the authorized
authenticated context and record the warm-run policy. The sibling shares context
authentication and HTTP cache, but does not copy sessionStorage history snapshots;
the shipped chart starts with its normal rolling one-day range. This is a fresh
tab navigation, not an in-place reload with a retained chart snapshot.
After upgrading from older harness versions, close their old measurement pages;
Playwright cannot unregister an initializer they already installed there.

For LoxBerry-Test, first acquire the normal shared test reservation, use an
already authorized Admin browser page with one to four selected sources, and
record deployed revision, browser version, source count and sparse/dense selection
policy without source identities. Run this read-only routine against that page.
Do not export authentication state or URLs containing credentials. Do not create,
alter or delete histories for this measurement. Release the reservation afterward.
The harness clicks Zoom in and Previous once on the disposable page. The caller's
selected range and page remain unchanged.

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
The shipped assets were from master `5621150cd3c6fbc03e2498467c11825c0f311e9c`;
the development probe/driver used the coverage-fix revision
`e9323ba95fa018f5c1a4a4e9ab1f758f61d4c5da`, before the later disposable-page
and Changed-selection hardening. The table retains that historical attribution;
later lifecycle checks are not additional benchmark samples.
These corrected runs replace the withdrawn pre-review samples: those fixtures
omitted recorded coverage and therefore inserted a gap between every event.
Both fixtures now report one coverage interval spanning their generated events.
An additional browser check after measuring confirmed blue data-stroke pixels
in both shipped uPlot canvases (460 per sparse chart, 32575–32578 per dense chart);
only pixel counts were returned, not images. This verification happens after
CPU/heap sampling and is not part of the measurement probe.

| Fixture / sample | First content ms | Zoom ms | Pan ms | Renderer thread CPU ms | End used heap bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sparse 1 | 64.8 | 27.9 | 29.4 | 55.9 | 4369984 |
| Sparse 2 | 59.8 | 27.0 | 29.1 | 56.8 | 4381056 |
| Dense 1 | 72.0 | 27.0 | 46.0 | 115.6 | 6830376 |
| Dense 2 | 141.6 | 26.9 | 46.4 | 121.4 | 9191256 |

Sparse fixtures contain 24 events per source across two days (24 returned events
across two sources in the initial day). Dense fixtures model 100000 events per
source over two days but return at most 2000 evenly sampled events per source,
with `reduced=true`. They exercise the existing bounded frontend reduction and
reload path, not a large SQLite database or backend history preparation.
Sparse samples made one prepare and one query (body/parse 2.1–4.6 ms); dense
samples made one prepare and four queries (2.6–30.6 ms). Each also retained a
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
Lifecycle tests verify disposable-page closure for successful, failed and
redirect-failed navigation, without invoking mutation APIs on the caller page.
An additional local Chromium smoke exercises A→B→A: a redirected measurement is
rejected and closed, and returning the caller to A has no probe or namespace.
