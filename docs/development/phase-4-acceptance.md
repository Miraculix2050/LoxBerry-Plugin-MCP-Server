# Phase 4 acceptance record

- **Status:** implementation complete; `0.4.0-alpha.10` published
- **Hardware status:** read paths, control notes, the plugin-owned cache clear, selected authorized Loxone control actions, and one bounded IRoomControllerV2 override are accepted; untested actions remain pending
- **Date:** 2026-08-14

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

## Status and energy model read-only acceptance

On 2026-08-14, the deployed service was queried read-only for one visible
representative of each `StatusMonitor`, `WindowMonitor`, `SmokeAlarm`,
`Tracker`, `Intercom`, `Meter`, `EFM`, and `PvProductionForecast` family. Each
description exposed the documented visible state references, `readable` was
true, and no operation was advertised. The `StatusMonitor` response included
its position-stable input/status mapping; the `WindowMonitor` response included
its typed item model. This accepts the live structure and description path for
those eight families, without disclosing identifiers, names, addresses, or
state values.

The current-state result is deliberately narrower. A single bounded read of
the 74 state references returned only `unknown` values after the documented
WebSocket status subscription, while the Miniserver remained reachable and the
structure cache current. The service therefore did not manufacture a value and
this report does not claim hardware confirmation for current state delivery of
these families. No state-changing command was issued to provoke an update.

For the visible `Meter` and `EFM` representatives, the service advertised four
and two statistic series respectively. One bounded one-day hourly query per
control returned 97 and 24 points without pagination. This is hardware
acceptance for their read-only statistics metadata and retrieval paths; it does
not confirm current state values or the remaining `PvProductionForecast` state
delivery.

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

## Structure-version refresh acceptance

On 2026-08-13, the deployed `0.4.0-alpha.5` structure-version refresh was
read-only accepted on the authorized LoxBerry test target. On one visible
control in the dedicated MCP test room and category, the user changed the
display name, a Control Note, rating, and independent favorite flag. After each
change, the next read reported a newer Loxone structure marker and current cache
freshness; the corresponding display name, bounded note result, rating, and
favorite flag were visible through the MCP tools without restarting the
Miniserver or plugin. No identifiers or user-authored note text are recorded
here.

## Alpha 9 and Alpha 10 LoxAPP3 model boundary

`0.4.0-alpha.9` adds bounded metadata and semantic event models plus documented
temporary climate and ventilation override contracts. They passed deterministic
tests. The focused file deployment passed backup and health checks. The authorized
MCP test intersection contains eligible `IRoomControllerV2`, `Ventilation` and
`ClimateControllerUS` controls; an `IRoomControllerV2` description confirmed the
new bounded timer-mode model and action allowlist. Its required confirmation
states were initially stale after the service restart, so fail-closed behavior
correctly prevented a write.

After the Alpha-10 transport correction was installed, a single 60-second Eco
`IRoomControllerV2.start_override` was issued only on the authorized MCP test
fixture. The Miniserver accepted the command, the documented `overrideReason`
confirmation state changed to the expected value, and the bounded control history
recorded the Eco timer activation as triggered by the MCP user. No retry or
additional stop command was sent; the accepted command was restricted to its
60-second duration.

On 2026-08-14, a later controlled stop request on the same fixture was accepted
by the Miniserver, but no newer `overrideReason=0` state event arrived within the
three-second confirmation window. It is therefore recorded as accepted but
unconfirmed, not as a confirmed stop action. No retry was sent. The documented
`stopOverride` command and the expected zero state remain covered by automated
tests; the missing fresh event is an external hardware/runtime observation.

Also on 2026-08-14, a separate visible `Ventilation.start_override` action was
issued in the authorized fixture with one visible mode and a 60-second duration.
The Miniserver accepted the command and delivered the documented current timer
confirmation. No stop command was sent; the timer was bounded to expire on its
own. This confirms that exact start action, but not `Ventilation.stop_override`
or the `ClimateControllerUS` override actions.
This confirms that exact action and mode on the maintainer fixture, not the
remaining HVAC/ventilation actions or timer modes.

On 2026-08-14, the MCP user was granted access to all three eligible controls
in the dedicated test intersection. The direct MCP connection and its structure
snapshot were current, but neither the required confirmation states nor ordinary
visible states received a current binary-state value. The runtime was corrected
to retain a sanitized event-stream failure class without re-raising that task's
error during cleanup; deterministic tests and a focused target deployment
passed, and the target emitted no stream-failure event. The absent initial state
tables therefore remain an external hardware/runtime observation. No additional
control command was sent, and the remaining actions stay hardware-unverified.

The later initial-state handshake acceptance supersedes that read-path finding:
the deployed server received one initial binary table with 350 structure-matching
states before returning the read result. HVAC descriptions and their visible
state references were confirmed on the MCP test fixture. The Miniserver did not
publish the selected HVAC individual values in that table, so they remain
`unknown` by design. This is a documented visualization-publication boundary,
not incomplete HVAC parsing, transport, or hardware acceptance. It does not
extend the separate evidence for untested temporary override actions.
