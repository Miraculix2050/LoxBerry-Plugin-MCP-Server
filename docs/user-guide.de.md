# LoxBerry MCP Server 0.2.0-alpha.1

## Voraussetzungen

- LoxBerry 4.0.0 oder neuer; Referenzsystem ist 4.0.0.14 auf Debian 13/arm64.
- Ein eigener Loxone-Benutzer mit möglichst kleinen Lese- und, falls benötigt,
  gezielt vergebenen Switch-Rechten.
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

Für Claude Desktop steht eine kurze
[Schritt-für-Schritt-Anleitung](clients/claude-desktop.de.md) mit fertigem
Konfigurationsbeispiel und Fehlerhilfe bereit.

Die sechs Lesetools bleiben standardmäßig aktiv. Für die optionale Bedienung
von Gen.-1-Switches aktiviere zusätzlich **Loxone-Steuerung**. Danach ist eine
neue OAuth-Freigabe mit `loxone:control` erforderlich. Deaktivieren widerruft
bestehende Control-Sitzungen; reine Lesesitzungen bleiben gültig. Bei einem
Gen.-2-/HTTPS-Ziel kann die Steuerung nicht aktiviert werden.

Speichern, Verbindungstest und Sitzungswiderruf funktionieren auch ohne
JavaScript. Mit JavaScript werden Status, Test und Widerruf ohne Seitenwechsel
aktualisiert.

## Umfang und Betrieb

Die Alpha veröffentlicht sechs dokumentierte `loxone_*`-Lesetools und optional
`loxone_operate_control`. Das Schreibtool akzeptiert ausschließlich eine
sichtbare Control-UUID vom Typ `Switch` und die Aktion `on` oder `off`. Es bietet
keine Namens-, Raum-, Bulk- oder freien Kommandos. Historie, LoxBerry-Tools und
Basic Auth bleiben ausgeschlossen. Ergebnisse und Aktionen entsprechen den
Rechten des angemeldeten Loxone-Benutzers.

Der englische Healthcheck führt keine Reparatur aus:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Logs erscheinen im LoxBerry-Logviewer. Der Diagnoseexport enthält nur Version,
Dienststatus, Transportart und maskierte Zähler. Sitzungen können einzeln oder
gemeinsam widerrufen werden; ein erreichbarer Miniserver erhält zusätzlich
best effort `killtoken`.

Jeder Schreibversuch erzeugt einen kompakten maskierten Eintrag im bestehenden
Service-Log. Wiederholte identische Ablehnungen werden gedrosselt; eine separate
Auditdatei wird nicht angelegt.

## Rücksetzen

Deaktiviere zuerst den Dienst in der UI. Bei einer fehlerhaften Vorabversion
kann das vorherige Plugin-ZIP über den Plugin Manager erneut installiert
werden. Konfiguration, Sitzungen, verschlüsselte Loxone-Tokens und der lokale
Installationsschlüssel bleiben beim Upgrade gemeinsam erhalten, sodass eine
gültige Sitzung anschließend ohne erneute Anmeldung weiterverwendet werden
kann. Eine Deinstallation entfernt Dienst, Apache-Regel und die enge
sudoers-Regel nur, wenn sie eindeutig dem Plugin gehören.
