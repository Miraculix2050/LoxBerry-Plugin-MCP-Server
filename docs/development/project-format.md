# Internal project format

The LoxCC envelope contains four little-endian 32-bit words: magic 0xAABBCCEE,
compressed length, decoded length and CRC32 of the decoded bytes. A bounded
LZ4-style block follows. This decoder validates exact lengths and checksums and
rejects invalid back-references. It does not interpret project XML.

Protocol research: the issue references Smarteon/lox-mcp, whose repository uses
AGPL-3.0. No implementation code is copied or vendored. The decoder is written
locally using the envelope facts and the public LZ4 block format description:
https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md
The upstream LZ4 specification is BSD-2-Clause; no runtime dependency is added.
Tests construct small original byte vectors, including overlapping matches.

Das interne LoxCC-Format enthält Kennung, komprimierte und dekodierte Länge sowie
CRC32. Der Decoder prüft diese Werte und ungültige Rückverweise vor Freigabe der
Projektbytes. Es wird kein Code der AGPL-Referenz übernommen und keine neue
Laufzeitabhängigkeit eingeführt. XML-Verarbeitung folgt separat.

## Parser evidence

The authorized target supplied ControlList/C blocks, Co connectors and In/Input
references. Both files decoded with valid CRCs and parsed successfully: 5,252 and
18,241 elements. The latter contained 54 literal attribute-newline anomalies.
The archive also contained three auxiliary files; these are bounded and validated
but not interpreted as projects. No source values were retained in this document.
The parser preserves duplicate attributes and mixed content, rejects declarations
and external entities, and retains unknown schema fields internally.

Beide realen Projekte wurden mit gültiger CRC dekodiert und erfolgreich geparst.
54 Attribut-Zeilenumbrüche wurden als Anomalien erfasst. Begleitdateien im ZIP
zählen zu den Größenlimits, werden aber nicht als Projekte interpretiert.

## Graph and processing boundary

C elements and their Co connectors retain source attributes and part-local IDs.
An In/Input reference contributes a signal edge from its referenced Co to its
containing Co. Ref aliases and containment have distinct edge kinds; traversal
never treats containment as evidence of signal causality. Unknown or ambiguous
references stay unresolved. No Miniserver identity is inferred from ZIP filenames.

## KNX/EIB semantic projection

The worker classifies only confirmed exact project types: `EIBline`, `EIBsensor`,
`EIBextsensor`, `EIBtextsensor`, `EIBactor`, `EIBextactor`, `EIBtextactor`,
`EIBPush`, `EibDimmer`, and `EIBJalousie`. Sensor types are
`bus_to_loxone` endpoints; actor types are `loxone_to_bus` endpoints. This records
the bus data-flow direction, never a physical device role. Group addresses are
kept verbatim and normalized only for validated two- or three-level forms.
For `EIBextsensor` and `EIBextactor`, validated `:0` and `:1` suffixes retain their exact original
value and an `edge` variant distinct from the canonical base address. `EibAddr`
is used when present; only `EIBextsensor` uses `EibAddrPulse` when `EibAddr` is absent. The
address projection names the field actually used. Other suffixes are invalid;
the suffix does not establish rising or falling edge semantics. Exact variant
search matches only that variant, while a canonical-base search may return both.
`EIBType` is retained when present as an unresolved source code; the model does not infer an
EIS or DPT meaning. Unknown attributes remain internal and are never a raw MCP
projection. Describe bounds connector IDs and keys plus incoming and outgoing
signal counts; those counts report configured graph wiring, not bus traffic.
Missing `EIBType` on the three newly modeled families is not diagnosed as a
source gap. Equal group addresses do not create graph edges.

When identical confirmed KNX blocks occur in distinct internal model sources,
the public projection uses one logical object. Its normalized source identity,
block type, and KNX projection must agree; equal titles or addresses alone never
merge objects. The raw graph remains internal provenance, while bounded opaque
model-source IDs and an occurrence count disclose multiplicity. Project status
calls the number of ingested model sources `project_parts`; it is not a count of
Loxone Config projects.

## Derived KNX signal-use evidence

The graph keeps raw `signal` and `reference` edges separate from reviewed,
derived internal connector edges. A derived edge exists only for an exact
allowlisted block type and input/output connector pair. It records a compact
interpretation such as `level`, `value`, `rising_edge`, or
`duration_sensitive`, and may retain a separate effect such as `toggle`.
Unknown block types, connector keys, duplicate connector keys, and incomplete
rules create no derived edge.

