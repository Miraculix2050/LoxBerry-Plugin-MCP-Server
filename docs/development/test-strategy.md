# Änderungsgetriebene Teststrategie

- **Zielgruppe:** Entwickler, Maintainer, Reviewer, Tester und KI-Agenten
- **Status:** Verbindliche Ausgangsbasis

Tests werden durch tatsächliche Änderungen ausgelöst. Gewählt wird der kleinste
reproduzierbare Prüfumfang, der Wirkung und Risiko des Diffs abdeckt. Es gibt keine
periodischen Pflichtläufe und keine ZIP-, Browser- oder Geräteabnahme ohne betroffene
Grenze.

## Ausführungsprofile

- **Changed:** Während Analyse und Implementierung betroffene statische Prüfungen und
  Tests ausführen. Auswahl mit `python tools/test.py --profile changed --plan` prüfen
  und anschließend ohne `--plan` starten. Eine unveränderte erfolgreiche Auswahl wird
  nicht wiederholt.
- **Full:** Format, Lint, strikte Typprüfung und alle deterministischen Tests. Full ist
  für unbekannte oder querschnittliche Pfade, die finale Revision ohne gleichwertige
  CI-Evidenz, Release-Pakete und CI vorgesehen.
- **CI:** Ein grünes Full-Gate auf demselben Commit ist die maßgebliche PR-Evidenz und
  muss lokal nicht erneut ausgeführt werden.

Changed darf in der vorhandenen Entwicklungsumgebung laufen. Vollständige lokale,
CI- oder Release-Evidenz benötigt Python 3.13, Perl und Node.js. Fehlt eine
Pflichtlaufzeit, ist das Ergebnis `incomplete` (Exitcode `2`), nicht bestanden.

## Testebenen

1. **Statisch:** Format, Syntax, Lint, Dokumentationsdiffs und Schemas
2. **Unit:** Validierung, Mapping, Rechte, Konfiguration und Migrationen
3. **MCP-Vertrag:** Tool-Liste, Schemas, Fehlercodes, Zeitlimits und Abbruch
4. **Integration:** Adapter gegen kontrollierte Mocks oder Fixtures
5. **Sicherheit:** Authentifizierung, Rechte, Allowlist, Injection, Pfade und Maskierung
6. **Browser:** nur betroffene Oberfläche auf notwendigen Viewports
7. **Zielgerät:** nur lokal nicht beweisbare LoxBerry-, Lifecycle- oder Gerätegrenzen

## Änderungs- und Risikomatrix

| Änderung | Automatisierte Prüfung | Browser | LoxBerry/Miniserver |
| --- | --- | --- | --- |
| Rechtschreibung, Links, redaktionelle Klarstellung | `git diff --check`, Linkprüfung falls vorhanden | Nein | Nein |
| Normative Spezifikation ohne Code | Konsistenzprüfung | Nur bei gerendertem Verhalten | Nein |
| Deterministische Logik oder Schema | betroffene Unit-/Vertragstests | Nein | Normalerweise nein |
| Defektbehebung mit Verhaltenswirkung | reproduzierender Regressionstest plus betroffene Tests | nach Wirkung | nach betroffener Grenze |
| Authentifizierung, Autorisierung oder schreibendes Tool | Vertrag-, Negativ- und Sicherheitstests | betroffener Ablauf | gezielter End-to-End-Test |
| Konfigurationswert, Default oder Migration | Validierung und Migrationsregression | betroffener Ablauf | bei Pfaden/Rechten/Persistenz |
| UI-Verhalten ohne Layoutwirkung | betroffene UI-/Sprachtests | `1280x800`, `390x844` | nur wenn installierter Pfad nötig |
| Shared Layout, Dialog oder Navigation | UI-/Sprachtests | vollständige Viewport-Matrix | installierte Seite falls nötig |
| Dienst, Systemrechte oder Lifecycle | Syntax plus betroffene Regressionen | nur betroffene Flows | gezielter Lifecycle-Smoke |
| Abhängigkeit oder Runtime | Full | nach Wirkung | Installations-/Start-Smoke |

