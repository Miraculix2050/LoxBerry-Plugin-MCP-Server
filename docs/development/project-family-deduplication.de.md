# Vorarbeiten zur Projekt-Deduplizierung zwischen OAuth-Familien (#379)

- Stand: Vorbereitung einer Untersuchung; das Produktverhalten bleibt unverändert.
- Umfang: OAuth-Familien und `sps.LoxCC`; keine Abhängigkeit von der Umsetzung von #239.
- Zielevidenz: In diesen Vorarbeiten nicht erhoben.
- [English version](project-family-deduplication.md)

## Bestehender Pfad und Grenze der Wiederverwendung

`LoxoneClient.download_project()` lädt ausschließlich die feste Projektressource
mit Loxone-Token und Benutzer der anfragenden Familie. Größe und Zeit sind
begrenzt; Weiterleitungen und automatische Wiederholungen sind ausgeschlossen.
Service-Zugangsdaten werden nicht eingesetzt. `ProjectService._load()` prüft
Scope, Familie und Tokenbestätigung, holt den Familientoken und serialisiert
Ladevorgänge über ein Semaphore. Der Cache-Schlüssel lautet
`(miniserver_id, identity_id, family_id)`; ein gleicher Marker erlaubt ausschließlich
die Wiederverwendung dieses Eintrags. Bei einem Miss folgen Download, Verarbeitung
im separaten `process_project()`-Subprozess, erneute Autorisierung und Markerprüfung.
Der Graph-Cache ist auf acht Einträge und 128 MiB konservative Größenberechnung
begrenzt; Familienansichten und Abfragen separat auf acht Einträge und 64 MiB.

`ProjectService.view()` verlangt die Übereinstimmung von Runtime-Subjekt und
Familie. Mapping und Abfragen vergleichen zusätzlich die Struktur des Aufrufers.
Die frische sichtbare Struktur wird im Tool-/Runtime-Pfad beschafft, nicht in
`load_snapshot()`. Ein Benchmark dieser Methode beweist deshalb weder frische
Sichtbarkeit noch MCP-Autorisierung. Widerruf beendet Ladevorgänge der betroffenen
Familie und entfernt deren Cache/Ansichten; Schließen entfernt sämtliche Inhalte.
Bestehende Worker-Tests decken Markerfehler, Projektwechsel, Widerruf und Grenzen
ab. `test_project_family_baseline.py` ergänzt Downloadisolation zweier Familien
einschließlich überlappender Aufrufe, abgelehnten Download, ungültigen Zugriff auf
einen warmen Familiencache, unabhängigen Widerruf und getrennte Ansichten.

Der untersuchte Code liefert keinen zuverlässigen unabhängigen Nachweis der
Projektleseberechtigung ohne Projektdownload. Authentifizierter Programmmarker
und sichtbare Struktur sind dafür kein Nachweis. Bis passende Ziel-/Protokollevidenz
vorliegt, muss jede neue Familie vor einem möglichen gemeinsamen Inhaltszugriff
selbst autorisiert herunterladen. Bestehende Cache-Hits sind eine Ausgangsbasis,
kein Beleg, dass sämtliche künftigen Berechtigungsgates aus #379 bereits erfüllt sind.

## Reproduzierbare lokale Ausgangsmessung

Im Repository mit Python 3.13 und Entwicklungsabhängigkeiten ausführen:

```powershell
$env:PYTHONPATH = 'src'
python tools/benchmark_project_families.py --nodes 1000 --families 2 --samples 3 --warm-calls 3
```

Das Werkzeug nimmt ausschließlich Anzahlen entgegen und erzeugt synthetisches
LoxCC mit Literalblöcken im Speicher. Es liest weder Projektdateien, Zugangsdaten,
Konfiguration noch Netzwerk. Die Ausgabe enthält feste Bezeichnungen, einen
synthetischen Hash und numerische Messwerte.

- Die Parsermessung im eigenen Prozess umfasst Entpacken, Decodieren und
  Graphaufbau sowie Python-Allokationen, CPU- und Laufzeit. IPC und Spitzen-RSS
  des separaten Workers werden nicht erfasst. Tracing beeinflusst die Laufzeit;
  nur Läufe mit gleicher Tracing-Konfiguration vergleichen.
- Die Servicephasen verwenden den unveränderten echten Worker mit simuliertem
  Download, Marker und Autorisierung. Pro Familie werden Cold-/Warm-Aufrufe,
  Downloadanzahl/-bytes und Worker-Laufzeit erfasst. Cold verarbeitet einmal;
  Warm verwendet den eigenen Graph wieder. Jede neue Familie lädt und verarbeitet.
- Tracemalloc im Elternprozess umfasst Mocks, Phasenberichte, IPC und Graphen;
  diese Werte sind kein Prozess-RSS. Die Cache-Größenberechnung ist eine
  konservative Schätzung. Worker-Laufzeit umfasst Start und Serialisierung und
  ist keine Parser-CPU-Zeit. Frische Struktur, Mapping, Abfrage und Cursor sind
  nicht Teil dieser Zeitmessung.
- Dies ist ausschließlich eine Vorher-Messung. Sie beweist weder Bytegleichheit
  zwischen echten Nutzern noch Berechtigungsverhalten, Ziellatenz oder Nutzen
  einer Optimierung.

## Möglicher Entwurf unter Evidenz- und Reviewvorbehalt

