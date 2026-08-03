# LoxBerry MCP Server

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. KI-Assistenten und Agenten können damit den Zustand einer Loxone-Miniserver-Installation abfragen und Befehle an Steuerungen senden. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst.

Zusätzlich stellt der MCP-Server ausgewählte Informationen und Funktionen der lokalen LoxBerry-Installation für KI-Assistenten und Agenten bereit.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente sehen und bedienen, für die dieses Konto berechtigt ist.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Phase 0 ist abgeschlossen. Runtime, Apache-Transport, OAuth-Server sowie die
Gen.-1-Loxone-/WebSocket-Anbindung sind auf der dokumentierten Referenzplattform
bestätigt. Der nächste Meilenstein ist Phase 1, die lokale Read-only Alpha mit
Pluginlayout, Dienst, Admin-UI und den ersten stabilen lesenden Tools.

Es gibt noch kein installierbares Testpaket. Die bestätigten Kombinationen und
bekannten Clientgrenzen stehen in der [Support-Matrix](docs/development/support-matrix.md).

## Entwicklung

- [Implementierungsrichtlinien](docs/development/implementation-guidelines.md)
- [Plugin-Konzept](docs/development/plugin-concept.md)
- [Änderungsgetriebene Teststrategie](docs/development/test-strategy.md)
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
