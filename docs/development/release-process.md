# Release process

Official plugin releases are built only by the owner-triggered GitHub Actions
workflow `Publish plugin release`. GitHub's automatically generated source ZIPs
are repository snapshots and are not installable LoxBerry plugin packages.

## Prepare master

1. Update `plugin.cfg`, `pyproject.toml`, the selected `release.cfg` or
   `prerelease.cfg`, and the matching `CHANGELOG.md` heading in a reviewed PR.
2. If runtime dependencies change, regenerate `runtime-arm64.lock` and
   `runtime-arm64.sha256` together and review every wheel filename and hash.
3. Merge only after the Full profile and package tests pass.

## Publish through the web UI

1. Open **Actions** and select **Publish plugin release**.
2. Choose **Run workflow** and select `master`.
3. Enter the exact version, choose `prerelease` or `stable`, tick the mandatory
   confirmation, and start the run.
4. Check the completed run and the ZIP plus `.sha256` assets on the release.

The workflow accepts only the repository owner as both the original actor and
the actor requesting a rerun. It checks out the immutable dispatch commit rather
than a later `master` head, validates metadata and changelog, and builds and
verifies the deterministic package,
creates an annotated `v<version>` tag, uploads to a draft release, downloads and
hash-checks both assets, and only then publishes the chosen channel. A compatible
orphaned tag or draft can be resumed only when its title, notes, and assets match
the verified build; published or mismatching state is never overwritten.

AI agents use this same path after the preparation PR is merged:

```powershell
gh workflow run "Publish plugin release" --ref master `
  -f version=0.3.0-alpha.1 -f channel=prerelease -f confirm_release=true
```

No agent may create an official ZIP locally. A future GitHub App actor remains
blocked until its exact actor identity is explicitly added and reviewed.

## Local test packages

`python tools/build_release_candidate.py --runtime-wheelhouse <verified-cache>`
creates `LoxBerry-MCP-Server-<version>-local-<commit>[-dirty].zip`. Local packages
are for testing only. On a clean identical commit their ZIP bytes are identical
to the GitHub package; only the outer filename and checksum-sidecar filename
differ.
