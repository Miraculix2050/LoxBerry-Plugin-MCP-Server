# Config / Miniserver KNX datatype evidence

On 2026-10-17, an authorized read downloaded the current Miniserver project
in memory. Its two LoxCC parts decoded to ControlList format 274, with Document
ConfigVersion 17020828. Comparison with the local Config project of the same
version used normalized object UUID, exact object type and group address.
No name, nearby address or dropdown position supplied a match.

All 335 objects in the larger part matched, including whether EIBType was absent;
there were zero mismatches or unmatched objects. The smaller part matched the
same 155 actor/text-actor objects, also without mismatches. These are duplicate
model occurrences, not 490 independent devices. Private project contents, UUIDs,
addresses, tokens and credentials are not retained here or in public fixtures.

| Source type | EIBType | Matched objects in larger part | EIS | DPT main types |
| --- | --- | ---: | --- | --- |
| EIBsensor | absent | 122 | unknown | 1 |
| EIBsensor | 4 | 32 | 5 | 9 |
| EIBsensor | 5 | 17 | 6 | 5 |
| EIBsensor | 8 | 6 | 9 | 14 |
| EIBsensor | 9 | 2 | 10 | 7, 8 |
| EIBactor | absent | 97 | unknown | 1 |
| EIBactor | 1 | 14 | 2 | 3 |
| EIBactor | 2 | 1 | 3 | 10 |
| EIBactor | 3 | 1 | 4 | 11 |
| EIBactor | 4 | 1 | 5 | 9 |
| EIBactor | 5 | 22 | 6 | 5 |
| EIBactor | 6 | 14 | 7 | 1 |
| EIBtextsensor | absent | 1 | 15 | 16 |
| EIBtextactor | absent | 5 | 15 | 16 |

The EIS/DPT relationships come from the
[Loxone datatype table](https://www.loxone.com/dede/kb/eibknx-datentypen/).
The independent Config reference selects the datatype meanings. The paired
comparison establishes preservation of these specific codes and omissions in
the Miniserver format. The user explicitly approved the missing scalar attribute
as the Config DPT1 default; no EIS type or numeric code zero is inferred.

`miniserver-knx-v1` enables only these observed pairs, guarded per part by exactly
one format version, one Document and one ConfigVersion attribute. Conflicting
or duplicate Type/EIBType attributes, empty/unknown values, other versions and
unpaired source-type/code combinations remain unresolved. Additional codes
covered by the offline Config report are not automatically enabled here.

Describe preserves `datatype.source_value` and adds `normalized_dpt_evidence`
with source format, mapping/version evidence, status, EIS and candidate main
types. Explicit mapped codes use `datatype.system=dpt_main_type`; a unique main
type is a decimal `normalized_code`, while multiple candidates leave it null.
An absent raw datatype remains null, with the implicit default in the separate
evidence field. ETS/manual `metadata.dpt_details` remains independent, including
multiple declarations and syntax status. EIBType4 can establish main type 9;
9.004 comes only from an explicit ETS/manual declaration. `subtype=null` and
`compatibility=not_established` prohibit turning main-type agreement into
device, telegram, unit, physical role or compatibility evidence.

Project model version 14 invalidates prior content interpretation; KNX analysis
version 13 counts endpoints without mapped main-type evidence in
`normalized_dpt_unavailable`. Raw datatype comparisons remain raw and are not
new compatibility checks. Tests use synthetic objects through the LoxCC
snapshot boundary and authorized MCP projection. Hotswap acceptance is separate
from native installation, KNX telegram observation or ETS/device compatibility.
