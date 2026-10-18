## Lighting and presence

Load core rules first. Resolve the exact visible control with the states module.
For a LightControllerV2, use `loxone_describe_control(view="lighting_context")`
to read source-proven mood IDs and names from its cached `moodList`. This is a
bounded read of the existing state, not an active device probe. Retain its exact
source-state reference, observation time and freshness in the answer.

Distinguish `unsupported`, `missing_reference`, `missing_value`, `invalid` and
`source_limit` from a valid empty list. `total` counts validated source entries;
it does not establish complete configured inventory. Respect `truncated`,
`omitted`, `name_truncated_indices` and `names_complete`. Unknown names remain
unknown. Do not silently replace omitted entries with guessed scene names.
Use existing full descriptions and bounded state reads only if their details
are required, and count those reads in workflow measurements.

Read the project module for configured structural paths and operations before
writes. A mood ID/name never grants operation permission. Existing operations
still require their exact current allowlist and human-requested target/action.
Visible moods, names, rooms and controller capabilities do not prove physical
luminaires, presence associations, scene intent or a professional lighting
assessment. Specialized lighting review from #441 is not supplied here.
