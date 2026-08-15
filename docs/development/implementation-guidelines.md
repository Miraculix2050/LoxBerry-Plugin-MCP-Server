# Implementation guidelines

- **Audience:** Developers, maintainers, reviewers, testers and AI agents.
- **Status:** Binding engineering rules for the released plugin.

## Product and architecture

- Keep the plugin local, transparent and least-privileged. No project cloud service, arbitrary shell, file access, remote relay or generic LoxBerry administration.
- Keep MCP transport, policy, adapters, configuration and UI logically separate and test domain logic without real devices.
- Treat tool names, schemas, plugin identity, persistent paths and configuration keys as released contracts. Use compatible changes or explicit migrations.
- New persistent stores, frameworks and services require a concrete operational need.

## MCP contracts and security

- Read-only is the default. Every mutation requires explicit enablement, narrow typed allowlists, validation, timeout handling, audit logging and a documented uncertainty result.
- Validate type, range, length and target. Never accept free paths, commands or arbitrary URLs.
- Keep stable structured error categories and never expose secrets in results, errors, HTML, URLs, arguments or logs.
- Loxone and LoxBerry authorization are separate. A Loxone login never grants LoxBerry administration.
- Use Loxone token authentication. Gen. 1 stays local and uses command encryption; Gen. 2 requires validated HTTPS/WSS with no cleartext fallback.
- Default to no writes, no public binding and no additional system privileges.
- Treat all external responses as untrusted and protect against injection, traversal, SSRF, unsafe redirects and oversized data.
- Store secrets separately with least-permissive practical file rights. Rate-limit failed authentication and write calls without exposing secrets.
- Keep dependencies minimal, pinned and reviewed for known vulnerabilities.

## Configuration, UI and lifecycle

- Keep authoritative configuration, secrets and runtime caches separate. Validate before atomic persistence and preserve the last valid runtime configuration after failure.
- Upgrade preserves supported user data. New keys have explicit defaults; changed keys require idempotent migrations and tests.
- Keep German and English user-facing text synchronized. Technical identifiers, tool names and logs remain English.
- Admin UI must be responsive, accessible and clear about saved, applied and running state. Do not reveal secrets or offer generic command consoles.
- Follow native LoxBerry installation, upgrade and uninstall conventions. Run services with minimal rights and keep persistent data outside packages and temporary directories.

## Logging and diagnostics

- Use sanitized, structured logs with component, severity and correlation ID. Never log full credentials, tokens, private keys, full structures or unnecessary sensitive states.
- Debug logging is opt-in. Diagnostics expose only fixed plugin-owned sanitized fields and never arbitrary logs, paths, journal or foreign-service data.

## Tests, documentation and releases

- Select validation through the [test strategy](test-strategy.md). Use Changed during iteration and Full on final cross-cutting revisions, release candidates and CI.
- Add regression coverage for contracts, authorization, migrations, security boundaries and defect fixes. Missing required runtime or hardware evidence is incomplete, not passing.
- Update documentation and `CHANGELOG.md` with behavior, configuration, security, compatibility, dependency or upgrade changes.
- Maintain a concise root README, structured user documentation, current support matrix and architecture documentation. Keep historical raw research and detailed evidence outside public product documentation.
- Release claims distinguish implemented, automated and hardware-confirmed behavior. Publish only through the reviewed release process.
