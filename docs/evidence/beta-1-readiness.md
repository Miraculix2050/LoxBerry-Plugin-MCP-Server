# Beta 1 readiness record

- **Date:** 2026-08-15
- **Candidate:** `0.4.0-beta.1`
- **Scope:** Feature-frozen `0.4.0` beta; only blockers, fixes and required compatibility changes may follow.

## Deterministic evidence

The final commit requires the Python 3.13 Full gate, release metadata validation,
a verified release-candidate ZIP and SHA-256 sidecar. CI is the authoritative
gate for the merged commit.

## Dependency and license check

Runtime dependencies are locked in `requirements/runtime-arm64.lock`. The
repository's Dependabot alerts endpoint was checked on 2026-08-15 but is disabled
for this repository, so it provides no vulnerability result. `pip-audit` is not
installed in the release environment. This is recorded as an incomplete external
vulnerability check, not as a clean result. The existing Apache-2.0 project
license and locked dependency set have not received a dated beta review.
Publication is blocked until the dependency, license and vulnerability check is
completed and recorded.

## Required native acceptance

Before publication, perform a native fresh install and a separate Alpha-15
upgrade of the verified candidate on the authorized target. For both paths,
verify terminal installer status, version, active service and loopback health;
for the upgrade also verify preserved supported configuration, sessions and
plugin identity. Smoke the Admin UI and an OAuth read-only MCP flow. No write
action is part of this record without separate current fixture authorization.

## Candidate evidence

The verified local candidate SHA-256 was
`92c26365f350977a2a2a89faae66ec7e201e8cb0bd4ed25a348c6d274da3a5a6`.
Its native installation on the authorized target restarted the service. The
subsequent loopback health response reported `0.4.0b1`; the bounded diagnostic
reported an active, enabled service and five retained sessions. The Plugin
Manager status files include terminal success (`0`) records for the install.

The Admin UI and OAuth read-only smoke remain open: both available browsers
received native HTTP Basic authentication rejection and no credentials were
entered. The incomplete external vulnerability check and these two smokes are
release blockers; this record does not claim publication readiness.
