# ADR 0008: Bounded virtual-input, central-shading and Daytimer controls

- **Status:** accepted
- **Date:** 2026-08-13

## Decision

`loxone_operate_control` is extended, without adding a raw-command input, for
three narrowly bounded families visible in the user-filtered structure:

- `Slider` and `LeftRightAnalog` reuse `set_value` only when the visible
  `min`, `max`, and `step` form a valid range.
- `CentralJalousie` accepts only documented whole-group commands: `open`,
  `close`, `shade`, `stop`, `enable_auto`, and `disable_auto`.
- A digital `Daytimer` accepts only `pulse`, `start_override` with a value of
  zero or one and a duration from one second through 24 hours, and
  `stop_override`. Calendar-entry and mode-list changes are excluded.

All existing OAuth, local enablement, current-structure validation, rate-limit,
audit, and no-retry rules apply. Virtual inputs and Daytimer overrides require
their advertised state for confirmation. A CentralJalousie has no documented
equivalent confirmation state in the current structure, so its result remains
explicitly accepted-but-unconfirmed unless a future documented state proves it.

`defaultRating` remains a bounded non-negative presentation value; it is not a
five-star value. The distinct LoxAPP3 `isFavorite` flag is exposed separately.

## Consequences

Climate, ventilation, alarms, locks, schedule editing, secured details, and
global operating-mode administration remain read-only or unavailable. They
need their own parameter model, authorization review and hardware acceptance;
this decision does not infer them from LoxAPP3 visibility.
