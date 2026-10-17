# Project fixture provenance

config-knx-datatypes.xml is a minimal derivative of the user-supplied Loxone
Config project EIBTypeZuordnungen.Loxone inspected on 2026-10-17. It retains
only ControlList Version=274/LxAV=87, Document ConfigVersion=17020828, endpoint
Type and explicit EIBType values, including omissions. Names, IDs, addresses,
credentials and every unrelated attribute were removed. The user created the
datatype selections explicitly. The sensor named Jalousie in the source omits
EIBType; it does not establish EIS7 sensor support. The user explicitly approved
interpreting omitted EIBType on EIBsensor and
EIBactor as the implicit DPT1 Config default, without assigning an EIS type.
An explicit actor EIBType=6 retains its separate EIS7/DPT1 interpretation.
The fixture remains unchanged to preserve the source omissions. This is Config-file
evidence, not evidence about decoded Miniserver sps.LoxCC data. EIS/DPT main-type relations
are documented at https://www.loxone.com/dede/kb/eibknx-datentypen/.

observed-topology.xml reproduces the ControlList/C/Co/In and U/K/Input/Ref
relationships observed in the authorized 2026-09-18 in-memory target inspection.
Every identifier and block type was replaced with a synthetic value; labels,
addresses, credentials, unrelated attributes and project contents were omitted.
The retained AQ/AI port keys are schema vocabulary. Inspection confirmed that an
input Co contains an In whose Input UUID refers to the upstream output Co.
This is a minimal structural derivative, not an exported project.

Runtime IDs were observed to match C/U exactly after hyphen/case normalization;
the runtime fixture added with mapping uses the same synthetic identifiers.

opening-contacts.xml is a minimal anonymized derivative of the authorized
2026-09-23 contact-consumer audit. Identities and display names were replaced.
It retains the observed source C/U -> InputRef C/Ref relationship, InputRef AQ,
Or I1/I2/Q and AutoJalousie Window keys, with a separate lockout input. The
InputRef projection is enabled only for an exact resolved block reference and
one AQ connector; it does not infer an arbitrary internal block relationship.
OR dependency semantics are backed by https://www.loxone.com/enen/kb/or/.
That documentation uses the UI output label O, while the observed project key
is Q; no O/Q or Dwc/Window alias is inferred. This fixture is static wiring
evidence, not a physical opening inventory or a real project export.

observed-knx.xml is an anonymized structural derivative of the KNX/EIB forms
observed in the same authorized project inspection. All identifiers, labels and
group addresses were replaced, while the exact `Type`, `EibAddr`, `EIBType`,
`C`, `Co` and `In` layout needed for semantic classification and graph traversal
was retained. It is not a raw project export.

knx-text-endpoints.xml is synthetic. It covers the confirmed type names,
EibAddr forms, and connector directions without retaining project identifiers,
labels, addresses, or other private source values.
