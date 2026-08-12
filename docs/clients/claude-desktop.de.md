# Claude Desktop verbinden

Diese Anleitung richtet Claude Desktop unter Windows für den LoxBerry MCP
Server ein. Claude startet dafür auf dem Computer eine kleine lokale Bridge
namens `mcp-remote`. Die Verbindung zum LoxBerry bleibt im lokalen Netzwerk und
wird nicht über einen Claude-Cloud-Connector hergestellt.

## Vorbereitung

### 1. Plugin und MCP-Adresse vorbereiten

- Das Plugin ist eingerichtet und aktiviert. Der Verbindungstest in der
  Plugin-Oberfläche ist erfolgreich.
- Verwende die dort eingetragene HTTPS-Adresse des **LoxBerry**, nicht die
  Adresse des Miniservers. Ergänze `/plugins/mcpserver/mcp`, zum Beispiel:

  ```text
  https://loxberry.example/plugins/mcpserver/mcp
  ```

- Veröffentliche die Adresse nicht im Internet. Der Computer mit Claude muss den
  LoxBerry lediglich im lokalen Netzwerk erreichen können.
- Benutzernamen, Passwörter und Tokens gehören weder in die MCP-Adresse noch in
  die Claude-Konfiguration. Die Anmeldung erfolgt später geschützt im Browser.

### 2. Node.js und npx installieren

`mcp-remote` ist ein Node.js-Programm. `npx` gehört zu npm und startet ein
solches Programm, ohne dass du dessen Installationsordner selbst suchen musst.

1. Lade die aktuelle **LTS-Version** von [Node.js](https://nodejs.org/) herunter.
2. Führe den Windows-Installer mit den vorgeschlagenen Komponenten aus und
   behalte die Aufnahme in `PATH` aktiviert. npm und `npx` werden dabei
   mitinstalliert; `npx` wird nicht separat heruntergeladen.
3. Schließe bereits geöffnete PowerShell-Fenster. Öffne PowerShell neu und
   prüfe die Installation:

   ```powershell
   node --version
   npm.cmd --version
   npx.cmd --version
   ```

Die `.cmd`-Form vermeidet dabei mögliche PowerShell-Execution-Policy-Fehler mit
den ebenfalls installierten `.ps1`-Startdateien. Alle drei Befehle müssen eine
Versionsnummer ausgeben. Beim ersten Start durch
Claude lädt `npx` die festgelegte Version `mcp-remote@0.1.38` einmalig aus dem
npm-Register in den lokalen npm-Cache. Danach kann diese Version aus dem Cache
erneut verwendet werden. Für eine bewusst dauerhaft offline gehaltene
Installation ist dagegen der unten beschriebene direkte Node-Aufruf gedacht.

### 3. Den richtigen npx-Pfad ermitteln

Normalerweise reicht in Claude der kurze Befehl `npx`. Falls Claude später
meldet, dass `npx` nicht gefunden wurde, ermittle den vollständigen Pfad in
PowerShell:

```powershell
where.exe npx
```

Verwende die ausgegebene Zeile, die auf `npx.cmd` endet. Ein typisches Ergebnis
ist `C:\Program Files\nodejs\npx.cmd`. Wird ein vollständiger Windows-Pfad in
JSON eingetragen, muss jeder umgekehrte Schrägstrich doppelt geschrieben werden:

```json
"command": "C:\\Program Files\\nodejs\\npx.cmd"
```

Der bei einer vorbereiteten Testinstallation sichtbare Pfad zu einer Codex-
Laufzeit ist **kein** allgemeiner Node.js-Pfad und darf nicht kopiert werden.

## Read-only-Verbindung einrichten

1. Öffne in Claude Desktop **Einstellungen → Entwickler** und wähle
   **Konfiguration bearbeiten**. Verwende immer diesen Menüpunkt, damit auch die
   Microsoft-Store-Version ihre tatsächlich aktive Datei öffnet.
2. Ergänze den Eintrag `loxberry-mcp`. Ersetze nur die Beispieladresse durch
   deine vollständige MCP-Adresse:

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
         ],
         "env": {
           "NODE_USE_SYSTEM_CA": "1"
         }
       }
     }
   }
   ```

   `-y` beantwortet die einmalige npm-Rückfrage automatisch. Die Einstellung
   `NODE_USE_SYSTEM_CA` erlaubt einer aktuellen Node.js-Version zusätzlich die
   unter Windows als vertrauenswürdig hinterlegten Zertifikate zu verwenden.
   Sie schaltet die Zertifikatsprüfung nicht aus.

   Sind bereits andere MCP-Server eingetragen, behalte diese und füge nur den
   neuen Block sowie das notwendige Komma hinzu.
3. Speichere die Datei und beende Claude Desktop vollständig. Öffne Claude
   danach erneut.
4. Beim ersten Verbindungsaufbau öffnet sich die Anmeldung im Browser. Melde
   dich mit dem dafür vorgesehenen Loxone-Benutzer an und bestätige den Zugriff.
5. Öffne in einem Claude-Chat **+ → Connectors**. `loxberry-mcp` und seine
   Werkzeuge müssen dort verfügbar sein. Status und MCP-Logs findest du
   zusätzlich unter **Einstellungen → Entwickler**.

### Scope für Read-only

Für die sechs Lesewerkzeuge muss kein Scope in die Claude-Konfiguration
geschrieben werden. Ohne ausdrückliche Angabe fordert die Bridge ausschließlich
`loxone:read` an. Kontrolliere diesen Scope vor der Bestätigung auf der
Freigabeseite im Browser.

## Optionale Loxone-Steuerung

> **Mit Claude abgenommen:** Registrierung, Freigabe mit `loxone:control`,
> Werkzeugsichtbarkeit und ein realer Aufruf wurden vollständig bestätigt. Der
> sichere Standard bleibt Read-only. Der Nachweis steht im
> [Phase-2-Abnahmebericht](../development/phase-2-acceptance.md).

Dieser Abschnitt gilt nur, wenn in der Plugin-Oberfläche unter **Zugriff auf den
Miniserver über den MCP Server** bewusst **Lesen und steuern** gewählt wurde.
Für normalen Lesezugriff ist er nicht erforderlich.

Die Steuerung benötigt immer beide Scopes:

```text
loxone:read loxone:control
```

`loxone:control` allein ist ungültig. Bestehende Read-only-Sitzungen erhalten
den zusätzlichen Scope nicht automatisch.

1. Wähle im Plugin **Lesen und steuern** und speichere die Konfiguration.
2. Erstelle den lokalen Ordner `C:\Users\Public\LoxBerryMCP` und darin die Datei
   `loxberry-oauth-client.json` mit diesem Inhalt:

   ```json
   {
     "scope": "loxone:read loxone:control"
   }
   ```

   Die Datei enthält keine Zugangsdaten und darf trotzdem nur lokal bleiben.
3. Ergänze am Ende der bestehenden `args`-Liste nach `"http-only"`:

   ```json
   "--static-oauth-client-metadata",
   "@C:\\Users\\Public\\LoxBerryMCP\\loxberry-oauth-client.json"
   ```

   Der vollständige Ausschnitt lautet dann:

   ```json
   "args": [
     "-y",
     "mcp-remote@0.1.38",
     "https://loxberry.example/plugins/mcpserver/mcp",
     "--transport",
     "http-only",
     "--static-oauth-client-metadata",
     "@C:\\Users\\Public\\LoxBerryMCP\\loxberry-oauth-client.json"
   ]
   ```

4. Widerrufe die bisherige Claude-Sitzung in der Plugin-Oberfläche. Beende
   Claude vollständig und starte es neu.
5. Melde dich erneut an. Die Freigabeseite zeigt den verpflichtenden
   **Lesezugriff** und zusätzlich die optionale **Loxone-Steuerung**. Aktiviere
   die Steuerungs-Checkbox nur, wenn diese Erweiterung beabsichtigt ist. Fehlt
   die Auswahlmöglichkeit, verwende die Steuerung nicht und bleibe bei der
   geprüften Read-only-Einrichtung.

Wird im Plugin später **Nur lesen** ausgewählt, werden Sitzungen mit
`loxone:control` widerrufen. Für erneuten reinen Lesezugriff entfernst du die
beiden Metadatenargumente wieder und verbindest Claude neu.

## Warum eine vorbereitete Konfiguration anders aussehen kann

Eine vorbereitete oder offline gehaltene Testinstallation kann direkt eine
bestimmte `node.exe` und eine bereits lokal installierte `proxy.js` starten. Das
ist dieselbe Bridge, nur ohne die Paketauflösung durch `npx`:

```text
npx mcp-remote@0.1.38 ...
        oder
