# Implementierungsrichtlinien

- **Zielgruppe:** Entwickler, Maintainer, Reviewer, Tester und KI-Agenten
- **Status:** Verbindliche Ausgangsbasis; wird mit der Implementierung verfeinert
- **Geltung:** Plugin, MCP-Schnittstelle, Weboberfläche, Konfiguration und Lifecycle

Diese Richtlinien legen früh die Grenzen fest, deren spätere Änderung teuer oder
sicherheitskritisch wäre. Sie schreiben noch keine unnötig detaillierte
Architektur vor. Implementierter und getesteter Stand hat Vorrang vor
Spekulation; neue Produktentscheidungen werden vor der Implementierung hier oder
in einer eigenen Architekturentscheidung dokumentiert.

## 1. Produktgrundsätze

Das Plugin betreibt den MCP-Server lokal auf dem LoxBerry. Es benötigt keinen
eigenen Cloud-Dienst. Die erste nutzbare Version konzentriert sich auf wenige,
verständliche und sicher begrenzte Funktionen statt auf eine möglichst große
Tool-Sammlung.

Verbindliche Grundsätze:

- **Lokal und transparent:** Daten verlassen das lokale System nur als Folge
  einer bewusst aufgebauten MCP-Verbindung oder eines ausdrücklich ausgelösten
  Befehls.
- **Minimale Rechte:** Jeder Assistent verwendet ein eigenes Konto und nur die
  benötigten Berechtigungen.
- **Read-only zuerst:** Neue Informationsquellen werden zuerst lesend angeboten.
  Schreibende Funktionen folgen erst mit klarer Autorisierung und Tests.
- **Keine versteckten Seiteneffekte:** Der Name und die Beschreibung eines Tools
  müssen erkennen lassen, ob es nur liest oder einen Zustand verändert.
- **Sichere Voreinstellungen:** Ohne abgeschlossene Konfiguration ist kein
  externer Zugriff und keine schreibende Aktion aktiv.
- **Nachweis statt Behauptung:** Unterstützte Plattformen, Browser und Geräte
  werden nur nach dokumentierter Prüfung zugesagt.

## 2. Anfangsumfang

Für eine erste lauffähige Version gehören dazu:

1. MCP-Erreichbarkeit und ein einfacher Health-/Versionsstatus
2. sichere Verbindung zu genau einer konfigurierten Loxone-Installation
3. Anmeldung mit einem dedizierten Loxone-Benutzer
4. lesende Abfrage von Räumen, Kategorien, Steuerungen und Zuständen entsprechend
   den Rechten dieses Benutzers
5. eine kleine Allowlist klar definierter Loxone-Schreibaktionen
6. lesende Diagnoseinformationen zum LoxBerry und zum Plugin
7. eine responsive Konfigurationsoberfläche
8. strukturierte, maskierte Logs und verständliche Fehlermeldungen
9. Installation, Upgrade und Deinstallation über den normalen LoxBerry-Workflow

Schreibende LoxBerry-Systemtools gehören erst in einen späteren Schritt. Vorher
müssen ein eigenständiges Autorisierungsmodell, eine enge Befehls-Allowlist,
Audit-Logging und Wiederherstellungswege feststehen. Ein Loxone-Login erteilt
niemals automatisch administrative Rechte auf dem LoxBerry.

Die lokale, SecurePIN-geschützte Neuausstellung des systemweiten
LoxBerry-Webserver-Zertifikats ist die erste ausdrücklich abgegrenzte
LoxBerry-Systemaktion. Sie bleibt auf die Admin-UI beschränkt und folgt
[ADR 0005](adr/0005-loxberry-web-certificate-reissue.md); sie wird nicht über MCP
veröffentlicht.

## 3. Architektur und Zuständigkeiten

- MCP-Transport, Tool-Definitionen, Loxone-Anbindung, LoxBerry-Anbindung,
  Autorisierung, Konfiguration und Weboberfläche bleiben logisch getrennte
  Komponenten.
- Protokoll- und Domänenlogik soll ohne echte Geräte, Browser oder
  Produktionsdateisystem testbar sein.
- Betriebssystemzugriffe liegen hinter schmalen Adaptern. Laufzeitcode baut keine
  Shell-Kommandos aus ungeprüften Zeichenketten zusammen.
- Lang laufende Aktionen unterstützen Zeitlimits und, soweit technisch möglich,
  Abbruch. Ein abgebrochener Aufruf darf keinen unklaren Zwischenzustand lassen.
- Schreibende Aktionen sind idempotent oder dokumentieren eindeutig, warum eine
  Wiederholung eine weitere Wirkung auslöst.
