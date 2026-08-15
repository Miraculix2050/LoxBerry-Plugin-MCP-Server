# Configuration

[Deutsch](configuration.de.md)

## Basic settings

Configure one local HTTPS origin and exactly one Miniserver target. Selecting a Miniserver stored in LoxBerry does not reuse its credentials. An unreachable or invalid target is not enabled.

## Certificate

Use an MCP client address covered by the LoxBerry web-server certificate. Certificate diagnostics show whether the configured origin matches. Reissuing a local certificate requires SecurePIN and confirmation; externally issued certificates are not changed.

## Feature switches

The admin interface only enables a feature globally. The client must also request the matching scope and the user must approve it.

Next: [Permissions](permissions.en.md).
