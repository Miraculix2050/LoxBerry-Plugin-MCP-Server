# Changelog

All notable user-visible changes are recorded here. GitHub release notes are
extracted from the matching version heading.

## 0.4.0-beta.3 - 2026-08-15

- Enable the bounded read-only feature families for fresh installations, prefill
  the HTTPS origin from LoxBerry's configured host, and register admin logs with
  the LoxBerry LogManager. Upgrades preserve their configuration; write scopes remain off.

## 0.4.0-beta.2 - 2026-08-15

- Enable bounded history/statistics and masked LoxBerry diagnostics for fresh
  installations. Saving the first complete configuration also enables the
  service; OAuth consent and local diagnostic approvals remain required.

## 0.4.0-beta.1 - 2026-08-15

- Add `loxone_get_room_snapshot` for bounded current states in one exact visible
  room and `loxone_get_weather` for current or paginated forecast weather.

- Add compatible semantic state values and read-only description models for
  visible `Irrigation` and `AlarmClock` controls while preserving their raw values
  and advertising no actions.

- Update the bundled `using-loxberry-mcp` agent workflow to revision 18 for room
  snapshots, weather, and the new read-only controller interpretations.

- Add bounded, paginated filtering for service events by trace ID, component,
  severity and RFC-3339 time range; diagnostic records now use UTC timestamps.

- Add optional time-range filters to control history and discovery filters for
  visibility, notes, favorites, room groups and bounded name searches.

- Add an explicit, fail-closed `room_group` reference to each visible room from
  `loxone_list_rooms`, and resolve visible room and control references in
  StatusMonitor and WindowMonitor descriptions.

- Preserve explicit WindowMonitor item mappings when LoxAPP3 represents them as
  a bounded object keyed by control identifier, so their referenced visible
  controls can be resolved without name inference.

- Begin the feature-frozen `0.4.0` beta channel. Future `0.4.0` changes are
  limited to beta blockers, fixes and necessary compatibility corrections.

## Unreleased

- Separate systemd runtime, MCP access and optional MQTT health configuration.
  MQTT health publishes retained Loxone-epoch heartbeat and systemd state topics

- MQTT health can optionally use a custom broker. Its password is stored in a
  separate encrypted credential store and is never displayed or logged.
  below the configurable `mcpserver` root without storing or displaying broker credentials.

- Harden Admin UI browser responses with no-store caching, CSP, frame, referrer
  and MIME protections across page, AJAX, download and redirect paths.

- Add Tool Explorer time-range shortcuts, in-tab reference selection, action-specific
  control fields, and collapsible advanced parameters.

- Generate a versioned HTML and JSON reference for the complete MCP tool
  contract during package builds, link it from Help and the Tool Explorer, and
  document `tools/list` as the authoritative installed tool surface.

- Restore date/time pickers for optional RFC-3339 tool parameters in the Tool Explorer.

- Update the bundled `using-loxberry-mcp` agent workflow to revision 24 with
  task-specific read paths, complete cache-operation authorization and
  uncertainty guidance, and fail-closed schema and parameter-source rules.

## 0.4.0-alpha.15 - 2026-08-15

- Fail closed when the Miniserver binary-state stream ends before its first
  state batch, instead of returning an apparently usable read session without
  current values.

- Wait briefly for the Miniserver's initial binary-state table when opening a
  read session, so current state reads no longer race the asynchronous stream.

- Suspend all pending remote Loxone token-revocation attempts for one hour after
  an authentication rejection or Miniserver source-IP lockout, preventing the
  revocation worker from creating a burst of further logins while retaining the
  tokens until remote confirmation is possible.

## 0.4.0-alpha.14 - 2026-08-14

- Use the existing narrow non-interactive service-stop permission during the
  pre-upgrade hook, so a native Plugin Manager upgrade can stop the MCP service
  before migrating its persistent auth data; upgrades from older releases
  without that permission safely stop only the plugin's own service process.

## 0.4.0-alpha.13 - 2026-08-14

- Stop the MCP service before an upgrade replaces its persistent auth data, so
  in-flight requests cannot fail against a temporarily unavailable store.
- Classify a Miniserver source-IP lockout received while sending a WebSocket
  command as a recoverable connection failure, including deferred token cleanup.
- Keep a failed Loxone binary-state stream fail-closed while recording only its
  sanitized exception class; the stream task is now consumed after that record
  so its error cannot be raised a second time during session cleanup.
