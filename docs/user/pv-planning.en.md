# Native PV production forecasts

Discover a visible `PvProductionForecast` with `loxone_find_controls`, then call
`loxone_read_controls(targets=[{"control_uuid":"<discovered UUID>"}], native_result_view="pv_forecast")`.
This read needs `loxone:read`, not local LoxBerry file approval. No control or
configuration is changed. The existing EFM views retain their own requirements.

The native `getForecasts` command supplies hourly kWh for today, tomorrow and the
day after tomorrow. The result normalizes these to Wh with Unix hour boundaries.
Aggregate states remain separate. State timestamps use the Loxone 2009 epoch;
forecast timestamps use Unix. Missing hours are not interpolated.

A ready block, zero error status, prediction timestamp no more than three hours
old and usable hourly values are required for availability. Ready=0 and -1
aggregate values mean no usable prediction. ErrorInfo is a native bitmask:
bit 1 indicates WeatherServiceError, bit 0 InternetError. These do not establish
an expired subscription or a particular network fault. Source publication and
forecast confidence are not supplied. Native forecasts are model estimates and
do not account for inverter limitations; compare them with real production.

The PVPF needs an active Loxone Weather Service and a configured installed kWp
value. Report missing setup; do not activate, subscribe or reconfigure automatically.
Native forecast support is distinct from the existing W/m² weather guidance.

A current native `ready=0` returns `not_ready` without requesting unavailable hourly data. Authorization and source visibility are still rechecked.
