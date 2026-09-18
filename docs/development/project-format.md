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

Source, decoder, parser and graph execute in a disposable subprocess with a
20-second deadline, bounded IPC and Linux address-space/CPU/core-dump limits.
Only project bytes and limits cross into the worker, never authentication tokens.
The service serializes builds and publishes complete immutable snapshots. Its
identity-isolated RAM cache is capped at eight entries and a conservative 128 MiB
accounting budget. A cache hit still requires a fresh successful download.

Der Graph unterscheidet Signal-, Referenz- und Hierarchiebeziehungen. Unbekannte
Referenzen bleiben sichtbar unaufgelöst. Die Verarbeitung läuft in einem
abbrechbaren Unterprozess; der Cache ersetzt keine Zugriffsprüfung.
