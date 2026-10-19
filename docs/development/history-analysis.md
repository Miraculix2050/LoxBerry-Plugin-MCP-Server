# Bounded historical analysis

Optional `history_analysis_context.v1` extends the existing source selection:
association indices reference only the supplied `sources`. Resolution reuses
the common optional-profile, visibility and publication guards. Exact source
membership and EFM topology are checked before historical reads. The final
structure read reuses the admitted history session rather than nesting runtime
admission. Profile revision, selected sources and operating companions are
rechecked before publication; context declarations participate in raw cursors.

`comparison.context_analysis` keeps request identities separate from persistent
binding identities. Observed episode gates remain intact. Observed and declared
candidate demand share the same neutral Decimal budget allocator, while the
legacy wrapper retains its released result. Declared uniform demand can cover
partial hours only as a conditional upper bound; measured hourly supply is never
interpolated. Search exhaustion discards all allocations. No modeled baseline is
serialized as an observed cycle or a measured historical saving.

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

`consumer_ranking` requires confirmed consumer bindings, distinct declared
boundaries, compatible energy representations/observation windows and an explicit
`comparison_options.comparable_boundaries_confirmed` assertion. The client must
confirm comparability and exclusion of parent/child overlap with the user; the
server cannot prove that conversation or physical independence. The result labels
this as user-declared compatibility and ranks individual counters without summing
them. Unknown source direction and reset limitations remain separate.

`pv_load_overlap` needs one confirmed production and one confirmed consumer/house
binding. It compares aligned whole hourly energy intervals, optionally retaining
only hours wholly within an evidenced binary Event History run/enable phase.
Hourly coincidence is not instantaneous simultaneity. The minimum of the two
hourly energies is an upper bound, never measured self-consumption or exact solar
attribution. Exact attribution stays undefined, including a zero-generation
denominator. Native EFM remains gated by its separate supported contract; no
generic balance engine, storage attribution or unmetered-rest inference is added.

`operating_phases` associates one binary capture history with one numeric source.
It reports energy only for whole hourly records fully contained in known active
phases, or an explicitly unweighted mean of temperature observations inside those
phases. Gaps, partial energy records and exclusive state endpoints remain intact;
association does not establish causation or appliance wiring.

`baseload` reports a time-weighted median of evidenced hourly mean powers for one
selected channel in the local 00:00-05:00 window. Hourly mean power is derived from
verified whole-hour Wh values, not held instantaneous samples. The window may be
overridden by ordered whole `night_start_hour`/`night_end_hour` values (end 24 is
next midnight). Ambiguous/nonexistent local boundaries fail explicitly; repeated
DST hours retain their actual duration. A 24-hour energy extrapolation is labelled
as an estimate and does not establish whole-installation base load. Raw power
samples without an evidenced duration cannot produce this estimate.

For solar-23, convert `estimated_24_hour_energy_Wh / 1000` to estimated daily kWh.
Divide by the mean daily solar energy in kWh over the same selected period to
obtain a dimensionless ratio; multiply by **100** to report a percentage. A
synthetic 100 W baseline gives 2.4 kWh per 24 hours; against 12 kWh/day the ratio
is 0.2 and the percentage 20%, not 0.2%. Missing, zero, negative or non-finite
solar energy leaves the result unavailable. Verify roles, boundaries, units and
coverage before applying the formula; a qualified formula without source values
is not an installation result. The ratio may exceed 100% and must not be clamped
or treated as measured solar supply, self-consumption, independence or savings.

Comparisons reuse the same source context, budgets and worker admission. Outputs
retain per-source provenance and expose a bounded `comparison` result with method,
units, usable intervals and limitations. Explicit raw pages preserve the common
UTC axis and separate original statistic points from observed state segments;
there is no interpolation or proportional energy allocation. Options and computed
comparison evidence participate in cursor proofs.

## Target evidence (2026-10-11)

Loxberry-Test acceptance used the installed aarch64/Python 3.13.5 plugin
0.4.0b4 runtime: authenticated MCP compact reads, two raw pages, invalid timezone,
missing binding, restricted visibility and unauthenticated denial. DE/EN Explorer
checks covered CSS 1280x800 and 390x844 without horizontal overflow or console
warnings/errors. SSH verified runtime hashes, preserved existing file modes,
new-file mode 0644, service health, guide revision 74 and Event History schema 7.
The original empty profile and configured recording sources were preserved.

Native Meter formats did not establish units; native binary sources without
recorded phases correctly returned insufficient evidence rather than zero
activity. Positive numeric results came from isolated installed fixtures,
including indexed phase-local SQLite predecessors and reconnect gaps; they do
not establish native measurement compatibility. Three native compact calls took
2092.77/1826.40/1752.96 ms and returned 2183 bytes each, versus 6429 bytes for the
corresponding raw reader. These are observations, not a controlled regression
benchmark or token measurements. Full performance/token acceptance follows in
the final acceptance PR.

