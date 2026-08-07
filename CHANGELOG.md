# Changelog

All notable user-visible changes are recorded here. GitHub release notes are
extracted from the matching version heading.

## Unreleased

## 0.3.0-alpha.1 - 2026-08-07

- Add disabled-by-default, locally approved `loxberry:read` diagnostics for
  sanitized LoxBerry system, plugin, and MCP service status.

- Give `service.log` a dedicated persistent Off/Error/Warning/Information/Debug
  level while retaining masked, unsuppressible audit records for control attempts.
- Enable the native LoxBerry Log Manager level for plugin logs and consolidate
  admin actions into one rotating `admin-ui.log` instead of one file per action.
- Bound both active logs to 512 KiB plus two backups and individual records to
  8 KiB while avoiding routine admin-page and HTTP access-log writes.
- Build official packages only through the owner-triggered GitHub workflow, with
  canonical ZIP and wheel output, locked runtime-wheel hashes, exact manifests,
  verified draft uploads, and separate read/write job permissions.

## 0.2.0-alpha.1 - 2026-08-05

- Add read-only and explicitly authorized Loxone MCP tools, OAuth, the integrated
  Tool Explorer, and the packaged `using-loxberry-mcp` agent skill.
- Package a fully offline Debian 13 arm64/Python 3.13 runtime for native
  installation through LoxBerry Plugin Manager.

## 0.1.0-alpha.1 - 2026-07-31

- Publish the first owner-tested MCP Server alpha for LoxBerry 4.
