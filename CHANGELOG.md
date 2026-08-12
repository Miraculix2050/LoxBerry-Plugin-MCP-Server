# Changelog

All notable user-visible changes are recorded here. GitHub release notes are
extracted from the matching version heading.

## Unreleased

- Discover explicitly user-linked controls as `visibility: "linked"`, describe
  both directions of the link, and support the bounded `UpDownAnalog.set_value`
  action when the linked control is currently visible and authorized.
- Add explicit `include_hidden` diagnosis to find, describe, state, notes,
  history, and statistics tools; hidden controls remain permanently non-operable.
- Restrict Jalousie slat actions to the documented blind animation mode and
  fail closed for shutters, curtains, unsupported, malformed, or absent modes.

## 0.4.0-alpha.2 - 2026-08-12

- Canonicalize signed-zero control values, preserve fractional statistic interval
  boundaries, and keep history and statistic pagination consistent through signed
  continuation anchors with stable occurrence tie-breakers without retaining result
  sets in RAM.
- Rate-limit denied LoxBerry cache-clear attempts and audit cancelled operations as
  having an unknown outcome.
- Finalize the `loxone:history` and `loxberry:operate` workflows with scoped
  Explorer grouping, guided statistic transfer, and scope-labeled local bindings.
- Describe every supported Loxone control type in `loxone_operate_control` and
  document the Phase-4 hardware acceptance boundary.

## 0.4.0-alpha.1 - 2026-08-11

- Add separately authorized `loxone:history` StatisticV2 and bounded
  control-history tools with
  short-lived RAM caching and an optional capped private compatibility cache.
- Extend bounded Loxone operations to TimedSwitch, Radio, LightsceneRGB,
  ColorPicker V1/V2 and Pushbutton without exposing raw commands.
- Add locally approved `loxberry:operate` with the sole plugin-owned statistic
  cache clear operation.
- Keep optional OAuth permissions requestable before administrator approval.
  The Tool Explorer requests every advertised scope and leaves the only visible
  selection to the post-login OAuth consent page; gated tools fail closed with
  `permission_denied` until approval.
- Document the complete verified/unverified control table and defer multiple
  Miniserver support with explicit security and acceptance requirements.
- Present global Loxone and LoxBerry capability gates as grouped, scope-labeled
  checkboxes instead of permission dropdowns.
- Accept the numeric `hasHistory` capability emitted by real Miniservers so a
  valid Loxone sign-in is not rejected while loading the user-visible structure.
- Accept the Miniserver's direct-list control-history response and let
  `loxone_find_controls` filter for history and/or StatisticV2 capabilities.
- Decode JSON-encoded `getStatisticInfo` values and request StatisticV2 binary
  files directly on the authenticated WebSocket so Gen. 1 Miniservers can
  return the documented binary response.
- Support visible legacy `statistic.outputs` through bounded raw binary WebSocket
  files; XML and FTP remain disabled.
- Add visible control presentation metadata and a bounded read-only tool for
  user-authored control notes; KNX/EIB Config project data remains unavailable.

## 0.3.0-alpha.1 - 2026-08-07

- Add disabled-by-default, locally approved `loxberry:read` diagnostics for
  sanitized LoxBerry system, plugin, and MCP service status.

- Give `service.log` a dedicated persistent Off/Error/Warning/Information/Debug
  level while retaining masked, unsuppressible audit records for control attempts.
- Enable the native LoxBerry Log Manager level for plugin logs and consolidate
  admin actions into one rotating `admin-ui.log` instead of one file per action.
- Bound both active logs to 512 KiB plus two backups and individual records to
  8 KiB while avoiding routine admin-page and HTTP access-log writes.
- Build official packages only through the owner-triggered GitHub workflow, with
  canonical ZIP and wheel output, locked runtime-wheel hashes, exact manifests,
  verified draft uploads, and separate read/write job permissions.

## 0.2.0-alpha.1 - 2026-08-05

- Add read-only and explicitly authorized Loxone MCP tools, OAuth, the integrated
  Tool Explorer, and the packaged `using-loxberry-mcp` agent skill.
- Package a fully offline Debian 13 arm64/Python 3.13 runtime for native
  installation through LoxBerry Plugin Manager.

## 0.1.0-alpha.1 - 2026-07-31

- Publish the first owner-tested MCP Server alpha for LoxBerry 4.