- Neue Frameworks, Dienste und persistente Speicher werden nur eingeführt, wenn
  ein konkreter Bedarf ihren Betriebs- und Updateaufwand rechtfertigt.

Vor dem ersten ausführbaren Commit werden Sprache, Laufzeit, offizielles
MCP-SDK, Transport und LoxBerry-Prozessmodell in einer kurzen
Architekturentscheidung festgehalten.

## 4. MCP-Tools und Datenverträge

- Tool-Namen sind stabil, eindeutig und handlungsorientiert. Lesende und
  schreibende Varianten werden nicht hinter einem mehrdeutigen Tool versteckt.
- Jedes Tool besitzt eine maschinenlesbare Eingabevalidierung, eine klare
  Beschreibung seiner Wirkung und ein strukturiertes Ergebnis.
- Eingaben werden hinsichtlich Typ, Länge, Wertebereich und zulässiger Ziele
  validiert. Freie Dateipfade, Shell-Befehle und beliebige Ziel-URLs sind nicht
  zulässig.
- Fehler unterscheiden mindestens ungültige Eingabe, fehlende Anmeldung,
  fehlende Berechtigung, nicht erreichbares Ziel, Zeitüberschreitung und internen
  Fehler. Geheimnisse erscheinen weder in Fehlern noch in Tool-Ergebnissen.
- Interne IDs sind die zuverlässige Referenz; für Menschen sichtbare Raum-,
  Kategorie- und Steuerungsnamen werden zusätzlich ausgegeben.
- Schemaänderungen nach dem ersten Release sind kompatibel oder werden mit
  Migration und Versionshinweis eingeführt. Felder werden nicht stillschweigend
  umgedeutet.
- Große Zustandsmengen benötigen Begrenzung, Filter oder Pagination, bevor sie in
  produktiven Installationen angeboten werden.

## 5. Authentifizierung, Autorisierung und Sicherheit

- Loxone-Zugriffe werden mit dem angemeldeten Loxone-Benutzer ausgeführt und auf
  dessen tatsächlich sicht- und bedienbare Elemente begrenzt.
- Für jeden Assistenten wird ein eigenes Konto mit minimalen Rechten empfohlen.
- Der Miniserver-Adapter verwendet ausschließlich Loxone-JWT/Tokenauth. HTTP
  Basic Authentication und persistente Loxone-Passwörter werden nicht angeboten.
- Gen. 1 wird mangels TLS ausschließlich lokal über HTTP/WS angebunden;
  Authentifizierung und Steuerkommandos verwenden zusätzlich die Loxone Command
  Encryption. Gen. 2 verwendet HTTPS/WSS mit vollständiger Zertifikatsprüfung
  und ohne stillen Rückfall auf Klartexttransport.
- LoxBerry-Funktionen haben eine separate Berechtigungsschicht. Zunächst sind sie
  nur lesend; Systemänderungen benötigen eine explizite Freigabe pro Aktionstyp.
- Schreibende Tools prüfen die Berechtigung unmittelbar vor der Aktion und
  protokollieren Zeitpunkt, Identität, Tool, Ziel und Ergebnis ohne Geheimnisse.
- Tokens, Passwörter, Cookies und private Schlüssel werden nie in Git, URLs,
  Prozessargumenten, HTML, normalen Logs oder unmaskierter Diagnose ausgegeben.
- Geheimnisse werden getrennt von normaler Konfiguration mit möglichst kleinen
  Dateirechten gespeichert. Die UI zeigt nur, ob ein Geheimnis gesetzt ist.
- Netzwerkzugriff wird nur auf den notwendigen Interfaces und Ports aktiviert.
  Eine Veröffentlichung ins Internet ist kein unterstützter Standardbetrieb.
- Eingaben und Antworten externer Systeme gelten als nicht vertrauenswürdig.
  Schutz gegen Command Injection, Path Traversal, SSRF, unzulässige
  Weiterleitungen und übergroße Daten gehört zur Implementierung.
- Fehlgeschlagene Anmeldungen und schreibende Aufrufe werden begrenzt, ohne
  berechtigte lokale Nutzung unnötig zu blockieren.
- Abhängigkeiten werden sparsam gewählt, versioniert und auf bekannte
  Schwachstellen geprüft.

## 6. Konfiguration

- Es gibt eine autoritative persistente Konfiguration mit dokumentiertem
  `schema_version`-Wert. Laufzeitcache und Geheimnisse sind davon getrennt.
- Plugin-Identität, Installationsordner und persistente Schlüssel werden nach dem
  ersten veröffentlichten Paket nicht ohne Migrationspfad umbenannt.
