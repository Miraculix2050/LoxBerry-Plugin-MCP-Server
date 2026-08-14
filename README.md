# LoxBerry MCP Server

> Install the ZIP asset from a project GitHub Release. GitHub's automatic
> **Source code** archives are not LoxBerry plugin packages. Local packages
> containing `-local-` are intended only for testing.

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. Die aktuelle Alpha erlaubt KI-Assistenten und Agenten standardmäßig ausschließlich, den Zustand einer Loxone-Miniserver-Installation zu lesen. Optional kann ein eng begrenztes Loxone-Schreibwerkzeug aktiviert werden. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst. Optional stehen ausschließlich lesende, maskierte LoxBerry-Diagnosen bereit.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente lesen oder bedienen, für die dieses Konto berechtigt ist. Steuerzugriff benötigt zusätzlich die bewusste Aktivierung im Plugin und den separat bestätigten Scope `loxone:control`.

Die optionale LoxBerry-Diagnose ist standardmäßig deaktiviert. Sie zeigt nur
maskierte System-, Plugin- und Dienststatusdaten sowie begrenzte,
server-erzeugte Ereignisfelder aus dem festen plugin-eigenen Service-Log.
`loxberry:read` benötigt eine
lokale Administratorfreigabe für exakt Client, Loxone-Identität und Miniserver.
Ein Client kann sie zusammen mit den Loxone-Scopes anfordern; bis zur Freigabe
bleibt die Diagnose ausstehend. Sie erlaubt keine
Reparatur, Neustarts oder andere LoxBerry-Aktionen.

Phase 4 ergänzt separat aktivierbare StatisticV2-, klassische Binärstatistik- und Control-Historie mit
`loxone:history`, sichtbare Darstellungsmetadaten sowie begrenzte Control-Hinweise
über `loxone:read`. `loxberry:operate` nutzt denselben lokalen Freigabemechanismus
und erlaubt ausschließlich das Löschen des plugin-eigenen Statistik-Caches.
Legacy-Statistik über XML/FTP und mehrere Miniserver sind nicht aktiviert.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Phase 1 bis Phase 3 sind abgenommen. Der vorbereitete Phase-4-Pre-Release
`0.4.0-alpha.14` stoppt den Dienst mit der begrenzten vorhandenen
Systemfreigabe vor einer Upgrade-Datenmigration und
behandelt eine temporäre Miniserver-IP-Sperre auch während eines WebSocket-Sends
als wiederherstellbaren Verbindungsfehler. Es enthält außerdem die begrenzten
LoxAPP3-Modelle für Klima, Lüftung, Status, Energie und globale Metadaten sowie
nur dokumentierte temporäre Overrides. Die vorherige `0.4.0-alpha.8` blockiert die MCP-Tool-Explorer-Anmeldung auf HTTP mit einem
Link zur gleichen IP-Adresse oder demselben Hostnamen über HTTPS sowie die versionsgeprüfte, begrenzte single-flight
LoxAPP3-Aktualisierung, einen kontrollierten Runtime-Shutdown und einen
ausschließlich flüchtigen Statistik-Cache. Das Schreibwerkzeug unterstützt auf Gen.-1-Controls die Typen
`Switch`, `Dimmer`, `LightController`, `LightControllerV2`, `Jalousie`,
`TimedSwitch`, `Radio`, `LightsceneRGB`, `ColorPicker`, `ColorPickerV2` und
`Pushbutton`. Es bleibt
standardmäßig deaktiviert, akzeptiert ausschließlich typabhängige dokumentierte
Aktionen und benötigt den separat bestätigten Scope `loxone:control`. Freie
Kommandos, Namens- und Sammelziele sind ausgeschlossen. Die sechs stabilen
lesenden Tools und bestehende Read-only-Sitzungen bleiben kompatibel. Die neuen
Phase-4-Pfade sind automatisiert geprüft; die abgegrenzten Hardware-Nachweise
stehen im Phase-4-Abnahmebericht.

Bestätigte Kombinationen, Nachweise und bekannte Clientgrenzen stehen in der
[Support-Matrix](docs/development/support-matrix.md), im
[Phase-1-Abnahmebericht](docs/development/phase-1-acceptance.md) und im
[Phase-2-Abnahmebericht](docs/development/phase-2-acceptance.md).
Der aktuelle Nachweisstand steht im
[Phase-4-Abnahmebericht](docs/development/phase-4-acceptance.md).

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

```powershell
.\tools\setup-development-environment.ps1
```

Das Skript sucht Python 3.13 zuerst im üblichen benutzerspezifischen
Installationspfad und legt `.venv` an. Ein anderer Interpreter oder Pfad kann
über `-PythonPath` beziehungsweise `-VenvPath` angegeben werden; `-DryRun`
prüft die Auflösung ohne Dateien oder Abhängigkeiten zu ändern.

Manuell entspricht das:

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