node.exe <lokaler Pfad zu proxy.js> ...
```

Der direkte Weg startet die Bridge nach der Vorbereitung vollständig aus lokalen
Dateien, benötigt aber einen eigens installierten Paketordner und dauerhaft
gültige absolute Pfade. Für normale Benutzer ist deshalb `npx` der einfachere
Standard. Kopiere niemals benutzerspezifische Node-, Codex- oder Projektpfade
von einem anderen Computer.

## Wenn es nicht funktioniert

- **`npx` wurde nicht gefunden:** Prüfe die drei Versionsbefehle und verwende
  danach den mit `where.exe npx` ermittelten vollständigen `npx.cmd`-Pfad.
- **Der Server erscheint nicht:** Öffne die Konfiguration erneut über Claude.
  Prüfe Schreibweise, Kommas und Klammern und starte alle Claude-Prozesse neu.
- **Zertifikatsfehler:** Das LoxBerry-Zertifikat muss für die verwendete Adresse
  gültig und unter Windows vertrauenswürdig sein. `NODE_USE_SYSTEM_CA` umgeht
  weder eine abgelaufene Bescheinigung noch einen falschen Hostnamen.
- **Keine Anmeldung oder Verbindung:** Prüfe die MCP-Adresse und den
  Dienststatus in der Plugin-Oberfläche. Veröffentliche Adresse und Logs nur
  maskiert.
- **Steuerungswerkzeug fehlt:** Prüfe Aktivierung, Metadatendatei, die beim
  OAuth-Dialog ausgewählte Steuerungsberechtigung und den Widerruf der alten
  Read-only-Sitzung.

Getestete Versionen und bekannte Einschränkungen stehen in der
[Support-Matrix](../development/support-matrix.md).

Weiterführend: [Claude-Dokumentation zu lokalen MCP-Servern](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop),
[npm-Dokumentation zu `npx`](https://docs.npmjs.com/cli/commands/npx/) und
[`mcp-remote`](https://github.com/geelen/mcp-remote).
