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

## Conditional future load planning

Use `loxone_plan_loads(options=...)` with `forecast_control_uuid`, offset-aware
future `start`/`end`, `timezone`, and up to 16 `consumer_binding_ids` from the
confirmed installation profile. Supply `baseload` and `storage_reserve`, each
with `origin="user_confirmed"` or `"user_estimate"` and either `constant_w` or
`hours=[{"start":<Unix hour>,"power_w":<W>}]`. Zero reserve is an explicit
scenario, never inferred battery absence. Do not include selected flexible loads
in the baseload. Missing scenario hours exclude those hours from planning.

Every load needs confirmed flexibility and `cycle_identity="user_confirmed_cycle"`.
Measured complete cycles are selected from the last seven completed local days
(`history_days` 1–31); this requires activated loxone:history and existing local
activity history. Otherwise a confirmed declared cycle energy and duration are
used as a uniform estimated load profile. No recorder is automatically enabled.

The planner assigns one contiguous cycle per selected consumer using the
remaining shared hourly PV energy after baseload and storage reserve. It respects
declared windows and completion limits. Known supported current locks exclude
a load; future locks, external activity and minimum-off-time clearance remain
conditions to confirm before operation. Hourly budgets assume within-hour energy
availability and cannot establish subhour power sufficiency. No battery discharge
is planned. Read the output assumptions, unplanned reasons and limitations.

At most 72 forecast hours, 16 loads, 100,000 historical points, 100,000 candidate
evaluations and 64 KiB output are admitted within 30 seconds. History and future
planning share two analysis slots. One PVPF forecast is read per plan; search
performs no source I/O. Results describe conditional PV coverage and additional
grid energy, not measured savings, an optimal schedule or operating permission.

## Tool Explorer

In the authenticated Explorer first discover PVPF, then select
`loxone_read_controls`, one target and `native_result_view=pv_forecast`.
For `loxone_plan_loads`, use the JSON editor for the structured `options` object
and the confirmed profile identifiers. Submit the explicit scenarios; the UI
never chooses a battery reserve or operates a device. Conditional windows show
UTC boundaries, PV coverage and additional grid energy; the full result retains
assumptions, conditions and unplanned reasons. An unavailable source has a
separate visible explanation. No configuration change is needed to expose the
new tools after the plugin update.

A current native `ready=0` returns `not_ready` without requesting unavailable hourly data. Authorization and source visibility are still rechecked.

An unknown or stale current native lock is explicitly reported as `native_current_lock_unresolved`; it is never a confirmed clear lock.
