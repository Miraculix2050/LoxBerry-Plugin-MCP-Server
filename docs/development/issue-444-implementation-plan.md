# Umsetzung von #444: parametrisierte MCP-Prompts

Umsetzungsabgleich: Der unten dokumentierte Plan bleibt der Lieferumfang.
Zwischenzeitlich auf `master` ergänzte numerische Solarvergleiche und bedingte
Planungsfunktionen behalten ihre eigenen Verträge und Abnahmegrenzen; die hier
vorgesehene Vergleichstage-Vorlage bleibt ausdrücklich qualitativ. Diese Auswahl
behauptet nicht, dass die getrennten Funktionen unimplementiert seien.

## Ziel und Lieferumfang

Die vorhandene MCP-Prompt-Infrastruktur um einen kleinen Katalog für Beleuchtung,
Zustände und Solaranalysen erweitern. Vorlagen formulieren einen lesenden
Arbeitsauftrag und verweisen auf vorhandene Tools und Skill-Module. Ihr Abruf
führt keine Analyse aus und erteilt keine Berechtigung.

**Planungsannahme:** Zunächst die heute verfügbaren Abläufe liefern. Teilantworten
sind zulässig, sofern die Vorlage ihren begrenzten Umfang ausdrücklich beschreibt.
Vollständige Lichtplanung, numerische Wetterbereinigung und Lastverschiebungsplanung
bleiben bei #441, #439 beziehungsweise #440.

## Vorlagen und öffentliche Schnittstelle

Die beiden bestehenden KNX-Prompts unverändert erhalten. Folgende Namen additiv
über `prompts/list` und `prompts/get` anbieten:

| Prompt | Zweck und Parameter |
| --- | --- |
| `lighting_naming_review` | Sichtbare Lichtfunktionen und belegte Quellstimmungen auf Benennungskandidaten prüfen; optionale `room_uuid`, `focus=all\|names\|moods`. |
| `presence_light_association` | Präsenz-Licht-Zuordnungen aus expliziten Projektverbindungen erklären; optionale `room_uuid`. Raumgleichheit allein belegt keine Verbindung. |
| `current_state_summary` | Aktuelle Isttemperaturen oder belegte Betriebszustände zusammenfassen; `focus=temperature\|operating_state`, optionale `room_uuid` oder `control_uuid`. |
| `temperature_history_summary` | Temperaturstatistik für einen ausdrücklich gewählten Zeitraum; genau ein `binding_id` oder `control_uuid`, dazu `start`, `end`, `timezone`. |
| `solar_daily_report` | Belegte Energiekomponenten eines lokalen Tages berichten; `date`, `timezone`, optionale bestätigte Produktionsbindung `binding_id`. Keine zugesicherte vollständige Eigenverbrauchsbilanz. |
| `comparable_day_review` | Verfügbare qualitative Wetterklassen-Peers vergleichen; `reference_date`, `start`, `end`, `timezone`. Keine numerisch wetterbereinigte Ertragsbewertung oder Kausalerklärung. |
| `consumer_pv_comparison` | Gemessene Verbraucher und PV zeitlich vergleichen; `start`, `end`, `timezone`, `focus=overlap\|ranking`, optionale `consumer_binding_id`. |
| `energy_period_report` | Qualifizierten Wochen- oder Monatsbericht aus verfügbaren Komponenten erstellen; `period=week\|month`, `date` als enthaltenes lokales Datum, `timezone`. |

Gemeinsame optionale Parameter: `language=en|de` mit Default `en`,
`detail=summary|findings` mit Default `summary`. Sämtliche Parameter werden als
MCP-Strings übertragen.

- Fehlende Zielauswahl führt zu einem Auftrag zur gezielten Auflösung sichtbarer
  beziehungsweise bestätigter Quellen. Mehrdeutige Ziele werden beim späteren
  Ablauf geklärt.
- Gelieferte widersprüchliche Selektoren und ungültige Argumente werden beim Abruf
  zurückgewiesen.
- Datumsangaben sind ISO-Kalenderdaten; `start`/`end` sind RFC3339-Zeitpunkte eines
  halboffenen Intervalls. IANA-Zeitzonen sind ausdrücklich erforderlich.
- Kalenderwochen beginnen montags. Monatsberichte folgen Kalendermonaten.
  Bestehende Analysegrenzen bleiben maßgeblich; größere Quellenmengen werden in
  getrennten begrenzten Aufrufen bearbeitet.

## Implementierung und Verhalten

