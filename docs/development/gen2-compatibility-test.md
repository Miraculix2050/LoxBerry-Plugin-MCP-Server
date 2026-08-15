# Gen. 2 compatibility test

Use this test only for an independently authorized Gen. 2 or Compact system.
It is a compatibility report, not a requirement for the product beta.

Record plugin, LoxBerry, architecture, firmware and client versions. Verify a
trusted HTTPS/WSS connection and confirm that hostname mismatch, untrusted and
expired certificates fail without a cleartext fallback. Exercise the documented
read-only tools, visibility filtering, snapshots, deltas, reconnect and masked
diagnostics. Do not include credentials, tokens, private addresses, full
structures or unmasked states.

Gen. 2 writes remain out of scope until read-only compatibility is independently confirmed.
