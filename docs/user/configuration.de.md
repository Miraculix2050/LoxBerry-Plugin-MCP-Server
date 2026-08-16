# Konfiguration

[English](configuration.en.md)

## Grundeinstellungen

Der Schalter **Dienst aktivieren** ist die gespeicherte Betriebsfreigabe. Nach einer Neuinstallation ist er aktiviert, MCP und MQTT-Health sind jedoch getrennt und jeweils deaktiviert. Aktivieren startet den Dienst sofort und beim nächsten Systemstart. Deaktivieren stoppt ihn sofort und verhindert seinen Start beim nächsten Systemstart; diese Wahl bleibt auch bei Updates erhalten. Die Statusaktionen **Starten**, **Stoppen** und **Neu starten** sind nur bei aktivierter Betriebsfreigabe verfügbar und ändern ausschließlich den aktuellen Laufzeitstatus, nicht das Verhalten beim Systemstart.

## MCP-Konfiguration

Konfiguriere eine lokale HTTPS-Origin und genau ein Miniserver-Ziel. Die Auswahl eines in LoxBerry hinterlegten Miniservers übernimmt keine dort gespeicherten Zugangsdaten. Bei der ersten Einrichtung wird die Origin aus LoxBerry-Hostname und HTTPS-Port vorgeschlagen; prüfe, ob sie zur Zertifikatsadresse im Browser passt. Erst **MCP-Zugriff aktivieren** gibt den MCP- und OAuth-Zugriff frei.

## Notaus-Signal (virtueller Status)

Das optionale **Notaus-Signal (virtueller Status)** steht im Abschnitt
**MCP-Konfiguration**. Wähle nur einen sichtbaren, als digital konfigurierten
virtuellen Status des ausgewählten Miniservers. Die Vorgabe **Kein virtueller
Status ausgewählt** lässt alle MCP-Tool-Aufrufe zu.

Bei einer Auswahl gilt: Der Wert `1` erlaubt MCP-Tool-Aufrufe, der Wert `0`
sperrt sie. Ein beim Dienststart noch unbekannter Wert oder ein Verlust der
Miniserver-Verbindung sperrt ebenfalls sicherheitshalber. Stelle den virtuellen
Status wieder auf `1` oder entferne die Auswahl und speichere die Konfiguration,
um Tool-Aufrufe wieder freizugeben. Die Sperre betrifft nur Tool-Aufrufe; OAuth,
die Tool-Erkennung und der HTTP-Health-Endpunkt bleiben erreichbar.

## MQTT-Konfiguration (Health)

MQTT-Health ist standardmäßig deaktiviert. Standardmäßig verwendet das Plugin Host, Port und Zugangsdaten des LoxBerry MQTT-Gateways zur Laufzeit. Für einen eigenen Broker deaktivieren Sie **LoxBerry MQTT-Gateway verwenden** und geben Host, Port, Benutzername und Passwort ein. Eigene Broker werden immer per TLS mit normaler Zertifikats- und Hostnamenprüfung verbunden. Das Passwort wird getrennt verschlüsselt gespeichert, nie wieder angezeigt und nie in Diagnose- oder Logausgaben aufgenommen. Mit **Gespeichertes MQTT-Passwort löschen** entfernen Sie es bewusst. Das Root Topic lautet standardmäßig `mcpserver`; der Heartbeat läuft standardmäßig alle 60 Sekunden. Die retained Topics sind `mcpserver/health/heartbeat`, `mcpserver/health/system_state` und `mcpserver/health/substate`. Ein kontrolliertes Stoppen veröffentlicht `inactive` und `dead`; bei einem unerwarteten Prozess- oder Verbindungsverlust veröffentlicht das retained Fallback `unknown`. Der Zeitwert verwendet Loxone-Epoch-Sekunden.

Ist MQTT-Health aktiviert, veröffentlicht das Plugin zusätzlich retained mit QoS
1 unter `<root>/emergency_stop/status` den Notaus-Status `enabled`, `disabled`
oder `unknown`. Dieses Topic ist unabhängig von den `health/*`-Topics.

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
