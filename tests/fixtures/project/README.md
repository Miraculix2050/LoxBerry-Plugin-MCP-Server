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

observed-knx.xml is an anonymized structural derivative of the KNX/EIB forms
observed in the same authorized project inspection. All identifiers, labels and
group addresses were replaced, while the exact `Type`, `EibAddr`, `EIBType`,
`C`, `Co` and `In` layout needed for semantic classification and graph traversal
was retained. It is not a raw project export.
