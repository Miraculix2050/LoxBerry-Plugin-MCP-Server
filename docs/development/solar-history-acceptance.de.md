# Lokale Solarhistorie: Abnahmestand vom 18. Oktober 2026

**#509 und #439 bleiben offen.** Der funktionale Zwischenstand ist auf
Loxberry-Test installiert. Es fehlt ein erfolgreicher echter Zahlenvergleich mit
einer Referenz und mindestens drei geeigneten historischen Vergleichstagen.
Fixtures ersetzen diese Abnahme nicht.

## Lieferung und Review

| Stufe | Lieferung | Gate |
| --- | --- | --- |
| 1: Normalisierung | PR #544 gemergt | Reine Berechnung und installiertes begrenztes Fixture geprüft; keine Aussage über physische Historie |
| 2: Aufzeichnung/PVPF | Entwurf PR #549, `1b7bf8e9` | Full-CI grün; Metadata-Refresh-Finding der dritten Review behoben/getestet; PR bleibt gemäß Drei-Runden-Grenze offen |
| 3: Numerischer Laufzeitpfad | Entwurf PR #550, `1f5bd272` | Full-CI auf diesem Commit grün; drei Reviewrunden, veraltete Quellen korrekt behandelt; danach am Ziel gefundene Explorer-Korrekturen getestet und lokal geprüft, keine vierte Review angefordert |
| 4: Integrierte Abnahme | Dieser Bericht | Echte Historie, positiver Vergleich und verbleibende Review-/Messgates ausstehend |

Der lokale Changed-Lauf wählte wegen des Querschnitts Full: 4.326 bestanden,
215 Windows-Plattform-Skips. Fehler durch gleichzeitig aktualisierte Supportmatrix
und lokale CRLF-Zeilenenden wurden separat korrigiert und geprüft. Spätere betroffene
Suiten bestanden, darunter 81 Zahlen-/Kernvertragsfälle, 87 Admin-/Explorerfälle und
80 Explorerfälle. Maßgeblich bleibt die Linux-Full-CI auf dem aktuellen Commit.
Es wurde kein offizielles Paket, Release, Tag oder Produktivstand veröffentlicht.

## Tatsächliche Zielnachweise

- Browser: authentifizierte Admin-Auswahl, Bestätigung, Speicherung und erhaltene
  Konfiguration; DE/EN-Darstellung. Numerischer Wechsel JSON → Formular und Aufruf
  in DE und EN bei gemessenen CSS 1280×800 und 390×844 erfolgreich, ohne horizontalen
  Überlauf. Mobile Quellenbreite sowie Objektvarianten-/Entwurfübernahme wurden
  reproduziert und mit bestehenden Steuerelementen und JSON-Editoren korrigiert.
- MCP: bestätigte Erzeugungszuordnung mit 96 nativen PV-Stundenpunkten über dieselben
  vier vergangenen lokalen Tage. Numerische Anfragen lieferten `ok=true`, fachlich
  jedoch `insufficient_evidence` für fehlende Wetterstunden. Ein laufender Tag
  behielt abgeschlossene Positionen und getrennte nicht verfügbare PVPF-Snapshots.
  Zwei gleichzeitige Analysen lieferten beide das erwartete begrenzte Ergebnis.
- Die unveränderte Klassenmethode meldete `not_found`, weil auf diesem Ziel keine
  aktuelle Wetter-Aufzeichnungsquelle konfiguriert ist. Das belegt die
  Verfügbarkeitsgrenze, keine erfolgreiche echte Klassenabnahme. Unzugängliche
  Zustandsauswahlen und unregistrierte/veraltete Quellen bleiben gesperrt.
  Berechtigungswechsel und Widerruf sind gezielt regressionsgeprüft; Zielrechte
  wurden dafür nicht verändert.
- SSH: Hotswap-Manifeste belegen Hashes, erhaltene Eigentümer/Rechte, Sicherungen
  und Dienst/Health. SQLite V9 mit `quick_check=ok`; bestehende Zustands-/Wetterhistorie
  erhalten. Der echte Abfrageplan nutzt Quelle, Fingerprint und Zeitindex.
  Sanitierte Zähler fanden im geprüften Zeitraum weder Traceback noch Speicher-
  oder Abonnementfehler. Unbeteiligte Konfiguration stimmt mit der gesicherten
  ursprünglichen Konfiguration überein.

