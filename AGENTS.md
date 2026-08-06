# Project Instructions

This repository contains the LoxBerry MCP Server plugin. Apply the mandatory
rules below to every change. Before implementation, read only the relevant
sections of `docs/development/implementation-guidelines.md`: sections 3-6 for
architecture, MCP contracts, security, or configuration; section 7 for UI;
section 8 for lifecycle; section 9 for logging; and sections 10-11 for tests,
documentation, or releases. Read the whole document only for cross-cutting or
unclear changes. Select verification from
`docs/development/test-strategy.md`; do not reread unchanged sections during the
same task.

## Working rules

- Keep changes small and compatible with the native LoxBerry plugin layout.
- Treat MCP tool names, input/output schemas, configuration keys, plugin identity,
  and persistent paths as contracts once released.
- Separate Loxone authorization from LoxBerry authorization. Never infer
  administrative LoxBerry permissions from a Loxone login.
- Default new capabilities to read-only. Mutating tools require an explicit,
  narrow allowlist, input validation, authorization, timeout handling, and an
  audit record.
- Keep developer-facing code, comments, logs, and technical diagnostics in
  English. Keep German and English user-facing UI and documentation synchronized.
- Never store or print credentials, tokens, session data, or private keys.
- Update documentation and tests together with behavior, configuration,
  permissions, dependencies, compatibility, or upgrade changes.
- Use change-driven tests. Documentation-only changes do not require device or
  browser acceptance unless they change generated or rendered behavior.
- During iteration use `python tools/test.py --profile changed`; inspect the
  selection first with `--plan` when scope is unclear. Reserve the Full profile
  for the final revision, cross-cutting fallback, CI, and release packaging.
- Do not claim platform, browser, device, or Miniserver compatibility without
  matching evidence.
- Preserve unrelated worktree changes and inspect `git status --short` before
  committing.
- Prepare release metadata and `CHANGELOG.md` through a reviewed PR. Official
  stable and prerelease packages, tags, and GitHub Releases must be created only
  from prepared `master` with the owner-triggered `Publish plugin release`
  workflow. AI agents invoke that same workflow with `gh workflow run`; local
  `-local-...` ZIPs are test artifacts only.

## Git workflow

Follow `CONTRIBUTING.md`. Never push directly to `master`. When the user clearly
requests a small editorial correction or a small specification addition without
immediate code, configuration, runtime, or security impact, complete the branch,
commit, push, ready PR, checks, merge, remote-branch cleanup, and local
fast-forward workflow without asking for separate confirmation at each step.
Stop on ambiguity, conflicting requirements, failed required checks, merge
conflicts, unexpected unrelated changes, or an analysis-only/no-push request.
All executable, behavioral, configuration, security, test, CI, dependency, and
normative contract changes require a normal reviewed pull request and must not be
auto-merged under this exception.
