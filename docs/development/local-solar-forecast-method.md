# Local irradiance forecasts and sampled solar windows (PR 9)

Predecessor: merged #507 / 37861f29. Parent: #440. The owner approved documented
W/m2 forecasts for conditional solar-window guidance, source discovery and
configuration suggestions. No local PV-yield forecast is known. Irradiance
does not establish plant output, available surplus, load admissibility or savings.
Future Loxone Config MCP imports remain a separately requested future integration.

## Source evidence

The installed Weather4Lox Visual Crossing driver copies `solarradiation` into
hourlyforecast.json `solarRadiation`; its installed v1 schema specifies W/m2.
Read-only production inspection found future hourly records with offset-aware
timestamps matching UTC epochs, including DST. These observations establish
the available source shape, not general plugin/provider compatibility.

The primary [provider API contract](https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/)
describes this field as forecast power at the prediction timestamp. Its separate
`solarenergy` field has accumulated-energy meaning. Other provider pages refer
to associated hourly periods or typical averages of extended fields. Treat this
adapter's values as timestamped irradiance samples; do not integrate them into
Wh/m2, assert interval-start/end energy or convert them to PV Wh/kWh.
The [source driver](https://github.com/Jan21493/LoxBerry-Plugin-Weather4Lox/blob/v4-prod/bin/grabber_visualcrossing.pl)
and [solar-element documentation](https://www.visualcrossing.com/resources/documentation/weather-api/energy-elements-in-the-timeline-weather-api/)
support a named, versioned source rule rather than inference from field names.

Native Loxone weather integers remain raw, unit-unverified values. The existing
owner-assumed 0-3 comparison mapping does not become W/m2. Names, lux or magnitudes
cannot qualify an arbitrary Miniserver state as a forecast.

## Local policy and configuration

Extend existing `loxone_get_weather` with `forecast_sources` and `solar_windows`;
do not add a tool or change actual/forecast/history defaults. Historical reads
keep their past-only gate. New local modes additionally require `loxberry:read`,
currently enabled local LoxBerry read policy and a matching live local approval.
A Loxone login never grants LoxBerry administration or this dataset access.

Use a default-off MCP setting for the one fixed Weather4Lox Visual Crossing v1
hourly file. Accept no path, URL, arbitrary provider, cloud request or API key.
LoxBerry Admin must review/confirm that this dataset belongs to the installation.
Capture a private source-identity fingerprint from normalized location/timezone,
registered format/provider and configured target origin. Expose no coordinates,
location text or private fingerprint. Source identity/target changes require
renewed local confirmation, not automatic retargeting. Enabling the adapter does
not change Weather4Lox configuration or implicitly enable LoxBerry read grants.

Disabled/unapproved sources are not probed. Discovery reports explicit disabled,
unapproved, missing, unsupported, changed, stale or available states and bounded
setup guidance. A disabled adapter is not evidence that the plugin is missing.
Missing qualifying sources must produce actionable configuration explanations,
not inferred data. Native unit-unverified forecasts remain accessible through
their unchanged forecast mode.

## Forecast contract

Bound file reads to 4 MiB, records to 768 and processing to the existing shared
two-worker/30-second admission. Reject duplicate JSON keys and unsupported
provider/version/shape. Validate number types/finiteness, IANA timezone, explicit
per-record offsets and agreement with integer UTC epochs. Missing, invalid,
duplicate or gapped points remain diagnostics; exclude them from usable windows
without changing the source file. Publish at most 16 safe diagnostics with total
count/truncation and sanitized correlated warnings for unexpected values.

Keep local file publication time/age separate from source-reported generation
time and provider forecast issue time. Provider issue time and confidence are
not established by this source and remain unknown. A configurable publication
age limit defaults to 180 minutes; publication freshness is not provider/model
freshness. Future publication clocks and stale publication cannot qualify.
Do not interpret the source's ambiguous refresh metadata as a freshness promise.

MCP output includes the registered source/rule, quantity/unit, point timestamp
basis, timezone, sample horizon, publication age, explicit uncertainty, declared
installation association and missing-evidence/setup guidance. Do not return the
foreign document, credentials, private paths or location metadata. Verify current
local policy/source identity and unchanged document before publication; changed
files fail with a retryable uncertainty result. No cache replaces authorization.

## Sampled future windows

Strict future options specify an offset-aware future start/end, IANA timezone,
duration of 1-24 hours and nonnegative minimum sample irradiance. Limit to 31
touched local days; this gate is independent of historical validation. Consider
only hourly sequences of the requested number of valid forecast samples. No
interpolation or gap bridging. The end is a nominal window boundary, not proof
that conditions persist between or after the sampled points.

Rank by mean sample irradiance, then earliest sample timestamp. Publish at most
16 nonoverlapping sampled examples with optional bounded samples only by opt-in.
The arithmetic mean of point predictions is not time-integrated irradiance or
plant energy. Zero-only sequences do not establish a solar opportunity.
Output remains weather guidance with unknown forecast confidence. PV-yield,
baseload/surplus allocation, native locks and device constraints are unqualified;
no allowed load schedule, operation or financial benefit is claimed.

## Delivery

Review the source/typed method before integration. Preserve old weather schemas,
fresh local approvals, rate limits, output bounds and cancellation admission.
Update canonical schemas/Explorer, skill guidance, DE/EN configuration/user docs,
support matrix and changelog. Separate installed source fixtures from genuine
source discovery and preserve other target work. #501 remains excluded/unclaimed.
#440 is not closed as complete PV-yield planning without its additional evidence.
