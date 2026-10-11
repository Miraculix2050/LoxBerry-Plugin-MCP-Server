# KNX information through MCP

Inspect the current tool schema and retrieve `loxone_get_skill_guide(section="core")`,
then `section="knx"` for a KNX task. Equivalent resources are
`skill://using-loxberry-mcp/core.md` and `skill://using-loxberry-mcp/knx.md`.
The no-argument tool and `skill://using-loxberry-mcp/SKILL.md` retain the complete
guide. If the client has not discovered the section argument, use the complete
guide rather than guessing unsupported arguments. If guidance retrieval fails,
stop the affected workflow. Other workflows and writes still need the full guide.

Project search also considers imported ETS and manual KNX names/descriptions,
including values hidden by overrides. It returns authorized project objects,
not every standalone local address or prefix label. Loxone names stay primary.
Use an exact address for targeted explanation; describe returned objects and
trace only when structural context is needed.

For inventory review explicitly select `ets_project_comparison` with KNX scope.
Defaults are unchanged. Check target, revision, freshness, coverage, diagnostic
omissions and required pages. Distinguish a sample from a complete requested review.
Manual-versus-imported `deviations` and Loxone-versus-ETS `names_differ` are
different comparisons. Unknown is not agreement; multiple names need a decision.

DPT declarations retain source and missing/empty/declared states. Syntax validation
does not prove registry membership, compatibility or an `EIBType` mapping. Import
time is not export time; Admin target assignment does not prove the correct ETS
project. Names, addresses and structural traces prove neither bus activity nor
physical roles or historical causes. File comparison and experimental XML download
remain on the KNX page; this read-only workflow cannot repair or export a project.

Task sections are derived from one bundled canonical guide and cached within the
running process. Retrieval loads no project/catalog and does not grant permission.
Token measurements must name the tokenizer/model/client and distinguish loaded
schemas, guide content and actual results. Character counts are not token counts.
For discovery mismatches, see [troubleshooting](troubleshooting.en.md).

## Compact ETS comparison

Explicitly select `analyses=["ets_project_comparison"]`, `scope="knx"` and
`view="summary"` for counts without individual address detail reads. Use
`view="findings"` for paginated source evidence or `view="detail"` with an exact
two-/three-level `address` (without a variant suffix) for one address. Returned
project objects retain their original `:0`/`:1` variants and Loxone names.
The omitted/default `view="full"` and other analyses keep their existing behavior.

Compact views accept `relation`, `names_differ`, `ambiguous_names` and `address`.
False name-deviation selection includes only compared, complete observed names;
unknown or incomplete names are not agreement. Filters are unavailable in full
view and cannot be mixed with other analyses. Summary has no continuation cursor.
Keep view, all filters and `source_details` unchanged on findings pages; target,
project and KNX revision changes require a fresh query.

`summaries.ets_project_comparison.counts` describes the whole bounded observation.
`selection.counts` describes retained, filtered observations; `selection.complete`
is false if observation truncation may hide further matches. Source completeness,
omitted groups and diagnostic counts remain separate on every compact page.
Use `source_details=true` only when full diagnostic/source groups are needed.
The protocol retains structured and text fallback results; clients should consume
one representation rather than inserting both into the AI context.
