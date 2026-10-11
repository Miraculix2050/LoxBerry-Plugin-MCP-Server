# Analysis questions and evidence

The acceptance catalog covers six lighting questions, seven state/history
questions and twelve solar questions. Issues #434, #435, #437, #438 and #445 extend
the foundations incrementally. This overview describes the baseline; it does not
confirm any particular installed version or hardware.

| Question area | Baseline | Requirements and limitations |
| --- | --- | --- |
| Current room temperature, kitchen light, door contact, active controls | conditional | Fresh visibility and proven state semantics; stale or unknown values remain unresolved. |
| Mean temperature and consumer energy | conditional | Suitable history, measurement role, unit, period and coverage; a heat pump is optional. |
| Light names, scenes and presence associations | conditional | Visible structure and evidenced project relationships; planning advice needs user intent and fixture data. |
| Solar yield, curves, consumer overlap, ranking, base load and report | conditional | Confirmed measurement sources and suitable history; shared analysis core not yet delivered. |
| Native energy balance and complete self-consumption values | unavailable | Depends on pending evidenced EFM projections and native results. |
| Weather comparisons, weather-adjusted anomalies and causes | unavailable | Requires further roadmap work and historical weather data. |
| Load shifting and tomorrow's operating windows | unavailable | Requires confirmed operating constraints, load profiles and a suitable PV forecast. |

“Conditional” means that the necessary data and semantics must actually exist;
it does not promise a complete automated analysis. “Supported” requires matching
acceptance evidence. “Experimental” describes a delivered capability with
explicitly outstanding compatibility evidence.

A qualified partial answer is correct when sources are missing. Do not infer
roles from names, invent history, or present coincidence as causation or exact
solar attribution. Analysis performs no control commands.

Details: [Acceptance procedure](../development/analysis-acceptance.md).
