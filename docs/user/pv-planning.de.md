# Native PV-Produktionsvorhersagen

Einen sichtbaren `PvProductionForecast` mit `loxone_find_controls` suchen und
`loxone_read_controls(targets=[{"control_uuid":"<gefundene UUID>"}], native_result_view="pv_forecast")` aufrufen.
Dieser Lesezugriff benötigt `loxone:read`, keine lokale LoxBerry-Dateifreigabe.
Steuerung und Konfiguration werden nicht verändert. Für EFM-Ansichten gelten
weiterhin deren eigene Voraussetzungen.

Der native Befehl `getForecasts` liefert stündliche kWh für heute, morgen und
übermorgen. Das Ergebnis normalisiert diese in Wh mit Unix-Stundengrenzen.
Der Adapter akzeptiert das direkte JSON-Prognoseobjekt sowie bisher unterstützte
`LL`-Antworten. Andere Befehle behalten ihre Prüfung des Antwortumschlags;
Fehlerantworten und ungültige Prognosedaten werden weiterhin abgewiesen.
Aggregierte Zustände bleiben getrennt. Zustandszeitstempel verwenden die
Loxone-Epoche 2009, Prognosezeitstempel Unix. Fehlende Stunden werden nicht ergänzt.

Verfügbarkeit erfordert einen bereiten Baustein, Fehlerstatus null, einen höchstens
drei Stunden alten Prognosezeitstempel und nutzbare Stundenwerte. Ready=0 und
aggregierte Werte -1 bedeuten keine nutzbare Vorhersage. ErrorInfo ist eine native
Bitmaske: Bit 1 steht für WeatherServiceError, Bit 0 für InternetError. Das belegt
weder ein abgelaufenes Abonnement noch einen bestimmten Netzwerkfehler.
Veröffentlichungszeitpunkt des Anbieters und Prognosesicherheit fehlen.
Native Vorhersagen sind Modellschätzungen und berücksichtigen keine
Wechselrichterbegrenzungen; mit realer Produktion vergleichen.

PVPF benötigt einen aktiven Loxone-Wetterdienst und die konfigurierte installierte
kWp-Leistung. Fehlende Einrichtung erklären; nicht automatisch aktivieren,
abonnieren oder umkonfigurieren. Native Prognosen sind von der bestehenden
W/m²-Wetterorientierung getrennt.

## Bedingte zukünftige Lastplanung

Fehlgeschlagene Prognoseabrufe unterscheiden Zeitüberschreitungen, Protokollfehler,
abgewiesene Anfragen, Verbindungsfehler und nicht verfügbaren Autorisierungsspeicher
durch feste bereinigte Meldungen. Die Fehlerkategorie bleibt
`temporarily_unavailable`; Meldungen enthalten weder rohe Serverantworten noch
Zugangsdaten. Das gilt für native Prognoseabrufe und den Planer. Ein Verbindungs-
oder Protokollfehler belegt keine fehlende Prognosekonfiguration. Fehlgeschlagene
Lesezugriffe werden nicht automatisch wiederholt.

Bei aktiviertem Debug-Logging benennt ein begrenztes Laufzeitereignis den
fehlgeschlagenen Schritt (Snapshot, Tokenzugriff, Sitzungsaufbau, Prognosebefehl,
Strukturprüfung oder Prognosedekodierung) und eine feste Ursachenkennung.
Verbindungsursachen unterscheiden geschlossene WebSockets, fehlgeschlagenen
Verbindungsaufbau, Quell-IP-Sperren und einen ungültigen Antwortumschlag;
nicht zugeordnete Ursachen bleiben unbekannt. Die `trace_id` entspricht dem
MCP-Fehler. Nutzdaten, Exception-Texte, Steuerungsidentitäten und Zugangsdaten
werden nicht protokolliert. Auf Info-Level entfallen diese Details.

