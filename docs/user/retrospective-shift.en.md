# Conditional retrospective load shifts

`loxone_analyze_history(operation="retrospective_shift")` calculates how much
measured export a complete observed load cycle might have absorbed at another
historical time. Every example is conditional: missing historical native-lock
information means `admissibility="not_proven"`. It is not a schedule or permission
to operate a device, measured self-consumption, proven solar attribution or a
net/financial saving.

## Confirm the inputs

The existing profile workflow below remains available. Alternatively, pass an
optional `analysis_context` (`history_analysis_context.v1`). Its associations use
zero-based `source_index` values into the existing `sources` list; they cannot
introduce other source IDs. Give every selected source one distinct association.
Declare one EFM or scenario scope. Independent supplies need separate requests.
Exact visible sources need no saved profile; references reuse currently confirmed
bindings without changing their roles, boundaries or cycle constraints.

An `observed` load references consumer and operating associations. Provide
measured-interval flexibility or reuse compatible confirmed profile constraints.
Both observed edges, continuous capture and complete hourly cycle energy remain
mandatory for a shift example. Effective cycle and analysis timezones must agree.
A `declared_real` load references a confirmed visible consumer and a complete
user-confirmed declared cycle. A `hypothetical` load has no consumer or operating
source and uses `scenario_assumption` cycle origin. Declared cycle energy is a
uniform demand estimate, never a reconstruction of missing measurements.

The export association itself must be `user_confirmed`; scenario role or direction
assumptions cannot establish the measured budget. If a profile-backed declared
real model supplies operating feedback, it must match the saved operating
companion. Missing-feedback limitations apply only to evaluated declared models
without that feedback.

Context results appear in `comparison.context_analysis`, with association IDs,
real binding references where present, measured episodes and conditional
allocations. All modeled loads share one measured historical export budget.
Declared allocations have no observed start/end and establish no historical
improvement. Missing activity/minimum-off evidence and historical locks remain
explicit limitations. Historical export is not automatically solar production.
No profile, recorder, configuration or device is changed.

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