## PR 8 installed comparison acceptance (2026-10-11)

Runtime `2cc6a7b33cf582898dc9b2837c6f4a90e06396d1` was accepted on the
same Loxberry-Test aarch64/Python 3.13.5/plugin 0.4.0-beta.4 environment.
Guarded hot-swap added one module, verified five hashes and preserved existing
0664 modes (new module 0644). Service health, guide 76 and history schema 7
passed. Existing recording and configuration were retained; no profile or
Loxone control writes were used.

Installed isolated fixtures passed ranking (300/100 Wh), PV/load upper bound
(100 Wh), energy inside complete active intervals (100 Wh), and night median
(150 W; 3600 Wh labelled daily estimate). These fixtures prove the installed
calculations, not native device semantics. Real authorized MCP calls exercised
all four new operations, raw continuation, invalid options, unknown bindings,
restricted visibility and unauthenticated denial. Native meter formats remain
unverified and profile roles are absent: comparisons correctly returned
`insufficient_evidence`, with no fabricated totals or attribution.

DE night-load and EN mixed-phase calls completed in the Explorer (2322/2341 ms).
Both languages were inspected at CSS 1280x800 and 390x844; no horizontal overflow
or warning/error console messages occurred. These timings and the three native
energy calls (2234.67/1809.61/1820.62 ms; 2230 bytes each) are bounded observations,
not controlled latency or token acceptance. The corresponding raw call returned
6425 bytes. Bytes are not tokenizer counts.


## Qualitative comparable days (PR 6)

The owner amended the initial numerical-day package on 2026-10-13 to permit a
coarse radiation-class branch, with native solarRadiation interpreted as classes
0-3 only under a labelled owner assumption. `comparable_days.radiation_classes.v1`
compares the same completed hour-start source-point positions and identical class
sequences; no radiation energy, temperature selection or normalized yield is
reported. Numerical source-read/model closeout follows the revised
[technical criteria](solar-history-acceptance.en.md); no empirical plant validation is claimed.

A dedicated structured-weather input and separate weather summary preserve the
released exact scalar source contract. Confirmed weather bindings are projected
through ProfileSources before scalar control/series/state access. The adapter
uses the existing fresh history context and admitted workers, one bounded
reception-index query, latest-eligible-version deduplication and renewed authorization /
configuration checks. It performs no database maintenance or recording writes.
Unexpected values remain in the archive and in bounded diagnostics with trace-
correlated sanitized warning logs. See [method review](comparable-days-method.md)
and [user contract](../user/comparable-days.en.md).


## Confirmed load constraints and observed cycles

The existing operating_phases branch can return comparison.load_cycles for one
confirmed consumer energy statistic (hour granularity) and its confirmed binary
operating-state binding (raw). Optional load_flexibility declarations are checked
through the current profile projection. One fresh admitted context, exact source
reads, native quantity/unit/interval rules and the original limits remain intact.
A profile revision change during calculation prevents output.

Capture indices are retained internally on decoded StateSegment objects without
changing published raw state rows. Only two observed edges inside one continuous
capture establish a complete activity episode. Program identity remains distinct
and user-declared; native locks and planning are explicitly not checked/evaluated.
Cycle energy requires complete whole hourly intervals tiling the episode. Missing
hours, truncation and derived overflow do not create a measured energy result.
Limits are 16 episodes / 128 total profile intervals and the existing 64-KiB
ceiling. See [load flexibility method](load-flexibility-method.md).

Native day/month/year difference aggregates do not qualify as hourly energies.
The runtime retains their explicit raw values when requested, but returns
non_hourly_interval_energy_not_supported rather than relabelling them as one-hour
energy. This applies to the shared energy/energy-comparison adapter as well as
cycle profiles; raw counter and documented hour behavior remain unchanged.

## Conditional retrospective shifts (PR 8)

The additive retrospective_shift operation uses the existing fresh historical
context/admission and past-only interval gate. One confirmed grid_export
statistic with explicit export direction and matching declared measurement
boundary supplies a shared hourly export budget for up to seven confirmed
consumer/operating-state pairs. Explicit boundary confirmation and usable
fingerprint-bound constraints are required. Repeated physical sources fail
rather than being silently deduplicated into a different requested load set.

Complete owner-confirmed cycles, matching duration and complete observed hourly
profiles feed the [reviewed conditional method](retrospective-shift-method.md).
All loads share one budget; original-date windows/completion, DST and continuous
inactive/minimum-off coverage are checked. Missing historical native locks keep
every example conditional and admissibility unproven. No future scheduling,
device operation, solar attribution, self-consumption or saving is established.

comparison.retrospective_shift records the profile revision; every new-operation
comparison rechecks revision before publication, including unavailable results.
The existing final access check, deadline/point/output limits, raw pagination
and legacy branches remain in force. Installed fixtures and genuine source
availability are separate acceptance evidence. #501 is excluded.
