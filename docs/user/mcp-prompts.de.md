# Lesende MCP-Promptvorlagen

Clients mit Unterstützung für MCP-Prompts können über `prompts/list` einen
Arbeitsauftrag auswählen und über `prompts/get` mit Parametern abrufen. Neben den
zwei [KNX-Vorlagen](knx-mcp.de.md) stehen acht Analysevorlagen bereit. Der Abruf
führt keine Datenabfrage, Analyse oder Änderung aus und erteilt keine Rechte.
Er liefert eine Textnachricht für den anschließenden KI-Workflow. Die vorhandenen
Tools bleiben in Clients ohne Prompt-Unterstützung nutzbar.

| Name | Zweck | Parameter neben `language` und `detail` |
| --- | --- | --- |
| `lighting_naming_review` | Sichtbare Lichtnamen und belegte Quellstimmungen prüfen | optional `room_uuid`, `focus=all\|names\|moods` (Default `all`) |
| `presence_light_association` | Explizite Projektverbindungen zwischen Präsenz und Licht erklären | optional `room_uuid` |
| `current_state_summary` | Isttemperaturen oder belegte Betriebszustände zusammenfassen | optional `focus=temperature\|operating_state` (Default `temperature`), `room_uuid` oder `control_uuid` |
| `temperature_history_summary` | Temperaturstichproben eines Zeitraums auswerten | genau ein `binding_id` oder `control_uuid`; `start`, `end`, `timezone` erforderlich |
| `solar_daily_report` | Verfügbare Energiekomponenten eines lokalen Tages berichten | `date`, `timezone` erforderlich; optional Produktions-`binding_id` |
| `comparable_day_review` | Qualitative Strahlungsklassen-Peers auswählen | `reference_date`, `start`, `end`, `timezone` erforderlich |
| `consumer_pv_comparison` | Verbraucher mit PV zeitlich vergleichen oder nach Energie ordnen | `start`, `end`, `timezone` erforderlich; optional `focus=overlap\|ranking` (Default `overlap`), `consumer_binding_id` |
| `energy_period_report` | Qualifizierten Wochen-/Monatsbericht erstellen | `period=week\|month`, enthaltenes `date`, `timezone` erforderlich |

Alle Parameter sind Strings. `language=en|de` wählt die Antwortsprache (Default
`en`), `detail=summary|findings` den Umfang (Default `summary`). Die technische
Rezeptnachricht bleibt englisch. `summary` bevorzugt kompakte Übersichten;
`findings` verlangt die erforderlichen begrenzten Folgeseiten. Keine willkürliche
Seitenobergrenze belegt Vollständigkeit. Höchstens 50 Datensätze pro Antwort.

Kennungen müssen aus der aktuellen autorisierten Discovery oder einem aktuell
bestätigten Profil stammen. UUID-Selektoren erlauben 1–128 ASCII-Buchstaben,
Ziffern, Unterstriche und Bindestriche; Bindungskennungen höchstens 64.
`control_uuid` erhält außerdem den vorhandenen Vertrag für maximal 128 Zeichen
lange Runtime-Unter-Control-IDs: UUID-Präfix und unveränderter opaker Suffix
wie `…/AI1`. Dieser Schlüssel ist kein Dateipfad und kein Beleg für ein
Elternobjekt; er bleibt als JSON-Wert unverändert. Die Validierung belegt nur
die Syntax, keine Existenz, Sichtbarkeit oder Rolle.
Namen, Freitextanweisungen, Pfade und URLs sind keine Selektoren. Fehlende oder
mehrdeutige Ziele werden im anschließenden Ablauf gezielt geklärt. Bei einer
Temperatur-Control-Auswahl muss dort eine passende veröffentlichte Istserie
gewählt werden; eine Profilbindung muss aktuell bestätigt und nutzbar sein.

Datumsparameter verwenden `YYYY-MM-DD`. `start`/`end` sind RFC3339-Zeitpunkte mit
Sekunden und Offset oder `Z`; der Bereich ist halboffen und umfasst höchstens
31 lokale Tage. `timezone` ist ausdrücklich eine IANA-Zeitzone. Wochen beginnen
montags, Monate am Monatsersten. Tages- und Periodengrenzen folgen dieser
Zeitzone, einschließlich 23-/25-Stunden-Tagen. Laufende Perioden bleiben
unvollständig, zukünftige Perioden liefern keinen historischen Bericht. Größere
Quellmengen müssen innerhalb bestehender Grenzen getrennt bearbeitet werden.

