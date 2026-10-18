# Local solar history: acceptance status, 18 October 2026

**#509 and #439 remain open.** The functional intermediate delivery is installed
on Loxberry-Test. A successful real numerical comparison with a reference and at
least three suitable historical peers is still missing. Fixtures do not replace it.

## Delivery and review

| Stage | Delivery | Gate |
| --- | --- | --- |
| 1: normalization | Merged PR #544 | Pure normalization and installed bounded fixture checked; no physical-history claim |
| 2: local recording/PVPF | Draft PR #549, `1b7bf8e9` | Full CI green; third review found a metadata-refresh issue, corrected/tested; PR remains open under the three-round limit |
| 3: numerical runtime | Draft PR #550, `1f5bd272` | Full CI green on this head; three review rounds, stale-source finding fixed; subsequent target-discovered Explorer corrections tested and inspected locally, with no fourth review requested |
| 4: integrated acceptance | This report | Pending genuine history, positive comparison and remaining review/measurement gates |

The local cross-cutting Changed run selected Full: 4,326 passed and 215 Windows
platform skips. Its support-matrix synchronization and local CRLF failures were
corrected and checked separately. Later affected suites passed, including 81
numerical/core contract cases, 87 Admin/Explorer cases, and 80 Explorer cases.
Exact-head Linux Full CI is the definitive package/merge check; no package,
release, tag or production installation was published here.

## Actual target evidence

- Browser: authenticated Admin source selection/confirmation/save and retained
  configuration; DE/EN layout checks. Numerical JSON-to-form execution succeeded
  in DE and EN at measured CSS 1280×800 and 390×844 without horizontal overflow.
  Mobile source-selection clipping and object-union/draft synchronization were
  reproduced and corrected using existing controls and JSON editors.
- MCP: a confirmed production binding read 96 native PV hourly points over the
  same four past local days. Numerical requests returned `ok=true` with
  `insufficient_evidence` for absent weather hours. A current-day request retained
  completed positions and separate unavailable captured PVPF revisions. Two
  simultaneous requests both returned the expected bounded result.
- The unchanged qualitative method returned `not_found` because no actual-weather
  recorder source is configured on this target. This proves the availability
  boundary, not successful real class-peer acceptance. Unavailable state selections
  and unregistered/stale sources retain fail-closed behavior; permission changes
  and revocation are covered by targeted regressions, without changing target rights.
- SSH: focused deployment manifests verify hashes, ownership/mode preservation,
  retained backups and service/health. SQLite V9 `quick_check=ok`; pre-existing
  scalar/weather history is retained. The real query plan uses the source,
  fingerprint and time index. Sanitized aggregate checks found no traceback,
  store failure or subscription failure in the inspected interval. Unrelated
  configuration matches the preserved pre-solar configuration.

Private manifests, timing samples and exact target identifiers remain in the
owner's Project-Data evidence directory, outside this repository.

## Performance and its limits

| Authenticated unchanged statistic | Before | After |
| --- | ---: | ---: |
| First after Explorer reload | 2,735 ms | 2,239 ms |
| Median of 20 successful serial repeats | 1,678.5 ms | 1,505 ms |
| Inclusive p95 of those repeats | 2,268.5 ms | 2,135.85 ms |
| Input points per response | 24 | 24 |
| Compact envelope UTF-8 bytes | 4,840 | 4,884 |

The same immutable day, source, arguments and client were used, with six seconds
between completed calls. The 44-byte addition is native Meter energy semantics.
No measured regression triggered the agreed investigation threshold. The first
call was not forced cache-cold; these observations do not establish a general
speedup. Earlier rate-limited responses were retained separately and excluded.

The new numerical negative case also completed 20 serial repeats, each with 96
input points and a 2,900-byte envelope. Two parallel analyses completed in 3,192 ms
combined. This measures bounded handling of missing weather, not the positive
peer workload. Independent source-access phase timing is not exposed at this MCP
boundary. Matched real-history before/after and phase measurements remain pending;
response bytes do not establish tokens, costs or #501 completion.

## Recording left running and remaining gates

Local irradiance and temperature capture began at **2026-10-18 12:18:18 UTC**.
The irradiance source is an independent configured WeatherData absolute W/m²
state, not the separately identified PV-derived circular signal. Its current
sample is zero and provider freshness is unverified. Temperature is the configured
minimum of two outdoor-sensor references, not a spatial mean. Source contracts
retain these limitations. Samples establish recorded source states, not continuous
physical measurements. PVPF snapshots were started earlier and remain forecasts.
The production binding uses the owner's explicit confirmation of isolated PV
generation; names and UUIDs are not hard-coded as application-wide roles.

Needed recording remains enabled on the test target. No production or Loxone
Config changes were made. Future acceptance must verify usable observations,
obtain a reference plus three suitable real peers, and assess native PV yield.
For #439 additionally verify direct/compatible self-consumption, current-day
windows, ranking and explained limitations against real evidence. No direct
self-consumption source or suitable export balance has been confirmed here.

PVPF remains `ready=0`, energy `-1`, `errorInfo=2`: readable, currently unavailable.
Structure File 17.1 p.115 defines cycle timestamps as the current prediction hour;
they do not establish full `period` energy bounds. Native period-to-actual matching
therefore remains `native_period_bounds_unverified`. The separate hourly adapter
in #542 can provide a later qualified integration point; no forecast is fabricated
or distributed across a partial day. This PVPF state does not block historical peers.
#510 remains the future planning follow-up; #501 is not declared completed.
