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
The shared resolver reads a profile only for explicit references and accepts only
currently confirmed projections. Exact declarations cannot override a profile
reference. Request aliases remain separate from persistent binding identities.
Publication rechecks installation, selected source metadata, profile revision and
all referenced operating companions, including changes with an unchanged revision.
These checks do not replace fresh transport authorization. Unrelated saved
bindings are not consulted to assign physical associations to profileless calls.
Follow-ups: #557 history, #558 weather/solar, #559 profile reuse;
existing #357, #441 and #444 own their respective EFM, lighting and prompt domains.

## Technical acceptance boundary

On 25 October 2026 the owner approved #510 closeout on software/technical
acceptance, including a real native PVPF read with 72 available hours on
Loxberry-Test. Comparison with three production intervals measured after forecast
capture and real single/competing-consumer planning were not performed and are
no longer closeout gates. This decision does not qualify hypothetical loads as
real consumers or establish empirical forecast accuracy, measured savings or
operating permission. Runtime evidence requirements remain unchanged. #440 has
its own retrospective technical closeout.

## Deutscher Überblick

Der Anfragekontext trennt native EFM-Zuordnungen, bestätigte Anlagenzuordnungen
und ausdrückliche Szenarioannahmen. Eine Anfrage verwendet genau ein gemeinsames
Energiebudget. Mehrere PVPFs benötigen bestätigte, überschneidungsfreie Abdeckung.
Reale Lasten ohne eigenen Zähler sind mit bestätigtem vollständigem deklariertem
Zyklus möglich; hypothetische Lasten bleiben getrennte Szenarien. Profile werden
nur gelesen. Fehlende Verdrahtung eines nur visualisierten PVPF ist für sich kein
Konfigurationsfehler. Der Kontext ist eine optionale alternative Auswahl in der
bestehenden Lastplanung; Altaufrufe und Profilformate bleiben erhalten. Am
25. Oktober 2026 hat der Eigentümer die technische Abnahme als Abschlussgrundlage
für #510 bestätigt, einschließlich eines nativen Abrufs mit 72 verfügbaren
Prognosestunden auf Loxberry-Test. Der Vergleich mit drei nach Prognoseabruf
gemessenen Produktionsintervallen und die Planung mit realen Einzel- bzw.
konkurrierenden Verbrauchern wurden nicht durchgeführt und sind keine
Abschlussbedingungen mehr. Daraus folgen keine empirisch belegte Prognosegüte,
reale Verbraucherabnahme, gemessene Einsparung oder Betriebsfreigabe.
Laufzeitanforderungen bleiben unverändert. #440 behält seinen unabhängigen
retrospektiven technischen Abschluss.

Der gemeinsame Resolver liest Profile nur bei ausdrücklichen Referenzen und
verwendet ausschließlich aktuell bestätigte Zuordnungen. Anfrageannahmen können
Referenzen nicht überschreiben. Vor Ergebnisausgabe werden Anlagenidentität,
Quellenmerkmale und alle verwendeten Verbraucher- und Betriebszustandsbindungen
erneut geprüft. Transportzugriffe benötigen weiterhin frische Autorisierung.
