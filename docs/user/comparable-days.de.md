# Vergleichbare Tage

## Ein expliziter Standort und mehrere Quellen

Optional ordnet `analysis_context.day_context` die vorhandenen `sources` über
`source_index` zu; der Kontext wählt keine zusätzlichen Quellen aus. `site`
enthält einen bestätigten `site_id`, `timezone` und
`association_origin="user_confirmed"`. Die Zeitzone muss der expliziten
Tool-Zeitzone entsprechen. Breiten- und Längengrad sind gemeinsam optional und
dürfen bestätigten PV-Parametern nicht widersprechen. Unabhängige Standorte
werden in getrennten Aufrufen untersucht.

`weather` wählt genau eine Quelle je `quantity` (`radiation`, `temperature`,
`forecast`). Die Zuordnungen verwenden `role="weather_context"` und bestätigte
Herkunft. Weitere angegebene Wetterquellen werden weder gemittelt noch nach Namen
ausgewählt. Die qualitative Methode nutzt die ausgewählte tatsächliche strukturierte
Strahlungsquelle; die numerische Methode behält registrierte Solarbeobachtungen
und native Decoder bei. Prognosen bleiben getrennte Prognosen. Strahlung neben
Produktionsdaten erfordert `radiation_independence_origin="user_confirmed"`;
dieselbe PV-Control darf ihre eigene unabhängige Strahlungsevidenz nicht liefern.

`assets` und `production` beschreiben mit `source_index`, `asset_ids` und
`coverage_origin="user_confirmed"` die Produktionsabdeckung. Diese muss die
deklarierten Anlagen überschneidungsfrei aufteilen: Ein Aggregat für Dach und
Garage darf nicht neben einem enthaltenen Einzelzähler beitragen. Mehrere
Produktionsquellen benötigen einen bestätigten gemeinsamen Versorgungsbereich.
Summiert werden nur qualifizierte vollständige Stunden, die in **jeder**
beitragenden Quelle vorliegen. Fehlende Daten werden weder Null noch Teilsumme
der Gesamtanlage. `production_sources` weist Qualifikation und vollständige
Stunden jeder Quelle aus.

Verschiedene Statistikreihen desselben Controls können Produktion und direkten
Eigenverbrauch oder Einspeisung als getrennte Messgrößen liefern. Dieselbe exakte
Quelle oder dieselbe Energierolle zweimal auf diesem Control wird abgewiesen.
Native Überschneidungsprüfungen gelten weiterhin zwischen Controls. Bei einer
Produktionsquelle reicht die bestehende bestätigte PV-minus-Einspeisung-Bilanz;
die zusätzliche Bestätigung des gemeinsamen Versorgungsbereichs gilt für mehrere
zusammengefasste Produktionsquellen.

Exakte stündliche Statistikselektoren funktionieren ohne Profil. Produktion,
direkter Eigenverbrauch und Netzeinspeisung benötigen bestätigte Zuordnungen;
Rollen belegen keine Einheiten, Mengen oder Messgrenzen. PV minus Einspeisung
behält zusätzlich die ausdrückliche Bilanzbestätigung, Einspeiserichtung und
passende Grenzen aller Produktionsquellen bei. Native EFM-Mitgliedschaft gilt
für alle Energiebeiträge. Ergebnisse geben Standort und Zuordnungen wieder und
kennzeichnen bestätigte Abdeckung als nicht unabhängig geprüft. Vor der Ausgabe
werden Sichtbarkeit, Installation, Quellenmerkmale und verwendete Profilrevisionen
erneut geprüft. Die bestehenden Abnahmegates #439/#509 bleiben offen.

## Numerische Wettervergleiche

Explizit `comparable_day_options.method="numerical"` mit `reference_day` wählen.
Vorgaben: Stunden 0–24, saisonaler Abstand ≤30 Tage, Strahlungsenergieabweichung
≤15 %, Temperaturabweichung ≤3 °C. Strengere Optionen sind möglich. Alle Kandidaten
verwenden das feste Referenzfenster; laufende Referenztage nur abgeschlossene
Stunden. Fehlende Daten verkleinern es nicht; mehrdeutige Zeitumstellungsstunden
werden ausgeschlossen.
Das angeforderte Ende begrenzt zusätzlich die abgeschlossenen Referenzstunden.
Bestätigte Profilrollen belegen keine stündliche Energiesemantik: Unqualifizierte
Statistiken bleiben unverfügbar; qualifizierte Reihen mit fehlenden Werten weisen
unvollständige Abdeckung aus.

