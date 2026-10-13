# Observed load cycles

`loxone_analyze_history(operation="operating_phases")` can describe observed
activity episodes when a confirmed consumer binding contains usable load
constraints and references a confirmed binary operating-state binding. This is a
historical, read-only analysis. It does not schedule or operate the load.

## Select confirmed sources

Configure the exact consumer energy statistic and its operating-state binding
in the installation profile. Declare time windows, timezone, latest completion,
duration, interruptibility and minimum run/off times; then confirm the whole
consumer binding. Provenance distinguishes complete measured intervals from a
user-declared cycle Wh value. Neither a role nor a declaration proves technical
energy units or interval meaning. This operation needs `loxone:read` and
`loxone:history`, enabled history and retained local state coverage.

```json
{
  "operation": "operating_phases",
  "sources": [
    {"binding_id": "my-consumer", "granularity": "hour"},
    {"binding_id": "my-operating-state", "granularity": "raw"}
  ],
  "start": "2026-10-11T00:00:00+02:00",
  "end": "2026-10-12T00:00:00+02:00",
  "timezone": "Europe/Berlin"
}
```

Replace both example IDs with currently visible confirmed bindings. The consumer
constraints must reference this exact operating-state binding. The period must
be past and touch at most 31 local days. Source reads share one freshly authorized
context and the existing point/deadline limits. If the profile changes during
analysis, the tool fails before returning a cycle result; read and review again.

## Interpret evidence and limitations

Inspect `comparison.load_cycles`. False-to-true-to-false edges inside one
continuous capture phase establish a complete observed activity episode. Initial
active values, query edges, restarted captures, missing/unknown states and gaps
remain incomplete diagnostics. Recorded local observation edges do not by
themselves prove native program identity.

`active_episode_only` is the default. An explicit `user_confirmed_cycle`
declaration is recorded as user-origin identity; it is not verified native
program identity. `native_lock_status="not_checked"` and
`planning_status="not_evaluated"` remain explicit. No lock is declared clear.

`energy_profile_complete` requires complete qualified hourly Wh/kWh interval
energies that tile the entire episode. Partial hours are not divided or
interpolated. `observed_energy_wh` and interval energies stay unavailable if the
profile is incomplete. A declared Wh value remains separately labelled and
never creates observed energy. Duration/minimum run/off discrepancies are shown.
Time-window admissibility and native locks are evaluated only by a later qualified
planning method; this stage supplies no shiftability or financial saving claim.

At most 16 episodes and 128 energy intervals are returned. Episode count and
separate episode/energy-profile truncation flags remain visible. An output limit
never turns a partial energy profile into a complete one. Existing aggregate
operating-phase results remain available independently.

Native day/month/year difference aggregates are not relabelled as hourly energy. They return `non_hourly_interval_energy_not_supported`; explicitly requested raw values are retained.
