# Einstieg

[English](getting-started.en.md)

## Voraussetzungen

- LoxBerry 4.0.0 oder neuer.
- Ein eigener Loxone-Benutzer mit möglichst kleinen Rechten.
- Gen. 1 über eine lokale HTTP-Adresse; Gen. 2 über HTTPS mit gültigem Zertifikat.
- Keine Zugangsdaten in URLs; HTTP Basic Auth wird nicht unterstützt.

## Installation und erste Verbindung

1. Installiere das Release-ZIP im LoxBerry Plugin Manager.
2. Öffne **LoxBerry MCP Server** und trage die lokale HTTPS-Origin des LoxBerry ein.
3. Wähle einen konfigurierten Miniserver oder gib den kanonischen Endpunkt ein.
4. Prüfe die Verbindung, aktiviere **MCP-Zugriff aktivieren** und speichere die MCP-Konfiguration.
5. Verbinde einen Client mit `https://<loxberry>/plugins/mcpserver/mcp` und folge dem OAuth-Login.

Die verwendete HTTPS-Adresse muss zum Webserver-Zertifikat passen. Die Plugin-Hilfe bietet kopierbare Hostname- und IP-Adressen.

Weiter: [Konfiguration](configuration.de.md) und [Client einrichten](../clients/README.md).
