# Experimental Gen. 2 read-only beta test

Gen. 2 is not maintainer-tested. Use only the matching prerelease ZIP and its
`.sha256` file. Verify the checksum before installation and use a dedicated
read-only Loxone user. Never attach passwords, tokens, full structure files,
internal addresses or unmasked state values to a report.

## Test sequence

1. Record plugin, LoxBerry, architecture, Miniserver firmware and MCP client
   versions.
2. Back up the current plugin configuration and keep the previous ZIP.
3. Install through Plugin Manager and run `bin/healthcheck`.
4. Configure a canonical HTTPS hostname with a valid certificate. Confirm that
   an invalid hostname, untrusted certificate and expired certificate each fail
   without HTTP/WS fallback.
5. Complete OAuth with the restricted user in one supported MCP client.
6. Run all six tools; confirm rooms, categories, controls and states are limited
   to that user's visible structure.
7. Leave the connection open long enough to observe snapshot/delta processing,
   force one network interruption and confirm reconnect with stale/current
   transitions.
8. Revoke the session in the UI and confirm subsequent MCP access fails.
9. Export the masked diagnostic and report each expected and observed result
   through the Gen. 2 issue form.

## Rollback

Disable the plugin, reinstall the previous ZIP through Plugin Manager and
restore only the normal configuration if needed. Do not restore encrypted
tokens without the matching installation key; authorize clients again instead.
