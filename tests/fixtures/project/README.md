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
