# LoxBerry MCP Server

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. Die aktuelle Alpha erlaubt KI-Assistenten und Agenten standardmäßig ausschließlich, den Zustand einer Loxone-Miniserver-Installation zu lesen. Optional kann ein eng begrenztes Loxone-Schreibwerkzeug aktiviert werden. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst. LoxBerry-Werkzeuge sind nicht Bestandteil dieser Version.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente lesen oder bedienen, für die dieses Konto berechtigt ist. Steuerzugriff benötigt zusätzlich die bewusste Aktivierung im Plugin und den separat bestätigten Scope `loxone:control`.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Phase 1 und die ursprüngliche Phase 2 sind abgenommen. Der zugehörige
Pre-Release `0.2.0-alpha.1` begrenzt das optionale Schreibwerkzeug noch auf
`Switch`. Der aktuelle, noch nicht als Folgerelease veröffentlichte Stand
erweitert dieses Werkzeug auf Gen.-1-Controls vom Typ `Switch`, `Dimmer`,
`LightController`, `LightControllerV2` und `Jalousie`. Es bleibt
standardmäßig deaktiviert, akzeptiert ausschließlich typabhängige dokumentierte
Aktionen und benötigt den separat bestätigten Scope `loxone:control`. Freie
Kommandos, Namens- und Sammelziele sind ausgeschlossen. Die sechs stabilen
lesenden Tools und bestehende Read-only-Sitzungen bleiben kompatibel.

Bestätigte Kombinationen, Nachweise und bekannte Clientgrenzen stehen in der
[Support-Matrix](docs/development/support-matrix.md), im
[Phase-1-Abnahmebericht](docs/development/phase-1-acceptance.md) und im
[Phase-2-Abnahmebericht](docs/development/phase-2-acceptance.md).

## Nutzung

- [Benutzeranleitung (Deutsch)](docs/user-guide.de.md)
- [User guide (English)](docs/user-guide.en.md)
- [Claude Desktop einrichten](docs/clients/claude-desktop.de.md)
- [Connect Claude Desktop](docs/clients/claude-desktop.en.md)

## Entwicklung

- [Implementierungsrichtlinien](docs/development/implementation-guidelines.md)
- [Plugin-Konzept](docs/development/plugin-concept.md)
- [Änderungsgetriebene Teststrategie](docs/development/test-strategy.md)
- [Entwicklungs- und Testautomatisierung](docs/development/automation.md)
- [Support-Matrix](docs/development/support-matrix.md)
- [ADR: Integrierter MCP Tool Explorer](docs/development/adr/0004-integrated-tool-explorer.md)
- [Recherche-Ergebnisse](docs/research/research-results.md)
- [Beitragen und Git-Workflow](CONTRIBUTING.md)

Die Referenzentwicklung verwendet Python 3.13. Für das vollständige lokale Gate
müssen außerdem Perl und Node.js im `PATH` verfügbar sein; damit werden die
ausführbaren Regressionstests für die Perl-CGI- und Browserlogik ausgeführt.
Nach dem Anlegen eines lokalen virtuellen Environments werden die fixierten
Laufzeit- und Testabhängigkeiten installiert und das Projekt ohne erneute
Abhängigkeitsauflösung eingebunden:

```text
python -m pip install -r requirements/runtime-arm64.lock -r requirements/dev.lock
python -m pip install --no-deps -e .
python tools/test.py --profile changed --plan
python tools/test.py --profile changed
```

Das Changed-Profil wählt während der Entwicklung nur betroffene Prüfungen aus.
`python tools/test.py --profile full` beziehungsweise der rückwärtskompatible
Aufruf `python tools/test.py` führt das vollständige Python-3.13-Gate für CI und
finale Revisionen aus. Details stehen in der
[Teststrategie](docs/development/test-strategy.md).

## Lizenz

Dieses Projekt steht unter der [Apache License 2.0](LICENSE).