- Restore Gen. 1 Loxone token authentication by using the firmware-supported
  JWT credential inside RSA/AES Command Encryption instead of the rejected
  token-hash variant; the independent Gen. 2 hash path remains unchanged.
- Stop Loxone token authentication attempts after three rejections of the
  `authwithtoken` step per OAuth session until a local administrator explicitly
  permits another bounded attempt. Miniserver source-IP lockouts are reported
  separately and never increment that counter.
- Enable LoxBerry Plugin Manager automatic update discovery for stable releases
  and explicitly opted-in prereleases.

## 0.4.0-alpha.12 - 2026-08-14

- Prevent concurrent local LoxBerry read or operate binding changes from
  overwriting one another. The Admin UI keeps parallel session actions pending
  until it refreshes one consistent server state.
- Add a reproducible Windows development-environment setup and keep temporary
  test data inside the project data area.

## 0.4.0-alpha.11 - 2026-08-14

- Add `loxberry_list_service_events`: a bounded, read-only MCP diagnostic feed
  exposing only allowlisted fields from server-authored records in the fixed
  plugin service log. Raw logs, arbitrary files, journal data, payloads and
  foreign services remain unavailable.
- Record sanitized error classes for unexpected LoxBerry diagnostic failures and
  retain the returned trace ID for correlation.
- Restore MCP Tool Explorer sign-in through approved HTTPS IP or hostname aliases:
  proxy the exact internal Explorer-session endpoint, bind it to the current
  validated Explorer origin, and retain its real error message for diagnosis.

## 0.4.0-alpha.10 - 2026-08-14

- Load the administrative configuration before deferred status and session data,
  so the management page remains responsive without weakening its consistency.
- Retain encrypted Loxone tokens after local session revocation until the
  Miniserver confirms `killtoken`; unavailable Miniservers are retried by the
  service without delaying the administrative UI.
- Correct the final transport allowlist for documented Daytimer, room-controller,
  ventilation and HVAC temporary overrides; unsupported raw commands remain rejected.

## 0.4.0-alpha.9 - 2026-08-13

- Add bounded LoxAPP3 climate, ventilation, safety/status, energy and global
  metadata models, semantic Daytimer/weather events, and documented temporary
  override contracts.
- Reuse the MCP Tool Explorer OAuth session in new browser tabs for up to eight
  hours without storing refresh credentials in browser storage; disconnect now
  revokes the shared Explorer session in every tab.

## 0.4.0-alpha.8 - 2026-08-13

- Keep the HTTP-to-HTTPS Explorer guidance visible after a sign-in click by
  performing the HTTP origin check before testing the intentionally absent
  authorization popup.

## 0.4.0-alpha.7 - 2026-08-13

- Block MCP Tool Explorer sign-in on HTTP before OAuth discovery and provide a
  link that reloads the same IP address or hostname over HTTPS; open the HTTPS
  authorization popup synchronously so Firefox retains the click activation.

## 0.4.0-alpha.6 - 2026-08-13

- Open the Tool Explorer OAuth popup synchronously from the user click, then
  navigate it after asynchronous discovery and PKCE setup.

## 0.4.0-alpha.5 - 2026-08-13

- Check the documented LoxAPP3 version marker before each due structure refresh
  and download the full user-filtered structure only after a detected change.
- Serialize due LoxAPP3 refreshes per OAuth family, close live Miniserver
  sessions on service shutdown without revoking persisted authorization, and
  extend the deterministic lifecycle tests.
- Move pure control discovery presentation into its own module and make local
  release-candidate source copies ignore untracked build and temporary artifacts.
- Simplify `loxberry_clear_statistics_cache` to report only removed RAM entries;
  the unused hybrid-cache compatibility fields are removed in this alpha.

## 0.4.0-alpha.3 - 2026-08-13

- Refresh the user-filtered LoxAPP3 structure after reconnects and at a bounded
  configurable interval, including visible Notes, ratings, and favorites; reject
  stale refreshes and oversized structures safely.
- Bound runtime WebSocket sessions by activity and capacity, avoid concurrent
  token-refresh/event reads, and close runtime connections together with OAuth
  family revocation.
- Replace the unused persistent statistics-cache mode with a bounded RAM-only
  cache and add advanced, validated structure and runtime limits.
- Preserve all bounded non-negative Loxone ratings, expose the independent
  favorite marker, and extend the bounded operation allowlist to virtual analog
  inputs, CentralJalousie, and digital Daytimer overrides.
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
