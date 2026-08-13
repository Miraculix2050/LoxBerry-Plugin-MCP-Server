# ADR 0008: Bounded documented LoxAPP3 control families

- **Status:** accepted
- **Date:** 2026-08-13

## Decision

`loxone_operate_control` is extended, without adding a raw-command input, for
documented, narrowly bounded families visible in the user-filtered structure:

- `Slider` and `LeftRightAnalog` reuse `set_value` only when the visible
  `min`, `max`, and `step` form a valid range.
- `CentralJalousie` accepts only documented whole-group commands: `open`,
  `close`, `shade`, `stop`, `enable_auto`, and `disable_auto`.
- A digital `Daytimer` accepts only `pulse`, `start_override` with a value of
  zero or one and a duration from one second through 24 hours, and
  `stop_override`. Calendar-entry and mode-list changes are excluded.
- `IRoomControllerV2` accepts a visible timer-mode `start_override` for one
  second through 24 hours and `stop_override`. Comfort temperatures, schedules,
  operating modes and permanent settings remain read-only.
- `Ventilation` accepts a one-second through 24-hour manual timer with a visible
  mode and `stop_override`. It does not alter profiles, limits, filter
  acknowledgements or arbitrary `controlInfo` actions.
- `ClimateControllerUS` accepts only documented fan and HVAC-mode timer
  overrides for one second through 24 hours, and their stop actions, when the
  corresponding logic input is not connected. Emergency, service and temperature
  actions remain read-only.

All existing OAuth, local enablement, current-structure validation, rate-limit,
audit, and no-retry rules apply. Virtual inputs and Daytimer overrides require
their advertised state for confirmation. A CentralJalousie has no documented
equivalent confirmation state in the current structure, so its result remains
explicitly accepted-but-unconfirmed unless a future documented state proves it.

`defaultRating` remains a bounded non-negative presentation value; it is not a
five-star value. The distinct LoxAPP3 `isFavorite` flag is exposed separately.

## Consequences

The target is complete, documented support of the user-filtered LoxAPP3
visualization surface: all normalized data is read-only first, while each write
requires its own documented parameter model and confirmation state. Calendar and
mode-list editing, global operating-mode administration, alarms, locks,
Intercom actions, irrigation, secured details, Config/KNX/EIB data and raw
commands remain unavailable. Documentation-based control support is never
reported as hardware-confirmed until its exact family and action has passed a
reversible target acceptance.
