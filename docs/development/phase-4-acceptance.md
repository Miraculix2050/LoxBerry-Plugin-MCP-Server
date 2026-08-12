# Phase 4 acceptance record

- **Status:** implementation complete; final source-revision Full gate pending
- **Hardware status:** legacy and StatisticV2 statistics, control history and the plugin-owned cache clear are accepted; control notes and all Loxone writes remain pending
- **Date:** 2026-08-12

Phase 4 adds StatisticV2 reads, bounded control history, six additional control
contracts and the plugin-owned statistic-cache clear action. Automated tests
cover schemas, parsing, bounds, authorization, local approval, migration and
negative command paths.

The initial local implementation gate completed formatting, linting, type checking
and 413 tests. Two independently assembled package ZIPs from the verified arm64
wheel cache were byte-identical and passed the source, runtime-hash and manifest
checks. At that earlier gate the workstation provided Python 3.12 only, so the repository's wrapper
correctly reports its mandatory Python 3.13 Full profile as incomplete; CI on
Python 3.13 remains the merge gate.

On 2026-08-12 the workstation Python launcher was present but no Python runtime
was installed. Therefore neither the Changed nor the Full profile can be repeated
locally for the current source revision; the final Python-3.13 CI Full gate remains
required before merge. `git diff --check` passed for the current revision.

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

No physical write has been authorized in this implementation run. Accordingly, new control types and V1 variants remain
`experimental`/unverified in the support matrix. Hardware acceptance must name
the exact harmless fixtures, record their initial state, execute each command
once, observe the result, restore the initial state, and keep secrets, UUIDs and
private addresses out of this record.

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

No tested control advertised `presentation.has_notes`. The required follow-up is
to find a visible control that advertises notes and call `loxone_get_control_notes`
once; no notes content should be copied into this record. The Explorer grouping
was accepted by the user. No authenticated Admin page was open for a browser
acceptance of the remaining Clients and sessions binding-table changes; that UI
check remains pending at the prescribed viewports.

All Loxone control writes remain deliberately untested and are excluded from this
acceptance run.

Legacy XML/FTP compatibility remains out of scope and disabled.
