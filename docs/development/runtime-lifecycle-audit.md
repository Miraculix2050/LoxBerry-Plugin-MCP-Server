# Runtime lifecycle concurrency audit

Issue #160 is an investigation, not a compatibility or device acceptance claim.
The baseline is master `200acc2`, after merged PR #311 (`dbdbcb7`).

## Existing coverage from PR #311

`tests/test_runtime_family_lifecycle.py` covers family churn, cancelled connection
holders, connect versus disconnect/revoke, queued read/history/control calls after
revocation or expiry, control-lock waiters, expired rate-key sweeping and live
rate-window preservation. Disconnect waits for connection publication using the
same family lock. It does not acquire the control lock, avoiding reversed lock
ordering. Holder/waiter counts keep a shared lock alive until its last user exits.
Rate windows intentionally survive disconnect until their last timestamp expires.

## Deterministic audit coverage

`tests/test_runtime_concurrency_audit.py` uses Events and acknowledged stream
batches. Two-second timeouts bound deadlocks; they do not choose race ordering.
Cleanup executes even when a regression assertion fails.

- Idle and capacity pruning, and close, complete while a refresh is paused. The
  stream task terminates and its websocket closes; the independently owned
  refresh session closes after its request completes. No test reuses a closed
  stream session for a command.
- Refresh publishes changed structure/state visibility as one synchronous step.
  A batch before publication uses the old allowlist; batches after publication
  use the new allowlist, and removed values disappear.
- A replaced family record must own its generation and cache. An old refresh
  must not remove the replacement's state values.
- Registered background stream tasks drain on shutdown. Repeated close does not
  close those sessions again, and records, family locks and caches are cleared.
- Concurrent new families must obey the configured active-session capacity.
- Normal stream termination during a read must invalidate current cache freshness.

## Confirmed defects and completion status

The audit initially reproduces three defects as strict expected failures:

- #318: simultaneous new connections bypass capacity before either is published.
- #319: a suspended refresh recreates cleaned cache or removes replacement state.
- #320: normal stream termination closes the websocket but leaves current values.

Each fix belongs in a separate reviewed PR and removes its expected-failure
marker. Passing the audit with expected failures does not resolve these bugs or
complete #160. Device/Miniserver and browser acceptance are not claimed by these
controlled-session tests. In-flight admission during shutdown and direct control
command/session ownership require explicit additional evidence before a broader
lifecycle claim.
