# Comparable days

## Numerical weather peers

Select `comparable_day_options.method="numerical"` explicitly, with `reference_day`.
Defaults: hours 0–24, seasonal distance ≤30 days, radiation-energy difference ≤15%,
temperature difference ≤3 °C. Stricter options are allowed. All candidates use the
fixed reference window; current reference days use completed hours. Missing data
never shrinks that window; ambiguous DST positions are excluded.
The requested end also caps completed reference hours. Confirmed profile roles
do not establish hourly energy semantics: unqualified statistics remain
unavailable; qualified statistics with missing values report incomplete coverage.

Register independent irradiance and outside-temperature sources in Admin with
documented units, cadence and confirmed installation association. Enable recording;
existing records remain readable when recording is disabled. Select each via
`{"source_kind":"solar_observation","control_uuid":"<control UUID>","state_uuid":"<value UUID>"}`.
The caller cannot supply evidence rules or units. Names never establish roles;
sources may be absent. Irradiance derived from the PV yield under assessment is
circular and unsuitable.

Select PV through `{"binding_id":"<confirmed production binding>","granularity":"hour"}`
with documented hourly energy statistics. A `self_consumption` binding supplies
direct PV self-consumption. Alternatively `pv_export_balance_confirmed=true`
explicitly confirms PV minus export, excluding storage discharge and other
generation. Matching confirmed profile boundaries and declared export direction
are additionally required. No storage model is inferred or negative balance clamped.

W/m² source-state observations are integrated trapezoidally into estimated Wh/m²:
no extrapolation, no gaps above twice the cadence, capped at 60 minutes.
Temperature uses the nearest recorded state within 60 seconds of hour start,
also bounded by cadence; the maximum actual offset is reported. This does not
prove continuous physical measurement. Weather similarity selects peers; no
additional physical PV normalization model is introduced.

Results explain selection, exclusions, tolerances, coverage and missing-source
setup. Peers sort by weather similarity. PV and self-consumption provide pairs
and a median group with at least three complete peers. PV strictly below −20%
marks a check candidate, never a fault diagnosis. A separate ranking shows the
strongest negative differences. Zero baselines have no ratio.

Optional PVPF uses the same selector with `state_uuid=null`. The latest eight
captured snapshots remain separate forecast context, with capture time, issue
time and native cycle times. Structure File 17.1 p.115 defines cycle times as the
current prediction hour, not the bounds of the complete `period` energy. Its
actual comparison remains `native_period_bounds_unverified`. Daily horizons have
no independently established native timezone here and are never allocated to
partial days. A future documented hourly adapter can supply exact valid periods;
only forecasts captured before those periods may then match complete actuals.
Forecasts do not select weather peers.

Each unique source/range is read once in one fresh authorized context. Limits:
16 sources, 100,000 points, 31 local days, 30 seconds, two analyses, 64 KiB.
Recording never backfills observations. Real multi-day acceptance remains required
before #509 and #439 close.

## Qualitative radiation classes

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
sources and interval semantics through the explicit numerical method above.
