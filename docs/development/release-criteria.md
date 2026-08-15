# Release criteria

A beta release freezes its declared feature scope. Until the matching stable
release, only beta blockers, fixes and necessary compatibility work are added.

Before publishing, require a green Full CI run on the final commit, reviewed
documentation and changelog, verified package and checksum, and no known
critical security, data-loss, installation or authorization defect. Record a
dated dependency, license and vulnerability check. Native evidence includes a
fresh install plus Alpha-to-Beta upgrade with preserved supported configuration,
sessions and plugin identity, installed version, service and loopback health.
Smoke the Admin UI and an OAuth read-only MCP flow. A write smoke is separate
and requires explicit fixture authorization. Record automated and hardware
evidence separately.

Official publication runs only from reviewed `master` through the owner-triggered
release workflow. Prereleases use an `alpha` or `beta` version; stable releases
use a plain release version.