Beispiel für `prompts/get` (MCP-Parameterobjekt):

```json
{
  "name": "solar_daily_report",
  "arguments": {
    "date": "2026-10-17",
    "timezone": "Europe/Berlin",
    "language": "de",
    "detail": "summary"
  }
}
```

Für einen Temperaturbericht lautet der Name `temperature_history_summary`, etwa
mit `binding_id="room_temperature"`, `start="2026-10-17T00:00:00+02:00"`,
`end="2026-10-18T00:00:00+02:00"`, `timezone="Europe/Berlin"` und `language="de"`.
Die beispielhafte Bindungskennung durch eine tatsächlich bestätigte ersetzen.

## Evidenz und Grenzen

Die Rezepte laden `core` und nur die benötigten Skill-Module, sofern sie für diese
Serverrevision noch nicht geladen sind. Fehlende Module, Fähigkeiten, Quellen,
Profile oder Rechte führen zu einer qualifizierten Teilantwort oder begründeter
Nichtverfügbarkeit. Bestehende Leserechte werden bei den tatsächlichen Aufrufen
erneut geprüft. Ein Loxone-Login erteilt keine LoxBerry-Rechte; der Abruf bestätigt
keine Vergleichbarkeit von Messgrenzen und erlaubt keine Schreiboperation.

- Lichtnamen und Quellstimmungen belegen weder vollständige Szeneninventare noch
  physische Lichtkreise, Szenenrollen oder professionelle Lichtplanung (#441).
  Präsenzzuordnungen brauchen explizite Projektpfade; Raumgleichheit genügt nicht.
  Bei `room_uuid` werden zuerst sichtbare Raum-Controls gesucht und deren genaue
  UUIDs auf Projektobjekte abgebildet; die Projektsuche hat keinen Raumfilter.
  Mehrdeutige Zuordnungen und raumübergreifende Endpunkte bleiben sichtbar.
- Temperaturmittel sind Stichprobenmittel, keine zeitgewichteten Mittelwerte.
  Ist- und Solltemperaturen sowie Aktualität und Abdeckung bleiben getrennt.
- Solarberichte bleiben Komponentenberichte. Native EFM-Kalenderansichten zeigen
  laufende Perioden und füllen keine historischen Lücken. Unbelegte
  Eigenverbrauchs-, Speicher- oder Restlastanteile bleiben unbekannt.
- Vergleichstage verwenden ausschließlich die vorhandene qualitative
  Strahlungsklassenmethode. Das gemeinsame lokale Stundenfenster ist vor dem
  Aufruf ausdrücklich zu wählen. Klassenannahme, Warnungen, Lücken und
  Sommerzeitausschlüsse bleiben sichtbar. Die separat implementierte numerische
  Vergleichsmethode und ihre technischen Quellenanforderungen gehören nicht
  zu dieser qualitativen Vorlage; sie liefert keine kausalen Erklärungen.
- PV-/Verbraucherüberlappung belegt keine exakte Solarzuordnung. Für Rankings
  muss der Nutzer vergleichbare Messgrenzen und ausgeschlossene Eltern-/Kind-
  Überlappungen ausdrücklich bestätigen; die Auswahl der Vorlage genügt nicht.
- Lastverschiebungs- und Zukunftsplanung gehören nicht zu diesen Vorlagen.
  Die getrennten bedingten Abläufe aus #440 und der
  [PVPF-Zukunftsplanung](pv-planning.de.md) behalten ihre eigenen Voraussetzungen.

[Support und Grenzen](analysis-support.de.md) bleiben maßgeblich. Die Zuordnung
zu den bestehenden Szenarien erweitert keine früheren Abnahme- oder
Kompatibilitätsaussagen. Automatisierte SDK-/Wire-Tests belegen den Protokollvertrag,
keine universelle Unterstützung durch Chat-Clients oder neue Geräteabnahme.
Die Expansion bleibt bei höchstens 4 KiB UTF-8, der gesamte Katalog bei 16 KiB.