`loxone_plan_loads(options=...)` benötigt `forecast_control_uuid`, zukünftige
`start`/`end` mit UTC-Offset, `timezone` und bis zu 16 `consumer_binding_ids` aus
dem bestätigten Installationsprofil. `baseload` und `storage_reserve` jeweils
mit `origin="user_confirmed"` oder `"user_estimate"` und entweder `constant_w`
oder `hours=[{"start":<Unix-Stunde>,"power_w":<W>}]` angeben. Reserve null ist
ein ausdrückliches Szenario und belegt keine fehlende Batterie. Ausgewählte
flexible Verbraucher nicht zusätzlich in die Grundlast einrechnen. Fehlende
Szenariostunden werden nicht verplant.

Jede Last benötigt bestätigte Flexibilität und `cycle_identity="user_confirmed_cycle"`.
Vollständige gemessene Zyklen werden aus den letzten sieben abgeschlossenen
lokalen Tagen ausgewählt (`history_days` 1–31); dies benötigt aktivierte
loxone:history und vorhandene lokale Aktivitätshistorie. Alternativ werden
bestätigte deklarierte Zyklusenergie und Dauer als gleichmäßiges geschätztes
Lastprofil verwendet. Keine Aufzeichnung wird automatisch aktiviert.

Pro Verbraucher wird ein zusammenhängender Zyklus in das gemeinsame stündliche
PV-Budget nach Abzug von Grundlast und Speicherreserve eingeordnet. Bestätigte
Fenster und Fertigstellungsgrenzen werden eingehalten. Bekannte unterstützte
aktuelle Sperren schließen eine Last aus. Zukünftige Sperren, andere Aktivität
und die Freigabe nach Mindestpause bleiben vor dem Betrieb zu bestätigende
Bedingungen. Stundenbudgets setzen Energieverfügbarkeit innerhalb der Stunde
voraus und belegen keine ausreichende momentane Leistung. Batterieentladung
wird nicht verplant. Annahmen, Gründe ungeplanter Lasten und Grenzen beachten.

Maximal 72 Prognosestunden, 16 Lasten, 100.000 historische Punkte, 100.000
Kandidatenprüfungen und 64 KiB Ausgabe innerhalb von 30 Sekunden. Historien-
und Zukunftsanalyse teilen zwei Plätze. Pro Plan ein PVPF-Prognoseabruf; die
Suche führt keine Quellzugriffe aus. Ergebnisse beschreiben bedingte PV-Abdeckung
und zusätzliche Netzenergie, keine gemessene Einsparung, optimale Planung oder
Betriebsfreigabe.

## Tool Explorer

### Anfragekontext statt dauerhaftem Profil

Alternativ zur bisherigen Auswahl `analysis_context` in `options` angeben;
`forecast_control_uuid` und `consumer_binding_ids` dann weglassen. Zeitraum,
Zeitzone, Grundlast und Speicherreserve bleiben erforderlich. Der Kontext enthält
`scope` (ausgewählter `efm` mit `monitor_uuid` oder ausdrücklich beschriebenes
`scenario`), `assets`, `forecasts` und `loads`. Genau ein gemeinsames Energiebudget
gilt pro Anfrage; getrennte Anfragen sind keine abgestimmten Fahrpläne.

Jede Anlage erhält eine anfragebezogene `asset_id`, Beschreibung, optional eine
`production_control_uuid` und `association_origin`. Jede Prognose benennt ihre
`control_uuid`, abgedeckte `asset_ids` und `coverage_origin`. Mehrere Prognosen
(maximal vier) benötigen bestätigte gemeinsame Versorgung und überschneidungsfreie
Abdeckung (`user_confirmed`); sonst ist nur eine ausdrücklich angenommene
Szenarioprognose möglich. Nur gemeinsame vollständig verfügbare Stunden werden
addiert. Ein nur visualisierter PVPF ist ohne Verdrahtung nicht automatisch falsch.

