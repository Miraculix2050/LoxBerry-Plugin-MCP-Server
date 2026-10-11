# Bounded historical analysis

One read-only tool, `loxone_analyze_history`, provides typed calculations.
`loxone_get_statistics` remains the compatible source reader with inclusive
filters and cursors. Observability describes available sources. A separate tool
keeps calculations independent of raw transport. It adds catalog/schema cost,
but avoids transferring complete series for each metric. Acceptance measures
both costs; bytes are not tokenizer measurements.

Pure calculations, existing native/SQLite adapters and a thin MCP adapter remain
separate. Confirmed profile bindings reference sources through current visibility;
declared roles do not authorize a source or prove quantities. Native Control
History remains separate. No persistent analysis cache or new decoder is added.

One fresh caller-owned context authorizes all deduplicated sources. Native cache
hits remain identity-bound and follow authorization. Indexed event reads use a
persisted baseline or predecessor within the same capture phase. Values outside
the phase, retention gaps, reconnect gaps and undecodable values stay unknown.

UTC half-open `[start,end)` requests require an explicit IANA timezone defining
local calendar days, not an assumed legacy Miniserver clock conversion. Limits
are 16 sources, 31 touched local days, 100,000 input points, 30 seconds, two
simultaneous analyses and 64 KiB serialized results. Stricter native limits,
including seven raw statistic days, remain. More than 128 capture phases fails
explicitly. Workers retain admission through cancellation and do not reacquire
the runtime semaphore already held by the context.

Temperature reports count, min/max and an explicitly unweighted sample mean.
Samples do not prove continuity. Energy uses verified counter differences between
observed endpoints or whole documented hourly intervals. Decreases, overlapping
intervals, unknown units/timestamps and overflow cannot produce energy claims.
Partial energy intervals are never divided proportionally. Direction and physical
measurement boundary remain independently unverified.

State duration uses documented binary states with a known phase baseline or
phase-local predecessor. Undecodable intervals and gaps contribute unknown time.
A quiet known phase can establish an unchanged state; an empty history without
a baseline cannot. Duration is not measured energy.

Results identify exact sources, units, methods/versions, requested interval,
usable evidence and limitations. `include_raw=true` requests at most 100 raw
observations or reconstructed segments per page. Cursor proofs bind family,
request and complete raw content; every page reacquires current visibility and
recomputes bounded evidence. Source changes invalidate old cursors. Raw values
are omitted by default.

Ranking/mixed comparisons follow in the next PR. Native EFM remains gated by its
separate reviewed contract; this is not a generic balance calculator.
