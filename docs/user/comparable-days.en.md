# Qualitative comparable days

`loxone_analyze_history(operation="comparable_days")` compares recorded weather
source points by radiation classes. It is a coarse comparison, not a radiation
energy calculation or a weather-normalized yield assessment.

The Weather Service documents classes 0 (very low), 1 (low), 2 (moderate) and
3 (high). The classification origin appears explicitly in the result. A native
mapping is not established merely because a raw value lies between 0 and 3;
unknown mappings produce `insufficient_evidence`. The native 0-3 mapping is an owner-approved assumption of 13 October 2026
and remains explicitly labelled as not technically verified. Unexpected values remain in the archive and
appear as bounded diagnostics with source time, raw numerical value and reason.
They are not used as valid classes. The tool warns the AI to inform the user and
emits a sanitized log event correlated with the response's trace ID. The warning
means the data does not fit the assumed mapping, not that a device fault is proven.
See the [official class descriptions](https://www.loxone.com/enen/kb/weather-service/).

Configure the actual weather source and its `solar_radiation` field in Admin.
Recording is opt-in and establishes no earlier history. Reading requires fresh
`loxone:read`/`loxone:history` authorization and enabled history. Select one exact
currently visible/configured source or a currently confirmed actual-weather
profile binding for that field. Forecasts are excluded.

```json
{
  "operation": "comparable_days",
  "sources": [{
    "source_kind": "structured_weather",
    "state_uuid": "<actual weather UUID>",
    "stored_mode": "actual"
  }],
  "start": "2026-10-01T00:00:00+02:00",
  "end": "2026-10-08T00:00:00+02:00",
  "timezone": "Europe/Berlin",
  "comparable_day_options": {
    "reference_day": "2026-10-07",
    "method": "radiation_classes",
    "start_hour": 10,
    "end_hour": 14,
    "maximum_seasonal_days": 30
  }
}
```

The UUID placeholder must be replaced with an authorized source identifier.
The interval must be past and nonempty and touch at most 31 local days. A fixed
local-hour window is shared by the reference and candidates; running reference
days use only completed hours. Each selected hour needs its hour-start source
point. Missing positions never shrink a candidate's comparison window. Ambiguous
or nonexistent daylight-saving positions are excluded. Matching class sequences
sort by seasonal distance and date, with reasons and exclusions in the result.

The reader uses one bounded reception-index query and retains the latest eligible received
version per source point. Both reception and source position must lie in the
requested interval; older source points and later receptions do not backfill it.
Reception/capture coverage does not prove continuous measurements. Provider or
station changes may remain undetectable. The result is compact; raw pages and
cursors are not offered by this operation. Existing scalar operations are unchanged.

There is no 15-percent irradiance tolerance, radiation energy, temperature-based
selection, normalized yield, fault diagnosis or self-consumption calculation in
this class method. Brightness in lux is additional context, not a universal
conversion to W/m2. Numerical comparisons need separate qualified historical
sources and interval semantics; they remain open in #439.
