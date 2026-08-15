# Current evidence

## Evidence levels

- **Implemented:** covered by the released code contract.
- **Automated:** deterministic CI validates the relevant behavior.
- **Hardware confirmed:** the exact documented combination was accepted on the authorized test system.

## Current summary

- LoxBerry 4.0.0.14 on Debian 13/aarch64, native installation, upgrade, service start and local HTTPS transport are hardware confirmed.
- Gen. 1 firmware 17.1.7.27, token authentication, visibility filtering, state snapshots and reconnect are hardware confirmed.
- Claude Desktop and Codex CLI completed the documented read-only connection flow; their client limitations remain listed in the support matrix.
- Bounded read-only history, statistics, weather, room snapshots and selected controller models are automated; only the combinations labelled hardware confirmed in the support matrix have real-device proof.
- Loxone control remains explicit, default-disabled and limited to visible type-specific actions. Hardware evidence applies only to the named fixtures and actions.

The detailed phase reports are historical evidence, not current support promises. The [support matrix](../development/support-matrix.md) is the public source of current compatibility claims.
