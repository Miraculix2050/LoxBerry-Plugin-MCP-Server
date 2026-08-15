# Support matrix

- **Status:** Current pre-release support statement.
- **Evidence:** [Current evidence](../evidence/current-evidence.md) distinguishes implemented, automated and hardware-confirmed behavior.

## Platforms and Miniservers

| Component | Status | Scope |
| --- | --- | --- |
| LoxBerry 4.0.0.14, Debian 13, aarch64 | hardware confirmed | native package, service, HTTPS transport and offline wheels |
| LoxBerry 3 and older Debian bases | unsupported | outside the supported baseline |
| Gen. 1, firmware 17.1.7.27 | hardware confirmed | local HTTP/WS, token authentication, visibility and states |
| Older Gen. 1 firmware | experimental | no compatibility promise |
| Gen. 2 / Compact | experimental | HTTPS/WSS fail-closed behavior is automated; real compatibility needs an independent report |

## MCP clients

| Client | Status | Known limit |
| --- | --- | --- |
| Claude Desktop `1.24012.9` with `mcp-remote` `0.1.38` | hardware confirmed | local bridge behavior only |
| Codex CLI `0.146.0` | hardware confirmed | client refresh and logout limitations do not weaken server audience or revocation rules |

## Product limits

- One Miniserver target is supported.
- External or cloud-hosted MCP access is unsupported.
- Read-only tools are available within the signed-in Loxone user's visibility.
- History, diagnostics and cache operation require their documented scopes and local approvals.
- Control is Gen.-1-only, default-disabled, type-specific and limited to visible operable controls.
- Only actions explicitly identified as hardware confirmed in the user capability documentation are hardware promises; other implemented actions remain unverified.

See [Gen. 2 compatibility testing](gen2-compatibility-test.md) and the [user capability overview](../user/capabilities.en.md).
