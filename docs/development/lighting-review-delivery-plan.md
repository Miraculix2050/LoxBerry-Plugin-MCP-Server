# Shared associations and lighting review delivery plan

Status: owner-approved implementation plan for #559 followed by #441.
Planning baseline: master `72766d32`; recheck current master before every PR.
Each PR is independently usable, reviewed, tested and accepted on Gen. 1
before integration of the next package. Branches use `codex/`.

Execution checkpoint: PR1 [#563](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/563),
PR2 [#568](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/568),
PR3 [#572](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/572) and
PR4 [#575](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/575)
are merged after their scoped review, tests and Gen.-1 acceptance. PR4's final
[gate record](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/575#issuecomment-6274992150)
binds review, CI and read-only target/browser evidence to its delivered stand.
PR5 [#579](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/579)
starts from merged PR4, master `b816081e`. Its integrated six-scenario Gen.-1 and
DE/EN functional browser acceptance are documented in the
[device gate record](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/579#issuecomment-6279288915).
Final integration preserves the accepted lighting code; #441 closes after the
remaining final PR checks and merge. Do not publish a competing #559 resolver or another profile
abstraction. The original plan-recording PR changed no runtime behavior.

Coordination with the #559 owner confirmed these shared interfaces:
`read_profile_bindings`, `resolve_source_association` and
`SourceSnapshot.capture/validate`. Lighting adapters use them rather than adding
another resolver. Typed light selections belong to the lighting domain. Preserve
the released energy provenance values; represent unresolved light relationships
as lighting diagnostics, not a new energy origin. Runtime child IDs remain exact
keys; published profile models retain their existing UUID contract. Profile
state/statistic membership is already checked by `project_profile.evidence`;
direct profileless mood/state selections require exact adapter-level membership
checks against fresh visible sources. The unaccepted local prototype is not merged.

## Goal and boundaries

Answer the six collected lighting questions with evidence-backed findings,
qualified planning advice and explicit missing context. Do not claim a complete
physical lighting audit. Reuse the existing lighting projection, mapping,
connector rules, profile store and request-local context resolver. No second
profile abstraction, new MCP tool, migration or persistent context store.
No Miniserver, profile, configuration or recorder writes and no induced events.

## PR 1: shared association resolution (#559)

- Generalize shared types and resolution for profile references and explicit
  declarations; integrate the existing energy context with that implementation.
- Separate server-proven relationships, user-confirmed associations, scenario
  assumptions and unresolved associations. Preserve existing energy contracts,
  including `native_efm` provenance.
- Check profile references against installation, revision, current visibility
  and usability. Reject contradictory inputs; never upgrade or persist caller
  confirmation. Names are not source identity.
- Preserve profile documents, keys, paths and authorization boundaries. Profiles
  remain optional reuse for hypothetical read-only scenarios.
- Review the lighting analyzer contract below before its implementation.
- Acceptance: existing energy planning uses shared resolution; #559 can close
  independently of lighting adoption.

## PR 2: lighting sources and outputs (#441)

- Add bounded visible lighting outputs to
  `loxone_describe_control(view="lighting_context")` while preserving existing
  mood projection and legacy default views.
- Include exact runtime identities, explicit parent provenance, source/version,
  freshness, completeness and omissions. A parent is not connector identity.
- Report source-proven capabilities only. Default Kelvin limits or a color
  picker do not prove installed tunable-white fixtures.
- Distinguish unsupported, missing, invalid and stale evidence.
- Acceptance: compact authorized source inventories are useful independently
  of the later analyzer.

## PR 3: presence and lighting relationships (#441)

- Reuse project find/describe/trace, exact runtime mappings, #219 parent anchors
  and #213 target-local mapping coverage.
- Preserve configured direct, indirect and central paths, references and
  unresolved internal flow. Names, room and category do not establish links.
- Preserve child runtime identity separately from parent project topology.
- New connector interpretation requires a reviewed versioned rule and tests;
  unsupported semantics stay unresolved. Do not create another lighting graph.
- Acceptance: existing project tools expose reproducible relationship evidence.

## PR 4: bounded lighting analyzer (#441)

Review the concrete [lighting analysis contract](lighting-analysis-contract.md)
with PR3 before implementing this package.

- Extend `loxone_analyze_project` additively with `scope="lighting"` and an
  optional typed lighting context. Preserve KNX/Modbus defaults and wire behavior.
- Select exact controller IDs or an exact room ID; never select by room name.
  Support multiple controllers per room and repeated names across rooms.
- Checks: inventory, naming candidates, presence relationships, confirmed scene
  role consistency and planning-context gaps. Naming conventions are explicit
  declarations, not inferred requirements.
- Reuse PR 1 resolution for optional profile references and explicit scene roles,
  room usage, naming conventions, fixtures, zoning and user intent. Scene identity
  is controller plus mood ID. Requests cannot create persistent confirmations.
- Return roomwise findings with evidence, stable references, provenance,
  completeness and missing context. Keep technical observations, confirmations,
  assumptions and conditional advice distinct.
- Bound selections to 16 controllers. Reuse trace limits (200 nodes, 16 levels,
  default depth 6) and existing pagination (maximum page size 50). Report omissions.
- Keep resolved context request-local. Bind cursors to caller, selection, context
  and relevant source versions; refresh authorization for every page.
- Acceptance: all six scenarios have evidence-bounded supported/partial results.

## PR 5: Explorer and integrated acceptance (#441)

- Extend the existing Explorer with lighting selections and results.
- Update the lighting guide and six-scenario DE/EN support matrix. New MCP prompt
  templates remain #444. Update schemas, architecture, DE/EN docs and changelog
  alongside behavior in each preceding PR, not only at the end.
- Acceptance: integrated user workflows and all six lighting questions are checked
  against actual capabilities and explicit limitations.

## Tests and reviews

- Inspect Changed selection with `python tools/test.py --profile changed --plan`;
  run affected checks during iteration and final Full CI on the exact PR head.
  Do not repeat equivalent successful final CI locally without a reason.
- Cover profile revision, visibility revocation, changed sources, contradiction,
  same-name independent controllers/plants, legacy energy contracts and zero writes.
- Cover multiple rooms/controllers, repeated mood IDs, hidden/missing/invalid
  sources, truncation, pagination and unsupported versions.
- Cover direct/indirect/central paths, ambiguous parents, unmapped sensors,
  unresolved flow and unchanged exact-only mapping definitions.
- Cover missing planning context, hypothetical assumptions, explicit scene roles
  and controller capabilities versus physical fixture claims.
- Architecture/contract review precedes analyzer implementation. Independently
  review final diffs and security boundaries; fix relevant findings, rerun affected
  checks/acceptance, at most five review iterations per PR. Unresolved findings
  or failed checks block merge. Recheck gates after master integration.
- Use normal linear reviewed PR merges. Never push directly to master.

Owner extension (2026-10-19): PR #568 may receive up to five further independent
reviews after the `85679bd3` checkpoint. This replaces the exhausted original
three-round limit for that PR; tests, live acceptance and merge gates still apply.

## Gen.-1 acceptance and completion

- Acquire and hold an exclusive Loxberry-Test reservation. Wait if busy; no
  parallel reservation/deployment. Release and verify terminal reservation state.
- Guarded hot-swap: retained backup, hashes, atomic replacement, native modes and
  owner, service/restart, health and scoped feature smoke; retain rollback evidence.
- Use real authorized HTTPS/Bearer MCP with certificate verification. Test missing
  and invalid authentication and available restricted identities; never expose
  credentials or fabricate grants.
- Compare actual moods, child controls and available project paths with sources.
  Missing device combinations remain unverified; synthetic evidence is separate.
- For affected Explorer flows, check DE/EN at CSS 1280x800 and 390x844; expand
  viewport checks only if shared layout is changed.
- Do not enable recording, change profiles/configuration, operate controls or
  induce events to manufacture acceptance. Keep private identifiers and detailed
  device receipts in the private evidence workspace.
- Close #559 after PR 1 gates. Close #441 after PR 5 gates and the six-scenario
  support matrix are complete. Report implemented, automated and device-confirmed
  evidence separately; missing required evidence remains incomplete.
