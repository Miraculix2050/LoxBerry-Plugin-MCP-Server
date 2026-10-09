# Autorisierte Projektwiederverwendung zwischen OAuth-Familien (#379)

- Status: Implementierung im Review; Zielabnahme noch unvollständig.
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
gelten weiterhin. Dies umfasst auch projektgestützte Öffnungsanalysen sowie
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

Die Abnahme benötigt außerdem echte Grants verschiedener Nutzer mit abweichender
Sichtbarkeit, kontrollierten Entzug der Projektleseberechtigung bei Warm-Aufrufen
und Fortsetzungen sowie einen kontrollierten Projektwechsel. Bytegleichheit zweier
Grants desselben Nutzers oder deterministische Mocks beweisen diese Fälle nicht.
Steuerungsaktionen in Raum/Kategorie MCP-Test autorisieren keine Administration
von Nutzerrechten. Gen.-1-Evidenz erlaubt keine Gen.-2-Zusage.

Merge und Issue-Abschluss benötigen abgeschlossene Ziel-Gates, grüne finale CI,
normales Review und separates Security-Audit ohne relevante offene Befunde.
