# Qualitativ vergleichbare Tage

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
historische Quellen und Intervallsemantik; sie bleiben in #439 offen.
