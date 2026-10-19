# Bedingte rückblickende Lastverschiebung

Der bestehende Profilablauf bleibt erhalten. Alternativ kann `analysis_context`
(`history_analysis_context.v1`) übergeben werden. Seine Zuordnungen verweisen mit
nullbasiertem `source_index` auf die vorhandene `sources`-Liste und führen keine
weiteren Quellen ein. Jede ausgewählte Quelle benötigt eine eigene Zuordnung.
Eine Anfrage behandelt einen EFM- oder Szenariobereich; unabhängige Versorgungen
bleiben getrennte Anfragen. Exakte sichtbare Quellen benötigen kein gespeichertes
Profil. Profilreferenzen verwenden aktuell bestätigte Rollen, Messgrenzen und
Zyklusregeln, ohne diese zu überschreiben.

Eine `observed`-Last referenziert Verbraucher und Betriebszustand. Ihre gemessenen
Intervallregeln werden ausdrücklich angegeben oder aus einem passenden Profil
übernommen. Beide Zyklusgrenzen, durchgehende Aufzeichnung und vollständige
stündliche Zyklusenergie bleiben für Verschiebungsbeispiele erforderlich.
Übernommene und angegebene Zykluszeitzonen müssen zur Analysezeitzone passen.
`declared_real` verwendet einen bestätigten sichtbaren Verbraucher und einen
vollständigen bestätigten deklarierten Zyklus. `hypothetical` hat keinen
Verbraucher- oder Betriebszustandsbezug und verwendet `scenario_assumption`.
Deklarierte Energie ist ein gleichmäßiges Bedarfsmodell und ergänzt keine
fehlenden Messungen.

Die Exportzuordnung selbst muss `user_confirmed` sein; Szenarioannahmen zu Rolle
oder Richtung begründen kein gemessenes Budget. Gibt ein profilgestütztes reales
Modell eine Betriebsrückmeldung an, muss diese dem gespeicherten Begleiter
entsprechen. Hinweise auf fehlende Rückmeldung gelten nur für tatsächlich
ausgewertete deklarierte Modelle ohne diese Rückmeldung.

`comparison.context_analysis` trennt Zuordnungs-IDs, echte Profilreferenzen,
gemessene Episoden und bedingte Modellzuweisungen. Alle modellierten Lasten
teilen ein gemessenes historisches Exportbudget. Deklarierte Zuweisungen haben
keinen gemessenen Ausgangslauf und belegen keine historische Verbesserung.
Fehlende Aktivitäts-/Mindestpausennachweise und historische Sperren bleiben
Einschränkungen. Netzüberschuss ist nicht automatisch Solarproduktion.
Profile, Aufzeichnungen, Konfiguration und Geräte werden nicht geändert.

`loxone_analyze_history(operation="retrospective_shift")` berechnet, wie viel
gemessenen Export ein vollständig beobachteter Lastzyklus zu einer anderen
vergangenen Zeit möglicherweise aufgenommen hätte. Jedes Beispiel ist bedingt:
fehlende historische Sperrinformation bedeutet `admissibility="not_proven"`.
Es ist kein Schaltplan, keine Betriebserlaubnis, kein gemessener Eigenverbrauch,
keine belegte Solarzuordnung und keine Netto- oder finanzielle Einsparung.

## Eingaben bestätigen

Lesen Sie das aktuelle Anlagenprofil. Wählen Sie eine bestätigte
`grid_export`-Energiestatistik mit `declared_direction="export"` und bis zu sieben
bestätigte Verbraucherstatistiken mit nutzbaren Lastgrenzen und ihren genau
zugeordneten bestätigten binären Betriebszuständen. Export und Verbraucher
benötigen dieselbe ausdrücklich erklärte Messgrenze. Bestätigen Sie die
Vergleichbarkeit erst nach Prüfung ihrer Bedeutung und Ausschluss doppelter
oder überlappender Verbraucherzähler. Das ist Ihre Erklärung; das Tool prüft
keine elektrische Verdrahtung.

Bestätigen Sie `cycle_identity="user_confirmed_cycle"` und
`energy_profile_origin="observed_intervals"`. Ein erklärter Wh-Gesamtwert liefert
kein Stundenprofil. Die Zustandshistorie muss aktiviert sein und den relevanten
Zeitraum abdecken. Nutzen Sie `hour` für Energie und `raw` für Zustände. Erforderlich
sind `loxone:read` und `loxone:history`.

```json
{
  "operation": "retrospective_shift",
  "sources": [
    {"binding_id": "my-export", "granularity": "hour"},
    {"binding_id": "my-consumer", "granularity": "hour"},
    {"binding_id": "my-operating-state", "granularity": "raw"}
  ],
  "start": "2026-10-11T00:00:00+02:00",
  "end": "2026-10-12T00:00:00+02:00",
  "timezone": "Europe/Berlin",
  "comparison_options": {"comparable_boundaries_confirmed": true}
}
```

Ersetzen Sie alle Kennungen durch bestätigte sichtbare Bindungen. Der Zeitraum
muss vergangen sein und höchstens 31 lokale Tage berühren. Wiederholte physische
Quellen werden abgelehnt. Ändert sich das Profil während der Analyse, lesen und
prüfen Sie erneut; wiederholen Sie nicht blind.

## Ergebnis einordnen

Prüfen Sie `comparison.retrospective_shift`, `profile_revision`, Einschränkungen,
die Anzahl ausgeschlossener Zyklen und Ausgabebegrenzungen. Benötigt werden
vollständige beobachtete Aktivitätsgrenzen, passende Laufdauer, keine
Mindestlauf-/Auszeitabweichungen und vollständige native stündliche Wh-/kWh-
Energieintervalle. Fehlende Stunden, Zyklen am Abfragerand, Aufzeichnungsneustarts,
unbekannte Zustände und Tages-/Monats-/Jahresaggregate qualifizieren sich nicht.

Alternative Beispiele erhalten den ganzen zusammenhängenden Zyklus, auch wenn
Unterbrechung erlaubt ist. Erklärte Fenster und Abschlusszeit beziehen sich auf
das ursprüngliche lokale Startdatum. Mehrdeutige oder nicht existierende
Sommerzeitgrenzen werden ausgeschlossen. Die ganze Alternative und die Auszeit
auf beiden Seiten benötigen durchgehend beobachtete Inaktivität innerhalb einer
Aufzeichnungsphase. Tatsächliche Aktivität und andere hypothetische Zyklen
derselben Last dürfen sich nicht überlappen.

Alle Beispiele teilen ein Exportbudget; dieselbe Exportenergie wird nicht
mehrfach vergeben. Die Methode wählt die höchste verbleibende bedingte Aufnahme, dann den
frühesten Start und eine feste Bindungs-/Zyklusreihenfolge.
`conditional_export_absorption_upper_bound_wh` und die Stundenanteile sind
bedingte Obergrenzen. Speicher, geänderte Reaktionen anderer Lasten und Vorgänge
innerhalb einer Stunde bleiben unbekannt.

Jedes Beispiel nennt `native_lock_status="not_checked"`,
`admissibility="not_proven"` und `historical_native_lock_coverage_missing`.
Beschreiben Sie es nicht als erlaubten oder empfohlenen Gerätebetrieb. Maximal
16 Beispiele und 128 Stundenanteile werden ausgegeben. Die Suche ist auf 4.096
Alternativen begrenzt; bei Überschreitung erfolgt keine Vergabe aus einer
Teilsuche. Ausgabebegrenzungen bleiben sichtbar und belegen keinen global
optimalen Schaltplan.
