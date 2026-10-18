# KNX information through MCP

## Loading and refreshing address administration

On opening, the page loads the catalog, grants and draft overview together.
An expanded main/middle-group view is included in this request. The saved login
is restored in parallel. A selected correction draft is also included using the
current overview; target, draft revision, sort and page must match. A remembered
project comparison is restored in parallel; comparison rows appear only after
checking the current catalog binding. Loading indicators remain
visible until their respective sections are ready.

In a visible tab, saved MCP grants are checked together every ten seconds.
This background check does not overwrite unsaved inputs. Project comparisons
continue downloading fresh project data under the caller's own Loxone permissions.
Within one admitted project read, only the normalized public certificate is reused;
subsequent calls fetch it again. Authentication and the final project-marker check
still use new connections. Verified HTTP trust configuration is reused per client.
Rebuilding the model can take longer, particularly after a service restart;
a complete page-loading time below five seconds has not yet been established.

The KNX helper loads solar analysis models only when they are used. Configured
sources remain fully validated even when recording is disabled. Unused topology
indexes are avoided for single-occurrence project identities; local UUID conflicts
and authorization checks remain unchanged. No additional result cache is introduced.

## Local Config file: EIBType mapping

Developers can inspect a local `.Loxone` XML project file read-only:
`python -m mcpserver.loxone.project.config_knx "path/to/project.Loxone"`.
Run this in the configured Python development environment. The file is neither
uploaded nor modified; output contains object type, XML index, raw EIBType,
mapping status and EIS/DPT main types, without project names or IDs.

The mapping is evidenced for format `274` with ConfigVersion `17020828`, for
example `EIBType=4` → EIS5/DPT9. For `EIBsensor` and `EIBactor` without an
`EIBType` attribute, the agreed implicit Config default is DPT1, without an
EIS type or invented raw code (`mapped_implicit_config_default`). An actor with
`EIBType=6` remains separately EIS7/DPT1 (`mapped_explicit_code`). Empty, unknown
or conflicting attribute values remain unresolved. Text sensors/actors are
recognized separately by object type. The mapping is named `config-knx-v2`.
Multiple candidate DPT main types remain intact, without deriving a subtype. Other versions are
reported as unverified. This inspection applies to Config project files. The
separately verified live MCP mapping is documented in the
[datatype evidence](../development/knx-datatype-evidence.md).

## Live MCP: Loxone main type and ETS subtype

For paired source-type/code combinations in Miniserver format `274` with
ConfigVersion `17020828`, Describe returns `normalized_dpt_evidence`: source format,
mapping version, EIS and candidate DPT main types. Sensor/actor `EIBType=4` yields
main type 9; `datatype.source_value` stays `4`, `system=dpt_main_type` and
`normalized_code=9`. ETS `DPST-9-4` remains separately `9.004` in
`metadata.dpt_details`. A subtype is never derived from EIBType. Multiple main
types remain candidates without selection. An absent sensor/actor attribute adds
separate DPT1 evidence without EIS or an invented raw code; actor code6 remains
EIS7/DPT1. Only paired combinations are enabled; empty/conflicting codes,
unverified versions and extended families remain unresolved. Main-type agreement
never confirms device/telegram compatibility.

## Address administration: search, editing and JSON exchange

Under **Group addresses**, **JSON exchange** appears directly below ETS import
and starts collapsed. As with other sections, its expanded state is retained
in the browser. **Search and filter** only changes the display. Saved group
addresses, including imported main/middle groups, appear below, followed by a
separate area for adding or editing an address. During editing, its heading
identifies the selected address.

JSON exchanges local address metadata, including imported values and manual
additions. Export includes only the displayed, filtered table page, not the
complete inventory. Import shows a preview first; only explicit application
adds included addresses or overwrites their metadata. Other addresses remain
unchanged. Address labels, the imported group hierarchy and reconstructable ETS
XML source data are excluded. JSON import removes existing XML reconstruction
provenance for affected addresses; reimport the original ETS XML file before a
later XML correction export. JSON exchange replaces neither ETS import nor a
complete backup.

## Sorting and project-comparison navigation