Lasten haben `load_id` und `kind`: `profile` verwendet `binding_id`; `real`
verwendet eine sichtbare `control_uuid` und einen bestätigten deklarierten `cycle`;
`hypothetical` verwendet ausschließlich einen angenommenen Zyklus ohne Geräte-ID.
`cycle` enthält Zeitzone, Fenster, Fertigstellung, Dauer, Unterbrechbarkeit,
Mindestlauf-/Pausenzeiten, `cycle_energy_wh`, `origin` und Begründung. Deklarierte
Energie wird gleichmäßig verteilt und nicht als Messung ausgegeben.

EFM-Zuordnungen werden nur aus nativen Teilnehmern bestätigt. Zusätzliche Lasten
gehören in ein Szenario. Native Zugehörigkeit beweist keine physische Messgrenze.
Unbekannter Steckdoseninhalt verlangt eine konkretere Gerätebeschreibung, nicht
einen erfundenen Verbraucher. Anfragen speichern keine Profilbestätigungen.
Der neue Ergebnistyp `conditional_context_planning.v1` enthält einzelne Prognosen,
Abdeckung, Herkunft, Lastmodelle und offene Zuordnungen. Hypothetische Lasten
erfüllen keine reale Verbraucherabnahme. Neue Kontextanfragen sind auf 64 KiB
Eingabe begrenzt; alle bisherigen Rechen-/Ausgabegrenzen bleiben erhalten.

Im authentifizierten Explorer zuerst PVPF suchen, danach
`loxone_read_controls` mit einem Ziel und `native_result_view=pv_forecast` wählen.
Für `loxone_plan_loads` den JSON-Editor für das strukturierte `options`-Objekt
und die bestätigten Profilkennungen verwenden. Die Szenarien ausdrücklich
angeben; die Oberfläche wählt keine Speicherreserve und schaltet kein Gerät.
Bedingte Fenster zeigen UTC-Grenzen, PV-Abdeckung und zusätzliche Netzenergie;
das vollständige Ergebnis behält Annahmen, Bedingungen und Gründe ungeplanter
Lasten. Eine nicht verfügbare Quelle wird sichtbar erklärt. Die neuen Tools
benötigen nach dem Plugin-Update keine zusätzliche Konfigurationsänderung.

Bei aktuellem nativem `ready=0` wird `not_ready` ohne Abruf nicht verfügbarer Stundenwerte zurückgegeben. Autorisierung und Quellensichtbarkeit werden weiterhin geprüft.

Eine unbekannte oder veraltete aktuelle native Sperre wird ausdrücklich als `native_current_lock_unresolved` ausgewiesen; sie gilt nicht als bestätigt aufgehoben.

Beispiel nur für `options.analysis_context`; UUID ersetzen und Zeitraum sowie
Grundlast/Speicherreserve in `options` ergänzen. Die Zahlen sind reine Annahmen:

```json
{
  "scope": {"kind": "scenario", "description": "Example only",
            "common_supply_origin": "scenario_assumption"},
  "assets": [{"asset_id": "pv", "description": "Explicit example coverage",
              "association_origin": "scenario_assumption"}],
  "forecasts": [{"control_uuid": "<visible PVPF UUID>", "asset_ids": ["pv"],
                 "coverage_origin": "scenario_assumption"}],
  "loads": [{"load_id": "example", "kind": "hypothetical", "cycle": {
    "timezone": "Europe/Berlin",
    "windows": [{"weekdays": [0,1,2,3,4,5,6], "start": "09:00", "end": "17:00"}],
    "latest_completion": "17:00", "duration_seconds": 3600,
    "interruptible": false, "minimum_run_seconds": 0, "minimum_off_seconds": 0,
    "cycle_energy_wh": 1000.0, "origin": "scenario_assumption",
    "rationale": "Illustrative complete job; no real appliance claim"
  }}]
}
```
