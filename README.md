# LoxBerry MCP Server

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. Die aktuelle Alpha erlaubt KI-Assistenten und Agenten, den Zustand einer Loxone-Miniserver-Installation zu lesen. Optional kann sie genau ein kontrolliertes Schreibwerkzeug für Gen.-1-Steuerungen vom Typ `Switch` bereitstellen. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst.

Die Steuerung bleibt standardmäßig deaktiviert. Weitere Control-Typen und
LoxBerry-Werkzeuge sind nicht Bestandteil dieser Version.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente lesen oder bedienen, für die dieses Konto berechtigt ist. Steuerzugriff benötigt zusätzlich die bewusste Aktivierung im Plugin und den separat bestätigten Scope `loxone:control`.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Phase 1 und Phase 2 sind abgenommen. Phase 2 ergänzt optional genau ein
kontrolliertes Schreibwerkzeug für Gen.-1-Controls vom Typ `Switch`. Es bleibt
standardmäßig deaktiviert, akzeptiert ausschließlich `on` und `off` und benötigt
den separat bestätigten Scope `loxone:control`. Die sechs stabilen lesenden
Tools und bestehende Read-only-Sitzungen bleiben kompatibel. Der zugehörige
Releasekandidat `0.2.0-alpha.1` ist noch nicht veröffentlicht.

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
python tools/test.py
```

`python tools/test.py` ist der einheitliche lokale und CI-Testbefehl. Er führt
Formatprüfung, Lint, strikte Typprüfung und die deterministischen Tests aus.

## Lizenz

Dieses Projekt steht unter der [Apache License 2.0](LICENSE).
