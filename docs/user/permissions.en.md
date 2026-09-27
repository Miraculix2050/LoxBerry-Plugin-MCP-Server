# Permissions

[Deutsch](permissions.de.md)

## Principle

Use a separate Loxone account for each assistant. The server only exposes elements that this user may see or operate.

| Scope | Enablement | Effect |
| --- | --- | --- |
| `loxone:read` | always | Read structure, current states, and bounded Project Intelligence through the same Loxone identity |
| `loxone:history` | optional | Read history and statistics |
| `loxone:control` | optional | Operate documented visible controls |
| `loxberry:read` | optional, local approval | Read masked plugin and system diagnostics |
| `loxberry:operate` | optional, with `loxone:history` and local approval | Clear the plugin-owned statistics cache, manage local event-history sources, and explicitly purge one inactive source's retained history |

Control is disabled by default. Local LoxBerry approvals are bound to the client application, Loxone identity, Miniserver, and exact capability; they never replace Loxone rights or OAuth consent. For the strictly validated local Tool Explorer, a new OAuth login can reuse its application approval until the displayed inactive-retention deadline. Other dynamically registered clients remain bound to their exact OAuth client identifier.

Project Intelligence does not add a scope. Every invocation checks the bound identity and reads
the currently visible Loxone structure through an authenticated session. Its project change marker
and the fresh visibility result determine cache validity. An unchanged marker
allows reuse of a bounded in-memory graph; a changed or unavailable marker invalidates it.
The project is downloaded again only when the graph must be rebuilt. Cached results never grant
OAuth access. It exposes
bounded graph status, search, object descriptions, and upstream/downstream signal or reference
traces, never raw project files or project modification.
Project search and analysis continuation pages reuse bounded ordered results for up to five minutes. A cursor
expires when that result is evicted or the project, visible structure, identity, or analysis
selection changes; restart from the first page in that case.
KNX/EIB metadata is an allowlisted, bounded projection of that same authorized project; it does
not expose arbitrary project attributes, ETS data, bus monitoring, or configuration writes.
Native Loxone History and statistics reads load the current user-filtered structure
afresh before returning data, including a statistics cache hit. An unchanged project
marker alone does not prove current visibility. Local Event History also checks
visibility with a fresh structure download.

Next: [Capabilities](capabilities.en.md).
