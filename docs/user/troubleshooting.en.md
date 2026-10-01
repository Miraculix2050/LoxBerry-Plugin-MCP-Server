# Troubleshooting

[Deutsch](troubleshooting.de.md)

| Symptom | Safe check |
| --- | --- |
| Client cannot reach the server | Check service status, local HTTPS address and certificate diagnostics. |
| OAuth login does not start | Open the HTTPS address; HTTP is not used for login. |
| A tool returns `permission_denied` | Check Loxone rights, requested scope and, when applicable, local admin approval. |
| A tool returns `emergency_stop_active` | Check the selected emergency-stop signal: `1` permits tool calls and `0` blocks them. With `unknown`, the service cannot confirm a safe value. Set the signal to `1` outside MCP or remove the selection; do not retry automatically. The response includes the current state and UTC times for observation and the start of the block. |
| No current values | Check the Miniserver connection and whether the Loxone user may see the controls. |
| An update failed | Wait for terminal Plugin Manager status and retain the earlier package. |

Do not export or share credentials, tokens, private addresses or complete state data. Use only masked plugin diagnostics.

## Temporary read unavailability

For `temporarily_unavailable`, retain `error`, `message`, `diagnostic_code`, and
`trace_id` with the tool and authorized target context. Also retain
`availability_phase` and `retry_after_seconds`. `local_rate_limit` identifies the
caller's local request budget; only this cause supplies a rounded-up delay of
1–60 seconds. Wait at least this delay and retry a read at most once. Capacity is
not reserved. Reuse successful descriptions and reduce concurrent fan-out.
Never automatically retry uncertain writes.

Runtime session establishment waits for local authentication coordination within
the configured connection timeout; waiting and login share that budget. Cancellation
stops waiting. Fresh MCP visibility still requires the caller's authenticated
structure; the Admin identity or an old cached structure cannot replace it.
`structure_refresh_auth_busy` means local coordination exhausted its wait before
login. `structure_refresh_source_ip_suppressed` means source-IP blocking or the
persistent breaker prevented access. Neither identifies the caller's rate budget.
Transport failures and remote session limits remain separate; a connection-category
error alone does not establish a Miniserver session limit. These diagnostics cannot
attribute older failures whose underlying exception was not retained (#332).

`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token`, and `structure_refresh_timeout` distinguish established
refresh exception categories. Token errors include missing tokens and token-store
failures. The phase identifies token lookup, session establishment, version check,
structure load, or session close. `structure_refresh_unknown` and
`availability_unknown` explicitly leave the cause unknown. No retry time is given
for these failures; do not invent one or infer it from a healthy service.

Use authorized, sanitized service diagnostics with the response's trace ID for
support. Warnings are suppressed for 60 seconds per category and phase; event
counts do not count failed calls, and missing events do not identify a cause.
