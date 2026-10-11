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
- `loxone_get_state_semantics` adds fixture-tested exact-state evidence for
  existing Irrigation/AlarmClock decoders, `value` format metadata on
  InfoOnlyAnalog/UpDownAnalog/Slider, UpDownAnalog ranges and StatusMonitor
  `inputStates` position-stable tuple decoding and configured-state counts. Other meanings remain unknown;
  this does not establish new firmware or control-family hardware compatibility.
- History, diagnostics and cache operation require their documented scopes and local approvals.
- Control is Gen.-1-only, default-disabled, type-specific and limited to visible operable controls.
- Only actions explicitly identified as hardware confirmed in the user capability documentation are hardware promises; other implemented actions remain unverified.

See [Gen. 2 compatibility testing](gen2-compatibility-test.md) and the [user capability overview](../user/capabilities.en.md).

- `loxone_get_active_alerts` evaluates documented, fixture-tested AalEmergency,
  AalSmartAlarm and AlarmChain rules (Structure File 17.1), plus Alarm.level
  stages (Structure File 17.0) with owner-approved zero-as-inactive assumption
  (#346, 11 October 2026). No active case has
  hardware observation evidence. This adds no hardware-family or firmware compatibility promise. Known
  unsupported monitor/alarm families make coverage partial; this is no safety
  certification or alarm notification service.
