# Autorisierte Projektwiederverwendung zwischen OAuth-Familien (#379)

- Status: implementiert; Gen.-1-Abnahme unten dokumentiert.
- Umfang: OAuth-Familien für `sps.LoxCC`. Service-Identitäts-Discovery in #239 bleibt getrennt.
- [English version](project-family-deduplication.md)

## Autorisierung vor Wiederverwendung

Jeder Projektaufruf, einschließlich Warm-Cache-Treffern und Pagination-Fortsetzungen,
lädt das Projekt mit dem eigenen Loxone-Token der aufrufenden Familie herunter.
Ein Marker, eine sichtbare Struktur oder der Graph einer anderen Familie beweist
keine aktuelle Projektleseberechtigung. Ein belastbarer kleinerer Nachweis fehlt.

Der Tool-/Runtime-Pfad prüft weiterhin OAuth-Scope, aktuellen Access-Token und
Familie, Tokenbestätigung sowie frisch geladene nutzersichtbare Struktur.
`ProjectService` prüft den Zugriff nach dem Download, nach Parsing oder
Wiederverwendung und nach der abschließenden authentifizierten Markerprüfung
erneut. Verweigerte Berechtigung, Markerfehler, Projektwechsel während der
Prüfung, Abbruch und Revocation liefern keine Daten.
Service-Zugangsdaten autorisieren keinen OAuth-Familienzugriff.

Der Eigentümer hat zusätzliche Downloads und Markerprüfungen bei Warm-Aufrufen
und Fortsetzungen freigegeben. Das ist eine bewusste Autorisierungsänderung,
keine Optimierung der Warm-Latenz. Cold-Load-Zeit und gehaltener Graphspeicher
sind die Vergleichsziele; die Architekturänderung ist das primäre Ziel.

## Begrenzter unveränderlicher Inhalt und getrennte Familiensichten

Erst nach eigenem erfolgreichen Download darf eine Familie Parse-Ergebnisse
mit gleicher Miniserver-Identität, SHA-256 der exakten Response-Bytes,
Parser-/Cache-Epoche, Projektmodellversion und Verarbeitungslimits verwenden.
Der Bundle-Fingerprint gehört zu einer anderen Hash-Domäne und ersetzt die
Bytegleichheit nicht. Geänderte Bytes bei gleichem Marker erneuern Snapshot
und Sicht der aufrufenden Familie.

Der vorhandene Lade-Semaphor serialisiert Downloads und Parsing. Zwei erfolgreiche
identische Downloads können deshalb ein abgeschlossenes Parse-Ergebnis teilen;
Downloads und Autorisierung werden nie zusammengelegt. Eine widerrufene Familie
kann keinen gemeinsamen Parse-Task eines anderen Aufrufers abbrechen.

Projektgestützte MCP-Aufrufe durchlaufen vor den gemeinsamen Leseslots eine
eigene Zulassung: ein aktiver Aufruf, keine Warteschlange und höchstens zwölf
Aufrufe pro rollender Minute über alle Familien dieser Runtime/dieses
Miniservers. Weitere Aufrufe liefern die vorhandene Temporarily-unavailable-
Antwort mit lokaler Rate-Limit-Diagnose. Normale Familien- und History-Limits
gelten weiterhin. Das globale Budget wird erst nach erfolgreicher Familien-/
History-Zulassung und aktueller Zugriffsprüfung belastet. Abgewiesene oder
abgebrochene Zulassung verbraucht kein Projektbudget anderer Familien;
zugelassene Arbeit bleibt auch bei einem Fehler belastet.
Dies umfasst auch projektgestützte Öffnungsanalysen sowie
History-/Observability-Abfragen. Andere Leseaufrufe behalten bei einer Flut
von Projektaufrufen verfügbare gemeinsame Slots.

Familienreferenzen bleiben an Miniserver, Identität und Familie gebunden.
Sichtbare Strukturen, Mappings, Queries, Cursor, Tokens und Rate Limits bleiben
getrennt. Der Inhaltsindex enthält nur Schlüssel; Graphen bleiben in den
vorhandenen Familien-/Sicht-Caches. Weder Rohbytes noch Graphspeicher werden
persistiert. Private Snapshot-Lookup-Tabellen werden einmal aufgebaut und von
allen Verbrauchern nur gelesen.

Familienreferenzen bleiben auf acht Einträge begrenzt. Das Graphbudget von
128 MiB zählt jeden einzigartigen gehaltenen Snapshot einmal. Sichten/Queries
behalten ihr separates konservatives Budget von acht Einträgen und 64 MiB.
Eviction entfernt Familienreferenz, Inhaltsschlüssel und Sichten gemeinsam.
Bereits laufende Aufrufe können zurückgegebene Snapshots halten; Cache-Accounting
ist weder eine RSS-Messung noch eine harte Grenze des Prozessspeichers.

