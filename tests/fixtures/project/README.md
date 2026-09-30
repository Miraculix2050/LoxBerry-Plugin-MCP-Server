# Project fixture provenance

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
