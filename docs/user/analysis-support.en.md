# Analysis questions: support and boundaries

The [read-only MCP prompt recipes](mcp-prompts.en.md) make available workflows
selectable with parameters. Retrieval runs no analysis and extends no domain
coverage (#444).

Current addition: [native PVPF forecasts and conditional future planning](pv-planning.en.md) use a separate PV source and confirmed load profiles. The retained solar-25 case below describes the original weather-only acceptance; it does not establish source, device or AI acceptance of the new planner.

Renewed #485 acceptance uses bytes, complete call counts, cold/warm durations and
domain answer quality. Token metrics are optional; bytes do not establish token
or cost savings. The original campaign retains its consumed 21 of 50 records.
The owner's 19 October follow-up permits at most 20 additional records, with
1–3 targeted answers per change (initially two for the combined activity fix).
Failures remain counted; this is no counter reset or full 25-question campaign.
Changing the criteria does not constitute passed acceptance; earlier measurements retain their
evidenced limitations.

For “what is switched on?”, distinguish documented logical control activity,
documented inactivity and not determinable. Current values and complete delivery
are not semantic or physical proof. Read semantic evidence before interpreting
activity; unknown/omitted meaning is never off. Dimmer position now has documented
numeric meaning, but no inferred percent scale or on/off predicate. Switch activity
encoding remains unverified. Names, moods and lock states do not close those gaps.

PR 6 adds [qualitative radiation-class peers](comparable-days.en.md) under an
explicitly owner-assumed native mapping. Unexpected values remain in the archive
and appear as bounded diagnostics with an AI warning and correlated sanitized
log. This does not complete solar-20-22 or qualify numerical irradiance.

Energy & solar PRs 4–5 add confirmed weather-source bindings, optional declared
PV parameters and independently opt-in [local weather recording](weather-history.en.md).
This does not yet deliver solar-20–22: numeric radiation semantics and the
numerical comparison method remain required; recording does not backfill earlier days.
Existing statistic/state weather sources retain their actual coverage and semantics.

The original 25 questions remain in the versioned acceptance catalog. Two later KNX cases are separate extensions. Snapshot: Analysis foundation PRs 1–8, 11 October 2026. Labels describe the evidenced answer scope, not exhaustive hardware coverage or 75 independent AI runs.

Supported: a bounded existing read workflow. Conditional: required sources, semantics, bindings and coverage must exist. Unavailable: the required feature belongs to open external workstreams. Experimental: advice requires additional user evidence and specialist review. Gen. 2/Compact remain experimental without matching device acceptance.

| ID | Question / operation | Status | Workflow and allowed boundaries |
| --- | --- | --- | --- |
| lighting-01 | scene inventory | conditional | `loxone_get_structure_overview` → `loxone_describe_control`; Visible source moods via lighting_context only; preserve freshness and omission limits, never infer complete scene inventory. |
| lighting-02 | naming review | supported | `loxone_find_controls` → `loxone_describe_control`; Naming candidates only; no duplicated physical circuit claim. |
| lighting-03 | presence links | conditional | `loxone_find_project_objects` → `loxone_trace_project_logic`; Explicit project links required; room membership is not a connection. |
| lighting-04 | lighting advice | experimental | `loxone_get_installation_profile` → `loxone_describe_control`; Planning advice needs user intent and fixture inventory; no automatic suitability proof. |
| lighting-05 | scene roles | conditional | `loxone_get_installation_profile` → `loxone_describe_control`; Source mood naming candidates via lighting_context; names do not establish scene roles. |
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
| solar-20 | similar days | conditional | `loxone_analyze_history`; Explicit numerical comparable_days use confirmed local radiation/temperature and hourly PV; self-consumption requires a direct or confirmed compatible balance. Real multi-day acceptance remains #509/#439. |
| solar-21 | self consumption difference | conditional | `loxone_analyze_history`; Numerical comparable_days quantify direct/qualified self-consumption differences with fixed weather peers; causes still require context. No storage model or fault diagnosis (#436/#439). |
| solar-22 | low yield | conditional | `loxone_analyze_history`; Numerical comparable_days rank weather peers and negative PV differences; groups require three complete peers. Seasonal proximity is not exact solar geometry; real acceptance remains open (#439). |
| solar-23 | night base load | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; baseload uses verified whole-hour energy-derived mean power in local 00-05; daily extrapolation is an estimate of the selected channel. |
| solar-24 | periodic report | conditional | `loxone_get_installation_profile` → `loxone_analyze_history`; Qualified component report only; native self-consumption/export/import remain #436, gaps and unknown rest/storage must stay explicit. |
| solar-25 | future windows | unavailable | `loxone_get_weather`; Tomorrow load/PV forecasts and operating constraints remain #440; weather alone does not establish a schedule. |

Numeric references: sample mean 21 °C; counter difference 3 kWh; rank 3/2 kWh; mixed hourly window 3600 s; night median 100 W and estimated 2.4 kWh/day. Conversion of evidenced synthetic power intervals into whole-hour energies is a fixture contract, not a new decoder. Details and measurement limits: [Acceptance report](../development/analysis-acceptance.md).

Correct qualified partial answers are allowed when sources are absent. No roles inferred from names, backfilled initial values, hidden identities, control commands or causal solar attribution. The former mandatory token target was replaced for #485; missing optional token values remain unknown and do not block closure. Response bytes establish no token or cost savings. The [bounded native acceptance](../development/analysis-acceptance-closeout.md) separates measured results from remaining limits.


## Request-local energy planning (#556)

The optional analysis context supports one explicitly selected common supply
budget with up to four confirmed disjoint PVPFs, profile references, real declared
cycles and explicitly hypothetical loads. Native EFM membership remains separate
from user associations. Multi-plant fixtures prove isolation and calculation,
not real multi-plant compatibility. Legacy calls remain supported. Positive real
PVPF/consumer acceptance remains open under #440/#510; fixtures cannot replace
missing real sources.

Direct self-consumption can use the exactly qualified native EFM
`totalSelfConsumption` series. It remains labelled as an EFM calculation; plant
association and complete hourly coverage require their own evidence.