Revocation bricht nur Ladevorgänge dieser Familie ab und entfernt ihre Referenzen
sofort. Eine andere gültige Familie muss ihren nächsten Aufruf weiterhin selbst
downloaden und autorisieren. Shutdown entfernt alle Referenzen; ein Neustart
verwendet keinen früheren Prozessspeicher. Andere Miniserver, Parser-/Cache-Epochen
oder Verarbeitungslimits teilen keinen inkompatiblen Graphen. Ein Identitätswechsel
verwendet keine alten Familiensichten.

## Deterministische Prüfung

`tests/test_project_family_baseline.py` prüft eigene Downloads gleicher und
verschiedener Identitäten, Miniserver-Isolation, überlappende Ladevorgänge,
verweigerte Cold-/Warm-Zugriffe, getrennte Sichten, geänderte Bytes bei gleichem
Marker, Revocation nach Download, Abbruch wartender Aufrufe, Limit-/Parserwechsel,
begrenzte Referenz-Eviction und Shutdown-Bereinigung.
Die vorhandenen Worker-/Tool-Tests erhalten Markerwechsel-, Token-,
Fresh-Visibility-, Mapping-, Query- und Cursorprüfungen.

Der ausschließlich synthetische Benchmark verwendet den echten Wegwerf-Worker
mit gemockter Autorisierung und Download. Mit Python 3.13 und Repository-Abhängigkeiten:

```powershell
$env:PYTHONPATH = 'src'
python tools/benchmark_project_families.py --nodes 1000 --families 2 --samples 3 --warm-calls 3
```

Er meldet Cold-/Warm-Download- und Worker-Zähler, Worker-Wall-Time, getracete
Elternprozess-Allokationen, Familienreferenzen, einzigartige Inhalte und
konservatives Graph-Accounting. Tracing verzerrt Zeiten; Worker-Wall-Time enthält
Start und IPC. Es beweist weder echte OAuth-Prüfung noch Rechteänderungen,
RSS oder Ziellatenz.

## Zielevidenz und verbleibende Gates

Der unveränderte Gen.-1-Pfad wurde mit zwei bestehenden Grants einer Identität
gemessen, jeweils mit eigenem autorisiertem Download und frisch geladener Struktur.
Die Response-Hashes waren identisch; Parsing erzeugte getrennte Snapshots.
Dieser direkte Familien-Token-Harness ist keine MCP-Access-Token-Abnahme.
Evidenz enthält nur anonyme Labels, Hashes, Bytezahlen und numerische Messwerte.

Vorher-/Nachher-Läufe benötigen gleiche Last, Graph-/Modellversion,
Stichproben und Konkurrenz. Struktur, Download, Parsing, Speicher und Gesamtzeit
getrennt messen; Cold-, Warm- und parallele Fälle sowie Fehlschläge melden.
Unsichere Authentifizierungsfehler nicht automatisch wiederholen.

Am 10.10.2026 verglichen je drei erfolgreiche Gen.-1-Stichproben Baseline
`962be53` mit Runtime `ace8b46`, Modell 13, zwei Grants einer Identität und
858.414-Byte-Responses. Ein gespeicherter Response-Byte-SHA-256 stimmt zwischen
Baseline und Kandidat überein. Der Harness lädt vor jedem Aufruf frische Struktur,
misst aber Snapshot-Laden und nicht den vollständigen MCP-/Query-Pfad.

| Messung (Mittelwert, sofern nicht anders angegeben) | Baseline | Gemeinsamer Inhalt |
| --- | ---: | ---: |
| Cold-Aufruf der ersten Familie | 24,31 s | 24,45 s |
| Cold-Aufruf der zweiten Familie | 24,82 s | 6,15 s |
| Beide Cold-Aufrufe zusammen | 49,12 s | 30,60 s |
| Gehaltene einzigartige Graphen | 2 | 1 |
| Konservatives Graph-Accounting | 74.108.432 B | 37.054.216 B |
| RSS des Harness-Elternprozesses | 118.797.653 B | 103.383.040 B |
| Spitzen-RSS des Harness-Elternprozesses | 125.246.123 B | 107.029.845 B |
| Parser-Worker-Wandzeit, beide Familien | 36,90 s | 18,26 s |
| Eigene Downloads, zwei kalte plus zwei warme Aufrufe | 2 | 4 |

