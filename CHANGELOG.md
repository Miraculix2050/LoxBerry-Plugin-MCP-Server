# Changelog

All notable user-visible changes are recorded here. GitHub release notes are
extracted from the matching version heading.

## Unreleased

- Fixed the masked Admin diagnostic download through same-origin AJAX when browser HTML submissions carry Origin null (#428).

- Preserve first OAuth revocation causes and correlate sanitized client, approval,
  runtime and remote-cleanup lifecycle events; expose bounded retained causes in
  local Admin diagnostics without transferring authorization (#425).

- Reuse a dedicated service-owned discovery connection for Admin selectors,
  downloading a complete current structure for each request while keeping MCP
  client authorization and recorder sockets separate. Bound session lifetime,
  frame dispatch and failures; document the accepted partial-permission-change
  uncertainty on uninterrupted sessions (#239, #297).
- Retain application display names for inactive LoxBerry read and operate approvals.
  Enrich old approvals only through exact retained session matches; keep client-bound
  authorization and unnamed fallbacks unchanged (#421).

- Pause new Miniserver authentication after three definite rejections in five
  minutes, with persisted 60-second to 60-minute backoff. Isolate public OAuth
  password failures from the shared service/token budget. Keep network
  failures, contention, project permissions and actual source-IP blocks distinct;
  allow explicit local Admin probes at least 60 seconds apart (#408).
- Add a dedicated KNX administration page with target-bound manual address metadata and JSON exchange; retain existing prefix-label text transfer.
  Confirm local deletion and form changes with accessible HTML dialogs.
- Add bounded modern ETS XML import with revision-bound preview, explicit duplicate
  decisions, selected group metadata, field overrides and transactional reimport.
  Complete replacement preserves manual records and explicitly reviewed overrides;
  native upgrades retain the KNX database through an integrity-checked SQLite snapshot.
  Loxone names remain primary. CSV and project metadata integration follow separately.

- Unify configured service-identity credentials and connection ownership for
  emergency-stop and Event History consumers. Keep separate connections, fresh
  visibility, existing authentication budgets and client OAuth authorization;
  always destroy owned tokens even when session cleanup fails (#406).

- Reuse immutable runtime mappings between independently authorized families of
  the same identity and Miniserver, with the exact shared snapshot and complete
  visible mapping inputs. Preserve private queries, fresh downloads and existing
  bounded view ownership without adding a cache pool (#404).

- Reuse immutable structure normalization after each own authenticated complete
  response, keyed by exact text, Miniserver/user and parser limits. Existing bounded
  connections own shared values; preserve private state, refresh ownership and
  authorization without another cache or retained raw document (#401).

- Reuse identical authorized project searches across families with complete visible
  mapping/filter keys, independent downloads and final permission checks. Keep
  bounded search results separate from private cursor generations and use the same
  cache owner for project analysis without changing its bounds (#399).

- Share read-only project query topology indexes across independently authorized
  views of the same graph. Keep visible mappings and names separate, reuse graph
  topology when a family's visible structure changes, and count shared index
  containers once within the existing bounded view cache (#398).

- Reuse authorized project-analysis results across OAuth families with identical
  inputs. Keep KNX visibility/taxonomy inputs and family cursor leases separate;
  retain independent downloads, fresh visibility and final authorization on every
  cache hit and continuation. Bound shared results and invalidate expired cursors
  across result recreation (#396).

- Share identical parsed project content across OAuth families only after each
  caller's own authorized download. Recheck project-read permission through a
  download on warm calls and continuations too; retain separate visible mappings,
  queries and cursors. Bound family references and account shared graphs once.
  Warm requests incur additional download/verification cost (#379).
  Admit one project-backed call at a time without a waiting queue, with a shared
  twelve-per-minute budget, before acquiring general read slots.
  Charge that budget only after family/history limits and current access admit
  the call, so rejected or cancelled admission cannot throttle other families.

- Resolve exact, unique cross-model `OutputRef` references to `VirtualOutCmd`
  within the same authorized project bundle. Preserve local-target precedence,
  ambiguity and unsupported reference gaps. Project model version 13 distinguishes
  the new graph interpretation; KNX analysis remains version 12 (#374).

- Disable automatic WebSocket transport pings for Loxone sockets, retaining
  bounded application keepalive and strict rejection of unexpected structure
  files. Fix the transport-ping/gzip HTML finding on the observed Gen. 1 target
  without decoding or skipping unrelated files (#384).

- Represent explicit Loxone API-connector wiring as bounded block communication
  dependencies in project describe/trace, with port/block metadata and no scalar
  values or inferred signal semantics. Preserve unresolved links and expose
  metadata for exact OutputAPI/API ports. Model/KNX analysis version 12, Opening
  connector rules 5 and canonical skill revision 54 invalidate prior projections.


- Support sparse State condition slots and optional bounded table inspection for
  exactly mapped visible controls, preserving literal templates and output gaps.

- Extend version-bound State AQ evidence to I1–I8 and all demonstrated fixed-operand operators, with first-match/AND semantics and conservative numeric independence. Preserve gaps for empty results and unsupported contracts; synchronize generic and opening traces.

- Recover a full Chart View cache per source, keeping existing plots visible while
  bounded replacement data loads. Preserve other sources and distinguish reduced
  detail from actual history changes (#371).

- Validate Admin and Event History POST origins against the request scheme, host
  and effective port; reject cross-scheme requests and ignore forwarding headers
  unless the webserver supplies trusted CGI metadata (#372).

- Decode bounded WindowMonitor contact bitmasks and original configured positions
  through shared state readers and opening-contact analysis. Preserve observation
  quality, malformed/missing values and mapping/truncation gaps; history remains
  source-dependent and contact conditions are not alarms (#349).
- Expose allowlisted raw analog Modbus actor configuration in project search/describe,
  preserving unresolved encodings and the sensor-only analysis boundary (#381).

- Derive configuration-bound State I2-to-AQ signal flow for the verified source
  version and equality/default table; retain connector-specific gaps for unknown
  State contracts and expose bounded provenance (#335).

- Preserve actual raw field/status evidence in Modbus mapping and polling
  comparison exclusions; reject reversed or contradictory containment as a
  grouping identity (#359).

- Reduce Chart View transfer and tab-local snapshot data by omitting previous
  event values that the charts do not display. Existing history storage and
  general history reads retain those values.

- Complete Modbus V1 static project analysis with configured mapping, direct
  consumer and raw polling checks, and expose all five checks through MCP and
  Explorer (#358–#360). Preserve KNX defaults, explicit coverage and evidence
  gaps; configuration establishes neither bus activity nor device validity.

- Let administrators export and load KNX prefix labels as a local UTF-8 text file.
  Loading is a draft until saved; clarify two- versus three-level address formats
  in the Admin help (#370, follow-up to #199).

- Expose bounded StatusMonitor configured tuples and position-stable current-state
  mapping through existing readers, with count semantics and explicit coverage (#348).
  State batch reads now require fresh visibility rather than cached visibility.

- Prepare an internal, typed Modbus V1 inventory/evidence-gap foundation with
  occurrence coverage, bounded construction, scoped cache/cursors and full-envelope
  byte fitting (#358). Public analysis remains KNX-only until #359/#360 complete
  all five checks; no Modbus traffic, device semantics or live compatibility claim.

- Sync parent directories for configuration and MQTT credential updates/deletion
  and configuration upgrades. Report visible changes with unconfirmed durability
  without automatic Admin compensation or service changes (#161).

- Add read-only, allowlisted raw `ModbusASensor` project evidence with explicit,
  absent, ambiguous and invalid values, bounded source occurrences and observed
  device/transport ancestry. Preserve authorization and KNX contracts; datatype,
  unit-ID, actor and runtime semantics remain unproven (#352, investigation #350).

- Show `source_type` in Tool Explorer array item previews before timestamp fallback.

- Clarify structure overview definition counts versus synthetic unassigned buckets
  in the public schema, examples and agent guide without changing response values (#212).

- Extend active visible alerts with documented AalSmartAlarm and AlarmChain rules,
  source context and acknowledgement without hiding active alarm bits. Preserve
  explicit coverage gaps for unsupported families and unknown context (#344).

- Add bounded, sanitized internal-flow gap evidence to opening-contact traces,
  preserving warnings, conservative completeness and existing connector rules (#335).
- Edit bounded object-list inputs as individual Tool Explorer entries and transfer
  response UUIDs into nested fields such as targets[].control_uuid. Preserve the
  existing JSON editor, draft parameters and explicit call confirmation.

- Add read-only `loxone_get_active_alerts` with evidence-backed AalEmergency
  activity, fresh visibility, bounded cached reads and explicit evaluation/delivery
  gaps. Other known monitor/alarm families remain unsupported; no guessed severity,
  acknowledgement or simultaneous-measurement claim (#167).

- Add read-only `loxone_read_controls` for known visible control UUIDs with compact
  identity and named cached values, atomic fresh visibility, fixed request/response
  limits and explicit delivery completeness. Optionally reuse the existing state
  semantics evidence model without relationship expansion (#168).

- Add read-only `loxone_get_state_semantics` for one freshly authorized visible
  control, with bounded state selection/pagination, per-claim provenance and
  explicit interpretation gaps independent of cached observation quality.
  Preserve existing Irrigation/AlarmClock read results; expose exact-state
  format/range and position-bound StatusMonitor metadata without guessed units,
  hidden-control expansion or a documentation-content pipeline (#166).

- Split Event History chart selector diagnostics into numeric-only coordination,
  token acquisition, session establishment and structure-load subphases while
  preserving existing timing fields and fresh discovery behavior (#297).

- Wait for runtime authentication coordination within the existing connection
  budget instead of immediately rejecting fresh MCP reads; preserve cancellation,
  fresh visibility and source-IP protection, and distinguish local contention
  from source-IP suppression with fixed value-safe diagnostics (#332).

- Let Event History Admin discovery wait within one bounded authentication budget
  when another plugin consumer holds the shared sign-in lock, instead of failing
  immediately; fresh visibility and source-IP suppression remain required (#331).

- Treat additional connected inputs or outputs outside reviewed block rules as
  incomplete opening-contact evidence, preventing false absent-connection findings.

- Preserve compatible temporary-unavailability errors while adding fixed runtime
  reason/phase diagnostics and bounded retry hints only for the caller's local
  rate budget. Distinguish structure-refresh connection, protocol, token, timeout
  and unknown failures; retain sanitized diagnostic correlation and update the
  canonical skill to preserve failure evidence and bound read retries (#328).

- Fail closed and drain the state-stream session when the initial state batch
  times out; ready subscriptions no longer wait for the full timeout.
- Serialize runtime session admission across families to enforce capacity during
  concurrent connects, and drain pending admission before shutdown completes.
- Discard structure-refresh results from disconnected or replaced runtime records
  so cleanup and reconnect cannot resurrect or overwrite per-family state cache.
- Mark cached runtime states stale on every state-stream termination, including
  normal iterator exhaustion and cancellation before websocket teardown.

- Extend the canonical skill with evidence-safe WindowMonitor coverage and
  bidirectional contact/consumer review, preserving intermediate logic and
  distinguishing configured wiring from unassessable physical completeness.

- Add the read-only opening-contact analyzer for bounded WindowMonitor references,
  duplicates, optional state alignment and exact bidirectional AutoJalousie.Window
  paths. Preserve reviewed InputRef/Or evidence, separate incomplete analysis from
  absent connections, and report assignment candidates without physical verdicts.

- Add value-safe WindowMonitor item diagnostics, visible-reference resolution
  counts and explicit UUID-based room consistency. Keep malformed positions and
  distinguish omitted evidence from unresolved retained entries without exposing
  hidden target details.

- Preserve the first 100 WindowMonitor positions instead of discarding larger
  collections. Expose collection counts, truncation and invalid-shape diagnostics;
  apply the same prefix to explicit read-only reference exposure.
  Preserve independently linked control authorization when monitor references overlap.

- Add `loxone_describe_control(view="state_refs")` for complete normalized state-name/UUID references without history, statistics, or other control metadata. Refresh user-filtered visibility before returning references, fail without cached fallback, and mark a disconnected event stream as stale.

- Release per-family Loxone runtime locks after their last holder or waiter and
  sweep expired rate-limit family keys without resetting live rate windows.
  Serialize disconnect with in-flight connection establishment.
  Recheck OAuth authorization for queued calls and before publishing a new
  connection while preserving token material needed for remote revocation.
  Report ended OAuth authorization as `permission_denied` for queued operations.

- Reduce analysis-worker graph pickle overhead while retaining all model fields
  and process isolation; add opt-in, numeric-only private worker phase diagnostics.

- Measure Event History chart CGI delivery through stdout flush and distinguish
  completed preparations from slow or failed requests in operational logs.

- Add `loxone_describe_control(view="operation_targets")` for compact control
  identity, visible allowed actions, and action-specific targets or ranges needed
  to prepare control operations.
  Refresh this view from the current user-filtered structure before selecting
  targets, and reject the description if that refresh fails.

- Explain raw project graph outliers with separate signal, reference, and derived-edge
  evidence. Report reference-only KNX endpoints separately from directly configured
  consumers and bound connector details in connectivity findings.

- Add paginated KNX address-prefix facts and local review candidates to project
  analysis. Allow administrators to configure Miniserver-scoped prefix labels
  with explicit provenance; labels never change project counts or imply bus semantics.

- Wake Chart View and recorded-source windows after recorder commits through a value-free local update signal. Append new chart points with cursor queries, refresh source totals from a fresh visibility-bound local overview, and keep charts visible across concurrent selector refreshes and routine coverage changes.

- Avoid loading the Loxone project runtime for Event History chart queries, reducing Admin helper startup cost. Reuse a bounded, tab-local Chart View snapshot after fresh visibility and history checks so reloads fetch only missing or newer values.

- Place each Chart View source's name, context, coverage details, and individual status beside its plot on wide screens; use the available Admin content width and show the shared capture warning only once above the charts.
- Expose bounded KNX coverage by source type in project status and analysis,
  distinguishing raw source occurrences, logical objects, unsupported types,
  ambiguous candidates and duplicate model-source occurrences. Identify raw
  Config datatype evidence separately from unavailable normalized DPT evidence.

- Add `loxone_list_event_history_sources` for currently visible control/state pairs; page both source lists with active/removed status and known recording end time. Allow the complete `loxberry_list_event_history_sources` with either exact local read or operate approval, and show its alternative requirements in the Tool Explorer.
- Zoom the Chart View time axis around the pointer with Ctrl+mouse wheel over a plot, while ordinary wheel scrolling remains available.
- Model `EIBextactor`, `EIBtextactor`, and `EIBtextsensor` as KNX endpoints.
  Preserve external-actor address variants and expose bounded connector wiring
  in project object descriptions without inferring text or bus semantics.

- Reject malformed or out-of-range KNX group-address search filters as
  `invalid_input` before loading the project. Valid absent addresses still
  return an empty result; exact original and canonical variant matching remains.

- Expose the local Weather-State cache processing time as nullable
  `received_at` in successful weather responses, separate from the Loxone
  source update time and MCP response time. Clarify that `stale` reflects cache
  availability rather than weather source age.

- Add locally bundled, read-only Event History charts for up to four visible sources in a separate Admin tab. Show independent scales, synchronized time and cursor, coverage gaps, bounded range queries, and incremental updates; require fresh profile-bound visibility proof and clear values on access loss. Upgrade the local store to schema v6 for chart invalidation and indexed append queries.
- Distinguish chart query failures, correlate them with sanitized Admin logs, and recover from history changes without dropping the retry.
- Keep chart zoom local within loaded periods, fetch missing intervals on navigation, append new points to existing plots, and reserve the event list for text changes.
- Reduce repeated configuration and visibility reads and reuse one local history store per bounded multi-source chart query.
- Preserve the local Event History SQLite database across native LoxBerry plugin upgrades with a consistent snapshot.
- Add field-aligned source formats and explicit value semantics to weather
  responses. Keep raw formats and weather values unchanged, and mark units and
  solar radiation semantics as unverified where the source does not establish them.

- Bind weather forecast cursors to the source update time and bounded forecast
  contents. A changed forecast rejects continuation with guidance to restart at
  page one; cursors issued before this change may also require a restart.
- Model `EIBextsensor` with validated `:0` and `:1` KNX address variants and
  `EibAddrPulse` fallback. Preserve the address source field and distinguish
  variants in search, trace, diagnostics, and KNX analysis without inferring
  physical edge behavior.

- Name the local event-history query `loxone_get_event_history`.

- Release process-local Tool Explorer session locks after the last active or
  waiting request, and prevent concurrent refresh from restoring a removed
  encrypted session.

- Show currently authorized room, category, and type context for Event History
  sources with local room, category, type, and status filters, sortable list
  columns, and estimated logical JSON value sizes. Upgrade existing SQLite
  history stores to schema v5 without scanning events during
  overview reads; measure legacy values in bounded background batches even when
  recording is disabled and refresh displayed sizes when backfill finishes.
  Keep physical SQLite and WAL sizes separate from these per-source estimates.

- Add deterministic DOM and mocked OAuth/MCP flow tests for the Tool Explorer,
  backed by a development-only pinned jsdom dependency. CI installs the test
  dependency without changing shipped JavaScript or plugin assets.
- Keep request-local Admin language previews in AJAX feedback, including
  emergency-stop discovery errors, without changing the LoxBerry system language.
- Reuse the bounded Project Intelligence graph and mapped query after an authenticated
  project-marker check, and reuse bounded search and analysis results across
  continuation pages. Expired or changed-context cursors require a new first page.
  Add sanitized History phase timings. Native History and statistics load the
  current user-filtered structure for each call, including cache hits; a project
  marker alone is insufficient proof of current visibility. Avoid repeated local
  authorization reads during a warm
  Project Intelligence query while retaining a fresh visibility check and one
  authorization check for each request.

- Add an opt-in compact `loxone_describe_control` history-target view with state
  UUIDs and advertised native statistic series, preserving the full default
  response. Mark StatisticV2 series omitted beyond the normalized 128-series
  limit without implying recording or historical coverage.
- Add a dedicated local Event History administration view for exact visible
  control/state selection, bounded evidence and storage status, retention settings,
  and separate confirmed source and whole-store deletion. Keep only enablement,
  a lightweight summary, and a link on the main Admin page.
- Load the Event History control list automatically after local status, checking
  visibility afresh on every page. Filter a bounded list by name, UUID, room,
  category, and type; load states on control selection and offer explicit refresh.
  Refresh open tabs after source changes and whole-history deletion without
  polling the event table. Migrate existing history stores for this change on
  the first local Admin read even when recording is disabled. Retry failed
  visibility refreshes, retain unchanged selector generations across tabs, and
  recover stale selections through a fresh authorization check. Share concurrent
  refreshes even when the catalog is unchanged, and preserve unsaved retention
  edits during background updates. Retry selector verification even when the
  local source list is empty or its store snapshot fails (including after an
  unchanged add), preserve selection on a stale catalog response, and avoid
  parallel decoding of large cache files.

- Make the Tool Explorer's selected-tool and result cards collapsible, with history
  arguments in a separate disclosure. Label array objects using available names,
  descriptions, identifiers, or relationship endpoints; use timestamps only as a
  final fallback and show null as `-` in the result tree.

- Keep Tool Explorer-specific presentation hints and workflows in a static registry.
  Unknown tools appear under Other tools and remain callable from their MCP schemas.

- Keep retained local event history readable after source removal when the caller
  can still see the state. Report recording status separately from period coverage,
  preserve re-addition gaps, and add a confirmed per-source purge for inactive
  sources without changing global retention limits. An enabled recorder with no
  configured sources no longer opens idle Miniserver connections. If removal
  metadata cannot be confirmed after recording stops, report an unknown outcome;
  a later manual remove can repair the marker without guessing its end time.
  Post-commit purge maintenance failures also report an unknown outcome.

- Show local timestamps and redacted argument summaries in Tool Explorer call
  history, keep MCP protocol details in a separate debug panel, and report each
  call's progress and outcome next to Run. Expanded protocol entries show the
  local date and time in compact metadata rows; history summaries prioritize
  changed arguments.

- Cache the last loaded emergency-stop signal options across Admin requests and
  share one explicit Miniserver refresh among concurrent administrators. Page
  reloads read only the local cache, including the server-rendered fallback. The
  initial Admin snapshot includes the cached list without a second CGI request.
  Explicit signal loads wait briefly for another Miniserver sign-in before
  reporting that authentication is busy.

- Keep the Admin emergency-stop retry button visible after a failed signal load
  and offer another refresh after a successful load, while honoring a supplied
  Miniserver retry time.

- Show required OAuth scopes beside each selected Tool Explorer tool and compact
  the tool summary, with expandable long descriptions and a smaller arguments heading.

- Show localized MCP tool hints and the conservative read/write classification
  in the Tool Explorer, with complete annotations in a technical disclosure.

- Show factual Admin summary badges for saved MCP/MQTT settings, sessions and pending approvals, and HTTPS certificate checks; keep session counts current while the page is visible.

- Allow slow read-only Admin certificate and emergency-stop discovery requests to finish instead of aborting before the target responds.

- Add local name and description search and scope filters to the Tool Explorer,
  with a compact multi-select group dropdown while retaining tool grouping,
  selection, and unsent drafts.

- Make Tool Explorer results and call history expandable, load large branches in
  batches, and keep complete raw JSON available on demand.

- Run expired Tool Explorer binding cleanup after releasing the OAuth store lock,
  so a stored expired session cannot block service startup or Admin data loading.

- Correct UTF-8 encoding of localized Admin AJAX error messages, including
  emergency-stop option loading warnings.

- Register actual Admin UI events with the native LoxBerry LogManager and show
  distinct empty-list and unavailable-service messages without logging on reads.

- Stack client sessions and LoxBerry approval bindings before their columns
  become cramped on narrow screens; show Loxone permission details as stacked
  records at intermediate widths. Keep a deliberately closed Admin section
  closed after reloading its hash URL while newly followed section links open it.
  Remove empty placeholders above the Admin section menu after notifications load.
  Dim the affected session or approval row while its revocation is running.

- Consolidate the existing MCP skill's diagnostic workflow: separate current
  observations, verified historical coverage, structural paths, and causal
  hypotheses; disclose gaps and uncertain transition times.

- Group service operation and autostart controls with service status, and move
  technical MCP tuning into Advanced settings. The connection test now uses the
  current unsaved Miniserver selection without saving the configuration.

- Recognize documented analog `value` states without an `analog` detail and
  preserve uncertainty when an explicit flag contradicts the control type.

- Match native statistic outputs to their states before recommending reuse, ignore
  disabled statistic groups, and classify documented digital states individually.
  Restrict the `Daytimer` analog flag to its value state.

- Recognize documented `InfoOnlyDigital` 0/1 states as discrete for observability
  recommendations when `is_analog` is absent; retain uncertainty for conflicting
  metadata or values.

- Extend `loxone_analyze_observability` with bounded per-state history-source
  recommendations based on observable value and control metadata. Reuse
  advertised native statistics, disclose unknown state mapping and period
  coverage, and avoid fixed sampling rates or automatic configuration changes.

- Preserve Loxone's canonical UUID representation when managing local event-history
  sources, so discovered control and state identifiers work unchanged across add,
  list, remove, and history reads.

- Initialize the native `admin-ui` LoxBerry Log Manager entry during both fresh
  installations and upgrades, preserving existing retention. The Admin UI now
  shows a localized empty state when no native plugin logs are available while
  keeping the mandatory `service.log` separate.

- Let Administrators revoke distinct local LoxBerry bindings concurrently in the
  Clients and sessions UI, including one `loxberry:read` and one
  `loxberry:operate` binding. Duplicate, same-binding, session-conflicting, and
  global revocations remain serialized.

- Deduplicate identical KNX blocks from separate internal model sources for
  Project Intelligence search, runtime mapping, and analysis. Project status
  now distinguishes opaque model sources from `project_parts`; logical KNX
  objects and analysis coverage disclose bounded source-occurrence provenance.

- Show the idle web-certificate reissue status as "Not started" instead of
  incorrectly reporting a failed reissue when no attempt was recorded.

- Bound remote Loxone token cleanup after local OAuth revocation to five network
  attempts per token and a persisted profile-wide cooldown. Cleanup no longer
  probes an open Miniserver authentication breaker. The Admin UI shows sanitized
  aggregate cleanup warnings and distinguishes emergency-stop discovery failures,
  with a manually initiated retry after the breaker's earliest retry time.

- Align the Admin UI navigation and page order around status, configuration,
  MCP access and HTTPS, clients, MQTT health, diagnostics, and help. Connection
  URLs and certificate actions now share the MCP access section; Help keeps the
  Tool Explorer, schema reference, and project guides. The section navigation
  renders independently of the LoxBerry header's JavaScript.

- Add `loxone_analyze_observability`, a bounded read-only assessment of current
  state availability, configured native statistic series and local event-history
  coverage for exact UUID-mapped controls structurally reachable from one project
  target. It reports gaps and uncertainty explicitly; graph reachability and
  configured statistics do not claim a historical cause or data coverage.

- Keep local LoxBerry approvals reusable for the same validated Tool Explorer,
  Loxone identity and Miniserver across ordinary OAuth re-login. OAuth families
  and credentials retain their short lifetimes; inactive Explorer approvals use
  a separately configurable 72-hour retention period and remain explicitly
  revocable in the Admin UI.

- Add a bounded, persisted shared Miniserver authentication breaker. Confirmed
  source-IP blocks suppress further service login attempts, while configured
  15-minute initial and 24-hour maximum lazy recovery delays can be adjusted
  in the Admin UI without exposing credentials, tokens, endpoints, or IPs.

- Report bounded, value-free KNX project-source diagnostics through project
  status, analysis and object descriptions. Parser anomalies and unsupported
  source forms remain visible without exposing raw project attributes or
  turning incomplete evidence into a configuration verdict.
- Add fixed value-free diagnostic categories to project-tool source-processing
  failures, so invalid or unsupported input is distinguishable from limits,
  timeouts and other processing failures.
- Add opt-in, bounded local event history for explicitly selected Loxone state
  sources. The recorder uses the LoxBerry-managed Miniserver identity, preserves
  short-lived state changes, reports coverage evidence, and is queried through
  `loxone_get_event_history`. Approved existing `loxberry:operate` clients can
  list, add, and remove sources without a new OAuth scope.

- Show the running service's emergency-stop signal and MQTT-compatible state in
  the Admin UI, including a clear indication when the current form selection
  has not yet been adopted by the service.

- Load Admin UI service state independently, defer closed certificate and
  session sections, and query emergency-stop options only on explicit request.
  Failed option discovery now distinguishes unavailable discovery from an empty
  matching list without changing fail-closed emergency-stop monitoring.

- Expand `loxone_analyze_project` to analysis version 2: bounded source-name
  patterns, exact UUID-mapped runtime context, local peer and graph outliers,
  and explicit data-limitations complement address, raw datatype, reviewed
  signal-use, path, and connection evidence. Findings remain traceable review
  facts, never KNX quality ratings or DPT/ETS claims.

- Make the MCP Tool Explorer compact on narrow screens and use a three-zone
  request/result workspace on sufficiently wide screens without changing MCP calls;
  the tool rail has enough width for long tool names.

- Remove retained MQTT health and emergency-stop topics from an obsolete broker
  destination after relevant MQTT configuration changes. If the old broker is
  unavailable, retain the new configuration and show an Admin UI warning.

- Add a documented Windows Python 3.13 development bootstrap and actionable
  diagnostics when a restricted environment cannot execute its interpreter.

- Add bounded, source-backed KNX/EIB semantics to Project Intelligence. Existing
  project search, description and trace tools can filter and report confirmed
  bus lines, endpoints and KNX logic blocks without exposing raw project
  attributes or inferring DPTs, physical device roles, or graph edges from
  equal group addresses. Search and trace return compact KNX summaries and cap
  their complete response envelopes at 64 KiB; describe retains the detailed
  KNX source evidence for one object. Reviewed internal block rules can now
  add separately marked signal-use observations and KNX/Loxone boundary paths;
  unknown block or connector behaviour remains absent rather than guessed.

- Render the Admin UI without waiting for service status or Miniserver emergency-stop
  discovery, while preserving an unavailable configured emergency-stop selection.

- Update Clients and sessions immediately after successful session actions and
  allow non-conflicting approvals or revocations to run in parallel, without
  relying on a follow-up refresh that can fail.

- Publish an unambiguous retained MQTT emergency-stop state: `not_configured`,
  `clear`, `active`, or `unknown`. Its dedicated MQTT connection now retains
  `unknown` after an unexpected connection or process loss.

- Restore the previous MCP or MQTT configuration, encrypted MQTT credential and
  running service together when applying a section-specific configuration fails.

- Add `loxone_get_structure_overview` for exact authorized-visible counts and
  bounded room, category and control-type breakdowns without additional
  Miniserver polling, state reads or Config-project access.

- Add the internal, read-only Loxone project pipeline for authenticated downloads,
  bounded LoxCC decoding, tolerant parsing, deterministic graph construction and
  evidence-based runtime UUID mapping.

- Add four bounded, read-only Project Intelligence tools for project status, object search,
  object descriptions, and upstream/downstream signal or reference traces. They use
  `loxone:read`, never return raw project XML, and keep ambiguous mappings explicit.

## 0.4.0-beta.3 - 2026-08-15

- Enable the bounded read-only feature families for fresh installations, prefill
  the HTTPS origin from LoxBerry's configured host, and register admin logs with
  the LoxBerry LogManager. Upgrades preserve their configuration; write scopes remain off.

## 0.4.0-beta.2 - 2026-08-15

- Enable bounded history/statistics and masked LoxBerry diagnostics for fresh
  installations. Saving the first complete configuration also enables the
  service; OAuth consent and local diagnostic approvals remain required.

## 0.4.0-beta.1 - 2026-08-15

- Add `loxone_get_room_snapshot` for bounded current states in one exact visible
  room and `loxone_get_weather` for current or paginated forecast weather.

- Add compatible semantic state values and read-only description models for
  visible `Irrigation` and `AlarmClock` controls while preserving their raw values
  and advertising no actions.

- Update the bundled `using-loxberry-mcp` agent workflow to revision 18 for room
  snapshots, weather, and the new read-only controller interpretations.

- Add bounded, paginated filtering for service events by trace ID, component,
  severity and RFC-3339 time range; diagnostic records now use UTC timestamps.

- Add optional time-range filters to control history and discovery filters for
  visibility, notes, favorites, room groups and bounded name searches.

- Add an explicit, fail-closed `room_group` reference to each visible room from
  `loxone_list_rooms`, and resolve visible room and control references in
  StatusMonitor and WindowMonitor descriptions.

- Preserve explicit WindowMonitor item mappings when LoxAPP3 represents them as
  a bounded object keyed by control identifier, so their referenced visible
  controls can be resolved without name inference.

- Begin the feature-frozen `0.4.0` beta channel. Future `0.4.0` changes are
  limited to beta blockers, fixes and necessary compatibility corrections.

## 0.4.0-beta.4 - 2026-08-17

- Add an optional fail-closed emergency-stop signal from a visible digital
  Loxone Virtual Status. It blocks MCP tool calls on `0` or an unknown signal
  state and publishes its retained MQTT status independently from health topics.

- Treat the service-enable switch as a saved boot setting: initialize it when
  the page loads and update it only after applying that setting, never from
  periodic service-status polling or separate Start/Stop/Restart actions. Disable
  those runtime actions while the saved service setting is off.

- Separate systemd runtime, MCP access and optional MQTT health configuration.
  MQTT health publishes retained Loxone-epoch heartbeat and systemd state topics

- MQTT health can optionally use a custom broker. Its password is stored in a
  separate encrypted credential store and is never displayed or logged.
  below the configurable `mcpserver` root without storing or displaying broker credentials.

- Harden Admin UI browser responses with no-store caching, CSP, frame, referrer
  and MIME protections across page, AJAX, download and redirect paths.

- Add Tool Explorer time-range shortcuts, in-tab reference selection, action-specific
  control fields, and collapsible advanced parameters.

- Generate a versioned HTML and JSON reference for the complete MCP tool
  contract during package builds, link it from Help and the Tool Explorer, and
  document `tools/list` as the authoritative installed tool surface.

- Restore date/time pickers for optional RFC-3339 tool parameters in the Tool Explorer.

- Update the bundled `using-loxberry-mcp` agent workflow to revision 24 with
  task-specific read paths, complete cache-operation authorization and
  uncertainty guidance, and fail-closed schema and parameter-source rules.

## 0.4.0-alpha.15 - 2026-08-15

- Fail closed when the Miniserver binary-state stream ends before its first
  state batch, instead of returning an apparently usable read session without
  current values.

- Wait briefly for the Miniserver's initial binary-state table when opening a
  read session, so current state reads no longer race the asynchronous stream.

- Suspend all pending remote Loxone token-revocation attempts for one hour after
  an authentication rejection or Miniserver source-IP lockout, preventing the
  revocation worker from creating a burst of further logins while retaining the
  tokens until remote confirmation is possible.

## 0.4.0-alpha.14 - 2026-08-14

- Use the existing narrow non-interactive service-stop permission during the
  pre-upgrade hook, so a native Plugin Manager upgrade can stop the MCP service
  before migrating its persistent auth data; upgrades from older releases
  without that permission safely stop only the plugin's own service process.

## 0.4.0-alpha.13 - 2026-08-14

- Stop the MCP service before an upgrade replaces its persistent auth data, so
  in-flight requests cannot fail against a temporarily unavailable store.
- Classify a Miniserver source-IP lockout received while sending a WebSocket
  command as a recoverable connection failure, including deferred token cleanup.
- Keep a failed Loxone binary-state stream fail-closed while recording only its
  sanitized exception class; the stream task is now consumed after that record
  so its error cannot be raised a second time during session cleanup.
- Restore Gen. 1 Loxone token authentication by using the firmware-supported
  JWT credential inside RSA/AES Command Encryption instead of the rejected
  token-hash variant; the independent Gen. 2 hash path remains unchanged.
- Stop Loxone token authentication attempts after three rejections of the
  `authwithtoken` step per OAuth session until a local administrator explicitly
  permits another bounded attempt. Miniserver source-IP lockouts are reported
  separately and never increment that counter.
- Enable LoxBerry Plugin Manager automatic update discovery for stable releases
  and explicitly opted-in prereleases.

## 0.4.0-alpha.12 - 2026-08-14

- Prevent concurrent local LoxBerry read or operate binding changes from
  overwriting one another. The Admin UI keeps parallel session actions pending
  until it refreshes one consistent server state.
- Add a reproducible Windows development-environment setup and keep temporary
  test data inside the project data area.

## 0.4.0-alpha.11 - 2026-08-14

- Add `loxberry_list_service_events`: a bounded, read-only MCP diagnostic feed
  exposing only allowlisted fields from server-authored records in the fixed
  plugin service log. Raw logs, arbitrary files, journal data, payloads and
  foreign services remain unavailable.
- Record sanitized error classes for unexpected LoxBerry diagnostic failures and
  retain the returned trace ID for correlation.
- Restore MCP Tool Explorer sign-in through approved HTTPS IP or hostname aliases:
  proxy the exact internal Explorer-session endpoint, bind it to the current
  validated Explorer origin, and retain its real error message for diagnosis.

## 0.4.0-alpha.10 - 2026-08-14

- Load the administrative configuration before deferred status and session data,
  so the management page remains responsive without weakening its consistency.
- Retain encrypted Loxone tokens after local session revocation until the
  Miniserver confirms `killtoken`; unavailable Miniservers are retried by the
  service without delaying the administrative UI.
- Correct the final transport allowlist for documented Daytimer, room-controller,
  ventilation and HVAC temporary overrides; unsupported raw commands remain rejected.

## 0.4.0-alpha.9 - 2026-08-13

- Add bounded LoxAPP3 climate, ventilation, safety/status, energy and global
  metadata models, semantic Daytimer/weather events, and documented temporary
  override contracts.
- Reuse the MCP Tool Explorer OAuth session in new browser tabs for up to eight
  hours without storing refresh credentials in browser storage; disconnect now
  revokes the shared Explorer session in every tab.

## 0.4.0-alpha.8 - 2026-08-13

- Keep the HTTP-to-HTTPS Explorer guidance visible after a sign-in click by
  performing the HTTP origin check before testing the intentionally absent
  authorization popup.

## 0.4.0-alpha.7 - 2026-08-13

- Block MCP Tool Explorer sign-in on HTTP before OAuth discovery and provide a
  link that reloads the same IP address or hostname over HTTPS; open the HTTPS
  authorization popup synchronously so Firefox retains the click activation.

## 0.4.0-alpha.6 - 2026-08-13

- Open the Tool Explorer OAuth popup synchronously from the user click, then
  navigate it after asynchronous discovery and PKCE setup.

## 0.4.0-alpha.5 - 2026-08-13

- Check the documented LoxAPP3 version marker before each due structure refresh
  and download the full user-filtered structure only after a detected change.
- Serialize due LoxAPP3 refreshes per OAuth family, close live Miniserver
  sessions on service shutdown without revoking persisted authorization, and
  extend the deterministic lifecycle tests.
- Move pure control discovery presentation into its own module and make local
  release-candidate source copies ignore untracked build and temporary artifacts.
- Simplify `loxberry_clear_statistics_cache` to report only removed RAM entries;
  the unused hybrid-cache compatibility fields are removed in this alpha.

## 0.4.0-alpha.3 - 2026-08-13

- Refresh the user-filtered LoxAPP3 structure after reconnects and at a bounded
  configurable interval, including visible Notes, ratings, and favorites; reject
  stale refreshes and oversized structures safely.
- Bound runtime WebSocket sessions by activity and capacity, avoid concurrent
  token-refresh/event reads, and close runtime connections together with OAuth
  family revocation.
- Replace the unused persistent statistics-cache mode with a bounded RAM-only
  cache and add advanced, validated structure and runtime limits.
- Preserve all bounded non-negative Loxone ratings, expose the independent
  favorite marker, and extend the bounded operation allowlist to virtual analog
  inputs, CentralJalousie, and digital Daytimer overrides.
- Discover explicitly user-linked controls as `visibility: "linked"`, describe
  both directions of the link, and support the bounded `UpDownAnalog.set_value`
  action when the linked control is currently visible and authorized.
- Add explicit `include_hidden` diagnosis to find, describe, state, notes,
  history, and statistics tools; hidden controls remain permanently non-operable.
- Restrict Jalousie slat actions to the documented blind animation mode and
  fail closed for shutters, curtains, unsupported, malformed, or absent modes.

## 0.4.0-alpha.2 - 2026-08-12

- Canonicalize signed-zero control values, preserve fractional statistic interval
  boundaries, and keep history and statistic pagination consistent through signed
  continuation anchors with stable occurrence tie-breakers without retaining result
  sets in RAM.
- Rate-limit denied LoxBerry cache-clear attempts and audit cancelled operations as
  having an unknown outcome.
- Finalize the `loxone:history` and `loxberry:operate` workflows with scoped
  Explorer grouping, guided statistic transfer, and scope-labeled local bindings.
- Describe every supported Loxone control type in `loxone_operate_control` and
  document the Phase-4 hardware acceptance boundary.

## 0.4.0-alpha.1 - 2026-08-11

- Add separately authorized `loxone:history` StatisticV2 and bounded
  control-history tools with
  short-lived RAM caching and an optional capped private compatibility cache.
- Extend bounded Loxone operations to TimedSwitch, Radio, LightsceneRGB,
  ColorPicker V1/V2 and Pushbutton without exposing raw commands.
- Add locally approved `loxberry:operate` with the sole plugin-owned statistic
  cache clear operation.
- Keep optional OAuth permissions requestable before administrator approval.
  The Tool Explorer requests every advertised scope and leaves the only visible
  selection to the post-login OAuth consent page; gated tools fail closed with
  `permission_denied` until approval.
- Document the complete verified/unverified control table and defer multiple
  Miniserver support with explicit security and acceptance requirements.
- Present global Loxone and LoxBerry capability gates as grouped, scope-labeled
  checkboxes instead of permission dropdowns.
- Accept the numeric `hasHistory` capability emitted by real Miniservers so a
  valid Loxone sign-in is not rejected while loading the user-visible structure.
- Accept the Miniserver's direct-list control-history response and let
  `loxone_find_controls` filter for history and/or StatisticV2 capabilities.
- Decode JSON-encoded `getStatisticInfo` values and request StatisticV2 binary
  files directly on the authenticated WebSocket so Gen. 1 Miniservers can
  return the documented binary response.
- Support visible legacy `statistic.outputs` through bounded raw binary WebSocket
  files; XML and FTP remain disabled.
- Add visible control presentation metadata and a bounded read-only tool for
  user-authored control notes; KNX/EIB Config project data remains unavailable.

## 0.3.0-alpha.1 - 2026-08-07

- Add disabled-by-default, locally approved `loxberry:read` diagnostics for
  sanitized LoxBerry system, plugin, and MCP service status.

- Give `service.log` a dedicated persistent Off/Error/Warning/Information/Debug
  level while retaining masked, unsuppressible audit records for control attempts.
- Enable the native LoxBerry Log Manager level for plugin logs and consolidate
  admin actions into one rotating `admin-ui.log` instead of one file per action.
- Bound both active logs to 512 KiB plus two backups and individual records to
  8 KiB while avoiding routine admin-page and HTTP access-log writes.
- Build official packages only through the owner-triggered GitHub workflow, with
  canonical ZIP and wheel output, locked runtime-wheel hashes, exact manifests,
  verified draft uploads, and separate read/write job permissions.

## 0.2.0-alpha.1 - 2026-08-05

- Add read-only and explicitly authorized Loxone MCP tools, OAuth, the integrated
  Tool Explorer, and the packaged `using-loxberry-mcp` agent skill.
- Package a fully offline Debian 13 arm64/Python 3.13 runtime for native
  installation through LoxBerry Plugin Manager.

## 0.1.0-alpha.1 - 2026-07-31

- Publish the first owner-tested MCP Server alpha for LoxBerry 4.
