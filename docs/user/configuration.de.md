# Konfiguration

[English](configuration.en.md)

## Grundeinstellungen

Konfiguriere eine lokale HTTPS-Origin und genau ein Miniserver-Ziel. Die Auswahl eines in LoxBerry hinterlegten Miniservers übernimmt keine dort gespeicherten Zugangsdaten. Bei der ersten Einrichtung wird die Origin aus LoxBerry-Hostname und HTTPS-Port vorgeschlagen; prüfe, ob sie zur Zertifikatsadresse im Browser passt. Das erste Speichern einer vollständigen, gültigen Einrichtung aktiviert den Server.

## Zertifikat

Verwende für MCP-Clients eine Adresse, die vom LoxBerry-Webserverzertifikat abgedeckt wird. Die Zertifikatsdiagnose zeigt verständlich, ob die konfigurierte Origin passt. Eine lokale Zertifikatsneuausstellung benötigt SecurePIN und eine Bestätigung; externe Zertifikate werden nicht verändert.

Damit ein Endgerät das lokale Zertifikat akzeptiert, installiere dessen CA-Zertifikat `cacert.cer` auf dem Endgerät. Lade es in LoxBerry unter `https://<LoxBerry-Hostname>/admin/system/services.php` herunter.

### Windows

1. Öffne die heruntergeladene Datei `cacert.cer` per Doppelklick.
2. Wähle **Zertifikat installieren…**.
3. Wähle **Zertifikatsspeicher manuell auswählen** und danach **Vertrauenswürdige Stammzertifizierungsstellen**.
4. Schließe die Installation ab und öffne die HTTPS-Origin erneut.

### Android

1. Lade `cacert.cer` über die LoxBerry-Systemdienste auf das Gerät herunter.
2. Öffne **Einstellungen** und suche nach **Zertifikat installieren**. Je nach Hersteller liegt die Funktion beispielsweise unter **Sicherheit und Datenschutz** → **Weitere Sicherheitseinstellungen** → **Verschlüsselung und Anmeldedaten**.
3. Wähle **CA-Zertifikat** und dann die heruntergeladene Datei `cacert.cer`. Bestätige die Sicherheitsabfrage; eine Bildschirmsperre kann erforderlich sein.
4. Öffne die HTTPS-Origin erneut.

Installiere ein CA-Zertifikat nur von deinem eigenen, vertrauenswürdigen LoxBerry: Es erlaubt dem Gerät, Zertifikate dieser CA zu akzeptieren. Die genaue Menübezeichnung kann je nach Android-Version und Hersteller abweichen.

## Funktionsfreigaben

Lesezugriff sowie Historie/Statistiken und LoxBerry-Diagnose sind grundsätzlich verfügbar. Der Client muss den passenden Scope zusätzlich anfordern und der Benutzer bestätigen; LoxBerry-Diagnose benötigt außerdem eine lokale Freigabe.

Weiter: [Berechtigungen](permissions.de.md).