Private Manifeste, Messreihen und genaue Zielidentitäten liegen außerhalb dieses
Repositorys im Project-Data-Evidenzverzeichnis des Owners.

## Performance und Grenzen

| Authentifizierter unveränderter Statistikaufruf | Vorher | Nachher |
| --- | ---: | ---: |
| Erster Aufruf nach Explorer-Neuladen | 2.735 ms | 2.239 ms |
| Median aus 20 erfolgreichen seriellen Wiederholungen | 1.678,5 ms | 1.505 ms |
| Inklusives p95 dieser Wiederholungen | 2.268,5 ms | 2.135,85 ms |
| Eingangspunkte pro Antwort | 24 | 24 |
| Kompakte Envelope in UTF-8-Bytes | 4.840 | 4.884 |

Identischer abgeschlossener Tag, Quelle, Parameter und Client; sechs Sekunden
Abstand nach jedem Aufruf. Die zusätzlichen 44 Byte sind native Zählersemantik.
Keine gemessene Regression überschritt die vereinbarte Untersuchungsgrenze.
Der erste Aufruf war nicht erzwungen cache-kalt; eine allgemeine Beschleunigung
ist damit nicht belegt. Frühere Rate-Limit-Antworten sind getrennt erhalten und
aus diesen Messungen ausgeschlossen.

Der neue numerische Negativfall bestand ebenfalls 20 serielle Wiederholungen mit
je 96 Eingangspunkten und 2.900 Byte Antwort. Zwei parallele Analysen zusammen:
3.192 ms. Das misst begrenzte Verarbeitung bei fehlendem Wetter, keinen positiven
Vergleichsfall. Eine unabhängige Datenzugriffs-Phasenzeit ist an dieser MCP-Grenze
nicht sichtbar. Gleiche echte Historie vor/nach Änderung sowie Phasenmessungen
bleiben ausstehend. Antwortbytes belegen weder Tokens noch Kosten oder #501.

## Weiterlaufende Aufzeichnung und offene Gates

Strahlungs- und Temperaturaufzeichnung begann am **18.10.2026 um 12:18:18 UTC**.
Die unabhängige konfigurierte WeatherData-Quelle liefert absolutes W/m²; das
separat identifizierte PV-abgeleitete Signal wird als zirkulär ausgeschlossen.
Aktuelle Strahlungsprobe null, Anbieterfrische unbelegt. Temperatur ist das
konfigurierte Minimum zweier Außensensorreferenzen, kein räumlicher Mittelwert.
Quellenverträge halten diese Grenzen fest. Erfasst werden Quellzustände, keine
kontinuierlichen physikalischen Messungen. PVPF-Snapshots liefen bereits vorher
und bleiben Prognosen. Die PV-Zuordnung beruht auf ausdrücklicher Bestätigung des
Owners zur isolierten Erzeugung, nicht auf fest codierten Namen oder UUIDs.

Die benötigte Testaufzeichnung bleibt aktiviert. Keine Änderung an Produktion
oder Loxone Config. Spätere Abnahme: nutzbare Beobachtungen prüfen, eine Referenz
mit drei geeigneten echten Vergleichstagen auswählen und PV-Ertrag bewerten.
Für #439 zusätzlich direkten/kompatiblen Eigenverbrauch, laufende Tage, Rangfolge
und erklärbare Grenzen mit echter Evidenz prüfen. Ein direkter Eigenverbrauchskanal
oder passende Einspeisebilanz ist hier noch nicht bestätigt.

PVPF bleibt `ready=0`, Energie `-1`, `errorInfo=2`: lesbar, aktuell nicht verfügbar.
Structure File 17.1 S.115 definiert die Zykluszeiten als aktuelle Prognosestunde;
sie belegen keine vollständigen `period`-Energiegrenzen. Der Prognose-Ist-Vergleich
bleibt deshalb `native_period_bounds_unverified`. Der getrennte Stundenadapter
in #542 ist ein späterer qualifizierbarer Integrationspunkt. Keine erzeugte
Prognose oder Aufteilung auf unvollständige Tage. Dieser PVPF-Zustand blockiert
den historischen Vergleich nicht. #510 bleibt für zukünftige Lastplanung offen;
#501 wird nicht als abgeschlossen erklärt.
