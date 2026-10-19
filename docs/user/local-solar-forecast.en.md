# Local irradiance forecasts

The existing weather tool can discover one qualified local forecast and compare
sampled future solar windows. This is weather guidance in W/m², with no claim of
PV yield, surplus, permitted device operation or savings. Lux has no universal
conversion to W/m². Native Loxone integer weather fields remain unqualified.

In Admin → Configuration → Local irradiance forecast, review the local
Weather4Lox VisualCrossing hourly source. Check its location and timezone against
the configured Miniserver installation. Explicitly confirm this association,
enable the source and save. This is off by default. Set a maximum local file
publication age (default 180 minutes); that is not proven forecast model age.
Changing source location, timezone or Miniserver requires renewed confirmation.
Disabling the adapter preserves the source file. No cloud request is made by
this adapter and no arbitrary source path or URL can be supplied.

The MCP client also needs `loxone:read`, independently enabled LoxBerry reads,
`loxberry:read` and a current local administrator approval for that client.
A Loxone login alone grants no local file access. Start with
`loxone_get_weather(mode="forecast_sources")`. This checks only the registered
local source. Disabled or unapproved sources are not probed. Missing, unsupported,
changed and stale sources are distinguished; explain the returned configuration
guidance and how qualified point predictions help compare future solar windows.
A future Config MCP import requires a separate explicit user instruction.

For `mode="solar_windows"`, supply `future_options` with future offset-aware
`start`/`end`, IANA `timezone`, `duration_hours` (1–24) and an optional nonnegative
`minimum_sample_irradiance_w_m2`. The range touches at most 31 local days.
At most 16 nonoverlapping examples are ranked by mean sample irradiance, then
earliest sample time. `include_samples=true` optionally returns the points.
No cursors or history options apply. Original actual/forecast/history modes and
their default behavior remain available.

Hourly samples are point predictions. Nominal window ends and sample means do
not prove conditions between samples or interval-mean irradiance. Do not integrate
them into Wh/m² or convert them to PV Wh. Local publication, source-reported
generation, unknown provider issuance and unknown confidence remain separate.
Invalid values are excluded from usable windows with bounded diagnostics and a
correlated warning log; the original file is retained. Unsupported numeric
precision retains numeric-only original text up to 256 characters. Inform the
user of these limitations without claiming a proven device fault. Gaps are not
interpolated. Actual PV-yield planning additionally needs qualified plant and
load evidence; native locks and allowed load schedules remain unknown.
The full planning follow-up is [#510](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/510).

For native PVPF hourly forecasts and conditional load scenarios see [PV planning](pv-planning.en.md). They use a separate native source; the weather windows above remain W/m² guidance.