Der erste Cold-Mittelwert unterscheidet sich um 0,6 %; drei Zeitstichproben
beweisen weder einen kleinen Erstlade-Rückschritt noch eine allgemeine
Latenzgarantie. Die Cold-Gesamtzeit zweier Familien sinkt um etwa 38 %, das
Graph-Accounting um 50 % und der gemessene Elternprozess-RSS um etwa 13 %.
Worker-Start und IPC bleiben Teil der Cold-Messung. Elternprozess-Spitzen-RSS
enthält keine Spitzen der Worker-Kindprozesse; Worker-Wandzeit enthält Start und
IPC und ist keine getrennte CPU-Zeitmessung. Warm-Snapshot-Aufrufe steigen
wie ausdrücklich freigegeben von etwa 2,6 s auf 6,1 s: Jeder Kandidatenaufruf
downloadet selbst, ohne erneut zu parsen. Frühere fehlgeschlagene Messungen
bleiben separat erhalten und gehen nicht in diese Erfolgs-Mittelwerte ein.

Nach dem gezielten Hotswap lieferten zwei echte MCP-Grants unabhängig aktuellen
Projektstatus mit gleichem Fingerprint/Modell und `stale=false`; der zweite Grant
benötigte 6,09 s. Eine echte parallele MCP-Prüfung ließ eine Projektanfrage zu,
wies die zweite mit `local_rate_limit` ab und beendete während des laufenden
Projektaufrufs eine andere frische Strukturübersicht erfolgreich. Finale
Source-CI, normales Re-Review und separates Security-Re-Review auf `ace8b46`
sind grün; der ursprüngliche Zulassungsbefund ist behoben und sein GH-Thread resolved.

Eine zusätzliche Prüfung mit direkten Familientokens verwendete zwei reale
Identitäten mit abweichender Sichtbarkeit. Beide luden identische Bytes unabhängig
herunter und teilten einen Graphen; Query-Instanzen und Views blieben getrennt:
402 gegenüber 60 Root-Steuerungen bei unterschiedlichen Mapping-Zahlen. Diese
Prüfung ersetzt keine Abnahme der MCP-Zugriffstokens.

Der Restricted-Explorer-Grant führte mit vorübergehendem Projektleserecht auch
echte MCP-Projektstatusaufrufe kalt und warm sowie erste Objektseite und
Fortsetzung erfolgreich aus. Der kontrollierte Rechteentzug erforderte einen
Miniserver-Neustart; der LoxBerry-MCP-Dienst lief mit seinem warmen Familiencache
weiter. Der ursprüngliche Grant und der vorbereitete Cursor lieferten danach
keine Daten. Auch normale Strukturaufrufe scheiterten; der Grant erforderte eine
erneute Anmeldung. Diese Phase belegt deshalb sicheres Sperren beim Neustart,
keinen isolierten Projektrechteentzug bei sonst gültiger Authentifizierung.
Nach erneuter Anmeldung durch den Nutzer konnte der Restricted-Grant die aktuelle
Struktur lesen; Projektstatus und Objektseite wurden mit `permission_denied`
abgewiesen. Seine Strukturübersicht enthielt 67 Steuerungen gegenüber 456 beim
primären Leser.
Projektrechteentzug bei Warm-Aufrufen und Fortsetzungen mit unverändertem Marker
ist deterministisch geprüft und wird nicht als Live-Beobachtung behauptet.

Der unabhängig autorisierte primäre MCP-Grant lud anschließend das geänderte
Projekt mit neuem Fingerprint und unveränderten Mapping-Zahlen; das Ergebnis war
aktuell.
Mit demselben Restricted-Token war der authentifizierte Marker
`jdev/sps/LoxAPPversion3` weiterhin verfügbar, während der Download von
`sps.LoxCC` mit `project_permission_denied` scheiterte. Dieses Live-Gegenbeispiel
schließt den Zeitstempel als Nachweis der Projekt-Downloadberechtigung aus.
Steuerungsaktionen in Raum/Kategorie MCP-Test autorisieren keine Administration
von Nutzerrechten. Gen.-1-Evidenz erlaubt keine Gen.-2-Zusage.

Merge und Issue-Abschluss benötigen abgeschlossene Ziel-Gates, grüne finale CI,
normales Review und separates Security-Audit ohne relevante offene Befunde.

## Autorisierte Wiederverwendung von Analyseergebnissen (#396)

Analyseergebnisse nutzen einen getrennten, begrenzten Cache im Arbeitsspeicher:
vier Einträge, insgesamt 64 MiB und fünf Minuten Gültigkeit. Modbus berücksichtigt
die vom Loader gebundene Projektidentität, Modell-/Analyseversionen und die
gewählten Analysen. KNX berücksichtigt zusätzlich den vollständigen Fingerprint
der sichtbaren Laufzeitzuordnung und gegebenenfalls die Adresstaxonomie.
Unterschiedliche KNX-Zuordnungen teilen keine fertigen Ergebnisse.

