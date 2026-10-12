# Energy & solar: aufeinander aufbauende PR-Serie

Dieses Dokument hält den vom Owner beauftragten Umsetzungsplan dauerhaft fest.
Es ist eine Planungs- und Übergabereferenz, keine Bestätigung einer abgeschlossenen
Implementierung, Abnahme oder Gerätekompatibilität. Fortschritt und Evidenz werden
in den jeweiligen Issues und Pull Requests dokumentiert.

Zugehörige Arbeitspakete:

- [#436 – Native Energieflussmonitor-/Energiemanager-Daten zugänglich machen](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/436)
- [#439 – Historische Wetterdaten und vergleichbare Tage](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/439)
- [#440 – Verbrauchsverschiebung bewerten und PV-Zeitfenster planen](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/440)

## Nachträgliche Owner-Entscheidung zur Messabnahme

Am 12. Oktober 2026 hat der Owner die genaue Performance-Abnahme zur separaten
Nacharbeit freigegeben, wenn die laufenden Messungen keinen belastbaren Durchbruch
liefern. Falls diese Vertagung erfolgt, gelten die folgenden Übergabeanforderungen
als Ergänzung zum ursprünglichen Plan unten:

- Die offene Messabnahme wird in einem separaten, gelabelten und verlinkten Issue
  weitergeführt; die Messgrenzen werden nicht als bestanden ausgewiesen.
- Das Folge-Issue muss die nicht funktionierenden Ansätze und ihre Ursachen sowie
  verwendbaren, nicht eingecheckten Messcode mit einer nachvollziehbaren Übergabe
  dokumentieren.
- **Das Mess-Folge-Issue darf nicht im ursprünglichen Umsetzungs-Chat bearbeitet
  werden.** Seine Bearbeitung muss in einem separaten Chat erfolgen.
- Funktionale Tests, Rechteprüfung, Größen- und Zeitgrenzen, Abbruch-/Worker-Schutz,
  Review, CI und Browser-/MCP-/SSH-Abnahme bleiben erforderlich.
- Der konkrete Folge-Issue-Link und die Auswirkung auf das jeweilige Merge-Gate
  werden im zuständigen Umsetzungs-PR dokumentiert. Dieses Dokument legt kein
  zusätzliches Mess-Issue an und behauptet dessen Abschluss nicht.

Die nachstehenden Messanforderungen bleiben der fachliche Zielumfang der
Nacharbeit. Die Vertagung ist keine Behauptung, dass die Grenzwerte eingehalten
werden, und ersetzt nicht die unabhängige AI-/Token-Abnahme in #485.

## Ausgangspunkt und Architektur

Geprüfte Basis des ursprünglichen Plans ist `master` auf `d14162c0`.
#434, #435, #437 und #438 sind umgesetzt und werden erweitert. #445 liefert den
Szenariokatalog; offene unabhängige AI-, Token- und Performance-Messungen liegen
in [#485](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/485).
Die genannte Basis ist der historische Planungsstand; jeder Folge-PR muss den
aktuellen gemergten Vorgänger als Basis verwenden.

Die Serie bleibt lokal und read-only gegenüber Loxone. Fehlende Wetterhistorie
erhält eine ausdrücklich aktivierbare Aufzeichnung. Zukunftsplanung bleibt ein
separates, bedingtes Paket, bis eine belegte lokale PV-Prognose verfügbar ist.

Die Architektur behält vier getrennte Schichten:

- **Quellenadapter:** native EFM-/Energiemanager-Daten, Statistiken, Event History
  und Wetteraufzeichnung.
- **Semantik und Profil:** versionierte Quellenregeln sowie ausdrücklich
  bestätigte Anlagenparameter und Betriebsgrenzen.
- **Reine Fachlogik:** Tagesvergleich und Lastverschiebung ohne Netzwerk,
  Speicherung oder Autorisierung.
- **MCP und UI:** schlanke Orchestrierung, aktuelle Rechteprüfung, begrenzte
  Ergebnisse und nachvollziehbare Fehler.

Bestehende MCP-Oberflächen werden additiv erweitert. Es entstehen weder ein
paralleler Energiebilanzrechner noch ein Tool je Solarfrage.

## PR-Abfolge und nutzbare Zwischenstände

Die PRs werden nacheinander geprüft und gemergt. Jeder Folge-PR basiert auf dem
gemergten Vorgänger; unabhängige Erweiterungen werden nicht in dessen Diff
aufgenommen. Die Issues beschreiben Arbeitspakete und müssen nicht jeweils exakt
einem PR entsprechen. Jeder PR liefert einen nutzbaren, geprüften Zwischenstand.

| PR | Umsetzung | Nutzbarer Zwischenstand |
| --- | --- | --- |
| **1 – Native EFM-Ergebnisse lesen** | Den [konkreten Vertrag aus #436](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/436#issuecomment-6113527821) über `loxone_read_controls` implementieren. | Aktuelle native Werte und laufende Periodenergebnisse sind mit expliziten Semantiklücken abrufbar. |
| **2 – EFM-Semantik und Berichtsfähigkeit** | Belegte Einheiten, Vorzeichen, Perioden und Messgrenzen ergänzen; native Berichtskomponenten mit den bestehenden Historien verbinden. | Energieberichte verwenden belegte Loxone-Ergebnisse und kennzeichnen fehlende Komponenten. |
| **3 – Energiemanager-Kontext** | Generationen getrennt erfassen; belegte Last-, Prioritäts-, Sperr- und Laufzeitinformationen über bestehende Beschreibung-/Leseflächen zugänglich machen. | Beratung kann vorhandene native Betriebsgrenzen berücksichtigen. |
| **4 – Wetter- und Anlagenkontext** | Das bestätigte Profil um Wetterquellen und optionale PV-Anlagenparameter erweitern; vorhandene Historien erschließen. | Bereits vorhandene Wetterhistorie lässt sich mit eindeutiger Herkunft und Abdeckung verwenden. |
| **5 – Lokale Wetteraufzeichnung** | Fehlende Historie durch einen standardmäßig deaktivierten Recorder im bestehenden History-Subsystem ergänzen. | Nach Aktivierung entstehen begrenzte, auswertbare Wetterdaten ab dokumentiertem Aufzeichnungsbeginn. |
| **6 – Vergleichbare Tage** | Erklärbare Tagesauswahl und Abweichungsbewertung als zusätzliche Operation von `loxone_analyze_history`. | Vergleichstage, Ertragsabweichungen und begründete Prüfkandidaten werden kompakt ausgegeben. |
| **7 – Bestätigte Lastflexibilität** | Profil und Admin-Oberfläche um Betriebsgrenzen ergänzen; beobachtete Zyklen mit bestehenden Historien beschreiben. | Nutzer können Verschiebbarkeit bestätigen und erkennen, welche Zyklen ausreichend belegt sind. |
| **8 – Rückblickende Lastverschiebung** | Begrenzte Gegenfaktualanalyse über `loxone_analyze_history`, aufbauend auf PR 2–7. | Vergangene Zyklen erhalten nachvollziehbare alternative Zeitfenster und qualifizierte Potenzialschätzungen. |
| **9 – Bedingte Zukunftsplanung** | Erst nach belegter lokaler PV-Prognose: Quellenvertrag, Prognoselesen und gemeinsame Fensterbewertung liefern. | Morgenfenster berücksichtigen Prognose, Grundlast, konkurrierende Lasten und bestätigte Betriebsgrenzen. |

### PR 1–3: native Energiequellen

**PR 1 übernimmt den bestehenden Vertrag ohne Aufweichung:**

- Optionales `native_result_view` mit `actual/day/week/month/year/lifetime`;
  genau ein EFM-Ziel, keine gemischte Zustandsauswahl.
- Zunächst ausschließlich Firmware **17.2.8.28**, strikt geprüfte
  Miniserver-Identität und frisch bestätigter **Loxone-Administrator**.
- Eigene authentifizierte Aufrufersitzung; Sichtbarkeit und Rechte vor dem Lesen
  und vor Ausgabe erneut prüfen. Perioden benötigen zusätzlich die bestehenden
  History-Berechtigungen und deren Aktivierung.
- Separates typisiertes `native_result`; keine künstlichen Zustands-UUIDs,
  kein Wertecache und keine automatischen Wiederholungen.
- Unveränderte Legacy-Aufrufe verursachen keine zusätzlichen Netzwerkzugriffe.
- Die festgelegten Parser-, Größen- und Zeitlimits übernehmen: 30 Sekunden
  insgesamt, 32 KiB äußere Antwort, 16 KiB JSON-Inhalt, höchstens 16 Eigenschaften
  und 64 KiB Ergebnis.

**PR 2 behandelt Semantik als eigenes Gate.** Feldnamen oder erfolgreiche
Browserantworten belegen keine Einheit oder Bilanzformel. Laufende native
Kalenderperioden werden insbesondere nicht als frei wählbare historische
Tageswerte verwendet. Berichte über „gestern“ benötigen eine separat belegte
historische Quelle. Fehlende Eigenverbrauchs-, Speicher- oder Restlastwerte
bleiben unbekannt.

**PR 3 trennt Energiemanager und EFM.** Jede Generation erhält eine Capability-Zeile
mit belegten und fehlenden Eigenschaften. Nicht nachgewiesene Familien bleiben
ausdrücklich unsupported/unverified. Der native Regelalgorithmus wird nicht
nachgebaut. Nichtadministrative EFM-Aggregate, Teilnehmerabfragen und weitere
Firmwareversionen bleiben separate Evidenzgates innerhalb #436.

### PR 4–6: Wetterhistorie und Vergleichstage

Das Profil erhält bestätigte Wetterquellenbindungen und optionale Angaben zu
installierter Leistung, Ausrichtung, Neigung, Verschattung und Standort.
Technische Quellenangaben und Nutzeraussagen behalten getrennte Herkunft.
Bestehende Profile werden idempotent migriert; unbekannte Parameter verhindern
einfache Vergleiche nicht pauschal.

Der Recorder aus PR 5:

- verwendet bestehende SQLite-, Retention-, Größen- und Coverage-Mechanismen;
  keinen zweiten Dienst oder separaten Datenspeicher;
- erhält einen getrennten Quellentyp für strukturierte Wetterdaten und erfindet
  keine Kontroll-UUID;
- speichert nur konfigurierte Felder, Quellenzeit, Empfangszeit und Herkunft;
- trennt aktuelle Quellenwerte, Prognosen und tatsächliche Messungen;
  Prognosepunkte werden nicht zu Beobachtungen umetikettiert;
- dokumentiert Start, Unterbrechungen, Quellenwechsel und Löschung;
- aktiviert sich ausschließlich über die bestehende autorisierte
  Admin-Konfiguration.

Unbekanntes `solar_radiation` darf erfasst werden, wird aber erst nach belegter
Einheit und Kodierung numerisch ausgewertet. Die Aufzeichnung füllt keine
Vergangenheit auf.

Für PR 6 gilt ein versioniertes, transparentes Verfahren:

- Ein Aufruf untersucht höchstens 31 zusammenhängende lokale Tage innerhalb der
  bestehenden Analysebudgets.
- Ein Referenztag und Kandidaten werden über dasselbe Zeitfenster verglichen;
  bei einem laufenden Tag nur über bereits abgeschlossene, gemeinsam belegte
  Intervalle.
- Initiale Vergleichstoleranzen: höchstens 30 Tage saisonaler Abstand,
  15 % Abweichung der belegten Strahlungsenergie und 3 °C Temperaturabweichung.
  Optionen und verwendete Grenzwerte erscheinen im Ergebnis.
- Mindestens drei geeignete Vergleichstage sind für eine gruppenbezogene
  Abweichungsbewertung erforderlich. Andernfalls werden nur einzelne Vergleiche
  beziehungsweise `insufficient_evidence` geliefert.
- Saisonaler Abstand ist ohne zusätzliche belegte Geometrie kein Nachweis
  gleicher Sonnengeometrie.
- Kandidaten werden nach normalisierter Wetterabweichung sortiert; Ergebnisse
  nennen Auswahlgründe, Ausschlüsse und Abdeckung.
- Niedriger Ertrag erzeugt einen Prüfkandidaten, keine Defektdiagnose.
  Eigenverbrauchsvergleiche benötigen zusätzlich die belegten nativen
  Energiegrößen.

Die Grenzwerte und Referenzfälle werden vor Implementierung im Methodenreview
festgeschrieben.

### PR 7–9: Lastverschiebung und PV-Fenster

PR 7 ergänzt je bestätigter Last: flexible Zeitfenster, spätesten Abschluss,
Laufdauer, Unterbrechbarkeit, Mindestlauf-/Sperrzeiten und Herkunft des Leistungs-
beziehungsweise Energieprofils. Unbestätigte Lasten gelten als nicht planbar.
Native Sperren bleiben verbindlich.

PR 8 bewertet ausschließlich ausreichend belegte Zyklen und vollständig nutzbare
Energieintervalle. Gemessener Export kann ein konservatives verfügbares Potenzial
belegen; zeitliche PV-Überlappung allein belegt weder Eigenverbrauch noch
Einsparung.

- Alternative Fenster müssen alle bestätigten Betriebsgrenzen erfüllen.
- Mehrere Lasten teilen sich ein gemeinsames Potenzialbudget; dasselbe
  Überschussintervall wird nicht mehrfach vergeben.
- Kandidaten werden deterministisch nach belegtem nutzbarem Potenzial, danach
  frühestem zulässigem Start sortiert.
- Unbekannte Speicherinteraktion, Restlast, Teilintervalle oder ungeeignete
  Auflösung begrenzen das Ergebnis ausdrücklich.
- Gegenfaktuale Werte enthalten Methode, Annahmen und Grenzen; finanzielle
  Einsparungen benötigen zusätzlich belegte Tarif- und Bezugsdaten.

**PR 9 beginnt mit einem Quellen- und Vertragsreview.** Erforderlich sind eine echte
lokale PV-Prognose, deren Einheit, Zeitachse, Aktualisierung, Horizont und
Unsicherheit sowie belegbarer Grundlastkontext. Wetterprognose allein reicht nicht.

Die Zukunftsoperation erhält eine eigene Zeitvalidierung und einen typisierten
Prognosevertrag; bestehende historische Operationen behalten ihr Vergangenheitsgate.
Ein gegebenenfalls notwendiger zusätzlicher MCP-Vertrag wird erst nach
nachgewiesener Lücke geprüft. Fehlt die Quelle, endet diese Stufe mit dokumentierter
Nichtverfügbarkeit; #440 wird hinsichtlich Zukunftsplanung nicht als vollständig
umgesetzt geschlossen.

## Performance und MCP-Verträge

Für die genaue Messabnahme gilt ergänzend die Owner-Entscheidung am Anfang dieses
Dokuments. Die Architektur- und Laufzeitgrenzen bleiben erforderlich.

- Quellen innerhalb eines Aufrufs deduplizieren und einen gemeinsamen frisch
  autorisierten Kontext verwenden.
- Vorhandene identity- und quellengebundene Statistikcaches weiterverwenden;
  Cachetreffer ersetzen keine Rechteprüfung. Native EFM-Ergebnisse bleiben in v1
  ungecached.
- SQLite-Abfragen über Quelle und Zeitraum indizieren; keine Vollhistorien laden
  und keine Abfrage je Vergleichstag ausführen.
- Tageskennwerte einmal berechnen und wiederverwenden. Reine Berechnungen laufen
  außerhalb des Event Loops über die bestehende begrenzte Worker-Zulassung.
- Bestehende Limits erhalten: 16 Quellen, 100.000 Eingangspunkte, 30 Sekunden,
  zwei parallele Analysen und 64 KiB Ausgabe; strengere Quellenlimits gelten
  weiterhin.
- Kompakte Ergebnisse sind Standard. Rohdaten bleiben explizit angefordert,
  begrenzt und paginiert.
- Abbruch, Timeouts und Fehler dürfen weder Sitzungen noch Worker-Slots dauerhaft
  belegen.

Pro Runtime-PR werden betroffene neue Workflows und unveränderte Kontrollworkflows
gemessen: mindestens 30 kalte und 30 warme Aufrufe je vergleichbarem Messfall,
mit p50/p95, Quellenzugriffen, Autorisierungs-, SQLite- und Berechnungszeiten sowie
Ergebnisgröße und beobachtbarem Speicherbedarf.

Für unveränderte Reads gilt **keine bestätigte Regression über 10 %**.
Rauschende Grenzfälle werden kontrolliert nachgemessen. Das 20-%-Tokenziel gilt nur
bei tatsächlich ersetztem Rohdatentransfer mit gleichwertiger Antwortqualität;
Bytes ersetzen keine Tokenmessung. Nicht verfügbare Telemetrie bleibt unvollständig.

## Reviews, Tests und Loxberry-Test-Abnahme

Jeder PR durchläuft dieselben Gates:

1. **Vertrags-/Methodenreview:** Architektur, Rechte, Semantik, Grenzen und
   nutzbares Ergebnis festlegen.
2. **Implementierungsschleife:** Changed-Auswahl prüfen, passende Tests ausführen,
   unabhängiges Code-/Security-/Performance-Review; Findings beheben und betroffene
   Prüfungen wiederholen, höchstens drei Reviewrunden.
3. **Finale Revision:** grünes Full-CI auf dem finalen Commit, keine relevanten
   offenen Findings und vollständige Zielabnahme für betroffene Laufzeitgrenzen.

Schemas, Explorer, Skill-Anleitung, DE/EN-Dokumentation, Supportmatrix und Changelog
werden im jeweiligen Verhaltens-PR aktualisiert.

Die Referenztests decken insbesondere ab:

- Legacy-Verträge ohne Zusatzprobes; Admin-, Scope-, Identitäts-, Firmware-,
  Sichtbarkeits- und Widerrufsgates.
- Fehlende EFM-Felder, unbekannte Semantik, ungültige/übergroße Antworten,
  doppelte JSON-Schlüssel, Timeout und Abbruch.
- Profilmigration, Recorder-Opt-in, Neustart, Retention, Aufzeichnungslücken und
  fehlende Vergangenheit.
- DST, laufende Tage, Einheitenkonflikte, fehlende Vergleichstage, Nullerzeugung
  und Zählerresets.
- Nichtverschiebbare Lasten, unsichere Zyklen, Sperren, Speicher und konkurrierende
  Lasten.
- Fehlende/veraltete PV-Prognosen sowie ausdrücklich untersagte Kausalitäts-,
  Bilanz- und Kompatibilitätsbehauptungen.

**Für jeden Runtime-PR erfolgt eine reservierte Hotswap-Abnahme auf Loxberry-Test:**

- Bestehende Reservierungs- und Deployment-Helfer verwenden; bei belegtem Ziel
  warten. Reservierung vor und nach den Tests prüfen.
- Backup, atomarer Austausch, SHA-256 und Rechteerhalt; neue Dateien nur über den
  vorgesehenen geprüften Deploymentpfad.
- **SSH:** installierte Hashes, Dienst, Loopback-Health, betroffene
  Migration/Persistenz und maskierte Diagnostik.
- **MCP:** positive verfügbare Quellen, negative Rechtefälle, kompakte Ergebnisse,
  Grenzen, Abbruch sowie kalte/warme Messungen.
- **Browser:** betroffene Admin-/Explorer-Flows in DE/EN bei `1280×800` und
  `390×844`; bei gemeinsamen Layoutänderungen die vollständige Viewport-Matrix.
- Bei Fehlern Rollback und verifizierter vorheriger Dienstzustand; bestehende
  Historien und Konfiguration erhalten.

Hotswap beweist keine native Installation oder Upgradefähigkeit. Nicht vorhandene
Gerätefamilien bleiben unverified; installierte Fixtures werden getrennt von echter
Quellenabnahme ausgewiesen.

Nach dem letzten lieferbaren PR folgt eine integrierte Browser-/MCP-/SSH-Abnahme
der betroffenen Solarfragen. #436, #439 und #440 werden nur entsprechend ihrer
tatsächlich erfüllten Pakete geschlossen. Die vollständige unabhängige
25-Fragen-Abnahme bleibt in #485.