Unabhängige Strahlungs- und Außentemperaturquellen im Adminbereich mit belegter
Einheit, Abtastperiode und bestätigter Anlagenzuordnung registrieren. Aufzeichnung
aktivieren; vorhandene Daten bleiben nach Deaktivierung lesbar. Auswahl jeweils:
`{"source_kind":"solar_observation","control_uuid":"<Baustein-UUID>","state_uuid":"<Wert-UUID>"}`.
Aufrufer können keine Evidenzregeln oder Einheiten vorgeben. Namen bestimmen
keine Rolle; Quellen dürfen fehlen. Aus dem bewerteten PV-Ertrag abgeleitete
Strahlung ist als Vergleichsbasis zirkulär und ungeeignet.

PV-Auswahl über `{"binding_id":"<bestätigte production-Zuordnung>","granularity":"hour"}`
mit dokumentierter stündlicher Energiestatistik. Eine `self_consumption`-Zuordnung
liefert direkten PV-Eigenverbrauch. Alternativ bestätigt
`pv_export_balance_confirmed=true` ausdrücklich PV minus Einspeisung ohne
Speicherentladung und andere Erzeugung. Zusätzlich müssen bestätigte
Profil-Bilanzgrenzen übereinstimmen und die Einspeiserichtung deklariert sein.
Kein Speicherbilanzmodell; negative Bilanzen werden nicht auf null begrenzt.

Als direkter Kanal wird auch die native EFM-Statistik `totalSelfConsumption`
unterstützt, wenn sie als akkumulierter StatisticV2-Kanal exakt Wh oder kWh
ausweist. Stundenwerte sind native Differenzsummen, keine vom Plugin berechnete
PV-/Speicherbilanz. Die Anlagenzuordnung muss bestätigt werden; der Eigenverbrauch
ist eine EFM-Berechnung und kein unabhängiger physischer Zähler. Andere EFM-Kanäle,
Währungen, Leistungseinheiten und unbekannte Formate erhalten diese Bedeutung nicht.
In allen historischen Vergleichen benötigt dieser Kanal die Rolle `self_consumption`;
er darf nicht als Erzeugung, Verbrauch eines Verbrauchers oder Einspeisung umgedeutet werden.

W/m²-Quellzustände werden trapezförmig zu geschätzten Wh/m² integriert: keine
Extrapolation oder Lücken über der doppelten Abtastperiode, maximal 60 Minuten.
Temperatur verwendet den nächsten aufgezeichneten Zustand innerhalb von
60 Sekunden zum Stundenbeginn, zusätzlich begrenzt durch die Abtastperiode.
Der größte tatsächliche Versatz wird ausgegeben. Das belegt keine kontinuierliche
physikalische Messung. Wetterähnlichkeit wählt Vergleichstage aus; es entsteht
kein zusätzliches physikalisches Modell zur PV-Normalisierung.

Ergebnisse erklären Auswahl, Ausschlüsse, Toleranzen, Abdeckung und Einrichtung
fehlender Quellen. Rangfolge nach Wetterähnlichkeit. Ertrag und Eigenverbrauch
liefern Paare und eine Mediangruppe mit mindestens drei vollständigen Tagen.
PV-Abweichungen strikt unter −20 % kennzeichnen Prüfkandidaten, keine Fehlerdiagnose.
Eine getrennte Rangfolge zeigt die stärksten negativen Abweichungen. Bei Null-Basis
entsteht kein Verhältnis.

Optionales PVPF nutzt denselben Selektor mit `state_uuid=null`. Die letzten acht
aufgezeichneten Snapshots bleiben separater Prognosekontext mit Erfassungs-,
Prognose- und nativen Zykluszeiten. Structure File 17.1 S.115 definiert die
Zykluszeiten als aktuelle Prognosestunde, nicht als Grenzen der gesamten
`period`-Energie. Der Istvergleich bleibt `native_period_bounds_unverified`.
Für Tageshorizonte fehlt hier eine unabhängig bestätigte native Zeitzone; sie werden
nicht auf unvollständige Tage verteilt. Ein späterer dokumentierter Stundenadapter
kann exakte Gültigkeitsintervalle liefern; nur zuvor erfasste Prognosen dürfen dann
mit vollständigen Istintervallen verglichen werden. Keine Wetterauswahl aus Prognosen.

Jede eindeutige Quelle wird pro Zeitraum einmal gemeinsam frisch autorisiert gelesen.

Bei aktivierter Debug-Diagnostik liefern korrelierte Phasenmeldungen die Zeiten
für Solarhistorienzugriff, Statistikzugriff, Energieaufbereitung und Berechnung
sowie Punktzahlen und Antwortgröße. Zugriffszeiten enthalten Warte- und
Berechtigungsprüfung des jeweiligen Aufrufs; sie sind keine reinen SQL-Zeiten.
Die Diagnostik erzeugt keine zusätzlichen Datenabrufe und gibt keine Quellwerte aus.

