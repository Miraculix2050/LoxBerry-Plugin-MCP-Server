# Änderungsgetriebene Teststrategie

- **Zielgruppe:** Entwickler, Maintainer, Reviewer, Tester und KI-Agenten
- **Status:** Verbindliche Ausgangsbasis

Tests werden durch tatsächliche Entwicklungsänderungen ausgelöst. Es gibt keine
täglichen oder wöchentlichen Pflichtläufe. Gewählt wird der kleinste
reproduzierbare Prüfumfang, der die Wirkung und das Risiko des Diffs abdeckt.
Die vollständige deterministische Suite wird später zum Gate für Pull Requests
und `master`, sobald ausführbarer Code vorhanden ist.

## Testebenen

1. **Statische Prüfungen:** Format, Syntax, Lint, Dokumentationslinks und
   maschinenlesbare Schemas
2. **Unit-Tests:** Validierung, Mapping, Rechteentscheidungen, Konfiguration,
   Migrationen und andere deterministische Logik
3. **MCP-Vertragstests:** Tool-Liste, Eingabe-/Ausgabeschemas, Fehlercodes,
   Zeitlimits und Abbruch mit simulierten Backends
4. **Integrationstests:** Loxone- und LoxBerry-Adapter gegen kontrollierte Mocks
   oder Fixtures; keine echten Zugangsdaten
5. **Sicherheitstests:** Authentifizierung, fehlende Rechte, Allowlist-Grenzen,
   Injection, Pfade, URLs, Secret-Maskierung und Rate Limits
6. **Browserprüfungen:** betroffene Weboberfläche auf Desktop und Mobile
7. **Zielgerätetests:** nur Grenzen, die lokal nicht zuverlässig beweisbar sind,
   etwa LoxBerry-APIs, Rechte, Dienste, Installation und Upgrade

## Änderungs- und Risikomatrix

| Änderung | Automatisierte Prüfung | Browser | LoxBerry/Miniserver |
| --- | --- | --- | --- |
| Rechtschreibung, Links, reine redaktionelle Klarstellung | Link-/Formatprüfung, sofern vorhanden | Nein | Nein |
| Normative Spezifikation ohne Codeänderung | Konsistenzprüfung und Review | Nur bei gerendertem Inhalt | Nein |
| Deterministische Logik oder Schema | betroffene Unit-/Vertragstests | Nein | Normalerweise nein |
| Authentifizierung, Autorisierung oder schreibendes Tool | Unit-, Vertrag-, Negativ- und Sicherheitstests | betroffener Ablauf | gezielter End-to-End-Test |
| Konfigurationswert, Default oder Migration | Validierung und Migrationsregression | betroffener Ablauf | bei LoxBerry-Pfaden/Rechten |
| UI-Verhalten ohne Layoutwirkung | UI-/Sprachtests | `1280x800` und `390x844` | nur wenn installierter Pfad nötig |
| Responsives/shared Layout, Dialog oder Navigation | UI-/Sprachtests | vollständige Viewport-Matrix | installierte Seite |
| Dienst, Systemrechte, Plugin-Lifecycle oder Hardware | Syntax plus Regressionen | nur betroffene UI-Flows | gezielte betroffene Szenarien |
| Abhängigkeit oder Runtime-Upgrade | vollständige deterministische Suite | nach Auswirkung | Installations-/Start-Smoke |

Unbekannte Laufzeit- oder Konfigurationspfade wählen sicherheitshalber die
vollständige automatisierte Suite. Das löst nicht automatisch eine komplette
Geräte- oder Browserabnahme aus.

## Desktop- und Mobile-Prüfung

Für UI-Verhalten ohne gemeinsames Layout werden nur der geänderte Ablauf bei
`1280x800` und `390x844` geprüft. Bei Änderungen an Layout, Navigation,
Dialogen, gemeinsamen Controls oder responsivem Verhalten gilt:

- `1280x800` Desktop
- `900x768` schmales Desktop/Tablet
- `390x844` primäres Mobile
- `360x800` und `320x568` als kurze Overflow-Smokes

Geprüft werden der effektive Viewport, horizontales Overflow, abgeschnittene
Inhalte, Touch-/Tastaturbedienung, sichtbarer Fokus, Lade-/Fehlerzustände und die
Browserkonsole. Screenshots werden für visuelle Änderungen und Fehler erstellt,
nicht routinemäßig nach jedem Schritt.

