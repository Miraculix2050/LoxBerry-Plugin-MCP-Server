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

Der Server veröffentlicht immer alle bekannten OAuth-Scopes. Die Checkboxen in
der Plugin-Konfiguration ändern diese Liste nicht; sie sind globale
Funktionsfreigaben. Die tatsächlich für eine Anmeldung erteilten Rechte werden
erst nach der Loxone-Anmeldung im OAuth-Berechtigungsdialog ausgewählt.

Die derzeit bekannte ChatGPT-/Codex-Desktop-App bevorzugt die vom Server
veröffentlichten Scopes und kann daher bei einer neuen Anmeldung alle fünf
anfordern:

```text
loxone:read loxone:history loxone:control loxberry:read loxberry:operate
```

Das bedeutet noch nicht, dass alle Rechte erteilt oder administrativ
freigegeben sind. Prüfe die im Browser angezeigte Auswahl bei jeder neuen
Anmeldung; das genaue Clientverhalten kann sich mit einer App-Version ändern.

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

## Berechtigungen und Adminfreigaben verstehen

Der Freigabedialog zeigt `loxone:read` verpflichtend. Die übrigen Scopes sind
optionale Checkboxen:

| Scope | Wirkung | Zusätzliche Freigabe |
| --- | --- | --- |
| `loxone:read` | Sichtbare Loxone-Struktur und aktuelle Zustände lesen | immer aktiv |
| `loxone:history` | Historie und Statistiken lesen | globale Admin-Checkbox |
| `loxone:control` | Unterstützte sichtbare Controls gezielt bedienen | globale Admin-Checkbox |
| `loxberry:read` | LoxBerry- und Plugin-Diagnosen lesen | globale und lokale Administratorfreigabe |
| `loxberry:operate` | Plugin-eigenen Statistik-Cache löschen | `loxone:history` sowie globale und lokale Administratorfreigabe |

`loxberry:operate` kann im Consent nur zusammen mit `loxone:history` bestätigt
werden. Für reinen Lesezugriff lässt du alle optionalen Checkboxen deaktiviert.

OAuth-Consent und Adminfreigabe sind zwei getrennte Prüfungen: Ein optionaler
Scope darf bereits im Token stehen, obwohl seine Funktion in der
Plugin-Konfiguration noch nicht aktiviert oder lokal freigegeben ist. Das
betroffene Werkzeug antwortet dann kontrolliert mit `permission_denied`. Es ist
keine weitere Berechtigungsauswahl in der Desktop-App oder im Tool Explorer
erforderlich.

Loxone-Steuerungen bleiben zusätzlich auf sichtbare Controls, dokumentierte
Aktionen und die Rechte des angemeldeten Loxone-Benutzers begrenzt.
LoxBerry-Freigaben sind an den konkreten OAuth-Client, die Loxone-Identität und
den Miniserver gebunden. Beim Deaktivieren einer optionalen globalen Freigabe
widerruft das Plugin passende Sitzungen; eine neue Berechtigung wird nie still
zu einer bestehenden Sitzung hinzugefügt.

## Fehlerbehebung

- **Server wird nicht gefunden:** Prüfe, ob **Streamable HTTP** gewählt wurde
  und die URL vollständig mit `/plugins/mcpserver/mcp` endet.
- **Zertifikatsfehler:** Öffne die LoxBerry-Adresse im Browser und behebe zuerst
  die Zertifikatswarnung. Deaktiviere die Zertifikatsprüfung nicht.
- **Authentifizieren fehlt:** Prüfe, ob der Server gespeichert und erreichbar
  ist. Öffne den Eintrag anschließend erneut.
- **Unerwartete Schreibrechte:** Widerrufe die Sitzung und authentifiziere dich
  erneut, ohne `loxone:control` oder `loxberry:operate` auszuwählen.
- **`permission_denied` trotz bestätigtem Scope:** Aktiviere die zugehörige
  globale Funktionsfreigabe. Für `loxberry:read` und `loxberry:operate` muss der
  Administrator zusätzlich die konkrete Anmeldung lokal freigeben.
- **Verbindung bleibt ausstehend:** Starte die Desktop-App neu und kontrolliere
  den Server anschließend über `/mcp`.

Weiterführend: [Offizielle OpenAI-Dokumentation zu MCP](https://learn.chatgpt.com/docs/extend/mcp).