- Defaults sind sicher und klein: keine schreibenden Tools, keine öffentliche
  Bindung und keine zusätzlichen Systemrechte ohne ausdrückliche Aktivierung.
- Vor dem Speichern werden alle Werte validiert. Mehrere zusammengehörige Dateien
  werden als konsistenter Satz erzeugt, geprüft und atomar ersetzt.
- Ein fehlgeschlagenes Speichern oder Anwenden erhält die letzte gültige
  Laufzeitkonfiguration. Die UI zeigt den Unterschied zwischen gespeichertem,
  angewendetem und aktuell laufendem Zustand.
- Upgrades erhalten Benutzerwerte. Neue Schlüssel bekommen explizite Defaults;
  entfernte oder geänderte Schlüssel benötigen eine idempotente Migration.
- Unbekannte Konfigurationswerte werden nicht kommentarlos gelöscht, sofern sie
  eine neuere Version oder Erweiterung darstellen könnten.
- Lokale Entwicklungs- und Testkonfiguration bleibt außerhalb des Repositorys.
  Eine `.env.example` darf nur Platzhalter und keine echten Zieladressen oder
  Zugangsdaten enthalten.
- Änderungen an Defaults, Schlüsseln, Migrationen oder Dateirechten benötigen
  Tests und Upgradehinweise.

## 7. Desktop, Mobile und Barrierearmut

- Desktop- und Mobilbrowser bieten dieselben wesentlichen Funktionen und
  Informationen. Mobile ist kein nachträglicher, funktional reduzierter Modus.
- Die Oberfläche wird responsiv aufgebaut; horizontales Scrollen der gesamten
  Seite, abgeschnittene Dialoge und außerhalb liegende Aktionen sind Fehler.
- Primäre Abnahmegrößen sind `1280x800` für Desktop und `390x844` für Mobile.
  Änderungen an gemeinsamem Layout werden zusätzlich bei `900x768`, `360x800`
  und `320x568` geprüft.
- Bedienung funktioniert mit Tastatur und Touch. Fokus bleibt sichtbar,
  Beschriftungen sind programmgesteuert zugeordnet und Status wird nicht nur
  über Farbe vermittelt.
- Asynchrone Aktionen zeigen Fortschritt und unterscheiden Erfolg, Warnung und
  Fehler. Navigation oder Aktualisierung darf keine ungespeicherten Eingaben
  unbemerkt verlieren.
- Benutzertexte und Benutzerdokumentation werden auf Deutsch und Englisch
  synchron gehalten. Technische Bezeichner, Tool-Namen, Konfigurationsschlüssel
  und Logs bleiben Englisch.
- Die Oberfläche zeigt keine vollständigen Secrets und bietet keine generische
  Shell- oder Dateisystemkonsole.

## 8. Zuverlässigkeit und LoxBerry-Lifecycle

- Installation, Upgrade und Deinstallation folgen dem nativen LoxBerry-
  Pluginlayout und sind wiederholbar.
- Dienste laufen mit den kleinsten praktikablen Rechten. Zusätzliche Benutzer,
  Gruppen oder `sudo`-Regeln benötigen eine dokumentierte Begründung.
- Persistente Konfiguration liegt nicht in temporären Verzeichnissen;
  Laufzeitcache und Locks liegen nicht im Paketverzeichnis.
- Start und Neustart prüfen die Konfiguration. Ein Fehler lässt den letzten
  bekannten gültigen Zustand bestehen und wird für Benutzer verständlich
  gemeldet.
- Gemeinsame Systemdateien oder Pakete werden nur entfernt, wenn die
  Plugin-Eigentümerschaft sicher nachgewiesen ist.
- Deinstallation entfernt plugin-eigene Dienste und Laufzeitartefakte.
  Benutzerkonfiguration wird nur entsprechend der dokumentierten
  LoxBerry-Konvention entfernt oder erhalten.

## 9. Logging, Datenschutz und Diagnose

- Logs sind strukturiert genug, um Zeit, Komponente, Schweregrad und eine
  Korrelations-ID für einen MCP-Aufruf zu erkennen.
- Normale Logs enthalten keine vollständigen Zustandsdumps der Installation und
  keine sensitiven Steuerungswerte, sofern sie für die Diagnose nicht notwendig
  sind.
- Wiederholte identische Fehler werden begrenzt, damit ein Ausfall weder Datenträger
  noch LoxBerry-Logverwaltung überlastet.
- Debug-Logging ist zeitlich oder explizit aktivierbar und standardmäßig aus.
- Ein Diagnoseexport maskiert Zugangsdaten, Tokens, Sessiondaten, interne
  Adressen und andere identifizierende Werte.
