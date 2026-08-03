# LoxBerry MCP Server 0.1.0-alpha.1

## Voraussetzungen

- LoxBerry 4.0.0 oder neuer; Referenzsystem ist 4.0.0.14 auf Debian 13/arm64.
- Ein eigener Loxone-Benutzer mit möglichst kleinen Leserechten.
- Gen. 1: private lokale HTTP-Adresse. Gen. 2: gültige HTTPS-Adresse mit
  vertrauenswürdigem Zertifikat; derzeit experimentell.
- Keine Zugangsdaten in URLs. Basic Auth wird nicht unterstützt.

## Installation und Einrichtung

Installiere das ZIP über den normalen LoxBerry Plugin Manager. Das Paket bringt
alle Python-Wheels offline mit. Öffne danach **LoxBerry MCP Server**:

1. Trage die lokale HTTPS-Origin des LoxBerry ein, z. B.
   `https://loxberry.local`.
2. Trage den kanonischen Miniserver-Endpunkt ein: Gen. 1 beispielsweise
   `http://192.168.1.20`, Gen. 2 ausschließlich `https://miniserver.example`.
3. Prüfe die Verbindung, aktiviere den Dienst und speichere.
4. Verbinde Codex CLI oder Claude Desktop mit
   `https://loxberry.local/plugins/mcpserver/mcp` und folge dem OAuth-Login.

Speichern, Verbindungstest und Sitzungswiderruf funktionieren auch ohne
JavaScript. Mit JavaScript werden Status, Test und Widerruf ohne Seitenwechsel
aktualisiert.

## Umfang und Betrieb

Die Alpha veröffentlicht ausschließlich die sechs dokumentierten
`loxone_*`-Lesetools. Sie bietet keine Steuerbefehle, Historie, LoxBerry-Tools,
Basic Auth oder generischen Kommandos. Ergebnisse entsprechen den Sichtrechten
des angemeldeten Loxone-Benutzers.

Der englische Healthcheck führt keine Reparatur aus:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Logs erscheinen im LoxBerry-Logviewer. Der Diagnoseexport enthält nur Version,
Dienststatus, Transportart und maskierte Zähler. Sitzungen können einzeln oder
gemeinsam widerrufen werden; ein erreichbarer Miniserver erhält zusätzlich
best effort `killtoken`.

## Rücksetzen

Deaktiviere zuerst den Dienst in der UI. Bei einer fehlerhaften Vorabversion
kann das vorherige Plugin-ZIP über den Plugin Manager erneut installiert
werden. Konfiguration und Sitzungen bleiben beim Upgrade erhalten. Eine
Deinstallation entfernt Dienst, Apache-Regel und die enge sudoers-Regel nur,
wenn sie eindeutig dem Plugin gehören.