Jeder Aufruf, auch ein Treffer oder eine Fortsetzung, lädt das Projekt mit dem
eigenen Grant herunter und aktualisiert die sichtbare Struktur. Nach Berechnung
oder Abruf wird die Berechtigung erneut geprüft. Die Berechnung wird je
Ergebnisschlüssel serialisiert; abgebrochene oder nicht mehr berechtigte Erzeuger
veröffentlichen nichts.

Cursor-Leases bleiben an Familie, Identität und Sicht gebunden, sind auf vier
Einträge begrenzt und enthalten weder Ergebnisse noch Berechtigungsnachweise.
Eine zufällige Generation verhindert, dass abgelaufene oder verdrängte Cursor
wieder gültig werden, wenn eine andere Familie dasselbe Ergebnis neu erzeugt.
Ablauf und Ergebnisverdrängung machen zugehörige Leases ungültig. Ergebnisse und
Leases werden nicht persistiert. Öffentliche Schemas und Analyseversionen bleiben
gleich. Zusätzliche Such-/Verbindungsindex-Caches gehören nicht zu dieser Änderung.

Der Loader bindet die private Projektidentität an exakte heruntergeladene Bytes,
Miniserver, Parser-Epoche/Modell und Verarbeitungsgrenzen, auch bei Graphen oberhalb
der Graph-Cachegrenze. Ein Zeitstempel beweist weder Berechtigung noch Byteidentität.

## Gemeinsame Query-Topologie (#398)

ProjectQuery trennt einen schreibgeschützten ProjectQueryIndex (Knoten und
Containment-Eltern/-Kinder) von familienspezifischen Zuordnungen und Kontrollnamen.
Queries können nach ihrem eigenen autorisierten Abruf nur beim exakt gleichen
Graphobjekt einen Index übernehmen. Dieselbe Familie kann die Topologie bei
geänderter sichtbarer Struktur behalten, wenn der Graph erhalten bleibt. Zugriffe
auf fehlende Kinder vergrößern die gemeinsamen Zuordnungen nicht.

Die vorhandenen begrenzten Sicht-/Query-Referenzen halten die Indizes; es gibt
keinen zusätzlichen globalen Pool, Persistenz oder Worker-Serialisierung. Der
Sichtcache mit acht Einträgen / 64 MiB zählt gemeinsam gehaltene Indexcontainer
einmal und familienspezifische Zuordnungs-/Query-Schätzungen getrennt. Verdrängung,
Widerruf und Schließen entfernen die jeweiligen Referenzen. Ein gültiges Ergebnis
kann oberhalb dieser Speichergrenzen ohne Cache-Aufnahme zurückgegeben werden.

Aufbau-/Allokationsmessungen sind getrennt von Netzwerkdownloads und dem gesamten
Prozessspeicher. Die Gen.-1-Prüfung nutzte zwei eigene Abrufe des einzigen
verfügbaren Vollzugriffs-Grants; verschiedene Familien und geänderte Sichten sind
zusätzlich deterministisch geprüft. Der bestehende Restricted-Grant bleibt ein
Live-Negativtest.

## Gemeinsame Suchergebnisse (#399)

Ein begrenzter ProjectResultCache hält Such-/Analysewerte getrennt von privaten
Cursor-Leases. Suchschlüssel enthalten Miniserver, exakte Projektidentität,
Modell-/Suchversion, vollständigen Fingerabdruck der sichtbaren Zuordnung
(einschließlich Namen) und normalisierte Filter. Limit und Cursor bestimmen nur
die Pagination. Suchergebnisse sind auf acht Einträge / 64 MiB / 300 Sekunden
begrenzt; Familien-/Identitäts-/Sicht-Leases haben eine getrennte Grenze von acht
Einträgen und zufällige Generationen. Analysen behalten ihre Grenzen von vier
Ergebnissen / vier Leases mit derselben Cache-Komponente.

Jede Suche lädt weiterhin selbst das autorisierte Projekt und die aktuelle Sicht
und prüft vor Aufnahme oder Rückgabe erneut die Berechtigung. Fehlgeschlagene oder
abgebrochene Berechtigungsprüfungen nehmen kein Ergebnis auf. Antwortmodelle
kopieren gespeicherte Daten. Ein bereits laufender autorisierter Treffer nimmt
sein ausgeliehenes Ergebnis nach gleichzeitiger Verdrängung unter denselben
Grenzen und ohne TTL-Verlängerung wieder auf, bevor er seinen Cursor zurückgibt.
Ablauf, Verdrängung und geänderte Eingaben machen
zugehörige Cursor-Leases ungültig; ein neu erzeugtes Ergebnis reaktiviert keinen
alten Cursor. Die Cache-Komponente persistiert und autorisiert nichts.
