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
`EIBactor`, `EIBPush`, `EibDimmer`, and `EIBJalousie`. `EIBsensor` is a
`bus_to_loxone` endpoint and `EIBactor` a `loxone_to_bus` endpoint. This records
the bus data-flow direction, never a physical device role. Group addresses are
kept verbatim and normalized only for validated two- or three-level forms.
`EIBType` is retained as an unresolved source code; the model does not infer an
EIS or DPT meaning. Unknown attributes remain internal and are never a raw MCP
projection. Equal group addresses do not create graph edges.

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

`loxone_analyze_project` version 2 returns bounded, deterministic project-local
evidence; it never grades a KNX installation. It aggregates canonical-address
and source-name patterns, conflicting raw `EIBType` values on one group address,
reviewed signal-use observations, exact runtime-mapping context, local peer and
graph outliers, static KNX/Loxone paths, and endpoints without an observed
project relationship. A runtime name, room, category, or control type is used
only after an exact UUID mapping and is never used to identify a project node.
Raw `EIBType` remains an unknown-system source code, so the analysis never
claims DPT compatibility. It reports fixed limitation codes whenever normalized
DPTs, semantic domains, reviewed usage, or exact runtime mappings are missing.
ETS data, bus traffic and physical-device use are outside this projection.
Findings are stable only for an unchanged project model and analysis version;
they include project-node evidence for follow-up describe or trace calls.
Source, decoder, parser and graph execute in a disposable subprocess with a
45-second processing deadline, bounded IPC and Linux address-space/CPU/core-dump
limits. The separate network download deadline remains 20 seconds.
Only project bytes and limits cross into the worker, never authentication tokens.
The service serializes builds and publishes complete immutable snapshots. Its
identity-isolated RAM cache is capped at eight entries and a conservative 128 MiB
accounting budget. A cache hit still requires a fresh successful download.

Der Graph unterscheidet Signal-, Referenz- und Hierarchiebeziehungen. Unbekannte
Referenzen bleiben sichtbar unaufgelöst. Die Verarbeitung läuft in einem
abbrechbaren Unterprozess; der Cache ersetzt keine Zugriffsprüfung.
