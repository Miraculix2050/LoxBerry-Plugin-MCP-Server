# Einstieg

[English](getting-started.en.md)

## Voraussetzungen

- LoxBerry 4.0.0 oder neuer.
- Ein eigener Loxone-Benutzer mit möglichst kleinen Rechten.
- Gen. 1 über eine lokale HTTP-Adresse; Gen. 2 über HTTPS mit gültigem Zertifikat.
- Keine Zugangsdaten in URLs; HTTP Basic Auth wird nicht unterstützt.

Loxone-Verbindungen deaktivieren automatische WebSocket-Transport-Pings und
behalten den Loxone-Anwendungs-Keepalive mit seiner Timeout-Behandlung bei. Auf
dem untersuchten Gen.-1-Ziel lösten Transport-Pings eine unerwartete gzip-HTML-Datei
aus. Unerwartete Strukturdateien bleiben Fehler; sie werden weder dekodiert noch
übersprungen. Dieser Befund belegt keine Kompatibilität mit anderen Firmwareständen
oder Miniserver-Generationen.

## Installation und erste Verbindung

1. Installiere das Release-ZIP im LoxBerry Plugin Manager.
2. Öffne **LoxBerry MCP Server** und trage die lokale HTTPS-Origin des LoxBerry ein.
3. Wähle einen konfigurierten Miniserver oder gib den kanonischen Endpunkt ein.
4. Prüfe die Verbindung, aktiviere **MCP-Zugriff aktivieren** und speichere die MCP-Konfiguration.
5. Verbinde einen Client mit `https://<loxberry>/plugins/mcpserver/mcp` und folge dem OAuth-Login.

Die verwendete HTTPS-Adresse muss zum Webserver-Zertifikat passen. **MCP-Zugriff & HTTPS** bietet kopierbare Hostname- und IP-Adressen.

Weiter: [Konfiguration](configuration.de.md) und [Client einrichten](../clients/README.md).
