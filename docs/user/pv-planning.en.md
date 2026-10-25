# Native PV production forecasts

Discover a visible `PvProductionForecast` with `loxone_find_controls`, then call
`loxone_read_controls(targets=[{"control_uuid":"<discovered UUID>"}], native_result_view="pv_forecast")`.
This read needs `loxone:read`, not local LoxBerry file approval. No control or
configuration is changed. The existing EFM views retain their own requirements.

The native `getForecasts` command supplies hourly kWh for today, tomorrow and the
day after tomorrow. The result normalizes these to Wh with Unix hour boundaries.
The adapter accepts the direct JSON forecast object and previously supported
`LL` responses. Other commands retain their response-envelope check; error
responses and invalid forecast data are still rejected.
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

Forecast read failures distinguish timeouts, protocol errors, rejected requests,
connection errors and unavailable authorization storage through fixed sanitized
messages. The error category remains `temporarily_unavailable`; the message does
not include raw server responses or credentials. This applies to both native
forecast reads and the planner. A connection or protocol failure is not evidence
of missing forecast configuration. Failed reads are not automatically retried.

With Debug logging enabled, one bounded runtime event identifies the failed step
(snapshot, token lookup, session establishment, forecast command, structure
recheck or forecast decoding) and a fixed cause label. Connection causes distinguish
WebSocket closure, connection establishment failure, source-IP blocking and an
invalid response envelope; unclassified causes remain unknown. The event's
`trace_id` matches the MCP error. No payloads, exception text, control identities
or credentials are logged. These details are omitted at Info level.

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

### Request context instead of a persistent profile

Alternatively provide `analysis_context` in `options`, omitting legacy
`forecast_control_uuid` and `consumer_binding_ids`. Time range, timezone, baseload
and storage reserve remain required. The context contains `scope` (selected `efm`
with `monitor_uuid`, or an explicit `scenario`), `assets`, `forecasts` and `loads`.
Each request has one supply budget; separate requests are not coordinated schedules.

Each asset has a request-local `asset_id`, description, optional
`production_control_uuid` and `association_origin`. Each forecast specifies its
`control_uuid`, covered `asset_ids` and `coverage_origin`. Multiple forecasts
(at most four) require confirmed common supply and disjoint coverage
(`user_confirmed`); otherwise only one explicitly assumed scenario forecast is
allowed. Only common complete hours are summed. A visualization-only PVPF is not
automatically misconfigured because no wire connects it to a meter.

Loads have `load_id` and `kind`: `profile` references `binding_id`; `real` uses a
visible `control_uuid` and confirmed declared `cycle`; `hypothetical` uses only a
scenario cycle without a device identity. The cycle specifies timezone, windows,
completion, duration, interruptibility, minimum run/off times, `cycle_energy_wh`,
`origin` and rationale. Declared energy is distributed uniformly and is not a
measurement. Hypothetical cycles must use `origin="scenario_assumption"`.

Only native participants establish EFM membership. Additional loads require an
explicit scenario. Native membership does not prove physical measurement scope.
Unknown socket loads require a clearer device description, not an invented
consumer. Requests never persist profile confirmations. The new result
`conditional_context_planning.v1` retains individual forecasts, coverage,
provenance, load models and unresolved associations. Hypothetical loads do not
satisfy real consumer acceptance. New context inputs are bounded to 64 KiB;
existing computation/output limits remain unchanged.

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

Example for `options.analysis_context` only; replace the UUID and supply the future
time range, baseload and storage reserve in `options`. Numbers are assumptions:

```json
{
  "scope": {"kind": "scenario", "description": "Example only",
            "common_supply_origin": "scenario_assumption"},
  "assets": [{"asset_id": "pv", "description": "Explicit example coverage",
              "association_origin": "scenario_assumption"}],
  "forecasts": [{"control_uuid": "<visible PVPF UUID>", "asset_ids": ["pv"],
                 "coverage_origin": "scenario_assumption"}],
  "loads": [{"load_id": "example", "kind": "hypothetical", "cycle": {
    "timezone": "Europe/Berlin",
    "windows": [{"weekdays": [0,1,2,3,4,5,6], "start": "09:00", "end": "17:00"}],
    "latest_completion": "17:00", "duration_seconds": 3600,
    "interruptible": false, "minimum_run_seconds": 0, "minimum_off_seconds": 0,
    "cycle_energy_wh": 1000.0, "origin": "scenario_assumption",
    "rationale": "Illustrative complete job; no real appliance claim"
  }}]
}
```
