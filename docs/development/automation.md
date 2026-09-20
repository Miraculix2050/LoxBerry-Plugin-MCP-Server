# Development automation

Use repository scripts for deterministic, shareable work. Keep target-specific
authorization, credentials, connection profiles, and private fixtures outside Git.

## Change-driven local checks

- `python tools/test.py --profile changed --plan` shows the checks selected from
  the branch diff, staged and unstaged changes, and untracked files without running
  them.
- `python tools/test.py --profile changed` runs that focused selection.
- `python tools/test.py --profile changed --files <path> [<path> ...]` selects from
  explicit paths. Use `--base-ref <ref>` only when automatic `origin/master`
  comparison is not appropriate.
- `python tools/test.py --profile full` runs formatting, lint, strict typing, and
  all deterministic tests. The backward-compatible `python tools/test.py` does the
  same.

Changed selection maps known files to affected tests. Documentation-only changes
run only `git diff --check`; unknown or cross-cutting paths fall back visibly to
Full. An invalid explicit base ref fails instead of silently choosing another scope.
Do not repeat an unchanged successful selection during the same iteration.

Focused checks may run in the available development environment. Full evidence
requires Python 3.13 plus Perl and Node.js; the runner exits `2` as incomplete when
those requirements are missing. CI runs Full on Python 3.13. A green Full CI result
for the same commit need not be duplicated locally.

When no `--basetemp` is already configured, the runner gives each pytest
invocation a unique repository-local temp directory under `tmp`. This avoids
relying on a global user temp directory that may be unavailable in a restricted
local environment and keeps overlapping test runs isolated.

## Windows development environment

Before running local checks on Windows, create the project-local Python 3.13
environment once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup-development-environment.ps1
```

The setup script requires an already-installed Python 3.13 interpreter, creates
`.venv`, installs the locked runtime and development dependencies, and installs
the project in editable mode. It does not download or install Python. Pass
`-PythonPath <path-to-python.exe>` when Python 3.13 is installed outside the
standard locations.

Use the virtual-environment interpreter for every local test command; do not use
the global `python` command:

```powershell
& .\.venv\Scripts\python.exe tools\test.py --profile changed --plan
& .\.venv\Scripts\python.exe tools\test.py --profile changed
```

In a restricted Codex sandbox, an installed Python interpreter can be visible
but not executable. Run the setup as an approved elevated command in that case.
For new Codex worktrees, configure the same Windows setup command as a local
environment setup script in the ChatGPT desktop app. The generated `.codex`
configuration is intentionally ignored and must not be edited manually.

## Packages

- `python tools/build_release_candidate.py --runtime-wheelhouse <cache>` runs Full,
  rebuilds the project wheel, builds one plugin ZIP, writes SHA-256, and verifies the
  archive.
- `python tools/prepare_wheelhouse.py --runtime-only <cache>` prepares a persistent
  external Debian 13/arm64 runtime-wheel cache. Recreate it after
  `requirements/runtime-arm64.lock` changes and never commit it.
- `python tools/verify_plugin.py <archive.zip>` verifies an existing archive without
  extracting or installing it.

Use `tools/build_plugin.py` and `tools/prepare_wheelhouse.py` only as low-level
building blocks. Build no ZIP for ordinary local checks or focused feature
acceptance. Use the release-candidate wrapper for installation, upgrade,
publication, or final release evidence.

## MCP client smokes

`pwsh -File tools/test_mcp_client.ps1` detects the active Microsoft Store or classic
Claude profile and exercises the read-only tools plus both skill-delivery surfaces.
Use `-CallbackPort <unused-port>` only for a callback-port conflict. Supply private
UUIDs only through an external `-VisibilityFixturePath` file.

`-ControlFixturePath <private-json>` is a separate explicit opt-in. Use it only for
a previously approved non-critical Gen. 1 Switch; it must restore the recorded
initial state. Never place fixture values in argv, logs, Git, or evidence.

## Target-system workflow

For focused development or feature acceptance, transfer only changed plugin-owned
files with a recoverable backup, preserved owner/mode, and atomic replacement.
Restart only `loxberry-mcpserver.service` when runtime code changed, then run the
narrow smoke that motivated the transfer. This is feature evidence, not package or
lifecycle evidence.

For native install, upgrade, or uninstall:

1. Verify the exact target profile, strict host key, local ZIP, checksum, and remote
   checksum.
2. Use the native Plugin Manager or its exact authorized installer command. Read the
   SecurePIN only from approved external input, never argv or logs.
3. Wait for terminal installer status before starting another lifecycle action.
4. Always verify installed version, service state, and loopback health.
5. Add Apache, ownership, secret modes, schema, persistence, browser, or MCP client
   checks only when affected by the diff or required for final release acceptance.
6. Preserve the installed plugin and configured clients unless removal is explicitly
   requested.

Batch browser DOM, overflow, focus, and console checks per viewport. Reuse an
authenticated session and capture screenshots only for visual changes or failures.
Never access production, change the Miniserver without explicit control authorization,
or publish private configuration or identities.
