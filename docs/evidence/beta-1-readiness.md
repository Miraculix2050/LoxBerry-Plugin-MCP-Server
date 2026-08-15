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
2026-08-15 review covered all 30 locked runtime packages. `pip-audit` 2.10.1
reported no known vulnerabilities. The project is Apache-2.0; every runtime
wheel supplied license metadata: 15 MIT, 10 BSD-3-Clause, and one each of
Apache-2.0, Apache-2.0 OR BSD-3-Clause, MIT-0, MPL-2.0 and PSF-2.0. The
sanitized dated result is retained in Project-Data evidence.

## Required native acceptance

Before publication, perform a native fresh install and a separate Alpha-15
upgrade of the verified candidate on the authorized target. For both paths,
verify terminal installer status, version, active service and loopback health;
for the upgrade also verify preserved supported configuration, sessions and
plugin identity. Smoke the Admin UI and an OAuth read-only MCP flow. No write
action is part of this record without separate current fixture authorization.

## Candidate evidence

The Alpha-15 upgrade candidate retained the supported configuration and five
sessions; its bounded diagnostic reported an active, enabled service. The
subsequent clean candidate SHA-256 was
`e0eea6e83013fcfc19d9d8877899257b9a5e51a2fff1d5d5b6954bb36ed53ae2`.
After a native Plugin Manager uninstall, it completed a separate fresh install
with terminal status `0`; the active service and loopback health reported
`0.4.0b1`. Both sanitized lifecycle records are retained in Project-Data
evidence.

Chrome acceptance used an authenticated LoxBerry administrator session. The
Admin UI showed Beta 1 and an active, running service on desktop and mobile;
the mobile viewport had no horizontal overflow. The authenticated Tool Explorer
completed the read-only `loxone_get_skill_guide` call successfully. No Loxone
write smoke was requested or performed.
