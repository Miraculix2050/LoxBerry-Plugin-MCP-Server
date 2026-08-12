# ADR 0007: Phase 4 history, bounded controls and LoxBerry operate

- **Status:** accepted; read-path and cache-operation hardware acceptance recorded
- **Date:** 2026-08-11

## Decision

Phase 4 adds two separately consented Loxone read tools:
`loxone_get_statistics` and `loxone_get_control_history`. Both require
`loxone:read loxone:history`, re-read the current user-filtered structure before
access, accept only visible UUIDs, enforce range, response and rate limits, and
never expose a raw Miniserver path. Control-history results deliberately omit
the triggering UUID and copy only bounded documented fields.

`loxone_describe_control` also exposes the bounded presentation fields rating,
password protection, read-only status, and a control-notes availability flag.
The separate read-only `loxone_get_control_notes` tool requires only
`loxone:read`, re-validates the visible control, and returns at most 500
characters of user-authored plaintext. Notes are untrusted content, not an
instruction channel. EIB/KNX addresses, data types, cyclic-send and
status-query configuration stay unavailable because they are not included in
the user-filtered Structure File; a rating is not treated as a favorite flag.

The statistic adapter supports `statisticV2` series and, when V2 is absent, the
documented legacy `statistic.outputs` series advertised by the user-filtered
structure. Legacy series use at most two monthly binary files and raw granularity
only; StatisticV2 uses its documented binary single-output endpoint.
On Gen. 1, the bounded binary file request is sent on the already authenticated
local WebSocket without the command-encryption envelope because that envelope
cannot carry a binary file response. Token authentication and all control
commands remain encrypted.
Raw queries are limited to seven days; aggregated queries to ten years. Results
are cached in RAM for 60 seconds. Hybrid mode additionally provides a bounded,
private, gzip-compressed, plugin-owned source cache for a future compatibility
adapter, with a configurable 16–512 MiB cap and LRU deletion. The current V2
adapter does not write source files.

FTP and legacy XML are intentionally not activated in this revision. The
existing OAuth integration stores a Loxone JWT but never a password, while FTP
requires separately proven credentials and can be slow for large files. A
fallback may be added only after a read-only spike proves authentication,
format, cancellation, incremental reads and cache behavior without storing or
logging a password. Until then there is no FTP polling and no claim of legacy
statistic compatibility.

`loxone_operate_control` gains bounded contracts for `TimedSwitch`, `Radio`,
`LightsceneRGB`, `ColorPicker`, `ColorPickerV2`, and `Pushbutton`. Commands are
derived solely from the normalized visible capabilities and typed parameters.
No raw, learn, rename, bulk, next/previous or expert command is accepted.

The only Phase 4 LoxBerry mutation is
`loxberry_clear_statistics_cache`. It requires both `loxone:read` and
`loxberry:operate`, global enablement, a local approval bound to the same OAuth
client, Loxone identity and Miniserver as `loxberry:read`, a separate rate
limit, and a compact audit record. It can delete only plugin-owned statistic
cache entries.

All known optional scopes remain discoverable and may be included in an OAuth
grant before their global or local policy gate is enabled. This keeps consent
separate from administrator approval and avoids a second client-side mechanism:
published tools fail closed with `permission_denied` until the corresponding
gate is satisfied. The Tool Explorer therefore requests every advertised scope
and leaves the single visible selection to the OAuth consent page after Loxone
sign-in. The authorization server may issue the selected subset;
`loxberry:operate` still requires `loxone:history`.

## Verification boundary

Fixture and contract tests prove parsing, allowlists, authorization, migration,
cache bounds and negative paths. On the authorized test installation, a legacy
statistic, a StatisticV2 series, bounded control history and the separately
approved plugin-owned cache clear have also been accepted. A notes-capable visible
control was not present during that run. User documentation and the support matrix
mark V1 compatibility and every action not explicitly accepted on the authorized
fixture as unverified. The Phase-4 acceptance record distinguishes state-confirmed
and only command-accepted writes, and records restoration where a state changed.