One KNX endpoint can reach several derived edges and therefore has several
usage observations. A trace may classify a bounded path as `knx_to_loxone`,
`loxone_to_knx`, or `knx_to_knx` only when its boundary endpoints are confirmed
KNX endpoints or exact runtime mappings. These paths describe static project
reachability, not a physical device role, bus telegram, or historical cause.

## KNX project analysis

`loxone_analyze_project` version 7 returns bounded, deterministic project-local
evidence; it never grades a KNX installation. It aggregates canonical-address
and source-name patterns, conflicting raw `EIBType` values on one group address,
reviewed signal-use observations, exact runtime-mapping context, local peer and
graph outliers, static KNX/Loxone paths, and endpoints without direct configured
wiring. Graph outlier degree retains raw signal-plus-reference counts, with separate
component and logical-counterpart counts; bounded edge samples keep derived semantic
edges distinct. Connectivity findings name the inspected connector scope and separate
direct signals from references. Reference-only endpoints receive a distinct finding.
Existing finding IDs use the version 6 hash basis despite the analysis-version change.
A runtime name, room, category, or control type is used
only after an exact UUID mapping and is never used to identify a project node.
Address-specific datatype and signal-use comparisons keep edge variants separate;
address-prefix patterns use the canonical base. Raw `EIBType` remains an
unknown-system source code, so the analysis never
claims DPT compatibility. It reports fixed limitation codes whenever normalized
DPTs, semantic domains, reviewed usage, or exact runtime mappings are missing.
ETS data, bus traffic and physical-device use are outside this projection.
Status and KNX analysis share `coverage_by_source_type`. `source_objects` counts raw
`C` occurrences. `modeled_endpoints`, `modeled_logic_blocks`, and `modeled_lines`
count logical objects after the existing identity-backed model-source collapse;
`duplicate_source_occurrences` counts the additional collapsed raw occurrences.
`invalid_or_missing_address` counts logical endpoints without a validated canonical
address. `unsupported` counts unmodeled `EIB*` source types, not unknown physical
devices. Marker-bearing objects without a confirmed `EIB*` type are counted only in
`ambiguous_source_objects`; they are not claimed as unsupported. Up to 50 sorted
source-type groups are returned. `groups_omitted` and `complete` disclose omitted
groups or ambiguous candidates; long labels have a bounded, hash-suffixed form.
Object details identify raw `EIBType` as `loxone_config` evidence. The separate
`normalized_dpt_evidence` field is null until an authoritative, versioned source is
implemented; `normalized_code` remains null. No DPT or EIS meaning is inferred.
The `address_hierarchy` analysis emits one paginated fact per observed canonical
prefix and bounded local pattern/outlier candidates. Prefixes are partitioned by
two- or three-level address format; a three-level leaf retains the original
address and edge variant in bounded examples. Logical-object and raw-occurrence
counts remain separate. Direct wiring counts directional project signal/reference
relationships and reports unresolved relationships separately. The optional
`knx_address_taxonomy` configuration contains at most 128 exact canonical
prefix labels bound to the configured Miniserver endpoint and explicit
`address_format` (`two_level` or `three_level`). The Admin form uses `2:` or
`3:` before each prefix. This distinguishes a two-level leaf from a three-level
middle prefix with the same numbers. Labels have
`admin_configured` provenance and never alter graph facts or counts. Analysis
cursor scope includes the taxonomy, so changed labels invalidate prior cursors.
When other analyses are requested, hierarchy findings use at most half of the
shared finding limit. `max_findings` marks omitted rows; summary counts still
describe all observed prefixes.

### Future live KNX diagnostics boundary

There is currently no authorized ETS import or bus-diagnostic adapter. A future
read-only capability must be explicitly enabled and require a dedicated
`knx:diagnostics` OAuth scope in addition to project read access. Neither the
scope nor a live tool is published until an actual fixed, authorized source and
its revocation path exist. Its bounded result must identify the adapter kind,
source version or fingerprint, observation time and freshness; redact raw
telegram payloads, credentials and private addresses. Static project wiring and
live observations must occupy separate fields. No observation may assert that
static graph reachability caused bus activity. With no authorized source, the
capability reports `unavailable` and produces no synthesized observations.

