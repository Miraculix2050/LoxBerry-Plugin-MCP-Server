# Architecture

- **Purpose:** Current implementation architecture and operational boundaries.
- **Audience:** Maintainers, reviewers and contributors.
- **Status:** Authoritative for the implemented system; ADRs record why significant decisions were made.

## System context

The plugin runs a local MCP server on LoxBerry. Apache publishes the fixed HTTPS MCP path and proxies only to a loopback service. The plugin has no project cloud service and supports one configured Miniserver.

```text
MCP client -- HTTPS/OAuth --> LoxBerry Apache -- loopback --> mcpserver service
                                                        |--> Loxone HTTP/WebSocket adapter
                                                        |--> LoxBerry read adapters
                                                        `--> configuration, sessions and bounded caches
```

## Components and contracts

| Component | Responsibility |
| --- | --- |
| MCP transport and registry | Streamable HTTP, stable tool schemas, validation and structured errors |
| OAuth and policy | PKCE, scopes, client binding, consent, revocation and per-call authorization |
| Loxone adapter | Token authentication, filtered structure, states, history and bounded control transport |
| Control registry | Explicit actions and value ranges per supported control type |
| LoxBerry adapters | Masked diagnostics and the limited plugin-owned cache operation |
| Admin UI and Explorer | Local configuration, session management and a separate OAuth test client |

## Authorization and data flow

Loxone authorization is evaluated with the signed-in Loxone user. LoxBerry authorization is independent: `loxberry:read` and `loxberry:operate` require matching local approval bound to client, Loxone identity and Miniserver. `loxone:control` additionally requires a global feature switch, OAuth consent, a visible operable Gen.-1 target and a typed allowlist.

The server loads the user-filtered structure at connection start and refreshes it only after a bounded version-marker check. State data is held in runtime snapshots; statistics use a bounded RAM cache. No arbitrary files, shell commands or target URLs are accepted from MCP input.

## Persistence and lifecycle

Configuration, encrypted sessions and plugin identity persist outside the package. Secrets are separated from ordinary configuration. Root lifecycle hooks consume service templates only from the current installer staging area, never from the installed plugin configuration or binary directories. The staging area's integrity remains a LoxBerry Core trust boundary because Core runs unprivileged lifecycle hooks before `postroot`; plugin code cannot make that shared staging area root-owned. Within the persistent LoxBerry tree, sensitive root operations use descriptor-relative traversal and reject symbolic links, non-regular files and path replacement. Install, upgrade and removal follow the native LoxBerry layout; upgrade preserves supported configuration and authentication state through idempotent migration. The service starts unprivileged, validates configuration and listens only on loopback.

## Security and observability

Gen. 1 uses local HTTP/WS plus Loxone command encryption; Gen. 2 requires validated HTTPS/WSS and never falls back to cleartext. Logs and diagnostic exports are structured and sanitized: no credentials, tokens, private keys, full structures or arbitrary raw logs. Writes are audited without secrets and are never retried after an uncertain outcome.

The authenticated Admin UI sends no-store cache directives, a same-origin Content
Security Policy, frame denial, a no-referrer policy and MIME sniffing protection
for page, AJAX, diagnostic-download and redirect responses.

## Related documents

- [Implementation guidelines](implementation-guidelines.md)
- [Architecture decisions](adr/README.md)
- [Test strategy](test-strategy.md)
- [Support matrix](support-matrix.md)
