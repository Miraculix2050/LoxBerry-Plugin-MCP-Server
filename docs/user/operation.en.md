# Operation

[Deutsch](operation.de.md)

## Updates

The Plugin Manager discovers regular updates through the stable release source. Prereleases are offered only when explicitly allowed there. Keep a working earlier package before updating a prerelease so that you have a recovery path.

## Sessions and approvals

Under **Clients and sessions**, administrators can inspect and revoke sessions and local diagnostic or operate approvals. On narrow screens, all fields and actions appear together under each session or approval. While a revocation is running, the affected row is dimmed. Revoking an approval ends matching sessions. Disconnecting the Tool Explorer revokes only its OAuth session; its local approval can reactivate for the same Loxone identity and Miniserver until the displayed deadline. The inactive retention is configurable from 1 to 720 hours and defaults to 72 hours.

Session revocation blocks MCP access immediately. Loxone token cleanup then runs in the background. The section shows aggregate warnings when cleanup is pending, the Miniserver blocks sign-ins, or remote revocation remains unconfirmed after bounded attempts. For an unconfirmed result, an administrator can inspect Loxone user management; the warning does not identify a user.

The last loaded emergency-stop signals appear immediately from the local cache when the page opens; this does not start a new Miniserver sign-in. **Refresh emergency-stop signals** explicitly reloads the list using the credentials configured in LoxBerry. This can take several seconds. Concurrent Admin requests wait for the same result. If a Miniserver sign-in block prevents the refresh, the page shows the earliest retry time. **Try again** becomes available afterward and makes at most one coordinated sign-in attempt. The last loaded signals are marked as potentially stale, and errors preserve the saved emergency-stop selection.
If another sign-in is merely in progress, the page instead shows a short retry time. The server-rendered fallback also displays aggregate cleanup warnings.

## Diagnostics and logs

The service log remains directly available under **Diagnostics and logs**. The LoxBerry LogManager lists native plugin logs after an actual Admin event has been recorded and registered. The Admin page distinguishes an empty LogManager list from an unavailable LogManager and a failed refresh request. Opening the log list does not create a log entry.

## Tool Explorer

Object lists such as targets show individual entries with **Add entry** and **Remove entry**. Use **Transfer** to copy a UUID into targets[].control_uuid; this replaces the selected list, as with simple list transfers. Other draft parameters are preserved. Optional state_names can be enabled per entry; omitting them reads all states. The complete arguments remain editable in the JSON editor.

The [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) is a local administrative test client. It signs in with a Loxone user and receives no rights from the LoxBerry admin session. Replace `loxberry` in the link with your installation's hostname when necessary. Mutating calls require confirmation before sending.
After sign-in, the connection card shows which OAuth scopes the session actually granted. Scopes marked **Not granted** were not granted to this session; local LoxBerry approvals and other authorization checks remain separate. The list clears when the session ends.
The connection card starts open so sign-in is immediately available. It can be collapsed after sign-in to make more room for the tool workspace. Its OAuth scope list starts collapsed, and the setup and schema-reference links remain visible above the card. Both disclosure choices persist across reloads and new tabs in the same browser.
RFC-3339 time fields are shown as local date/time fields and sent as UTC.
Time-range shortcuts and references from earlier results simplify common queries;
technical page parameters are available under **Advanced options**.
Search the available tools by name or description and combine the search with
one or more groups in the expandable filter. **All** clears the group selection.
Filtering is local and keeps the selected tool and
its unsent draft.
Tools without a known Explorer presentation hint appear under **Other tools**;
their forms and calls still use the schemas from `tools/list`.
For the selected tool, the Explorer shows its read/write classification and
explicit MCP hints. Incomplete or contradictory metadata is conservatively
marked **May write**. Hints are not a safety guarantee; the complete annotations
are available under **Technical MCP metadata**.
The summary also lists required OAuth scopes for known tools. The scopes actually
granted to this session remain visible in the connection card. Long tool
descriptions can be expanded from the compact summary.
**Selected tool** and **Result** can be collapsed and reopen when a relevant
selection or new result needs them. For history results, **Arguments used** have
their own disclosure.
Results and history entries appear as an expandable tree. Large branches show
100 entries at a time; **Show more** loads the next batch. The disclosure arrow
opens a branch, while the separate value button reuses its unchanged value and path.
Objects in arrays show a short name, type (including `source_type`), identifier,
or relationship endpoints
when available. Time fields are the final fallback when nothing more descriptive
is present. `null` appears as `-` in the tree; copying and transferring retain
the original value.
The complete response remains available under **JSON** and through **Copy JSON**.
Call history shows a local timestamp, duration, outcome and a short redacted
argument summary where the tool schema permits one. Selecting an entry still
opens its result and lets you load the call as a draft. Progress and the outcome
of the current call appear next to **Run tool**; connection status stays in the
connection card. The separate **MCP protocol / debug** panel contains the
bounded request and response transcript for troubleshooting. Expanded entries
show compact **Date/time** details above HTTP status and duration. History and
transcript remain in the current tab and clear when its session ends.

MCP clients receive the tool descriptions published by the specific installation, including their input and output schemas, through the MCP method `tools/list`. The Tool Explorer reads and visualizes that exact response. **Help** also provides a static HTML reference for the complete tool contract of this plugin version and the same data as a JSON download.

Next: [Troubleshooting](troubleshooting.en.md).