Reine Übersetzungsänderungen werden in Deutsch und Englisch bei `390x844`
geprüft; weitere Größen sind nur bei erkennbarem Umbruchrisiko nötig.

## Zielgerät und Lifecycle

Ein echtes LoxBerry-/Loxone-System wird verwendet, wenn Mocks die geänderte
Grenze nicht beweisen können:

- native LoxBerry-Pfade oder APIs
- Benutzer, Gruppen, Dateirechte oder `sudo`
- systemd und Prozess-Lifecycle
- Netzwerkbindung und Verbindung zum Miniserver
- Installation, Upgrade oder Deinstallation
- reale Berechtigungsfilter des Loxone-Benutzers

Es werden nur betroffene Dateien und Abläufe getestet. Bestehende Konfiguration,
Dateirechte und Dienstzustände werden vorher gesichert und danach
wiederhergestellt. Eine Änderung am Installer benötigt den normalen
Plugin-Manager-Weg; ein Merge allein benötigt keine vollständige
Installationsabnahme.

## Öffentliche Betatests für nicht vorhandene Hardware

Steht eine zugesagte Hardwaregeneration den Maintainern nicht zur Verfügung,
wird die fehlende reale Prüfung ausdrücklich als `unverified` beziehungsweise
`experimental` ausgewiesen. Sie wird nicht durch Mocks als bestanden erklärt.

Tests auf einem Miniserver Gen. 2 werden durch freiwillige Dritte über eine
öffentliche Beta erbracht. Dafür stellt das Projekt ein versioniertes
Pre-Release-Paket, Prüfsumme, Testplan, Rücksetzweg, maskierten Diagnoseexport
und ein strukturiertes GitHub-Issue-Formular bereit. Der Test startet read-only
und verwendet einen dedizierten Loxone-Benutzer mit Minimalrechten.

Ein verwertbarer Bericht enthält:

- Plugin-, LoxBerry- und Miniserver-Version
- CPU-Architektur sowie MCP-Client und dessen Version
- ausgeführte Testfälle mit erwartetem und beobachtetem Ergebnis
- ausschließlich maskierte relevante Logauszüge
- Kennzeichnung, ob nur gelesen oder ausdrücklich eine Teststeuerung bedient
  wurde

Passwörter, Tokens, vollständige Strukturdateien, interne Adressen und
unmaskierte Zustandsdaten werden nicht angefordert. Schreibtests sind ein
separater Opt-in-Schritt an unkritischen Steuerungen mit dokumentierter
Wiederherstellung. Maintainer und KI-Agenten greifen nicht ohne eine separate,
ausdrückliche Zustimmung remote auf Geräte der Betatester zu.

Die Support-Matrix unterscheidet selbst getestete, durch mindestens einen
vollständigen unabhängigen Bericht bestätigte, experimentelle und nicht
unterstützte Kombinationen. Ein fehlender Betatester ist kein fehlgeschlagener
Test, aber die betreffende Kombination bleibt unbestätigt.

## Mindestanforderungen an Tests

- Tests sind deterministisch, wiederholbar und enthalten keine echten Secrets,
  IP-Adressen oder benutzerspezifischen Gerätedaten.
- Erfolgs-, Fehler-, Berechtigungs- und Timeoutpfade werden abgedeckt.
- Schreibende Tools prüfen zusätzlich Wiederholung beziehungsweise Idempotenz.
- Mocks bilden nur benötigte externe Verträge ab und definieren nicht heimlich
  das Produktverhalten neu.
- Ein Regressionstest schlägt vor dem Fix fehl und danach erfolgreich an.
- Fehlende Pflichtabhängigkeiten oder nicht ausführbare Prüfungen werden als
  unvollständig gemeldet, nicht als bestanden.
- Testergebnisse nennen Umfang, Umgebung und nicht geprüfte Grenzen.

## CI-Aufbau

Solange noch kein ausführbarer Code vorhanden ist, wird kein Platzhalter-Workflow
benötigt. Der erste ausführbare Commit führt einen einheitlichen lokalen
Testbefehl und denselben CI-Pfad ein. CI läuft auf Pull Requests und Pushes nach
`master` und umfasst mindestens Syntax/Lint, Unit- und MCP-Vertragstests.

Ein GitHub-Pflichtcheck wird erst aktiviert, wenn sein Name und seine Runtime
stabil sind. Zielgeräte und echte Miniserver werden nicht aus öffentlicher CI
angesprochen. Zugangsdaten werden auch nicht als Workaround in Repository-
Secrets für Fork-PRs verfügbar gemacht.
