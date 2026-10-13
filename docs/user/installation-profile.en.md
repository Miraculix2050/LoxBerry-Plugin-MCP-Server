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

Select **Weather context** to bind an exact current or forecast weather source and
one weather field. This source has its own visibility check and no control UUID.
Formats are presentation metadata; units and the `solar_radiation` encoding remain
unverified. Current source values are not automatically measured observations,
and forecasts are not historical measurements. Existing state/statistic weather
bindings keep their original coverage. Structured weather history requires the
independently enabled [recorder](weather-history.en.md); profile declarations do
not check its coverage. Source formats and rule changes
require review; provider, station and location changes cannot be fully detected.

Production bindings optionally contain **PV installation parameters**: installed
kWp, paired latitude/longitude and up to 16 uniquely identified arrays with optional
capacity, north-zero clockwise azimuth, tilt and a qualitative shading description.
All are user declarations, confirmed with the entire binding on each save.
Drafts or bindings requiring review do not provide usable confirmed parameters.
Unknown geometry does not by itself prevent simple comparisons. Array capacities
are independent declarations; no completeness, sum equality, individual measured
yield or shading loss factor is inferred. PV details are withheld when their
production source is inaccessible or invalid.

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
The authorized read context remains admitted through the local file read and
checks access again before returning a page. Revocation or expiry during a file
wait prevents publication; the final check does not add a Miniserver request.
Missing weather sources omit the complete binding. Replacing a binding ID checks
both the old and new source, including changes of source kind. MCP cannot delete
an inaccessible old weather binding; authenticated local Admin can remove orphaned
local metadata. If a full MCP page exceeds 64 KiB, request a smaller `limit`.

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
Version 1 is validated and migrated to version 2 in memory without changing file
content on reads. The next authorized revision transaction persists version 2.
Older plugin versions cannot read version 2: binary rollback after a profile write
requires restoring the prior profile backup together with the older code.

Admin source selection is limited to 500 entries. Larger installations can enter
exact IDs from Explorer; current Admin visibility is validated again before saving.
Admin visibility never grants a MCP client additional Loxone access.


## Flexible load constraints

Consumer bindings optionally declare local weekly time windows, an explicit
same-day/next-day completion deadline, expected duration, interruptibility,
minimum run/off times and energy-profile provenance. Select an independently
confirmed binary operating-state binding. Changing any parameter requires
renewed confirmation of the whole binding. These are user declarations; they
neither prove a physical program cycle nor authorize a load operation.

`active_episode_only` is the default. Select `user_confirmed_cycle` only if you
explicitly confirm that this operating state represents the complete appliance
cycle. Unknown/native locks remain `not_checked` and must never be bypassed.
Measured interval energy and a user-declared Wh value are kept separate. See
[observed load cycles](load-cycles.en.md) for the historical analysis.

A hidden, missing, changed or unconfirmed companion makes constraints unusable.
Its identifiers are withheld; the stored declarations are retained. Edit cannot
silently erase withheld constraints. Reusing a companion binding ID for another
source requires renewed consumer confirmation. MCP replacement/deletion checks
old and new companion visibility as well as the primary source.

Profile schema v3 reads validated v1/v2 files without rewriting them or changing
the revision. The next authorized mutation stores v3. Source fingerprints and
existing confirmations are retained. Older readers cannot consume v3; rollback
requires the appropriate profile backup rather than relabelling the version.
