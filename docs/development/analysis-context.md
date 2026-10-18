# Request-local energy context

The context resolver separates native EFM membership from owner-confirmed physical
associations and request-local scenario assumptions. The caller cannot submit
`native_efm` provenance: only the server produces it from configured participants.
Names, uniqueness, shared categories and matching power values are not membership.

One request describes one energy budget. Independent supplies require separate
requests; these are scenarios, not coordinated schedules or energy reservations.
Up to four PVPFs may cover a confirmed common supply only when their asset sets
partition the declared production coverage. These declarations do not independently
prove physical coverage. An aggregate and its included individual forecast cannot
both contribute. Unknown or conflicting coverage prevents combined calculation.

Real request-local loads require a freshly visible native control and a confirmed
complete declared cycle. They need no dedicated meter. Hypothetical loads have no
native source, remain explicitly hypothetical and cannot satisfy real acceptance.
Profile references reuse existing confirmed models without changing the profile.
EFM reports accept only configured participants. Additional loads require an
explicit scenario; they never become EFM members through a user declaration.

Incomplete EFM topology, ambiguous references and selected parent/child meters
fail closed. Native membership alone does not establish measurement boundaries,
units or signs. Existing version-gated adapters retain their evidence boundaries.

The context is an optional alternative selection in `loxone_plan_loads(options)`.
It cannot be mixed with legacy forecast/binding selection. The legacy path retains
its result type; the context path returns `conditional_context_planning.v1`.
Multiple forecasts share one authenticated transport and one final structure read.
Legacy tools and profile stores retain their contracts.
Follow-ups: #557 history, #558 weather/solar, #559 profile reuse;
existing #357, #441 and #444 own their respective EFM, lighting and prompt domains.

## Deutscher Überblick

Der Anfragekontext trennt native EFM-Zuordnungen, bestätigte Anlagenzuordnungen
und ausdrückliche Szenarioannahmen. Eine Anfrage verwendet genau ein gemeinsames
Energiebudget. Mehrere PVPFs benötigen bestätigte, überschneidungsfreie Abdeckung.
Reale Lasten ohne eigenen Zähler sind mit bestätigtem vollständigem deklariertem
Zyklus möglich; hypothetische Lasten bleiben getrennte Szenarien. Profile werden
nur gelesen. Fehlende Verdrahtung eines nur visualisierten PVPF ist für sich kein
Konfigurationsfehler. Der Kontext ist eine optionale alternative Auswahl in der
bestehenden Lastplanung; Altaufrufe und Profilformate bleiben erhalten. #440/#510 bleiben bis zur
positiven realen Prognose- und Verbraucherabnahme offen.
