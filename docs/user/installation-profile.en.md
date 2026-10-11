# Confirmed installation profile

Open **Confirmed installation profile** on the plugin home page. Select a visible
measurement source or state and assign a role. Optionally declare a measurement
boundary, direction and rationale. Without **Explicitly confirm this binding**,
the binding remains a draft. Editing requires confirmation again.

Multiple producers, meters and consumers are supported; storage and individual
appliances are optional. Roles are not inferred from names or categories. A
confirmed role does not prove a unit, aggregation or physical measurement boundary.
Technical semantics are checked separately. This first profile slice contains no
energy/history calculations and no MCP write operation.

`loxone_get_installation_profile` requires `loxone:read` and returns at most 100
bindings per page. Follow `next_offset` until it is null. Every call checks fresh
visibility. Hidden controls and their bindings are omitted; there is no global
binding count. If an old source disappears from a still-visible control, a
sanitized invalid binding is shown without the old source ID.

Technical source changes yield **Review required**; presentation renaming does
not change confirmation. Pages and responses distinguish **Draft**, **Confirmed**,
**Review required**, and **Source no longer available**. Unavailable data must not
be interpreted as an absent installation component.

The profile is bound to the Miniserver endpoint and serial identity. An installation
replacement does not inherit old bindings. Explicitly delete the old profile and
create new bindings. Individual bindings and the entire profile can be deleted.
An HTML dialog identifies the deletion scope; **Cancel** or Escape closes it without changes.
Deletion retains a revision to protect against stale writes. Reload after a
conflict; when persistence is uncertain, inspect the stored state instead of
automatically retrying.

Only minimal profile metadata is persisted in `installation-profile.json` in the
plugin-owned data directory, limited to 256 bindings and 1 MiB. Native service
configuration determines the data directory through the existing KNX store path.
No credentials, measurements or complete structures are stored in the profile.
Upgrade preserves it; unknown schema versions are rejected without overwriting.

Admin source selection is limited to 500 entries. Larger installations can enter
exact IDs from Explorer; current Admin visibility is validated again before saving.
Admin visibility never grants a MCP client additional Loxone access.
