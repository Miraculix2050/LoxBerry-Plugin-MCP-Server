# Phase 4 acceptance record

- **Status:** implementation complete; reviewed source revision and CI accepted; release metadata prepared
- **Hardware status:** read paths, control notes, the plugin-owned cache clear and selected authorized Loxone control actions are accepted; untested actions remain pending
- **Date:** 2026-08-12

Phase 4 adds StatisticV2 reads, bounded control history, six additional control
contracts and the plugin-owned statistic-cache clear action. Automated tests
cover schemas, parsing, bounds, authorization, local approval, migration and
negative command paths.

Two independently assembled package ZIPs from the verified arm64 wheel cache
were byte-identical and passed the source, runtime-hash and manifest checks.
The current local Full profile completed with Python 3.13: formatting, linting,
strict type checking and 466 tests passed. The final PR CI gate remains
authoritative.

The byte-identical local test package with SHA-256
`18ce1053e3419ed9b61d76298c84bdd067e844cbd4e321d9d0606582d3e0d76a` was
installed through the native Plugin Manager on the authorized LoxBerry test
target. The installer reached terminal status `0` after 77.2 seconds and the
post-install health check passed. Browser acceptance of the installed
`0.4.0-alpha.1` Explorer confirmed that no permission choice appears before
sign-in and that the page explains permissions are selected after Loxone login.
Automated OAuth tests confirm that the consent page offers the client-requested
optional scopes and issues only the selected canonical subset. No OAuth login or
tool mutation was performed during this UI check.

## Read-only installation inventory

The connected, previously installed MCP server was queried read-only on
2026-08-11. Four pages contained 351 visible controls. Every type listed as
“readable in the maintainer installation” in the user guide was found and could
be described as readable. `LightController`, `ColorPicker`, `IRoomController`
and `IRCDaytimer` V1 were not present; their documentation therefore remains
unverified. The installed pre-Phase-4 server did not expose the new history
capability fields, so this inventory is not statistic/history acceptance. No
UUID, control name, state value, address or credential is recorded here, and no
control tool was called.

## Classic statistic read acceptance

On 2026-08-12, one visible `InfoOnlyAnalog` control that advertises the
documented legacy `statistic.outputs` structure was read through the deployed
MCP service. `loxone_describe_control` advertised one `legacy:0` series and a
two-day `raw` `loxone_get_statistics` query returned a bounded, paginated result.
This confirms the authenticated WebSocket `binstatisticdata/{controlUUID}/{YYYYMM}`
path and multi-output decoder for that installation. The test was read-only; no
UUID, control name, value, address or credential is recorded here.

## StatisticV2, history and cache acceptance

On 2026-08-12, a visible Meter control advertised a `statisticV2` series. A
bounded one-day `hour` query returned a paginated result through
`loxone_get_statistics`, confirming the real StatisticV2 binary endpoint and
decoder. A separate visible IRoomControllerV2 control advertised history; a
bounded `loxone_get_control_history` request returned redacted entries. Both
tests were read-only.

With the already granted `loxone:history` and locally approved `loxberry:operate`
scope, `loxberry_clear_statistics_cache` completed successfully. It removed one
RAM entry and no persistent entry, confirming the narrow plugin-owned cache
operation without touching Loxone controls or configuration.

Five controls in the dedicated test fixture advertised `presentation.has_notes`.
`loxone_get_control_notes` was called once for one of them and returned a bounded,
current result. Its user-authored content was intentionally not copied into this
record. The Explorer grouping was accepted by the user. The authenticated Admin
page was accepted for the Clients and sessions binding tables at 1280x800,
390x844, 900x768, 360x800 and 320x568: both scope-binding tables, their
headers, binding IDs and revoke actions remained visible and the page had no
horizontal overflow.

## Authorized control-write acceptance

On 2026-08-12, the user authorized tests only for the controls simultaneously
assigned to the dedicated harmless MCP test room and category. All 27 visible
test controls were described and all 132 advertised states were read. The
following actions were sent once through the deployed MCP service:

- `Dimmer`: `set_level` and `off` were accepted and confirmed; the initial off
  state was restored.
- `LightControllerV2`: a visible `set_mood` action was accepted and confirmed;
  the initial mood was restored.
- `TimedSwitch`: `on` and `off` were accepted and confirmed; the initial state
  was restored.
- `Jalousie` `stop`, `LightsceneRGB` `on` and `off`, `Radio` `reset`, and
  `Pushbutton` `pulse` were accepted by the Miniserver. Their available feedback
  did not confirm a resulting state, so this record does not claim physical
  effect confirmation.

`CentralJalousie`, `ClimateControllerUS`, `Ventilation`, `IRoomControllerV2`,
the visible sliders/status controls and the `ColorPickerV2` were read on the
same fixture. V1 variants and every other untested action remain unverified. No
UUID, control name, state value, address or credential is recorded here.

### Supplemental controlled-fixture evidence

On 2026-08-12, a visible `ColorPickerV2` subcontrol with no direct room or
category assignment was operated through its parent `LightControllerV2`, which
was assigned to both dedicated MCP test groups. `set_color_hsv` was accepted
and confirmed through the visible color state; the original color state was
then accepted and confirmed as restored. This is fixture-specific acceptance
evidence and does not make unassigned controls generally eligible for writes.

The dedicated `Jalousie` fixture is configured for shutter animation. `open`,
`set_position`, and `enable_auto` were accepted and confirmed through their
advertised feedback. `close`, `shade`, `stop`, and the first `disable_auto` were
accepted but their immediate feedback did not confirm an effect. A final
explicit `disable_auto` was accepted and confirmed, restoring the initial
automatic-mode state.

The earlier Lamelle and combined-position commands were accepted before the
fixture's shutter animation was classified. They are not acceptance evidence
for a shutter configuration and are no longer advertised for this mode. The
final combined restoration command was not confirmed; no further write was
sent automatically. Therefore this record does not claim that the initial
Jalousie position was restored or that the unconfirmed commands had a physical
effect.

After the focused runtime deployment on 2026-08-12, a read-only description of
the same fixture advertised `open`, `close`, `shade`, `stop`, `set_position`,
`enable_auto`, and `disable_auto`, but no Lamelle or combined-position action.
This confirms the fail-closed capability boundary on the target; no additional
Jalousie command was dispatched for this check.

Legacy XML/FTP compatibility remains out of scope and disabled.

## Alpha 3 bounded-control acceptance

On 2026-08-13, the focused plugin-owned deployment passed its retained-backup
and health checks on the authorized LoxBerry test target. A `Slider` in the
dedicated MCP test room and category accepted `set_value`, confirmed the new
state, and then confirmed restoration of its initial value. A
`CentralJalousie.stop` command in the same intersection was accepted. Its
documented structure has no state suitable for confirmation, so this is only
command-accepted evidence. No digital Daytimer exists in the authorized test
intersection; Daytimer override actions remain hardware-unverified.