Unbekannte Laufzeit- oder Konfigurationspfade fallen auf Full zurück. Das löst nicht
automatisch Browser-, Geräte- oder Paketabnahme aus.

## Browserprüfung

Für Verhalten ohne Shared-Layout-Wirkung genügen `1280x800` und `390x844`. Bei
Layout, Navigation, Dialogen oder gemeinsamen Controls zusätzlich `900x768`,
`360x800` und `320x568` prüfen. Reine Übersetzungen werden in DE und EN bei
`390x844` geprüft; weitere Größen nur bei erkennbarem Umbruchrisiko.

DOM-, Overflow-, Touch-/Tastatur-, Fokus- und Konsolenprüfungen je Viewport gebündelt
ausführen und vorhandene authentifizierte Sitzungen wiederverwenden. Lade-, Fehler-
und gespeicherte/ungespeicherte Zustände nur prüfen, wenn der Diff sie berührt.
Screenshots nur für visuelle Änderungen oder Fehler erstellen.

## Zielgerät und Lifecycle

Ein echtes Zielsystem ist nötig, wenn Mocks die betroffene Grenze nicht beweisen:
native Pfade/APIs, Benutzer und Rechte, systemd, Netzwerkbindung, reale Loxone-
Authentifizierung/Berechtigungen sowie Installation, Upgrade oder Deinstallation.

Für einen plugin-eigenen Datei-Hot-Swap genügen Backup, Hash, atomarer Austausch,
erhaltene Rechte, gegebenenfalls Dienstneustart, `/healthz` und der betroffene
Feature-Smoke. Das ist keine Installations- oder Upgrade-Evidenz.

Nach einem nativen Lifecycle-Vorgang immer terminalen Installerstatus, installierte
Version, Dienst und Loopback-Health prüfen. Apache, Dateirechte, Secret-Modi, Schema,
Persistenz, Browser und MCP-Client nur ergänzen, wenn der Diff diese Grenzen berührt
oder eine finale Release-Abnahme verlangt. Ein Merge allein benötigt keine
Plugin-Manager-Abnahme.

Bestehende Konfiguration und Dienstzustände werden erhalten. Zugangsdaten, Tokens,
interne Adressen und unmaskierte Gerätedaten erscheinen weder in Befehlen noch
Evidenz. Schreibtests bleiben ein separates Opt-in an ausdrücklich genehmigten,
unkritischen Steuerungen mit Wiederherstellung.

## Nicht vorhandene Hardware

Nicht real geprüfte Kombinationen bleiben `unverified` oder `experimental`; Mocks
ersetzen keine Hardware-Evidenz. Für Gen. 2 gilt der separate
[Gen.-2-Kompatibilitätstest](gen2-compatibility-test.md). Maintainer und AI-Agenten greifen nur mit einer
separaten ausdrücklichen Zustimmung auf Geräte Dritter zu.

## Mindestanforderungen

- Tests sind deterministisch und enthalten keine Secrets oder privaten Gerätedaten.
- Defektbehebungen und relevante Verhaltensänderungen erhalten einen Test, der den
  Fehler beziehungsweise Vertrag vor der Korrektur nachweisbar abdeckt. Rein
  redaktionelle oder mechanische Änderungen benötigen keinen künstlichen Test.
- Sicherheits- und Schreibpfade decken Fehler, Berechtigungen, Grenzen, Timeout und
  bei Schreibaktionen Wiederholung beziehungsweise Idempotenz ab.
- Mocks bilden nur benötigte externe Verträge ab.
- Fehlende Pflichtprüfungen werden als unvollständig ausgewiesen.
- Der Abschlussbericht nennt einmalig Prüfumfang, Umgebung und nicht geprüfte Grenzen;
  Zwischenstände benötigen keine wiederholte vollständige Evidenzliste.

## CI

PRs und Pushes nach `master` führen das Full-Profil mit Python 3.13 aus. Öffentliche
CI greift nicht auf Zielgeräte oder echte Miniserver zu und erhält keine privaten
Zugangsdaten als Workaround. Der Full-Check auf dem finalen Commit ist das Gate für
den Merge; lokale Full-Wiederholungen nach unverändert grüner CI sind unnötig.
