# ADR 0005: Bounded Loxone Control Types

- **Status:** Accepted
- **Date:** 2026-08-06
- **Accepted:** 2026-08-06
- **Supersedes:** ADR 0003

## Context

The original Phase-2 implementation normalized a control operation target from
the non-standard field `action`. Loxone's official V17 Structure File defines
the mandatory field as `uuidAction`. Consequently, real controls could be
visible and operable in the Loxone visualization while the MCP server reported
no allowed action.

Phase 2 also needs bounded support for dimmers, lighting controllers, and normal
or automatic blinds without exposing a raw Miniserver command surface. The
[official Loxone V17 Structure File](https://www.loxone.com/enen/wp-content/uploads/sites/3/2026/04/1700_Structure-File.pdf)
is normative. Other open-source Loxone MCP servers were considered only as a
design comparison and do not override the official contract.

## Decision

### Structure and authorization

The normalized operation target comes only from `uuidAction`. A missing target
or a read-only internal or external restriction makes the control non-operable.
`details.isAutomatic` is retained only as a boolean capability flag for a
`Jalousie`. The documented integer `details.animation` is normalized only when
it is in the official range 0 through 5; malformed or unknown values are
discarded. All other details remain excluded from the normalized model.

The existing controls remain unchanged: the tool is disabled by default,
requires `loxone:read` plus `loxone:control`, resolves an exact UUID in a freshly
loaded user-filtered structure, rate-limits and serializes writes, audits the
attempt, and never retries an uncertain dispatch.

### Tool contract

The stable `loxone_operate_control` tool is extended with optional typed
parameters. `loxone_describe_control` advertises only actions supported by the
control type and identity:

| Type | MCP actions | Official Miniserver commands |
| --- | --- | --- |
| `Switch` | `on`, `off` | `on`, `off` |
| `Dimmer` | `on`, `off`, `set_level` | `on`, `off`, `{position}` |
| `LightController` | `on`, `off`, `set_mood` | `on`, `off`, `{sceneNumber}` |
| `LightControllerV2` | `off`, `set_mood` | `changeTo/0`, `changeTo/{moodId}` |
| `Jalousie` | `open`, `close`, `shade`, `stop`, `set_position` | `FullUp`, `FullDown`, `shade`, `stop`, `manualPosition` |
| Jalousie with `details.animation = 0` only | plus `set_slat_position`, `set_position_and_slats` | `manualLamelle`, `manualPosBlind` |
| automatic `Jalousie` | plus `enable_auto`, `disable_auto` | `auto`, `NoAuto` |

Percentages are finite values from 0 through 100. Legacy scenes are decimal
numbers from 0 through 99. V2 mood IDs are bounded decimal values returned by
the control's current visible `moodList`; `0` remains the documented off target.
The server validates nonzero V2 targets against that current list immediately
before dispatch and rejects missing, stale, malformed, or unlisted mood targets.
Parameters must match the selected action exactly; extra and missing parameters
are rejected. Relative-motion pairs, scene/mood mutation, naming, presence,
end-position adjustment, expert operations, arbitrary paths, name targets, and
bulk operations remain unavailable.

Animation 0 is the documented blind mode. A shutter, curtain, unsupported, or
unknown animation mode never advertises or accepts slat actions. This is a
fail-closed capability boundary; it does not expose the raw animation value to
the MCP client.

Command confirmation uses a newer matching official state when a deterministic
target state exists. Actions without a deterministic documented result can be
accepted but unconfirmed. The response retains the existing fields and adds the
control type plus sanitized observed values.

## Verification boundary

Deterministic tests construct commands against mocks only and cover every
supported type, invalid action/parameter combinations, range limits, scope and
visibility failures, read-only restrictions, command encryption, and uncertain
outcomes. Target validation for this change is strictly read-only: no real
control command is dispatched and no physical device is moved or switched.
Therefore the implementation can be reported as specification-aligned and
package-tested, but not as hardware-confirmed control compatibility.