Data-column headings are buttons. Click once for ascending order and again for
descending order; arrows show the direction. Keyboard navigation is supported.
The selected order survives a reload in the same tab. Action columns without a
data value are excluded. The XML-selection column can be sorted by checked state.

Group addresses, file comparison, project comparison and correction drafts are
sorted before pagination, across the entire dataset. JSON export still uses
exactly the displayed address page with its filters and sort order. Checkboxes
and editing actions remain attached to the original records. Sorting changes
neither address data nor decisions.

In **ETS/Loxone project comparison**, **Previous** and **Next** show result pages
with their entry range. Previously read pages may be reused in the open tab for
up to one minute, bounded to 20 pages and 8 MiB. New server requests check access
and the project again; **Run comparison** always reads fresh results. Project
evidence is still checked freshly before XML preview/download.

After reload, only target binding, page position and sorting are restored; result
content and credentials are not persisted in browser storage. Results are read
freshly. If the dataset shrinks, navigation starts from the beginning again. A
temporary read failure keeps the previous view visible but prevents its use as
current export evidence until a successful refresh.

## Correction drafts in the browser

### Managing main and middle groups

Under **Group addresses**, ETS import and JSON exchange precede separate
**Main and middle groups** and **Individual addresses** views. Group data loads
only when opened; collapsed groups add no request. Open states survive reload.

The group list includes all imported groups, including empty groups, and local
group labels. Default prefix sorting is hierarchical, with main groups before
their middle groups; all data columns sort before pagination. Counts describe
stored associated addresses, not devices or bus usage. Preserved import format
and documented import ranges remain authoritative even after changing an
individual address's local spelling. Two-level addresses have no middle groups.

To create a local group, enter format, prefix (e.g. `6` or three-level `6/2`) and
label, then save. **Edit local label** updates the same saved address label;
imported name and local label remain separate. **Remove** deletes only the local
label; imported groups and child addresses remain. A local-only group without a
label disappears from the list. Concurrent saved changes cause a conflict rather
than being overwritten.

Existing text editing remains under **KNX address labels → Advanced editing**
for bulk changes and full-address labels. Save or discard pending text edits
before saving structured group changes. Both views share the existing maximum
of 128 active labels. Local group creation does not create ETS groups; the XML
correction exporter does not create, move or restructure groups in ETS.

The selected correction draft and its displayed page survive a reload of the
same tab when browser storage is available. Only the target-bound selection is
stored. The page retrieves the draft and its current revision freshly from the
server; removed or expired drafts are not restored. Complete displayed target
values can be edited immediately; truncated values are fetched in full first.

**Accept** confirms a proposal in the draft without applying it to local metadata
or ETS. If a confirmed save is followed by a failed view refresh, the page says
so explicitly. If the decision itself could not be confirmed, select **Refresh
drafts** and check the saved state. The last view remains visible on temporary
failures, but its actions stay blocked until a fresh read succeeds. An uncertain
write is never replayed automatically.

## MCP workflow

### From comparison to correction

1. Import the original ETS XML under **Group addresses → ETS import**. CSV and
   JSON do not supply reconstructible XML provenance.
2. Connect and run **ETS/Loxone project comparison**. Differences are review
   candidates, not proven defects; comparison changes no data.
3. For direct ETS export, display the desired result page and select addresses
   and explicit target values under **Experimental ETS XML correction export**.
   Choices cover only that result page, not all pages.
4. Alternatively inspect a **correction draft**, compare sources and destination,
   edit target values and **confirm** individual, selected or all remaining
   proposals. Batch confirmation displays the selection first and records only
   decisions; it does not apply local values or create an ETS file.
5. Save confirmed local address/label changes separately after full-value
   confirmation. Select confirmed ETS rows in the dedicated export column and
   open their preview. Local changes do not automatically become ETS proposals.
