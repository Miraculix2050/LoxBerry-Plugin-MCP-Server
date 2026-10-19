# Analysis semantic evidence

Rules extend the existing pure state resolver. A control name, category,
user-declared profile role or adjacent state never authorizes a decoder.

Structured weather profile bindings use `installation_weather.raw_fields.v1` as
a provenance/fingerprint rule only. Their exact advertised actual/forecast UUID
and selected field are checked in the caller's fresh structure; only that field's
documented presentation format participates. This rule verifies neither numeric
units nor solar-radiation encoding, and cannot fully identify provider/station/site
changes. PV geometry/capacity/shading remain explicitly confirmed user declarations
attached to a production source; they never become technical decoder evidence.

Primary source: [Loxone Structure File 17.1](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf),
dated 2026-08-06, 168 pages, SHA-256
`97bbc5ec79c8479c0f2f561a55780a764a518fe420d11fd2fc26979fc41e5f23`.
Page references below are one-based PDF pages. Each rule records document and
rule versions; absent firmware evidence remains absent.

| Exact type/state | Meaning and value gate | Source/version | Evidence limit |
| --- | --- | --- | --- |
| `IRoomControllerV2.tempActual` | Finite numeric current temperature | pp.73,76; V2 available since Miniserver 10.0 | Explicit complete Celsius/Fahrenheit format required for a known unit. |
| `IRoomControllerV2.tempTarget` | Finite numeric target temperature | pp.73,76; same gate | Target temperature does not establish heating activity. |
| `InfoOnlyDigital.active` | Numeric zero/one indication | p.72; Structure File 17.1 | No physical appliance, contact or power role is inferred. |
| `Hourcounter.active` | Numeric zero/one counter activity | pp.70–71; Structure File 17.1 | Counter activity does not establish measured energy. |
| `Dimmer.position` | Finite numeric current position | p.60; Structure File 17.1 | No percent scale, fixed 0–100 range, binary activity predicate or physical output proof. |

Authorized read-only type evidence on Loxberry-Test confirmed the exact V2 type
and both temperature states, plus `InfoOnlyDigital.active`. Its V2 format is
`%.1f°`: this proves neither Celsius nor Fahrenheit. Hourcounter coverage is
document/fixture based until an authorized target specimen is tested. Evidence
does not claim support for every firmware version or unknown future variants.

Missing values retain the supported descriptor with unavailable interpretation;
nonfinite numbers, booleans, strings and undocumented binary codes are invalid.
Unknown units remain unknown. Generic analog format strings and arbitrary
`Switch.active` states receive no new technical inference. Current observation
quality remains separate from semantic evidence, and historical coverage is not
inferred from current state readability.

### Activity interpretation follow-up (#485)

The pinned PDF above was rechecked, including visual page inspection. Page 60
defines Dimmer position and says the off command sets it to zero. This establishes
position meaning, not the converse predicate that every zero proves off, nor a
positive-value threshold for activity. Only the position decoder is added.
Pages 136–137 identify `Switch.active` as the switch state and describe on/off
commands; they do not explicitly establish its numeric response encoding. The
review therefore retains `Switch.active` as unknown rather than copying the
InfoOnlyDigital rule. Similar observed values or commands are not extra evidence.

Compact reads retain their default `include_semantics=false`, original raw values,
authorization and byte/count limits. Warnings and field descriptions distinguish
delivery coverage from semantic evidence. Unknown/partial/invalid interpretations
remain explicit; known position/temperature evidence grants no generic activity
predicate. Guides and the existing state-summary prompt require current values
and an exact appropriate rule, separating logical activity/inactivity from unknown
and from physical appliance operation. Offline protocol/decoder tests cannot prove
that a model will follow the guidance; bounded new answer checks remain separate.

## Energy Manager generation contracts (#436)

