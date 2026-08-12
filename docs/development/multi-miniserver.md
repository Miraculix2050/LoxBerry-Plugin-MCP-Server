# Multiple Miniserver support (Phase 5 or later)

Phase 4 deliberately keeps the existing single-target configuration and one
Miniserver identity per OAuth grant. Installations with more than one
Miniserver are not currently supported or testable by the maintainer.

## Different topologies

“Multiple Miniservers” can describe materially different cases:

1. Independent projects: each Miniserver has its own structure, users and
   permissions. The MCP client must select an explicit target.
2. Gateway or client systems: one Miniserver exposes or references controls
   owned by another. The visible gateway structure remains authoritative; the
   plugin must not infer that a referenced control permits a direct connection
   to its owner.
3. Trust or intercommunication projects: Miniservers exchange values or
   commands but retain separate authentication and permission boundaries.

“Master” or “host” is therefore not a safe universal model. Future design must
represent the configured topology explicitly and still treat each direct
endpoint as its own security principal.

## Required extensions

- Replace the single endpoint with a bounded target list containing a stable,
  non-secret target ID, display name, endpoint and generation.
- Add an explicit `target_id` to discovery and operation contracts, or bind a
  connection to one target with no silent cross-target search.
- Bind OAuth families, Loxone tokens, local LoxBerry approvals, cursors,
  rate-limit buckets, state snapshots and statistic cache keys to `target_id`.
- Keep identities separate per target. Equal usernames and passwords may reduce
  user input, but do not allow token reuse and must never cause credentials to
  be stored or copied between targets.
- Support several simultaneous users as separate OAuth families and separate
  in-memory/encrypted Loxone tokens. No session may overwrite another user's
  target credential.
- Define deterministic duplicate-name presentation and cross-target pagination.
- Add migration from the single endpoint, per-target revoke/kill-token behavior,
  partial-outage semantics, UI selection and masked diagnostics.

## Acceptance preconditions

Implementation should start only with at least two authorized test targets and
fixtures covering independent and linked projects. Required evidence includes
same-name controls, different permissions, equal and different usernames,
parallel users, one target offline, per-target revoke, cache isolation and no
write reaching a target other than the one explicitly selected.