Findings are stable only for an unchanged project model and analysis version;
they include project-node evidence for follow-up describe or trace calls.
Source, decoder, parser and graph execute in a disposable subprocess with a
45-second processing deadline, bounded IPC and Linux address-space/CPU/core-dump
limits. The separate network download deadline remains 20 seconds.
Only project bytes and limits cross into the worker, never authentication tokens.
`process_analysis(..., timings=...)` optionally fills a private numeric diagnostic
dictionary: process creation, input pickle, stdin write/drain, waiting until the
first output byte, remaining stdout through EOF, process exit, result unpickle,
total duration and input/output byte counts. Child stdin, input unpickle, analysis
and result pickle durations are returned as four fixed binary numbers on stderr
only in this opt-in mode. No project content, selected-analysis names or identity
is logged or added to MCP responses. Child durations overlap parent pipe/wait
intervals; do not add them to the parent total. Process creation does not include
all child imports, and stdin backpressure can include remaining child startup.
The first-byte/EOF intervals are observable stream boundaries, not pure kernel
transfer timings. Measure repeated real-project runs with target load before
attributing a bottleneck; fewer pickle bytes alone do not establish a speedup.
Analysis input uses a per-pickler dispatch table for `GraphNode`, `GraphEdge` and
`SemanticEdge`. It passes all fields to the existing immutable constructors,
avoiding repeated frozen-slot dataclass field inspection on serialization and
restoration. It does not project or omit graph data, change global pickle
registration, or persist pickle bytes. Source/snapshot workers keep their existing
serialization. Both processes must use the same installed model code.
The service serializes builds and publishes complete immutable snapshots. Its
identity-isolated RAM cache is capped at eight entries and a conservative 128 MiB
accounting budget. A cache hit still requires a fresh successful download.

## Observability analysis

`loxone_analyze_observability` is a separate, time-bounded read-only projection for one
project node or exact runtime-control mapping. It traces only the requested upstream,
downstream, or combined structural reachability and keeps only exact UUID mappings. It then
reports current-state availability, advertised native statistic-series metadata, and local
event-history coverage for the requested period. Structural reachability is not a causal
claim; advertised statistics are deliberately not fetched and report `not_checked` temporal
coverage. At most 20 statistic series per control are returned; `native_statistics_truncated`
marks omitted metadata. State names are capped at 200 UTF-8 bytes and
`state_names_truncated` marks omitted text. Control names and types use the same cap and
`control_metadata_truncated` marks omitted text. Missing or partial local coverage is an evidence
gap, never proof of non-occurrence.
Each returned control also carries bounded, per-state `recommendations` for
incomplete local coverage. They classify from the observed value and explicit
control metadata, never from names; ambiguous behavior remains `undetermined`.
Documented digital state keys are treated as discrete only when their observed
numeric value is exactly 0 or 1 and no applicable analog flag contradicts it.
`Daytimer.details.analog` applies to `value` only. Local recording is not recommended
for `Daytimer` because event-history sources reject that control type. Control-level range metadata
can support `value` but does not classify unrelated states.
The documented `value` state of `InfoOnlyAnalog`, `UpDownAnalog`,
`LeftRightAnalog`, and `Slider` supplies analog evidence even when
`details.analog` is absent. An explicit conflicting digital flag remains
`undetermined`; the documented analog type takes priority over the small-range
discrete heuristic.
Native StatisticV2 outputs map by state key and legacy outputs by their documented
UUID. Disabled groups or frequencies are omitted. A legacy output without a
state UUID keeps the recommendation `undetermined`; mapped series still have
unverified period coverage. Existing
partial local recording is continued when no native series is advertised.
Suggested native sampling intervals remain qualitative because the structure does not establish
the signal dynamics or diagnostic resolution.

### Source diagnostics

The snapshot records bounded, value-free source diagnostics for parser anomalies,
missing or invalid KNX fields, unmodeled attributes on confirmed KNX objects and
attribute-backed unclassified KNX candidates. MCP status returns aggregate counts;
analysis returns bounded groups and describe returns the selected node's diagnostic
shape. Diagnostics contain no raw unknown values and are not configuration findings.
The internal aggregation is capped at 2,048 groups and public analysis at 50 groups;
both make omissions explicit. Describe returns at most 50 node diagnostics and
reports its own truncation and omitted-count metadata when that cap applies.

Der Graph unterscheidet Signal-, Referenz- und Hierarchiebeziehungen. Unbekannte
Referenzen bleiben sichtbar unaufgelöst. Die Verarbeitung läuft in einem
abbrechbaren Unterprozess; der Cache ersetzt keine Zugriffsprüfung.