**Help and developer tools** provides links to the project and guides, Tool Explorer, schema reference, local event history, KNX address management, confirmed installation profile and individual message approval. Each link briefly explains the purpose and limits of its destination. KNX address management and the installation profile also remain available under **MCP configuration**, with the same explanations. Message approval opened from Help keeps the current page language.


Read core first, then only the workflow sections selected by its task index. Before a write load core and operations; add read modules only when their evidence is needed. If section retrieval fails use the complete guide; if that also fails stop the affected workflow. The legacy full-guide tool default and URI remain available.

Tool descriptions summarize purpose, decisive prerequisites and limitations. Read parameter bounds and selection rules in the schema fields; retrieve longer recipes through the core task index. Statistic series are not an energy balance, advertised history metadata is not retrieved period evidence, and project reachability is not historical causation.

For confirmed source selection, use `loxone_get_installation_profile(view="summary")`.
The compact page retains exact sources, confirmation/review status, provenance
and usability warnings. Use `view="full"` when rationale, display names or complete
PV/load parameters are needed, especially before confirming a replacement or
deletion. Both views freshly check visibility on every page and share pagination
and size limits; omitted summary fields are not absent stored declarations.

Set `include_outputs=true` with `view="lighting_context"` when exact visible
runtime lighting outputs are needed. The bounded projection retains explicit
parent identity, structure version and state references, with omissions. Runtime
containment does not identify a project connector or physical luminaire; color
picker support does not prove installed tunable-white lighting. No actions occur.

For a bounded lighting review, use `loxone_analyze_project(scope="lighting",
lighting_selection={"controller_uuids":["exact-visible-controller-id"]})`, or select
one exact `room_uuid` instead. A room selects at most 16 visible LightControllerV2
controls and reports exclusions. Default checks cover inventory, naming candidates,
configured presence relationships, scene roles and missing planning context.
Follow `next_cursor` with unchanged inputs, at most 50 findings per page.

In the Explorer, select `scope=lighting` to show `lighting_selection` and optional `lighting_context`; ETS-only fields are visible only for KNX and are removed when switching to Modbus or lighting. The form scope selector clears incompatible fields, selected checks and cursors, while preserving the ordinary page limit. Scope edits in JSON also remove incompatible fields/checks and cursors, retaining explicit checks that match the new scope; malformed JSON or argument types remain validation errors. Select the complete visible LightControllerV2 result row from `loxone_find_controls` to transfer its exact ID into an analyzer draft; this never runs a tool automatically. Review and run the draft explicitly. The result summary counts observations, review candidates, context gaps and conditional guidance on the current page. Read naming completeness independently from selection coverage; expand the evidence tree or JSON for exact references, origins and limits. See the [six lighting scenarios](analysis-support.en.md).

Optional `lighting_context` uses `schema_version="lighting_analysis_context.v1"`.
Declare exact controller+mood identities, presence-source IDs, literal naming
prefixes and room use/intent/fixtures/zones with explicit `origin` and `rationale`.
Each room field and zone has independent provenance. Existing profile binding IDs
reuse confirmed sources only; a confirmed binding does not confirm a hypothetical
role or installed fixture. Presence sources may be outside the selected room but
must remain visible. Duplicate resolved identities and overlapping prefixes are
rejected. This creates no saved profile or configuration changes.
Scenes without a declared role remain missing context. Noncurrent mood names are
excluded from naming comparisons with explicit freshness gaps. An unavailable
profile is a source/retry problem, not an instruction to change valid inputs.
Direct sources need no profile or installation serial; explicit binding references
retain installation and content-change checks. Child targets retain their parent
anchor provenance. Truncated unresolved counts remain explicitly partial.

Results retain source versions, freshness, omissions and room/controller/scene
references. Naming differences are review candidates; configured reachability is
not observed causation. Unknown paths and truncated names stay incomplete.
Controller Kelvin defaults prove neither installed tunable-white fixtures nor a
design need. Overall advice is conditional, not a professional physical audit.

For a presence/light relationship, establish exact source and controller IDs;
names or a shared room do not prove an association. Inspect project mapping and
source coverage, find/describe the exact objects, then trace the relevant direction
with `include_internal_flow_gaps=true`. Keep raw wiring, reviewed internal edges,
unmodeled internal flow and ambiguous parents distinct. Preserve child identity
separately from parent topology and retain all limits; a missing bounded path does
not establish physical absence. No configuration or control writes are required.

Use `loxone_describe_control(view="lighting_context")` for bounded source mood
IDs/names of one visible LightControllerV2. Check status, source state, timestamp,
freshness and omissions; missing or invalid data is not an empty scene inventory.
Names never prove scene roles, presence connections or physical luminaires.
The full default and all existing operation safeguards remain unchanged. The
complete compact envelope is limited to 64 KiB (`response_too_large` for
oversized retained control metadata).

## Authentication diagnostics in Clients and sessions

Local administrators can explicitly open and refresh the bounded authentication
history and its summary for an app/identity/Miniserver binding. Sessions with the
same binding show the same history; it is not a per-session attribution. Details
do not poll in the background. The view separates observed rejection, confirmed
source-IP blocking, suppressed attempts, confirmed recovery and unavailable
history. A block observation does not identify its cause. Unavailable or empty
history does not prove a healthy system. No extra recovery action is introduced;
the existing Admin probe keeps its existing protection and rate limits.

The overview shows at most 50 distinct active app/identity/Miniserver bindings.
When more exist, it warns that the list is truncated and shows the number of
omitted distinct bindings; repeated sessions of the same binding count once.
A rejected Miniserver command is reported separately from rejected authentication.