Nach dem erfolgreichen autorisierten Download jeder Familie werden die exakten
Antwortbytes gehasht. Unveränderlicher geparster Inhalt könnte nach Miniserver,
SHA-256 und expliziter Parser-/Modellversion adressiert werden. Der bestehende
Bundle-Digest hasht sortierte entpackte Mitglieder und ist eine andere Domäne;
er darf nicht stillschweigend als Beleg gleicher Antwortbytes dienen.
Autorisierungsepoche/-referenz, sichtbare Struktur, Mapping, Abfrage, Cursor,
Ratenlimits und Token bleiben je Familie getrennt. Kein neuer Cache und kein
persistenter Store darf rohe Projektbytes behalten.

Eintrags- und Bytegrenzen müssen auch Graphen berücksichtigen, die Ansichten und
aktive Anfragen halten. Nur Parsing darf nach unabhängigen autorisierten Downloads
zusammengeführt werden. Abbruch oder Widerruf eines Wartenden darf weder Arbeit
einer anderen gültigen Familie abbrechen noch eine neue Referenz ermöglichen.
Nach dem Warten und vor Ausgabe sind Familie und Version erneut zu prüfen.
Widerruf entfernt ihre Referenz sofort; Dienstende entfernt alle Referenzen.
Versions-/Identitätswechsel oder fehlgeschlagene frische Nachweise erlauben keinen
Rückfall auf alte Inhalte. Diese Vorarbeiten liefern weder gemeinsamen Cache noch
Berechtigungsprobe oder produktive Instrumentierung.

## Zielmessprotokoll (offen)

Explizit autorisierte Test-Grants und kontrollierte Berechtigungs-/Projektänderungen
verwenden. Ziel reservieren; Revision, Parserversion, anonyme Fallbezeichnungen,
Stichprobenanzahl, Arbeitslast, Aufwärmung, Cache-Zustand und Konkurrenz erfassen.
Projektbytes, Benutzernamen, Token, URLs und Installationskennungen weder behalten
noch veröffentlichen.

Zwei Grants eines Nutzers sowie Grants verschiedener Nutzer vor und nach
Sichtbarkeitsänderung, verweigertem Projektlesen und Projektupdate vergleichen.
Nur bereinigte Hashes, Bytegrößen und numerische Zeiten/Zähler aufzeichnen.
Frische Sichtbarkeitsprüfung, autorisierten Download, Parser-CPU/-Laufzeit,
Mapping/Abfrage, Gesamtlatenz und Eltern-/Worker-Speicher getrennt erfassen.
Passende Cold-, Warm- und konkurrierende Wiederholungen einschließlich Fehlern
erheben. Unsichere Autorisierungsfehler nicht automatisch wiederholen.

Zuerst den unveränderten Dienst messen. Ein späterer experimenteller Entwurf braucht
vergleichbare Arbeitslast, Rechte, Revisionen, Stichproben und Konkurrenz für
Vorher/Nachher. Eine Schwelle für wesentlichen Nutzen vor Auswertung vereinbaren;
hier werden weder eine Schwelle noch positive Zielergebnisse behauptet.

## Sicherheits- und Lifecycle-Matrix

| Fall | Erforderlicher Nachweis vor produktiver Wiederverwendung |
| --- | --- |
| Zwei Familien, gleiche Bytes/Marker | Jede lädt mit eigenen Rechten; erst danach gemeinsames Parsing/Inhalt |
| Gleicher Marker, Sichtbarkeit entfernt | Frische Aufruferstruktur entfernt Controls; Mapping/Abfrage/Cursor übernehmen keine fremde Sichtbarkeit |
| Gleicher Marker, Projektlesen verweigert | Kein Inhalt über fremde Referenz; Berechtigung auch bei Cache-Hits nachweisen |
| Widerruf während Download/Parsing/Warten | Kein Ergebnis/Referenz für widerrufene Familie; andere gültige Familie bleibt unabhängig |
| Projektwechsel während Verifikation | Inkonsistente Version ablehnen; kein alter Ersatz |
| Identitäts-/Miniserverwechsel | Keine Referenz, Ansicht oder Cursor überschreitet die Grenze |
| Marker-/Strukturfehler, Bestätigung nötig, Auth busy, Quell-IP-Sperre | Geschlossen fehlschlagen; begrenzten Coordinator und Ratenlimits erhalten |
| Konkurrierende gleiche/verschiedene Inhalte | Unabhängige Downloads; begrenztes gemeinsames Parsing und Warteschlangen |
| Abbruch, Verdrängung, aktive Ansichten | Keine verlorenen Referenzen, unberechtigte Ausgabe oder unberücksichtigten Inhalte |
| Neustart/Stopp/Parserwechsel | Speicherreferenzen löschen; keine persistierten Projektdaten oder inkompatible Wiederverwendung |
| MCP-Cache-Hit und Folgeseite | Scope, Familie, Bestätigung, Projektberechtigung und frische Sichtbarkeit erneut prüfen |

Die neuen Tests belegen ausgewählte **bestehende Isolationsgrenzen**, keine Abnahme
eines gemeinsamen Caches. Weitere Fälle benötigen deterministische Tests des
Entwurfs und passende reale Berechtigungs-/Lifecycle-Evidenz. #379 erst nach diesen
Gates und nachgewiesenem Zielnutzen umsetzen. #239 behält eigene Service-Identitäts-,
Transport- und Discovery-Gates; keines der Issues liefert den Nachweis des anderen.
