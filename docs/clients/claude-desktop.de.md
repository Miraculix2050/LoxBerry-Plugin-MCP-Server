# Claude Desktop verbinden

Diese Anleitung richtet Claude Desktop unter Windows für den LoxBerry MCP
Server ein. Claude verwendet dabei eine kleine lokale Bridge. Die Verbindung
zum LoxBerry bleibt im lokalen Netzwerk und wird nicht über einen
Claude-Cloud-Connector hergestellt.

## Vorher prüfen

- Das Plugin ist eingerichtet, aktiviert und der Verbindungstest ist
  erfolgreich.
- Claude Desktop ist installiert.
- Node.js mit `npx` ist installiert. Öffne bei Bedarf PowerShell und prüfe dies
  mit `npx --version`. Wird der Befehl nicht gefunden, installiere zuerst eine
  aktuelle LTS-Version von [Node.js](https://nodejs.org/). Beim ersten Start
  lädt `npx` die festgelegte Bridge-Version einmalig aus dem npm-Register.
- Halte die im Plugin eingetragene HTTPS-Adresse des LoxBerry bereit. Ergänzt
  um `/plugins/mcpserver/mcp` ergibt sie die MCP-Adresse. Dafür ist keine
  Veröffentlichung des LoxBerry im Internet erforderlich.

Benutzernamen, Passwörter und Tokens gehören **nicht** in die Konfigurationsdatei.
Die Anmeldung erfolgt später geschützt im Browser.

## MCP-Server hinzufügen

1. Öffne in Claude Desktop **Einstellungen → Entwickler** und wähle
   **Konfiguration bearbeiten**.
2. Ergänze den Eintrag `loxberry-mcp` in der geöffneten Datei. Ersetze nur die
   Beispieladresse durch deine vollständige MCP-Adresse:

   ```json
   {
     "mcpServers": {
       "loxberry-mcp": {
         "command": "npx",
         "args": [
           "-y",
           "mcp-remote@0.1.38",
           "https://loxberry.example/plugins/mcpserver/mcp",
           "--transport",
           "http-only"
         ]
       }
     }
   }
   ```

   Sind bereits andere MCP-Server eingetragen, behalte diese und füge nur den
   neuen Block hinzu. Achte auf gültiges JSON und die notwendigen Kommas.
3. Speichere die Datei und beende Claude Desktop vollständig. Öffne Claude
   danach erneut.
4. Beim ersten Verbindungsaufbau öffnet sich die Anmeldung im Browser. Melde
   dich mit dem dafür vorgesehenen Loxone-Benutzer an und bestätige den Zugriff.
5. Öffne in einem Claude-Chat über **+ → Connectors** die Liste der Verbindungen.
   `loxberry-mcp` und seine Werkzeuge müssen dort verfügbar sein. Den Status und
   die MCP-Logs findest du zusätzlich unter **Einstellungen → Entwickler**.

## Wenn es nicht funktioniert

- **`npx` wurde nicht gefunden:** Installiere Node.js und starte Claude danach
  neu.
- **Der Server erscheint nicht:** Öffne die Konfiguration erneut über Claude.
  Prüfe Schreibweise, Kommas und Klammern. Beende anschließend wirklich alle
  Claude-Fenster und starte die App neu.
- **Microsoft-Store-Version:** Verwende immer **Konfiguration bearbeiten** in
  Claude. Diese Version kann ihre aktive Datei in einem Store-Profil statt im
  klassischen `%APPDATA%`-Ordner ablegen.
- **Keine Anmeldung oder keine Verbindung:** Prüfe, ob die MCP-Adresse im
  Browser grundsätzlich zum LoxBerry führt und ob der Dienst in der
  Plugin-Oberfläche aktiv ist. Veröffentliche die Adresse oder Fehlermeldungen
  nicht unmaskiert.
- **Zugriff neu erteilen:** Widerrufe die betroffene Sitzung in der
  Plugin-Oberfläche und verbinde Claude erneut.

Getestete Versionen und bekannte Einschränkungen stehen in der
[Support-Matrix](../development/support-matrix.md).

Weiterführend: [Claude-Dokumentation zu lokalen MCP-Servern](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
und [`mcp-remote`](https://github.com/geelen/mcp-remote).
