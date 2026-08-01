# LoxBerry MCP Server

Das McpServer-Plugin betreibt einen [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)-Server direkt auf dem LoxBerry. KI-Assistenten und Agenten können damit den Zustand einer Loxone-Miniserver-Installation abfragen und Befehle an Steuerungen senden. Dabei verwendet das Plugin die vorhandenen Räume, Kategorien und Steuerungsnamen – ohne eigenen Cloud-Dienst.

Zusätzlich stellt der MCP-Server ausgewählte Informationen und Funktionen der lokalen LoxBerry-Installation für KI-Assistenten und Agenten bereit.

## Sicherheit und Berechtigungen

Der Zugriff auf Loxone-Funktionen ist durch den Loxone-Login geschützt. Ein verbindender Assistent muss sich mit einem Loxone-Benutzerkonto anmelden und kann nur die Elemente sehen und bedienen, für die dieses Konto berechtigt ist.

Für jeden Assistenten sollte ein eigener Loxone-Benutzer mit den minimal erforderlichen Rechten angelegt werden. Zugangsdaten und andere Geheimnisse dürfen nicht im Repository gespeichert werden.

## Projektstatus

Das Plugin befindet sich im Aufbau. Installations-, Konfigurations- und Nutzungsanleitungen werden zusammen mit der ersten lauffähigen Version ergänzt.

## Lizenz

Dieses Projekt steht unter der [Apache License 2.0](LICENSE).
