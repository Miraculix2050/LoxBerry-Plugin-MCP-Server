# Local solar history: technical acceptance

The owner revised the closeout criteria on 20 October 2026. Technical source-read
and calculation evidence replaces a positive comparison of real historical days
as the closeout gate for #439/#509. Real comparison days, multi-day collection
and matched positive real-history performance are no longer closure requirements.
This decision does not relax runtime input qualification or missing-data behavior.

Delivered stages: [#544](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/544)
normalization, [#549](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/549)
local recording/PVPF, [#550](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/550)
numerical runtime, [#551](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/551)
acceptance boundaries and [#577](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/577)
native EFM self-consumption and bounded phase diagnostics.

## Evidence required for closeout

| Criterion | Evidence |
| --- | --- |
| Real source reads | Reserved read-only native weather/radiation/temperature and hourly PV/EFM reads, declared units, capture/time contracts and owner-confirmed plant associations. Existing Browser/MCP/SSH evidence may be reused. |
| Normalization | `test_solar_history.py`: known integration/unit-conversion results, no extrapolation, bounded gaps, duplicate/source rules and explicit estimates. |
| Selection and deviations | `test_comparable_days.py`: inclusive tolerances, three-peer groups, strict anomaly threshold, zero denominators, fixed completed-hour windows and DST exclusions. |
| Integrated calculation | `test_numerical_day_tools.py`: hand-calculated PV/self-consumption medians and ranking for complete/running days, matching/mismatched export balance, missing evidence, source isolation and one read per source/range. |
| Authorization and resources | Existing contract regressions for revocation, source changes, limits, deadlines/cancellation, compact output and unchanged qualitative calls; existing bounded timing/size measurements plus correlated phase tests. |
| Delivery | Current-head Full CI, resolved relevant review findings, paired DE/EN guidance and scoped technical Browser/MCP/SSH acceptance. |

Synthetic reference cases establish arithmetic and software contracts, not an
empirically validated plant, calibrated weather measurements or fault diagnosis.
A representative native read proves readability, not physical observation lineage.
Weather-service values remain identified by their provenance; unknown provider
clock/measurement details remain unknown. Forecasts and PV-derived radiation
cannot be relabelled as independent observations. Unqualified or missing runtime
inputs still produce an explained unavailable result. Recording never backfills,
rewrites outage zeroes or converts reception coverage into measured coverage.

Detailed dated evidence remains in the owner's private Project-Data archive.
Reuse successful unchanged target checks; this documentation/test closeout does
not itself require another deployment, recorder change or multi-day campaign.

PVPF forecast/actual matching and positive future planning remain separate in
#510. Aggregate cycle times do not establish full period-energy bounds; never
allocate daily forecasts to incomplete actuals. #501 is not completed or waived.
See the [user contract](../user/comparable-days.en.md).
