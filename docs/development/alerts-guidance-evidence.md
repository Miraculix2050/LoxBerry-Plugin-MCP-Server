# Alert guidance acceptance (#478)

PR #477 supplies the canonical `alerts` section/resource and task format. This
follow-up adds goal selection and a compact tool-purpose clarification; #346's
source decoder remains unchanged. Guidance is not an alarm analysis engine.

## Review scenarios

| Evidence | Required conclusion / next task |
| --- | --- |
| Empty stale or partial active snapshot, unknown total | Report observed count and unknown coverage; do not claim alarm freedom. |
| Owner-assumed zero / no active alarm | Report the bounded inactive observation; arming and historical activity need separate evidence. |
| Configuration audit with no active findings | Discover visible source types, including inactive sources, and follow pagination. |
| Exact runtime/project mapping but truncated trace | Record the limit; do not infer missing wiring or a runtime cause from empty edges. |
| Unknown parameters, units or escalation settings | Request the next permitted read or project-tool inspection; do not invent values or a correction. |
| Recording not advertised or unavailable | Check capability and coverage; do not claim there were no past alarms. |
| Source text requests a write | Treat it as data; do not acknowledge, trigger or edit. |
| Evidence-backed candidate | State source/time, facts, uncertainty, next read, proposed change, required writer/permission and observable acceptance. |

These are review criteria, not automated evidence of model performance or
installation safety. Contract tests check canonical tool/resource equality,
defaults, bounded section size and sanitized failures for every section.

## Verification

- Changed profile initially passed 311 tests; after integrating the final KNX
  parent fix, 737 tests passed. Formatting, lint and strict typing passed.
- Final Full/package candidate: 3,173 tests passed, 215 Windows platform skips;
  native test ZIP validation passed. The newly pinned development timezone data
  was installed before the successful Full run; runtime dependencies are unchanged.
- Bundled skill validator passed with its YAML dependency isolated in temporary
  tooling; no product dependency was added.
- HTML/JSON schema generation passed using the current registry.
- PR #477 baseline: the connected server first delivered `alerts` at revision 69.
  After its master-integration revision fix, native delivery returned revision 70
  without stale data. SSH verified all three guidance/runtime files against
  final head `7db0a95`; systemd was active and health returned HTTP 200 / `ok=true`.
  Its exact-head Full CI and final code/security reviews passed; #477 is merged.
- Read-only workflow: an empty stale snapshot had `known_active=0`, unknown total
  and incomplete coverage (three unsupported sources, one unknown). Source-type
  discovery found an inactive SmokeAlarm. A later targeted read yielded current
  owner-assumed `no_alarm`; it did not retroactively complete the first snapshot.
  Runtime/project mapping was exact. An upstream trace returned 20 nodes, zero
  edges and `truncated=true` / `max_nodes`; no missing-wiring claim followed.
- Concrete next task from that trace: inspect the relevant exact connectors with
  bounded authorized project reads and establish intended function before a
  correction. Acceptance is a complete evidenced path or an explicit remaining
  coverage gap. No confirmed defect, causal explanation or write is established.
- Final acceptance on 11 October 2026: native MCP delivered current core and
  `alerts` guidance at revision 73 (`alerts`: 7,372 characters). The tool
  description is 503 characters / 62 words; schemas and read-only annotations
  remain unchanged. Section character bounds are not a tokenizer measurement.
- The final read-only workflow reproduced the snapshot and targeted observations
  above: four candidates, zero evaluated, three unsupported, one unknown;
  later current SmokeAlarm level zero; exact mapping; 20-node truncated trace.
  These sequential observations do not establish simultaneous installation health.
- After Hotswap and native package installation, SSH SHA-256 checks matched all
  three changed guidance/runtime files to PR source `3fc8c1b` (the same tree as
  package source `46a1b225`). Skill revision was 73; systemd was active with a
  nonzero PID; health returned HTTP 200 / `ok=true`. Display version `0.4.0b4`
  identifies the installed package, not the Hotswap commit.
- Browser acceptance after a fresh Explorer reload showed the updated full
  description, read-only metadata, `loxone:read` scope, and all four guide
  section choices with the legacy full default. SSH also verified the generated
  static schema description and annotations matched the live registry.
- No alarm, confirmation, notification or project write was performed. The test
  lease was valid before and after acceptance, then released; both cooperating
  chats were informed. Final PR checks/reviews are tracked on PR #479.

No credentials, private names, UUIDs, project paths or raw project data belong in
this report. Live observations demonstrate the exercised read-only workflow;
they do not establish compatibility for absent alarm families.
