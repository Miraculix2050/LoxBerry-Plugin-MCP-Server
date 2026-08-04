# LoxBerry MCP Server

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. Die aktuelle Alpha erlaubt KI-Assistenten und Agenten ausschließlich, den Zustand einer Loxone-Miniserver-Installation zu lesen. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst.

Schreibaktionen und LoxBerry-Werkzeuge sind nicht Bestandteil dieser Version.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente lesen, für die dieses Konto berechtigt ist.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Phase 1 ist abgeschlossen. `0.1.0-alpha.1` ist das installierbare Read-only-
Prerelease mit nativem Pluginlayout, Dienst, responsiver Admin-UI, OAuth und
sechs stabilen lesenden Tools. Die Referenzkombination wurde real auf LoxBerry
4.0.0.14, Debian 13/aarch64 und einem Gen.-1-Miniserver abgenommen.

Bestätigte Kombinationen, Nachweise und bekannte Clientgrenzen stehen in der
[Support-Matrix](docs/development/support-matrix.md) und im
[Phase-1-Abnahmebericht](docs/development/phase-1-acceptance.md).

## Entwicklung

- [Implementierungsrichtlinien](docs/development/implementation-guidelines.md)
- [Plugin-Konzept](docs/development/plugin-concept.md)
- [Änderungsgetriebene Teststrategie](docs/development/test-strategy.md)
- [Entwicklungs- und Testautomatisierung](docs/development/automation.md)
- [Support-Matrix](docs/development/support-matrix.md)
- [Recherche-Ergebnisse](docs/research/research-results.md)
- [Beitragen und Git-Workflow](CONTRIBUTING.md)

Die Referenzentwicklung verwendet Python 3.13. Nach dem Anlegen eines lokalen
virtuellen Environments werden die fixierten Laufzeit- und Testabhängigkeiten
installiert und das Projekt ohne erneute Abhängigkeitsauflösung eingebunden:

```text
python -m pip install -r requirements/runtime-arm64.lock -r requirements/dev.lock
python -m pip install --no-deps -e .
python tools/test.py
```

`python tools/test.py` ist der einheitliche lokale und CI-Testbefehl. Er führt
Formatprüfung, Lint, strikte Typprüfung und die deterministischen Tests aus.

## Lizenz

Dieses Projekt steht unter der [Apache License 2.0](LICENSE).
