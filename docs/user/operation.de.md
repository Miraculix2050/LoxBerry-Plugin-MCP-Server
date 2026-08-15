# Betrieb

[English](operation.en.md)

## Updates

Der Plugin Manager erkennt reguläre Updates über die stabile Releasequelle. Vorabversionen werden nur angeboten, wenn sie dort ausdrücklich zugelassen sind. Halte vor einem Update einer Vorabversion ein funktionierendes vorheriges Paket für einen Rückweg bereit.

## Sitzungen und Freigaben

Unter **Clients und Sitzungen** können Administratoren Sitzungen und lokale Diagnose- oder Operate-Freigaben prüfen und widerrufen. Ein Widerruf beendet passende Sitzungen.

## Tool Explorer

Der [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) ist ein lokaler administrativer Testclient. Er meldet sich mit einem Loxone-Benutzer an und erhält keine Rechte aus der LoxBerry-Admin-Sitzung. Ersetze `loxberry` im Link bei Bedarf durch den Hostnamen deiner Installation. Ändernde Aufrufe verlangen vor dem Senden eine Bestätigung.
RFC-3339-Zeitfelder werden als lokale Datum-/Zeitfelder angezeigt und als UTC übermittelt.

MCP-Clients erhalten die auf der konkreten Installation veröffentlichten Werkzeugbeschreibungen sowie deren Ein- und Ausgabeschemas über die MCP-Methode `tools/list`. Der Tool Explorer liest genau diese Antwort und visualisiert sie. Unter **Hilfe** stehen außerdem eine statische HTML-Referenz des vollständigen Werkzeugvertrags dieser Plugin-Version und dieselben Daten als JSON-Download bereit.

Weiter: [Fehlerbehebung](troubleshooting.de.md).
