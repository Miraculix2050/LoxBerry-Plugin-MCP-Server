# Local solar history: acceptance gates

Local observation normalization is delivered by merged [PR #544](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/544).
The recording/PVPF stage is [PR #549](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/549),
the numerical runtime is [PR #550](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/550),
and the integrated closeout summary is [PR #551](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/551).
Detailed dated target/browser/MCP/SSH and performance evidence belongs in the
owner's private Project-Data archive, outside public product documentation.

#509 and #439 remain open until a successful real numerical comparison includes
a reference, three suitable historical weather peers and qualified PV yield.
For #439 also verify direct/compatible self-consumption, completed-hour running-day
windows, ranking and explained limitations. Fixtures do not replace device evidence.
Retain exact-head Full CI and the agreed review gates; after three unsuccessful
rounds keep the affected PR open. Later corrections need review before merge.

Use a documented local source contract and representative sample. Independent
W/m² observations may produce explicitly estimated Wh/m². Exclude PV-derived
circular baselines; identify temperature aggregation and provider-freshness gaps.
Needed test recording may remain enabled with a privately documented start;
recording never backfills history. Preserve unrelated configuration and history.
Matched real-history performance and independent data-access phase measurements
remain an acceptance gate; negative-case timings alone do not establish it.

PVPF availability is separate from historical-peer acceptance. Native cycle times
describe the current prediction hour, not full period-energy bounds. Keep actual
matching unavailable until separately documented intervals are supplied; never
allocate a daily forecast to incomplete actuals. The separate hourly adapter in
#542 is a possible integration point. #510 remains future planning; #501 is not
completed by this work. See the [user contract](../user/comparable-days.en.md).