The [separate native-energy matrix](native-energy-results.md#energy-manager-context)
uses official Structure File 17.1 pp.61–63. Gen-1 load metadata and cached IDs
are not temporally joined. Gen-2 documented global kW/percent units do not supply
load pwr/ppwr units, signs, measurement boundaries or meter proof. Parameter edit
locks do not establish general load locks; activation does not prove a physical
cycle. Cached detailed load decoding requires fresh visible Loxone administration.
Generation-specific rulesets version new source references; unchanged existing
families retain their released fingerprints. Source-shape fixtures do not prove
device/firmware compatibility. No historic load-lock or PV-forecast source is added.

## Counter and series evidence (prepared before PR 5 decoding)

| Exact source | Proven fields | Source/version | Limit |
| --- | --- | --- | --- |
| `statisticV2.groups.accumulated=true` | Cumulative readings; differencing is intended | Structure File 17.1 pp.19–21 | Reset/rollover correction is not specified. False/absent does not prove interval energy. |
| V2 `raw/all` | Recorded numeric samples, UTC Unix timestamps | pp.22,24 | Sampling mode does not prove continuous coverage or a hold/interpolation rule. |
| V2 `diff/hour,day,month,year` | Sum of recorded differences; hourly example timestamps the interval start | pp.23–24 | No general timestamp convention for all modes; no proportional splitting of partial intervals. |
| `Meter.actual/total/totalNeg` | Power or flow, and meter readings; formats belong to each exact channel | pp.105–106; optional subtype fields since 13.01 | Unit formats alone do not prove energy, physical direction or measured versus calculated origin. Reset-to-zero is supported; observed decreases still need evidence. |
| Meter bidirectional/storage | Runtime subtype tokens are documented | pp.105–106 | Grid versus storage roles and channel sign must not be guessed from names. EFM bindings remain gated by #363/#364/#436. |
| Legacy statistic output | Explicit state UUID, local-Miniserver seconds since 2009 epoch | pp.18–19 | The existing UTC-shaped projection does not establish timezone conversion or DST uniqueness; retain this limitation. |

Current official [meter](https://www.loxone.com/dede/kb/zaehler/),
[bidirectional meter](https://www.loxone.com/dede/kb/zaehler-bidirektional/)
and [storage meter](https://www.loxone.com/dede/kb/zaehler-speicher/) pages
were checked on 2026-10-11. They describe configurable units and input-dependent
measurement/calculation. They supply no version-bound installation input proof.
No new EFM value decoder, XML alias, physical scaling or sign mapping is accepted.

For exact Meter channels plus complete W/kW/Wh/kWh datapoint formats, the resolver
can expose the configured engineering quantity/unit as `structure_declared`.
This combined channel/unit evidence is not physical calibration or input-topology
proof. Exact IRCv2 temperature series similarly use their own explicit format;
conflicting explicit current/series units remain unknown. Legacy series retain
their existing fingerprint shape; V2 rule/recording metadata changes require
profile review. Warm statistic payloads are keyed by fresh technical source
metadata as well as caller identity and query, so raw/diff changes cannot reuse
an incompatible payload. Fresh authorization remains mandatory on cache hits.


## EFM self-consumption statistics (#439/#509)

Rule `EFM.series.totalSelfConsumption.v1` applies only to the exact EFM output
`totalSelfConsumption`, valid accumulated StatisticV2 metadata and an exact native
Wh/kWh format (printf or decimal-place pattern). It reuses the existing StatisticV2
Unix interval-start/difference-sum contract. The official Energy Flow Monitor
knowledge base defines native self-consumption; the exact output/format contract
was additionally sampled read-only on Loxberry-Test: 48 hourly native differences,
format `0,000kWh`, accumulated=true. The owner confirmed this source's association
and intended self-consumption coverage on 19 October 2026, including previously
stored PV energy. That declaration is installation evidence, never a global
physical-boundary inference. The public article does not enumerate this wire field;
the exact native channel mapping is retained as an explicit decoder rule backed by
that representative metadata/sample, rather than attributed to the PDF.

This is an EFM-computed counter, not an independent physical meter or a new storage
balance. Boundary, direction, physical measurement and reset uncertainty remain
explicit. `direct_observed` retains its compatible source-series method name; the
metric carries `native_efm_calculation_not_independent_meter`. Unknown formats,
other fields/types and legacy statistics are excluded. Money, power and percentage
channels cannot inherit this qualification. Profile ruleset changes still invalidate
old source bindings; request-local confirmed associations avoid implicit profile
mutation. No genuine weather-peer acceptance follows from synthetic weather tests.

Numerical debug phases use the existing request trace and logger:
`numerical_solar_read`, `numerical_statistic_read`, `numerical_energy_preparation`,
`numerical_calculation` and `numerical_response`. Read durations include each
authorized/worker call's waiting overhead; they are not pure database CPU time.
Read records report only point counts and timing, response records only count/bytes.
No source identity, value, extra query, cache or default logging change is added.