- Die Registrierung in `src/mcpserver/prompts.py` erweitern; neue Rezepte in einem
  eigenen Analyse-Prompt-Modul bündeln. Vorhandene KNX-Validierungsmuster
  übernehmen, ohne KNX-Verträge zu verändern.
- Strikte, begrenzte Selektoren und feste Auswahlwerte verwenden. Keine freien
  Zusatzanweisungen, Befehle, Pfade oder URLs akzeptieren. Fehler bleiben
  sanitisiert; Argumentinhalte erscheinen nicht in Logs.
- Jede Expansion liefert eine kompakte Textnachricht mit Ziel, Auswahl, Zeitraum
  und benötigten Skill-Modulen. `core` sowie nur die einschlägigen Module laden
  lassen; bereits für dieselbe Serverrevision geladene Module wiederverwenden.
- Abruf und Auflistung bleiben vollständig datenfrei. Verfügbarkeit, Profilstatus
  und frische Berechtigungen werden erst durch den ausführenden Client mit den
  bestehenden Lesefunktionen geprüft. Der Katalog variiert nicht je nach
  Gerätebestand oder Benutzerprofil.
- Rezepte verlangen Quellen, betrachteten Zeitraum, Aktualität, Abdeckung,
  Auslassungen und die Trennung von Beobachtung, Berechnung, Schätzung und
  Hypothese. Unbestätigte Rollen, unbekannte Semantik und fehlende Quellen bleiben
  ausdrücklich offen.
- Native EFM-Perioden nicht für gestern oder beliebige historische Zeiträume
  verwenden. Historische Komponenten über bestehende bestätigte Quellen
  auswerten. Verbraucher-Rankings benötigen weiterhin die ausdrückliche
  Vergleichbarkeitsbestätigung.
- Schema-Katalog, Explorer-Referenz, Paketprüfung, Smoke-Client und
  Changed-Testauswahl um die neuen Prompts ergänzen. Keine neue interaktive
  Explorer-Auswahloberfläche einführen.
- DE/EN-Anleitungen und Beispiele synchron ergänzen. Skill-Revision und
  entsprechende Referenzen aktualisieren, soweit der Skill-Inhalt geändert wird.

## Tests und Abnahme

- SDK-Vertragstests für vollständige Auflistung, Argumentmetadaten, sämtliche
  Vorlagen und beide Sprachen; bestehende KNX-Verträge unverändert prüfen.
- Nachweisen, dass List/Get weder Quellen lesen noch Profile laden,
  Berechtigungen erweitern oder Funktionen ausführen.
- Negativtests für unbekannte Argumente, falsche Typen, ungültige
  UUIDs/Bindungskennungen, widersprüchliche Selektoren, Datumsbereiche, Zeitzonen,
  überlange Eingaben und Injection-Versuche; keine Eingabewerte in Fehlern oder
  Logs.
- Vorhandene Wire-Tests für frisches OAuth und verweigerten Zugriff erweitern.
  Fehlende Module, Fähigkeiten, Profile sowie partielle Evidenz im
  Szenariokatalog als qualifizierte Ergebnisse abdecken.
- Größenbudgets festlegen: höchstens 4 KiB UTF-8 je Expansion und 16 KiB für den
  gesamten Prompt-Katalog. Das bisherige KNX-spezifische Listenbudget
  entsprechend aufteilen.
- Schema-/Explorer-Referenz und Paketinhalt prüfen; installierten Smoke-Client
  für alle registrierten Namen erweitern. Client-Unterstützung nur für tatsächlich
  geprüfte Clients dokumentieren.
- Während der Umsetzung Changed-Auswahl zunächst mit `--plan` kontrollieren.
  Finale Revision mit Full lokal oder gleichwertigem grünem CI-Lauf auf demselben
  Commit absichern. Browser- oder Geräteabnahme nur bei tatsächlich berührter
  Grenze.

## Lieferung und Abschlusskriterien

Ein zusammenhängender Feature-PR mit Verknüpfung zu #444, synchroner
Dokumentation, Tests und Review. Keine Release-Veröffentlichung als Bestandteil
dieser Änderung.

Vor Abschluss die acht Vorlagen gegen den versionierten Szenariokatalog prüfen
und ihre belegten Grenzen dokumentieren. Verbleibende vollständige Fachfunktionen
ausdrücklich mit #439, #440 und #441 verknüpfen. #444 erst schließen, wenn dieser
begrenzte Lieferumfang im Review als Erfüllung akzeptiert ist; andernfalls bleibt
es mit einer konkreten Restliste offen.
