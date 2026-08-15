# Permissions

[Deutsch](permissions.de.md)

## Principle

Use a separate Loxone account for each assistant. The server only exposes elements that this user may see or operate.

| Scope | Enablement | Effect |
| --- | --- | --- |
| `loxone:read` | always | Read structure and current states |
| `loxone:history` | optional | Read history and statistics |
| `loxone:control` | optional | Operate documented visible controls |
| `loxberry:read` | optional, local approval | Read masked plugin and system diagnostics |
| `loxberry:operate` | optional, with `loxone:history` and local approval | Only clear the plugin-owned statistics cache |

Control is disabled by default. Local LoxBerry approvals are bound exactly to client, Loxone identity and Miniserver; they never replace Loxone rights or OAuth consent.

Next: [Capabilities](capabilities.en.md).