- Telemetrie an einen Hersteller- oder Projektserver findet nicht statt.

## 10. Tests und Qualitätsnachweise

Die verbindliche Auswahl steht in der [Teststrategie](test-strategy.md).
Grundsätzlich gilt:

- Tests werden durch tatsächliche Änderungen ausgelöst, nicht periodisch.
- Während der Implementierung wird die Changed-Auswahl verwendet und nur nach
  relevanten weiteren Änderungen wiederholt. Full läuft einmal auf der finalen
  Revision oder als gleichwertiges CI-Gate desselben Commits.
- Deterministische Logik wird lokal und in CI ohne echten Miniserver oder
  LoxBerry getestet.
- MCP-Schemas, Berechtigungsgrenzen, Konfigurationsmigrationen und Fehlerpfade
  erhalten gezielte Regressionstests.
- Browser- und Zielgerätetests werden risikobasiert ausgewählt.
- Eine reine Dokumentationskorrektur benötigt keinen vollständigen Build,
  Browserlauf oder Gerätetest.
- Fehlende Laufzeit oder ausgelassene Pflichtprüfung ist „unvollständig“, nicht
  „bestanden“.
- Der erste ausführbare Code bringt mindestens Syntax-/Lintprüfung, Unit-Tests
  und einen CI-Workflow für Pull Requests und `master` mit.

## 11. Dokumentation, Versionierung und Releases

- Das Root-README bleibt Projektübersicht und Einstiegspunkt.
- Benutzeranleitung, Konfigurationsreferenz, bekannte Einschränkungen und
  getestete Support-Matrix entstehen spätestens vor dem ersten öffentlichen
  Testpaket.
- Verhaltens-, Konfigurations-, Abhängigkeits-, Sicherheits- und Upgradeänderungen
  aktualisieren Dokumentation und Changelog im selben Pull Request.
- Versionsnummern und Releasepakete werden erst automatisiert, wenn
  Plugin-Metadaten, Paketlayout und reproduzierbare Prüfungen stabil sind.
- Releaseaussagen unterscheiden klar zwischen implementiert, automatisiert
  getestet und auf realer LoxBerry-/Loxone-Hardware bestätigt.

## 12. Was am Anfang bewusst nicht benötigt wird

Folgende Themen werden erst bei einem nachgewiesenen Bedarf eingeführt:

- eigener Cloud-Dienst, Remote-Relay oder öffentliche Internetfreigabe
- beliebige Shell-, Dateisystem- oder Paketverwaltungsbefehle über MCP
- schreibende LoxBerry-Systemtools vor einem separaten Autorisierungsmodell
- mehrere Microservices, Message Queue oder eigene Datenbank für kleine
  Konfigurations- und Cachemengen
- Hochverfügbarkeit, Clusterbetrieb oder Mandantenfähigkeit
- vollständige Unterstützung beliebig vieler Miniserver
- automatische Geräteerkennung und umfassende Tool-Abdeckung in der ersten
  Version
- aufwendige Telemetrie-, Analyse- oder Dashboard-Infrastruktur
- vollständige Browserautomatisierung für jede Textänderung
- kompletter Installations-/Upgrade-/Uninstall-Test für jeden Merge
- automatische Releases, Signierung und mehrere Releasekanäle vor stabilem
  Packaging
- Kompatibilitätszusagen für ungeprüfte LoxBerry-Versionen, Architekturen,
  Browser oder Loxone-Konfigurationen

Diese Zurückstellungen sind keine dauerhaften Verbote. Sie verhindern, dass die
erste Version Betriebs- und Sicherheitskomplexität ohne unmittelbaren Nutzen
ansammelt.

## 13. Offene Entscheidungen vor dem ersten ausführbaren Commit

Vor Beginn der Laufzeitimplementierung werden kurz dokumentiert:

1. Programmiersprache, Runtime und unterstützte LoxBerry-Basisversion
2. verwendetes MCP-SDK und Netzwerktransport
3. Prozess-/Dienstmodell und Port-/Interface-Bindung
4. Ablage, Verschlüsselung und Rotation von Sitzungen und Secrets
5. konkreter Loxone-Anmelde- und Berechtigungsfluss
6. Autorisierung der lesenden LoxBerry-Diagnose
7. Plugin-ID, Ordnername und Konfigurationspfade
8. minimales Tool-Inventar und Abgrenzung der ersten Schreibaktionen
9. CI-Runtime und reproduzierbarer lokaler Testbefehl

Danach werden Entscheidungen als kleine, nachvollziehbare Änderungen an diesem
Dokument oder als kurze Architecture Decision Records gepflegt.
