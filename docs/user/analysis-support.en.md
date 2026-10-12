# Analysis questions: support and boundaries

Energy & solar PR 4 adds confirmed weather-source bindings and optional declared
PV parameters. This context alone does not deliver solar-20–22: structured weather
history, numeric radiation semantics and the comparison method remain required.
Existing statistic/state weather sources retain their actual coverage and semantics.

The original 25 questions remain in the versioned acceptance catalog. Two later KNX cases are separate extensions. Snapshot: Analysis foundation PRs 1–8, 11 October 2026. Labels describe the evidenced answer scope, not exhaustive hardware coverage or 75 independent AI runs.

Supported: a bounded existing read workflow. Conditional: required sources, semantics, bindings and coverage must exist. Unavailable: the required feature belongs to open external workstreams. Experimental: advice requires additional user evidence and specialist review. Gen. 2/Compact remain experimental without matching device acceptance.

| ID | Question / operation | Status | Workflow and allowed boundaries |
| --- | --- | --- | --- |
| lighting-01 | scene inventory | conditional | `loxone_get_structure_overview` → `loxone_describe_control`; Visible scenes only; absent visibility does not prove absent configuration. |
| lighting-02 | naming review | supported | `loxone_find_controls` → `loxone_describe_control`; Naming candidates only; no duplicated physical circuit claim. |
| lighting-03 | presence links | conditional | `loxone_find_project_objects` → `loxone_trace_project_logic`; Explicit project links required; room membership is not a connection. |
| lighting-04 | lighting advice | experimental | `loxone_get_installation_profile` → `loxone_describe_control`; Planning advice needs user intent and fixture inventory; no automatic suitability proof. |
| lighting-05 | scene roles | conditional | `loxone_get_installation_profile` → `loxone_describe_control`; Scene roles must be confirmed; labels alone are not technical roles. |
| lighting-06 | context review | experimental | `loxone_find_project_objects` → `loxone_get_installation_profile`; Qualified design review only; specialist lighting work remains outside this foundation. |
| basic-07 | temperature summary | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; temperature_summary: actual-temperature unit and UTC samples; sample mean is not time weighted. |
| basic-08 | consumer energy | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; energy: optional consumer, confirmed boundary; counter endpoint differences remain partial with unknown resets. |
| basic-09 | active controls | conditional | `loxone_find_controls` → `loxone_get_state_semantics`; Known operational states only; unknown controls prevent a complete installation-wide answer. |
| basic-10 | home temperature | supported | `loxone_find_controls` → `loxone_get_state_semantics`; Exact current actual temperatures, with freshness and explicit units; no inferred house average. |
| basic-11 | kitchen light | conditional | `loxone_find_controls` → `loxone_get_state_semantics`; Select the visible kitchen control and proven operating state; do not infer from names or arbitrary numeric values. |
| basic-12 | room temperature | supported | `loxone_find_controls` → `loxone_get_state_semantics`; Room selection must be explicit; report actual temperature separately from target. |
| basic-13 | door contact | conditional | `loxone_find_controls` → `loxone_read_controls`; Exact authorized contact and proven direction; present configuration is not historic state. |
| solar-14 | yield comparison | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; energy per explicit local period; confirmed production binding and complete evidence required for full-day claims. |
| solar-15 | native balance | unavailable | `loxone_describe_control`; Native EFM period balance depends on #436/#363/#364; no parallel balance engine. |
| solar-16 | aligned curves | conditional | `loxone_analyze_history`; pv_load_overlap plus opt-in source-separated UTC raw pages; hourly energy is not instantaneous power or grid flow. |
| solar-17 | pv overlap | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; pv_load_overlap with optional observed enable signal; complete active hours only, upper bound rather than exact solar attribution. |
| solar-18 | consumer ranking | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; consumer_ranking requires explicit comparability confirmation; exclude parent/child overlap and do not sum independent ranks. |
| solar-19 | retrospective shift | unavailable | `loxone_analyze_history`; Historical observations may inform a qualified response; load-shifting recommendations remain #440. |
| solar-20 | similar days | unavailable | `loxone_get_statistics`; Historical weather and matched-day method remain #439. |
| solar-21 | self consumption difference | unavailable | `loxone_get_statistics`; No causal self-consumption explanation without native EFM, historical weather and context (#436/#439). |
| solar-22 | low yield | unavailable | `loxone_get_statistics`; Weather-normalized anomalies and installation parameters remain #439. |
| solar-23 | night base load | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; baseload uses verified whole-hour energy-derived mean power in local 00-05; daily extrapolation is an estimate of the selected channel. |
| solar-24 | periodic report | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; Qualified component report only; native self-consumption/export/import remain #436, gaps and unknown rest/storage must stay explicit. |
| solar-25 | future windows | unavailable | `loxone_get_weather`; Tomorrow load/PV forecasts and operating constraints remain #440; weather alone does not establish a schedule. |

Numeric references: sample mean 21 °C; counter difference 3 kWh; rank 3/2 kWh; mixed hourly window 3600 s; night median 100 W and estimated 2.4 kWh/day. Conversion of evidenced synthetic power intervals into whole-hour energies is a fixture contract, not a new decoder. Details and measurement limits: [Acceptance report](../development/analysis-acceptance.md).

Correct qualified partial answers are allowed when sources are absent. No roles inferred from names, backfilled initial values, hidden identities, control commands or causal solar attribution. Token consumption and the 20-percent token target remain incomplete without available token measurements; response bytes are not tokens.
