# Development automation

Use repository scripts for deterministic, shareable work. Keep target-specific
authorization, connection profiles, credentials, and private test fixtures outside Git.

## Local and CI-safe commands

- `python tools/test.py` runs the deterministic formatting, lint, type, and test gate.
- `python tools/build_release_candidate.py --runtime-wheelhouse <cache>` rebuilds the
  project wheel, runs the full gate, builds the plugin twice, requires byte-identical
  ZIPs, writes the checksum, and verifies the final archive. Omit the cache argument to
  download the pinned Debian 13/arm64 wheels into a temporary directory.
- `python tools/verify_plugin.py <archive.zip>` verifies checksum, paths, file modes,
  LF text files, plugin identity, required entries, and the offline wheelhouse without
  extracting or installing the archive.
- `pwsh -File tools/test_mcp_client.ps1` starts the configured Claude MCP proxy and
  exercises all six read-only tools. Use `-VisibilityFixturePath <private-json>` to add
  a real visible/hidden-control boundary test. The private JSON contains only
  `visible_control_uuid` and `hidden_control_uuid` and remains outside Git.
- `-ControlFixturePath <private-json>` is a separate explicit opt-in for the Phase 2
  target smoke. It expects only `control_uuid` and `initial_state` (`on` or `off`),
  switches once to the opposite state and restores the recorded initial state. Use it
  only for a previously approved non-critical Gen. 1 Switch; keep the fixture outside
  Git.

`tools/build_plugin.py` and `tools/prepare_wheelhouse.py` remain useful low-level
building blocks for focused development. Use the release-candidate wrapper for any
artifact that is intended for target installation or publication.

## Target-system workflow

Automate orchestration, evidence collection, and sanitized checks, but keep explicit
boundaries around state-changing operations:

1. Verify the exact target profile and strict host key before transfer.
2. Compare local and remote SHA-256 before installation.
3. Prefer the native LoxBerry Plugin Manager or its exact installer command for install,
   upgrade, and uninstall.
4. Read the SecurePIN only from an approved external file or interactive input. Never
   place it in arguments, logs, repository files, or generated evidence.
5. Run health, service, Apache, ownership, configuration-schema, and MCP read-only
   smokes after the lifecycle action.
6. Preserve the installed plugin and configured MCP clients unless the requested test
   explicitly includes removal.

Replacing individual installed files is a diagnostic shortcut, not release evidence.
Limit it to plugin-owned paths, save a recoverable copy, preserve owner and mode,
restart only the affected plugin service, and follow it with a normal package upgrade
before claiming lifecycle acceptance.

Never automate changes to a Loxone Miniserver, access to a production LoxBerry, or the
publication of private addresses, identities, configuration, or test fixtures.
