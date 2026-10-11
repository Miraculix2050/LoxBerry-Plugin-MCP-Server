# Confirmed installation profile

Open **Confirmed installation profile** on the plugin home page. Select a visible
measurement source or state and assign a role. Optionally declare a measurement
boundary, direction and rationale. Without **Explicitly confirm this binding**,
the binding remains a draft. Editing requires confirmation again.

Multiple producers, meters and consumers are supported; storage and individual
appliances are optional. Roles are not inferred from names or categories. A
confirmed role does not prove a unit, aggregation or physical measurement boundary.
Technical semantics are checked separately. The profile contains no energy/history
calculations of its own.

In **Approve MCP profile management**, enable the default-disabled capability and
approve or revoke active clients individually. Approval binds the exact client,
user and Miniserver; names are display labels. New Explorer clients require a new
approval. General LoxBerry operation rights alone do not permit profile changes.

`loxberry_save_installation_profile` saves one exact binding;
`loxberry_delete_installation_profile` deletes one binding or the entire profile.
Both require `loxone:read`, `loxberry:operate`, general local operation approval
and the independent profile approval. The existing operate scope also requires
`loxone:history`. The AI must first explain the exact proposal or deletion scope
and obtain your explicit confirmation in chat. It then passes `confirm=true` and
`expected_revision` from a fresh read. The server records the client's assertion;
it cannot independently prove the conversation. Saving a draft does not confirm
its role. For `write_outcome_uncertain`, inspect the stored state and never
automatically retry. A changed revision requires reading again and reconfirming
any changed proposal. MCP whole-profile deletion is denied when any affected
binding is outside current visibility. Installation replacement is reset in Admin.

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