6. Review the XML preview, confirm experimental use and download. The origin
   message distinguishes draft export from direct comparison selection. Test in
   a backed-up ETS project copy first: genuine ETS compatibility remains
   unconfirmed (#419). None of these steps writes Loxone Config.

### Finding and retaining drafts

New correction drafts remain for 30 days; existing drafts keep their stored
deadline. **Extend** retains a still-existing draft for at least another 30 days.
Editing or archiving does not extend retention. Expired drafts are cleaned up
and cannot be restored. **Archive** blocks confirmation, apply and export but
keeps the draft readable until its displayed deadline. **Reopen** resets decisions
to proposed. Changed sources still require a new proposal; extension refreshes
neither source evidence nor permissions. Archives share the existing eight slots/
32 MiB budget. **Delete** frees a slot without changing previously applied values.
Deletion confirmations remain bound to the original Admin session for seven days
without field values (128 global receipts, no eviction). A full receipt budget
blocks further deletion until expiry. After an uncertain response, refresh the
draft list first; never retry automatically.

Optional `metadata` on the existing preparation tool supplies `title` (160
characters), `summary` (1024) and `source_chat` (160, readable chat title). Admins
can also edit these descriptions. They are unverified author descriptions, not
identity, instructions or permission; never infer chat titles from OAuth app
names. The overview displays title/deadline; the selected view displays creation,
last-edit time and decision counts.

Inspect the current tool schema and retrieve `loxone_get_skill_guide(section="core")`,
then `section="knx"` for a KNX task. Equivalent resources are
`skill://using-loxberry-mcp/core.md` and `skill://using-loxberry-mcp/knx.md`.
The no-argument tool and `skill://using-loxberry-mcp/SKILL.md` retain the complete
guide. If the client has not discovered the section argument, use the complete
guide rather than guessing unsupported arguments. If guidance retrieval fails,
stop the affected workflow. Other workflows and writes still need the full guide.

Project search also considers imported ETS and manual KNX names/descriptions,
including values hidden by overrides. It returns authorized project objects,
not every standalone local address or prefix label. Loxone names stay primary.
Use an exact address for targeted explanation; describe returned objects and
trace only when structural context is needed.

Use the discovered `loxberry_get_knx_catalog` for standalone local inventory:
`kind="addresses"` reads ETS/manual records; `kind="prefix_labels"` reads active
style-bound labels even without addresses.
`kind="imported_groups"` instead returns all stored imported main and middle
groups, including empty groups and groups not selected as active address labels.
Start with `view="summary"` and follow every entries page for a complete review.
`query` searches prefix, name and description; `source="manual"`/`"both"` or
`deviations_only=true` return no groups because this inventory has only imported
sources. `address` is allowed only for `kind="addresses"`.

Each group includes `group_id`, address format, prefix, level, imported fields,
numeric bounds and `active_label`. `range_source="ets_xml"` identifies stored
XML bounds; `"address_prefix"` identifies bounds derived from the prefix, for
example for CSV. Address queries link matching groups through `group_ids` to
deduplicated `group_context`. Existing `prefix_ids`/`prefix_context` remain limited
to active labels. Manual labels do not overwrite imported group names. The
address table displays main and middle groups with prefix and imported name;
unknown groups remain unknown, and two-level import representations have no
middle group. A later local change of address representation retains the group
assignment from the stored import format.
Completeness refers to the stored import inventory, not a guaranteed complete
ETS project. Merge imports may retain groups from previous files. Group names
support review candidates against a confirmed addressing convention but do not
prove correct function assignment or signal relationships.

It requires separate OAuth consent
to `loxberry:knx:read`, Admin enablement on the KNX page and an explicit approval
for the exact client, identity, Miniserver and local target. It is disabled by
default. Loxone login, diagnostic and operation approvals do not grant access.
Admins can refresh candidates and revoke approvals there. Explorer approvals use
the configured inactivity lifetime. A target change cannot reuse another target's
approval. Disabling access retains approvals but blocks reads.

The KNX Admin read/draft badges display saved enablement, not unsaved checkbox
edits. Visible tabs refresh these policies every ten seconds and when returning
to the tab. External changes update the badge while retaining local edits and
their original conflict revision; unavailable status is shown explicitly.
The address-label badge counts saved unique address-format/prefix combinations,
including imported labels, counting a manual/imported pair only once.

When opened or reloaded, the KNX page loads the catalog, delegation policies and
shared correction drafts in one request. OAuth session restoration runs in
parallel. Loading hints remain visible until their respective operation ends;
a delegation or draft section failure does not hide other successfully loaded
sections. Independent refresh buttons and regular saved-policy checks remain
available.

Project comparison shares the browser OAuth session with MCP Tool Explorer.
Sign-in offers the same optional scopes; required Loxone read access is selected,
while additional permissions need explicit selection. Disconnect signs out all
connected Explorer/KNX tabs. Logout errors remain visible; refresh cannot restore
a successfully disconnected session. Local file comparison needs no OAuth login.

Expanded and collapsed section cards, including ETS import, survive reloads in
this browser when browser storage is available.
Forms and buttons adapt to narrow mobile views; wide tables remain horizontally
scrollable within their container.
Empty tables retain their headers, a subtle blank area and a contextual note
outside the table. Discard controls require pending files, drafts or results.
XML correction export requires a current project comparison with eligible
entries, an explicit selection and a successful preview. The experimental
checkbox confirms one download; it is not a saved enablement setting.

Delegation actions requested during a status refresh run in order; further input is disabled once the first action is queued. An existing XML preview can still be discarded with **Cancel** after logout or an invalidated project comparison. The action remains disabled while requests are running. Even after a failed load or preview response, discarding also removes comparison or XML drafts that may have been saved on the server. A failed discard preserves the state for another attempt.

Start with `view="summary"`, then narrow literal `query`, `source`,
`deviations_only` or exact `address` before fetching entries (default 50, maximum
100). Addresses accept no `:0`/`:1`. Summary hydrates no address rows and has no
cursor. Entries keep sparse imported/manual sources, local resolution, unverified
DPT declarations and deduplicated prefix context. Unknown fields, explicit empty
values and `false` remain distinct. Prefix labels imply no signal relationship;
`import_format` proves no XML export eligibility. No project download or Loxone
names are included: use authorized project tools for current-project comparison.

`total_matching` and `count_scope` refer to selected local records or active
prefixes. Repeat selection and limit on continuation. Cursors bind caller, target
and SQLite/manual-label revisions. Each newly issued cursor lasts five minutes;
successful, freshly authorized continuation renews the next cursor. They end on
restart. Changes require a fresh query. Whole rows fit within 64 KiB;
`page_truncated` identifies a shortened page. Consume structured output once,
not the text fallback too. Reads share global admission and have a bounded
30/minute family quota. Storage failures never produce successful empty catalogs;
authorization is checked again before returning data.

For inventory review explicitly select `ets_project_comparison` with KNX scope.
Defaults are unchanged. Check target, revision, freshness, coverage, diagnostic
omissions and required pages. Distinguish a sample from a complete requested review.
Manual-versus-imported `deviations` and Loxone-versus-ETS `names_differ` are
different comparisons. Unknown is not agreement; multiple names need a decision.

DPT declarations retain source and missing/empty/declared states. Syntax validation
does not prove registry membership, compatibility or an `EIBType` mapping. Import
time is not export time; Admin target assignment does not prove the correct ETS
project. Names, addresses and structural traces prove neither bus activity nor
physical roles or historical causes. File comparison and experimental XML download
remain on the KNX page; this read-only workflow cannot repair or export a project.

Task sections are derived from one bundled canonical guide and cached within the
running process. Retrieval loads no project/catalog and does not grant permission.
Token measurements must name the tokenizer/model/client and distinguish loaded
schemas, guide content and actual results. Character counts are not token counts.
For discovery mismatches, see [troubleshooting](troubleshooting.en.md).

## Optional task prompts

Clients supporting MCP prompts can select `knx_ets_inventory_review` or
`knx_address_explanation` through `prompts/list` and retrieve the recipe through
`prompts/get`. Retrieval reads no project/catalog and grants no permission. The
AI uses the same discovered read-only tools with fresh authorization. Prompts
are user-selected task starters, not background checks or automatic task creation.
Clients without prompt support can ask the same question in normal chat.

Inventory parameters: `focus` is `all` (default), `names`, `coverage` or `dpt`;
`detail` is `summary` (default) or `findings`; `language` is `en` (default) or `de`.
For example, `prompts/get` with `name="knx_ets_inventory_review"` and
`arguments={"focus":"names","detail":"findings"}` starts a naming review. The
answer distinguishes summary, sampled findings and complete requested coverage.
An absent/partial import is a limitation, not evidence of unused addresses.

Address explanation requires a valid two-/three-level `address`, preserving an
explicit `:0`/`:1`; optional `language` has the same choices. For example,
`name="knx_address_explanation", arguments={"address":"1/2/3:1"}` keeps the project
variant and queries approved local metadata by base address `1/2/3`. Multiple
objects/names stay explicit. Description, DPT declarations and prefix context are
additional sources, not proof of physical relationships or bus activity.

If listing or arguments differ from this reference, reconnect through the
client's supported discovery workflow. Do not manufacture a missing prompt/tool
call. Missing guidance/tools or denied permissions stop the affected checks;
these prompts cannot import files, modify metadata or export ETS corrections.
For protected local `prompts/list` captures, the offline discovery comparator
also supports `--kind prompts`; this compares advertisements, not recipe text
or whether a client can execute the task.

## Compact ETS comparison

Comparison reads ETS names for common addresses in one batch; other metadata is
loaded only for the delivered page. Counts still cover the entire observed
inventory even when the findings list is bounded. This optimization preserves
name precedence, authorization checks and revision checks.

Explicitly select `analyses=["ets_project_comparison"]`, `scope="knx"` and
`view="summary"` for counts without individual address detail reads. Use
`view="findings"` for paginated source evidence or `view="detail"` with an exact
two-/three-level `address` (without a variant suffix) for one address. Returned
project objects retain their original `:0`/`:1` variants and Loxone names.
The omitted/default `view="full"` and other analyses keep their existing behavior.

Compact views accept `relation`, `names_differ`, `ambiguous_names` and `address`.
False name-deviation selection includes only compared, complete observed names;
unknown or incomplete names are not agreement. Filters are unavailable in full
view and cannot be mixed with other analyses. Summary has no continuation cursor.
Keep view, all filters and `source_details` unchanged on findings pages; target,
project and KNX revision changes require a fresh query.

`summaries.ets_project_comparison.counts` describes the whole bounded observation.
`selection.counts` describes retained, filtered observations; `selection.complete`
is false if observation truncation may hide further matches. Source completeness,
omitted groups and diagnostic counts remain separate on every compact page.
Use `source_details=true` only when full diagnostic/source groups are needed.
The protocol retains structured and text fallback results; clients should consume
one representation rather than inserting both into the AI context.

## Shared correction proposals

After discussing concrete changes, an AI may prepare a bounded draft through
`loxberry_prepare_knx_corrections`. This requires separate OAuth consent to
`loxberry:knx:drafts`, explicit Admin enablement and an exact target-bound
approval on the KNX page, in addition to local catalog read permission. Both
capabilities remain independently disabled by default. A Loxone login grants
neither. Disabling access retains approvals and proposals but blocks MCP access.

Select local metadata or experimental ETS export targets explicitly. Imported
source values remain immutable. A proposal changes no overrides, export target,
ETS or Loxone project. The authenticated KNX page shows the same persisted
proposal with separate sources; it does not inherit an OAuth client's Loxone
project credentials. Current project evidence is explicitly unchecked there.
The Admin page can edit a selected target value and record accepted/rejected/proposed
decisions per change. Edits reset the affected decision without changing its identity or
immutable sources. The exact original project stand remains bound; acceptance does not
verify project access or apply changes. MCP can record concrete agreed decisions with
`loxberry_prepare_knx_corrections(mode="review", decisions=[{"change_id": "...",
"decision": "accepted"}])`, omitting `changes` and supplying current target,
catalog/manual/draft revisions and a stable request ID. Unselected decisions remain
unchanged. Apply prefix labels separately from addresses; select accepted export proposals on the Admin page.

New drafts have a 30-day lifetime (existing deadlines remain unchanged),
at most 50 changes each, and share the
existing global eight-draft/32-MiB budget with imports, comparisons and XML
previews. Edits do not renew expiry. MCP sees only its own target-bound drafts;
Admin inspection does not transfer ownership to other clients. Stale drafts
remain inspectable, but preparing a changed source stand requires a new proposal.

Read compact summaries first, then selected pages (default ten, maximum twenty);
continue with the returned draft revision. Values longer than 128 characters are
marked truncated; full detail selects one row. After uncertain creation, read by
the stable request ID; after uncertain editing, inspect the known draft ID. An
absent result while the worker may still run does not prove failure. Never retry
automatically. Exact repeated preparation is idempotent; conflicting reuse of a
request ID is rejected. Reads/preparation share bounded worker admission and
local read rate limits. Normal draft reads do not parse files or load catalogs.

Each draft retains at most 128 hashed edit/decision receipts without eviction; further edits are rejected when that bound is reached. This accommodates individual review and edits across the 50-change batch while retaining the global byte bound.

## Apply agreed local changes

In addition to read and draft access, OAuth consent to `loxberry:knx:write`,
independent enablement and exact client approval on the KNX page are required.
Writing is disabled by default. Agreement to an analysis or draft replaces
neither this approval nor the concrete user decision.

After explicit user agreement, call `loxberry_apply_knx_corrections(action="apply")`
with accepted `approved_change_ids`, target/catalog/manual/draft revisions and
a new stable `request_id`. Do not resend values. Maximum 50 changes; existing
`storage="addresses"` (default) applies existing name/description overrides.
`storage="prefix_labels"` applies style-bound prefix labels after additional
Admin prefix activation for approved write clients. Select one storage per call;
mixed selections are rejected. No DPT, flag, import, ETS or Loxone changes. Preserve unselected overrides and the original address.
Removing an override differs from intentionally emptying a description.
Project-bound drafts explicitly require `use_project_evidence=true` with a
freshly authorized unchanged project snapshot.

Field effects and a bounded operation receipt, available for seven days, commit
together. After uncertainty use only `action="reconcile"` with the same IDs,
revisions and request ID. Even an absent receipt does not permit automatic retry.
A receipt describes the original result; reread the current local catalog and
verify affected fields afterwards. Loxone names remain primary and unchanged.
Prefix effects and their receipt share one atomic configuration save; address
effects and their receipt share one SQLite transaction. There is no combined
cross-store write. Prefix receipts are bounded to 32 unexpired operations and
16 KiB, without eviction of valid evidence. A full ledger rejects further prefix
writes until expiry. The result returns the changed manual-label revision; the
import catalog revision is unchanged. Accepted ETS proposals can be selected for the existing experimental XML preview.

Configuration schema 12 migrates schema 11 with prefix access disabled. Native
upgrade preserves existing labels and receipts. Back up the matching configuration
before upgrading; older code cannot read schema 12.

General settings saves preserve the current KNX labels and their receipts, even
when a full configuration document includes stale copies. Use the revision-bound
KNX label action to edit labels.

The authenticated Admin page can apply an individually selected, accepted local-only
change after an HTML confirmation showing its full value. This uses Admin authentication,
not MCP client grants. Project-bound proposals additionally require the current Loxone connection. A fixed
loopback bridge independently verifies Admin authentication and fresh project access;
browser-supplied stand identifiers do not authorize an operation.
After an uncertain result, use **Check the exact operation outcome** without repeating
the write. Address/prefix destinations remain separate and imports/ETS/Loxone unchanged.

Pending operation identities/revisions are retained in this tab session storage for at most seven days, without field values or credentials, so reloading keeps exact reconciliation available. A definitive pre-effect rejection clears them. An unresolved operation can be explicitly dismissed only after checking the current catalog; dismissal never retries a write.

## Accepted ETS export proposals

Select accepted `ets_export` name/description rows and open the existing XML
preview. No local override or import field changes. Only existing XML-proven
addresses with reconstructible metadata are eligible; prefixes, new addresses
and deliberately empty descriptions are rejected. The preview retains the exact
proposal selection and revisions in the same Admin session. Download rechecks
expiry, decisions, target, catalog/manual revisions and any authorized project
binding. Changes require a new preview. Confirm the experimental download only
for a backed-up ETS project copy. Actual ETS compatibility remains unconfirmed
(#419); MCP never downloads or writes ETS files. A Loxone Config destination
remains a proposal for a future available writer, not an implemented project write.
