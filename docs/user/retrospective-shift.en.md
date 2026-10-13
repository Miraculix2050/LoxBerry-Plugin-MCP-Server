# Conditional retrospective load shifts

`loxone_analyze_history(operation="retrospective_shift")` calculates how much
measured export a complete observed load cycle might have absorbed at another
historical time. Every example is conditional: missing historical native-lock
information means `admissibility="not_proven"`. It is not a schedule or permission
to operate a device, measured self-consumption, proven solar attribution or a
net/financial saving.

## Confirm the inputs

Read the current installation profile. Select one confirmed `grid_export`
energy statistic with `declared_direction="export"`, and up to seven confirmed
consumer statistics with usable load constraints and their exact confirmed
binary operating-state bindings. Export and consumers must have the same
explicit measurement boundary. Only assert comparable boundaries after checking
their meaning and excluding duplicate/overlapping consumer counters. This is
your declaration; the tool does not verify electrical wiring.

Confirm `cycle_identity="user_confirmed_cycle"` and
`energy_profile_origin="observed_intervals"`. A declared Wh total does not provide
an hourly shape. State history must be enabled and retain the relevant past
coverage. Use `hour` granularity for energy and `raw` for state. Scopes are
`loxone:read` and `loxone:history`.

```json
{
  "operation": "retrospective_shift",
  "sources": [
    {"binding_id": "my-export", "granularity": "hour"},
    {"binding_id": "my-consumer", "granularity": "hour"},
    {"binding_id": "my-operating-state", "granularity": "raw"}
  ],
  "start": "2026-10-11T00:00:00+02:00",
  "end": "2026-10-12T00:00:00+02:00",
  "timezone": "Europe/Berlin",
  "comparison_options": {"comparable_boundaries_confirmed": true}
}
```

Replace all IDs with confirmed visible bindings. The period must be past and
touch at most 31 local days. Repeated physical sources are rejected. If the
profile changes during analysis, read and review again; do not blindly retry.

## Interpret the result

Inspect `comparison.retrospective_shift`, its `profile_revision`, limitations,
excluded-cycle count and output truncation. Complete observed activity edges,
matching duration, no run/off discrepancies and complete native hourly Wh/kWh
interval energies are required. Missing hours, query-edge cycles, capture
restarts, unknown states and day/month/year aggregates cannot qualify.

Alternative examples preserve the whole contiguous cycle, including when
interruption is permitted. Declared windows and completion are anchored to the
original local start date. Ambiguous/nonexistent local DST boundaries are
excluded. The entire alternative and required off time on both sides need
continuous observed inactive coverage in one capture phase. Neither actual
activity nor another hypothetical cycle of the same load may overlap.

All examples share one export budget; the same export energy is never allocated twice.
The method chooses the highest remaining conditional absorption, then earliest
start and stable binding/episode order. `conditional_export_absorption_upper_bound_wh`
and the hourly allocations are conditional upper bounds. Storage, changing
responses of other loads and sub-hour dynamics remain unknown.

Each example explicitly reports `native_lock_status="not_checked"`,
`admissibility="not_proven"` and `historical_native_lock_coverage_missing`.
Do not describe it as an allowed or recommended device operation. At most 16
examples and 128 hourly allocations are published. Search is bounded to 4,096
alternatives; exhaustion returns no allocation from a partial search. Output
truncation remains visible and does not establish a globally optimal schedule.
