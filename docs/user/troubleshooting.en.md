# Troubleshooting

## OAuth session and approval lifecycle

Use the local Admin diagnostic download when a session disappears or an approval
stays inactive. `auth_lifecycle` reports retained revoked-family counts by cause
and at most 20 recent revocations with time, source and masked references. This
is local LoxBerry-admin diagnostics; Loxone authorization does not grant access.

The first revocation stores `revoked_at`, `revocation_reason` and
`revocation_source` on the existing family. Repeated revocations preserve that
first cause. Historical records without a cause remain `unknown`; no later
Admin action is attributed as their original trigger. Metadata follows existing
family retention and disappears when that family is collected.

| Cause | Recorded initiating path |
| --- | --- |
| `oauth_revocation` / `explorer_logout` | Explicit OAuth revocation / Explorer logout |
| `refresh_reuse` / `refresh_invalid_state` | Reuse of a consumed refresh token / invalid refresh state causing revocation |
| `admin_session` / `admin_all_sessions` | Local Admin revoked one / all sessions |
| `approval_read_removed` / `approval_operate_removed` | Local Admin removed the matching LoxBerry approval |
| `scope_disabled` | Configuration disabled an authorized capability |
| `unknown` | Original cause was not recorded or is unsupported |

Plugin logs use `component=auth_lifecycle` with fixed event, reason, source,
capability, outcome and correlation fields. `family_ref` is a domain-separated
hash of a randomly issued opaque family ID and correlates OAuth, runtime and
remote-cleanup events. `client_ref` is keyed per installation; `binding_ref`
is a separate hash of the existing opaque binding. References grant no rights
and do not imply that two differently registered clients are interchangeable.
Source labels identify the initiating path, not a verified human operator.

At normal INFO logging, rare events cover registration, family creation and
revocation, expiry/removal, approval changes, connection opening/termination,
service start/stop and remote cleanup outcomes. DEBUG adds successful token
issuance/rotation, exact approval matching per capability, rejected refreshes,
close requests and cleanup attempts/suppression. Ordinary store reads produce
no lifecycle entries. Existing log-level controls and rotation remain in effect;
a process crash cannot emit a graceful stop, and missing logs are not proof of
an absent event.

Admin helper events are forwarded to the native LoxBerry Admin log through a
strict fixed-field filter, following the native plugin log level. Each helper
forwards at most six detailed entries plus a count summary to bound pipe output.

Store transition events are emitted after a successful durable commit. A bulk
mutation emits at most 32 detailed entries plus a count summary; persisted
first causes remain available independently of log rotation. Remote cleanup
queueing, confirmed kill, already invalid, nominal expiry and unconfirmed
outcomes remain distinct. A connection ending is not an OAuth-family revocation.
No tokens, raw client/family IDs, names, endpoints, credentials or arbitrary
exception messages are added to these diagnostics.

A startup that never receives its first state batch closes with
`initial_state_timeout`; cancellation does not turn that failure into a normal
local disconnect. OAuth expiry and refresh revocation causes are forwarded to
the corresponding runtime close.

The browser diagnostic download requires JavaScript. It uses the same-origin
AJAX path and downloads the masked JSON locally; strict Origin checks and the
no-referrer policy remain active.

## Repeated Miniserver authentication rejection

Three definite authentication rejections in five minutes pause new sign-ins
for 60 seconds. Public OAuth password failures have their own budget and pause
only public sign-ins. Service and token rejections share a second budget; its
pause also covers the token phase of public sign-ins. A public password pause
does not block service connections or token revocations. Actual IP blocks remain
global. Rejected recovery probes double that pause
up to 60 minutes. Network errors, timeouts, busy coordination and denied project
permissions do not consume this budget. Existing authenticated connections stay
open. This is plugin policy, not a guaranteed Miniserver IP-block threshold.

The Sessions section shows the protection reason and remaining wait. A local
administrator can explicitly try one sign-in with the LoxBerry-configured
credentials, at least 60 seconds after the previous attempt. Confirm the warning:
another rejection can extend the pause or cause an IP block. Automatic retries and
MCP clients cannot bypass the pause; a confirmed Miniserver IP block takes priority.

If protection persistence is unavailable, new sign-ins stop. Restore access to the
private plugin state file and restart the service after resolving the cause; do
not delete an active protection record merely to retry. An interrupted process
leaves a conservative reservation of at most one hour. This also protects other
processes if an authentication outcome could not be saved. No credentials or token values appear in status.
An existing source-IP recovery policy can require a longer reservation and takes priority.
Token-wide cleanup is not offered; its effects are under separate investigation.

An authentication outcome that is still unknown additionally reserves the existing global IP recovery interval. After a crash or an outcome write failure, this protection can temporarily defer all new authentication; normal persisted password rejections do not activate it. Tokens already issued when sign-in completion is suppressed are encrypted for coordinated revocation. If that write also fails, the transaction retains the token and blocks new issuance until cleanup is queued.

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
login. `structure_refresh_auth_cooldown` means the preventive rejection pause or
uncertain protection persistence prevented network access.
`structure_refresh_source_ip_suppressed` means source-IP blocking or the
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

### Admin discovery connection

Event History and emergency-stop selectors reuse a dedicated connection with the
LoxBerry-configured Miniserver identity. Each fresh selector request still downloads
the complete structure; captured history and normal MCP clients keep their existing
authorization boundaries. If the service is stopped or discovery fails, no fresh
login is started in the CGI helper. Keep the saved selection and retry explicitly
after correcting the cause. Retained emergency options are marked stale and do not
authorize operations.

The connection expires after 60 seconds of inactivity or five minutes of reuse.
Credential/configuration changes and connection failures discard it. An accepted
limitation remains: partial rights changes may not affect a still-open Miniserver
session until it disconnects or is replaced. A fresh structure download is not a
universal proof of immediate permission revocation. MCP clients never receive this
service identity's access through the selector endpoint.
