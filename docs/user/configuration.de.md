# Konfiguration

[English](configuration.en.md)

## Grundeinstellungen

Konfiguriere eine lokale HTTPS-Origin und genau ein Miniserver-Ziel. Die Auswahl eines in LoxBerry hinterlegten Miniservers übernimmt keine dort gespeicherten Zugangsdaten. Das erste Speichern einer vollständigen, gültigen Einrichtung aktiviert den Server; prüfe die Verbindung vor dem produktiven Einsatz.

## Zertifikat

Verwende für MCP-Clients eine Adresse, die vom LoxBerry-Webserverzertifikat abgedeckt wird. Die Zertifikatsdiagnose zeigt verständlich, ob die konfigurierte Origin passt. Eine lokale Zertifikatsneuausstellung benötigt SecurePIN und eine Bestätigung; externe Zertifikate werden nicht verändert.

## Funktionsfreigaben

Lesezugriff sowie Historie/Statistiken und LoxBerry-Diagnose sind grundsätzlich verfügbar. Der Client muss den passenden Scope zusätzlich anfordern und der Benutzer bestätigen; LoxBerry-Diagnose benötigt außerdem eine lokale Freigabe.

Weiter: [Berechtigungen](permissions.de.md).
