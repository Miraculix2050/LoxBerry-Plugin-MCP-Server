# Conditional future load planning (#440 / #510)

The owner approved one narrow read-only tool because future planning combines
forecast and load evidence without changing the past-only history contract.
Transport is in the PVPF adapter, orchestration in load_planning_runtime, pure
search in load_planning, and MCP registration/error mapping in load_planning_tools.
No new store, background service or forecast model is introduced.

Inputs select an exact visible native PVPF, future offset-aware interval (at most
72 hours), IANA timezone and 1–16 unique confirmed consumer bindings. Scenarios
explicitly supply baseload and storage reservation as W, constant or aligned
hourly values, with declared/estimated origin. At hourly resolution W times one
hour is Wh. Missing scenario hours are excluded. Selected flexible consumers must
not also be included in baseload. No battery discharge or charge optimizer is added.

Complete cycle identity is user-confirmed. A declared duration/energy pair creates
a uniform estimated cycle. An observed model selects the newest complete eligible
cycle from existing hourly energy and operating phases in seven completed local
days by default (1–31 configurable). The existing semantic, boundary and complete-
cycle checks are reused. Incomplete data never manufactures a cycle or recorder.

One cycle is assigned per selected consumer. Candidates begin at source hour
boundaries and remain contiguous, within declared weekday/windows and latest
completion. Ambiguous or nonexistent local window boundaries are excluded. Whole
cycles satisfy their declared minimum run duration. Future external activity,
initial minimum-off clearance and complete native locks remain explicit conditions.
Supported known current locks exclude a load; unknown is never interpreted clear.
Hourly energy allocation assumes within-hour availability, including estimated
uniform demand for partial-hour cycles, and does not establish instantaneous power.

Every consumer shares one residual hourly PV budget after baseload/storage.
Greedily choose greatest remaining conditional PV coverage, then earliest local
completion deadline, start and binding ID. Recompute coverage after each assignment.
Never allocate one unit of PV twice. This is a deterministic heuristic, not an
optimal control algorithm or a device schedule. Return conditional coverage and
additional grid energy separately from measured self-consumption or savings.

Forecast is read once. Historical sources are read outside search, operating
phases deduplicated by exact source. Bound historical input to 100,000 points,
candidate evaluations to 100,000, output to 16 assignments / 64 KiB and total work
to 30 seconds. History and future planning share two admitted analysis tasks;
cancellation retains admission until the worker terminates. Profile revision,
visibility and source identity are checked before publication. No shared cache
may substitute for caller authorization.

Acceptance uses deterministic arithmetic/contracts, source-call counters,
negative/changed inputs and cancellation tests, then a reserved Loxberry-Test
Hotswap with Browser/MCP/SSH checks. Fixtures are distinct from a real available
PVPF forecast and a comparison with measured production. The native PVPF read
returned 72 available hours on Loxberry-Test after the #586 adapter fix. On
25 October 2026 the owner approved closing #510 on software/technical acceptance:
the three measured production intervals after forecast capture and real
single/competing-consumer planning were not performed and are no longer closeout
gates. This does not establish empirical forecast accuracy, real consumer
validation, measured savings or operating permission. Runtime qualification and
conditional planning semantics are unchanged. #440 retains its separate
retrospective technical closeout. Independent #501 measurement remains excluded.