Grenzen: 16 Quellen, 100.000 Punkte, 31 lokale Tage, 30 Sekunden, zwei Analysen,
64 KiB. Aufzeichnung erzeugt keine frühere Historie. Echte mehrtägige Abnahme bleibt
Voraussetzung für den Abschluss von #509 und #439.

## Qualitative Strahlungsklassen

`loxone_analyze_history(operation="comparable_days")` vergleicht aufgezeichnete
Wetter-Quellenpunkte anhand von Strahlungsklassen. Das ist ein grober Vergleich,
keine Strahlungsenergierechnung oder wetterbereinigte Ertragsbewertung.

Der Wetterservice dokumentiert Klassen 0 (sehr niedrig), 1 (niedrig), 2 (moderat)
und 3 (hoch). Die Herkunft der Klassenzuordnung steht ausdrücklich im Ergebnis.
Ein Rohwert zwischen 0 und 3 allein belegt keine native Zuordnung; eine unbekannte
Zuordnung liefert `insufficient_evidence`. Die native 0-3-Zuordnung ist eine Owner-Annahme vom 13. Oktober 2026
und bleibt ausdrücklich als nicht technisch verifiziert gekennzeichnet. Unerwartete Werte bleiben in der
Historie und erscheinen als begrenzte Diagnostik mit Quellenzeit, numerischem
Rohwert und Grund. Sie werden nicht als gültige Klassen verwendet. Das Tool warnt
die KI, den Nutzer zu informieren, und erzeugt einen sanitisierten Logeintrag mit
der Trace-ID der Antwort. Die Warnung bedeutet, dass die Daten nicht zur
angenommenen Zuordnung passen; sie belegt keinen Gerätefehler. Siehe die
[offiziellen Klassenbeschreibungen](https://www.loxone.com/dede/kb/weather-service/).

Richten Sie in Admin die aktuelle Wetterquelle und ihr Feld `solar_radiation` ein.
Die Aufzeichnung ist ausdrücklich zu aktivieren und erzeugt keine frühere
Historie. Lesen erfordert frisch bestätigte `loxone:read`-/`loxone:history`-Rechte
und aktivierte Historie. Wählen Sie genau eine aktuell sichtbare und konfigurierte
Quelle oder eine aktuell bestätigte Anlagenprofilbindung für dieses Feld der
aktuellen Wetterquelle. Prognosen werden ausgeschlossen.

```json
{
  "operation": "comparable_days",
  "sources": [{
    "source_kind": "structured_weather",
    "state_uuid": "<UUID der aktuellen Wetterquelle>",
    "stored_mode": "actual"
  }],
  "start": "2026-10-01T00:00:00+02:00",
  "end": "2026-10-08T00:00:00+02:00",
  "timezone": "Europe/Berlin",
  "comparable_day_options": {
    "reference_day": "2026-10-07",
    "method": "radiation_classes",
    "start_hour": 10,
    "end_hour": 14,
    "maximum_seasonal_days": 30
  }
}
```

Ersetzen Sie den UUID-Platzhalter durch die Kennung einer autorisierten Quelle.
Der Zeitraum muss vergangen und nicht leer sein und darf höchstens 31 lokale
Tage berühren. Referenz und Kandidaten verwenden dasselbe feste lokale
Stundenfenster; bei laufenden Referenztagen nur abgeschlossene Stunden. Jede
ausgewählte Stunde braucht ihren Quellenpunkt am Stundenanfang. Fehlende
Positionen verkleinern kein Vergleichsfenster. Mehrdeutige oder nicht existierende
Sommerzeitpositionen werden ausgeschlossen. Gleiche Klassenfolgen werden nach
saisonalem Abstand und Datum sortiert, mit Auswahlgründen und Ausschlüssen.

Der Reader verwendet eine begrenzte Abfrage über den Empfangszeit-Index und
behält die zuletzt empfangene zulässige Version je Quellenpunkt. Empfang und Quellenposition
müssen im angeforderten Zeitraum liegen; ältere Quellenpunkte und spätere
Empfänge füllen ihn nicht rückwirkend auf. Empfangs-/Aufzeichnungsabdeckung
belegt keine kontinuierlichen Messungen. Anbieter- oder Stationswechsel können
unerkannt bleiben. Die Ausgabe ist kompakt; diese Operation bietet keine
Rohdatenseiten oder Cursor. Bestehende skalare Operationen bleiben unverändert.

Diese Klassenmethode verwendet keine 15-Prozent-Strahlungstoleranz,
Strahlungsenergie, temperaturbasierte Auswahl, Ertragsnormierung, Defektdiagnose
oder Eigenverbrauchsrechnung. Helligkeit in Lux ist zusätzlicher Kontext, keine
allgemeine Umrechnung in W/m2. Numerische Vergleiche benötigen separat belegte
historische Quellen und Intervallsemantik über die explizite numerische Methode oben.
