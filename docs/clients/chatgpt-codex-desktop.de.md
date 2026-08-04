# ChatGPT-/Codex-Desktop-App einrichten

Die ChatGPT-Desktop-App kann den LoxBerry MCP Server direkt per Streamable HTTP
und OAuth verwenden. Anders als bei Claude Desktop werden dafür weder Node.js
noch `npx` noch eine lokale Bridge benötigt.

## Vorbereitung

Vor der Einrichtung benötigst du:

- ein installiertes, eingerichtetes und aktiviertes LoxBerry-MCP-Server-Plugin;
- die HTTPS-Adresse deines LoxBerry, die vom Computer aus erreichbar ist;
- ein vom Computer als vertrauenswürdig erkanntes HTTPS-Zertifikat;
- die vollständige MCP-Adresse. Sie besteht aus der LoxBerry-Adresse und dem
  festen Pfad `/plugins/mcpserver/mcp`, zum Beispiel:

  ```text
  https://loxberry.local/plugins/mcpserver/mcp
  ```

Verwende hier die Adresse des **LoxBerry**, nicht die Adresse des Loxone
Miniservers. Trage keine Zugangsdaten in die URL ein.

Entscheide außerdem vor der Anmeldung, welche Rechte benötigt werden:

- Ist **Loxone-Steuerung** im Plugin deaktiviert, wird nur der Lesezugriff
  `loxone:read` angeboten.
- Ist **Loxone-Steuerung** aktiviert, bietet der Server zusätzlich
  `loxone:control` an. Die Desktop-App bevorzugt die vom Server angebotenen
  Scopes und fordert deshalb bei einer neuen Anmeldung beide Rechte an.

## MCP-Server hinzufügen

1. Öffne in der ChatGPT-Desktop-App die **Einstellungen**.
2. Öffne **Plugins > MCP**. Je nach App-Version heißt der Bereich direkt
   **MCP-Server**.
3. Wähle **MCP-Server hinzufügen**.
4. Vergib einen verständlichen Namen, zum Beispiel `LoxBerry MCP Server`.
5. Wähle als Typ ausdrücklich **Streamable HTTP**.
6. Trage die vollständige MCP-Adresse ein, zum Beispiel:

   ```text
   https://loxberry.local/plugins/mcpserver/mcp
   ```

7. Bestätige mit **Speichern**.
8. Sobald die App den Server gefunden hat, wähle **Authentifizieren**.
9. Im Browser öffnet sich die Freigabeseite des LoxBerry MCP Servers. Prüfe die
   angezeigten Rechte und bestätige die Anmeldung nur, wenn sie deiner Auswahl
   entsprechen.
10. Kehre anschließend zur Desktop-App zurück. Falls die App einen Neustart
    anbietet oder verlangt, führe ihn aus.

Der Server sollte danach als verbunden erscheinen. Über `/mcp` kannst du in der
Desktop-App die verbundenen MCP-Server kontrollieren.

## Lese- und Schreibrechte verstehen

Wenn die Loxone-Steuerung im Plugin aktiviert ist, fordert die Desktop-App bei
der Authentifizierung beide Scopes an:

```text
loxone:read loxone:control
```

Der Freigabedialog zeigt **Lesezugriff** verpflichtend und
**Loxone-Steuerung** als optionale Checkbox. Nur wenn die Steuerung ausgewählt
und bestätigt wird, stehen die sechs Lesewerkzeuge und das begrenzte
Switch-Schreibwerkzeug zur Verfügung. Das Schreibwerkzeug kann ausschließlich
freigegebene, sichtbare Gen.-1-Switches ein- oder ausschalten. Die tatsächlichen
Möglichkeiten bleiben zusätzlich durch die Rechte des angemeldeten
Loxone-Benutzers begrenzt.

Die Schreibrechte werden nicht nachträglich still hinzugefügt: Sie müssen auf
der Browser-Freigabeseite ausgewählt und dort bestätigt werden. Für reinen
Lesezugriff lässt du die optionale Checkbox deaktiviert.

Beim späteren Deaktivieren der Loxone-Steuerung widerruft das Plugin bestehende
Control-Sitzungen. Authentifiziere die Desktop-App danach erneut, um eine reine
Read-only-Sitzung zu erhalten.

## Fehlerbehebung

- **Server wird nicht gefunden:** Prüfe, ob **Streamable HTTP** gewählt wurde
  und die URL vollständig mit `/plugins/mcpserver/mcp` endet.
- **Zertifikatsfehler:** Öffne die LoxBerry-Adresse im Browser und behebe zuerst
  die Zertifikatswarnung. Deaktiviere die Zertifikatsprüfung nicht.
- **Authentifizieren fehlt:** Prüfe, ob der Server gespeichert und erreichbar
  ist. Öffne den Eintrag anschließend erneut.
- **Unerwartete Schreibrechte:** Widerrufe die Sitzung und authentifiziere dich
  erneut, ohne die optionale Steuerungsberechtigung auszuwählen.
- **Verbindung bleibt ausstehend:** Starte die Desktop-App neu und kontrolliere
  den Server anschließend über `/mcp`.

Weiterführend: [Offizielle OpenAI-Dokumentation zu MCP](https://learn.chatgpt.com/docs/extend/mcp).
