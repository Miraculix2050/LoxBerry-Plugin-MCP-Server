# Konfiguration

[English](configuration.en.md)

## Grundeinstellungen

Im Bereich **Status & Betrieb** zeigt **Dienstbetrieb und Autostart** die gespeicherte Betriebsfreigabe. Nach einer Neuinstallation ist sie aktiviert, MCP und MQTT-Health sind jedoch getrennt und jeweils deaktiviert. Das Anwenden der aktivierten Freigabe startet den Dienst sofort und beim nächsten Systemstart. Das Deaktivieren stoppt ihn sofort und verhindert seinen Start beim nächsten Systemstart; diese Wahl bleibt auch bei Updates erhalten. Die Statusaktionen **Starten**, **Stoppen** und **Neu starten** sind nur bei aktivierter Betriebsfreigabe verfügbar und ändern ausschließlich den aktuellen Laufzeitstatus, nicht das Verhalten beim Systemstart.

## MCP-Konfiguration

Die Überschriften der Admin-Bereiche zeigen den zuletzt erfolgreich geladenen, gespeicherten MCP- und MQTT-Status sowie die aktuelle Sitzungszahl und Zahl ausstehender Freigabeaktionen. Auch bei geschlossenem Sitzungsbereich wird die Liste alle zehn Sekunden aktualisiert, solange die Seite sichtbar ist. Der HTTPS-Hinweis beruht auf den Zertifikats-, Origin- und Hostnamenprüfungen; während des Ladens oder bei fehlenden Daten erscheint ein neutraler Status. Ein geänderter Formularwert beeinflusst die Badges erst nach erfolgreichem Speichern.

Konfiguriere unter **Verbindung** eine lokale HTTPS-Origin und genau ein Miniserver-Ziel. Die Auswahl eines in LoxBerry hinterlegten Miniservers übernimmt keine dort gespeicherten Zugangsdaten. Bei der ersten Einrichtung wird die Origin aus LoxBerry-Hostname und HTTPS-Port vorgeschlagen; prüfe, ob sie zur Zertifikatsadresse im Browser passt. **Verbindung testen** verwendet das aktuell ausgewählte oder manuell eingegebene Ziel, ohne die Konfiguration zu speichern. Erst **MCP-Endpunktzugriff aktivieren** gibt den MCP- und OAuth-Zugriff frei. Die Berechtigungen und die Aktivierung der lokalen Ereignishistorie bleiben direkt sichtbar; Aufrufgrenzen, Laufzeit-, Struktur- und Cache-Einstellungen stehen unter **Erweiterte Einstellungen**. Deren Werte werden auch bei geschlossenem Abschnitt gespeichert.

### Wiederherstellung der Authentifizierung

Die erweiterten Grenzen enthalten eine erste und eine maximale Wartezeit für genau einen bedarfsgetriebenen Wiederherstellungsversuch der Miniserver-Authentifizierung. Standard sind 15 Minuten und 24 Stunden. Bestätigt der Miniserver eine Sperre der Quell-IP, startet der Dienst bis zum Ablauf der Frist keine weitere Anmeldung; erst ein tatsächlicher Tool- oder Laufzeitbedarf darf dann einen Versuch auslösen. Bei einer erneuten Sperre verdoppelt sich die Frist bis zum konfigurierten Maximum. Diese Werte sind Plugin-Policy und keine behauptete Sperrdauer des Miniservers; eine Änderung startet selbst keinen Loginversuch.

## Lokale Ereignishistorie

Die Hauptseite zeigt Aktivierung, Anzahl konfigurierter aktiver Quellen, aktuelle Größe von SQLite-Datenbank und WAL-Datei sowie Links zur **Lokalen Ereignishistorie** in der Konfiguration und unter **Hilfe und Entwicklerwerkzeuge**. Die eigene Ansicht zeigt lokale Messwerte zuerst und lädt die Control-Auswahl im Hintergrund. Bei jedem Öffnen prüft sie die sichtbaren Controls frisch; bis dahin werden keine gespeicherten Control-Namen angezeigt. Die begrenzte Liste lässt sich nach Name oder UUID sowie nach Raum, Kategorie und Typ filtern; pro Filtergruppe sind höchstens 100 ausgewählte Werte möglich. **Controls laden** erzwingt eine neue Abfrage. Wähle danach einen gemeldeten Zustand des Controls; höchstens 64 Control/State-Paare können aktiv sein.

Bei wenigen Zuständen genügt die Auswahlliste; bei längeren Listen erscheint zusätzlich ein Textfilter. Während des Ladens ist die Zustandseingabe gesperrt. Die Miniserver-Struktur nennt keine verlässlichen Werttypen: Ein sichtbarer Zustand kann Werte liefern, die sich nicht aufzeichnen lassen. Der Recorder unterstützt nur skalare Werte und meldet nicht unterstützte Werte im Laufzeitstatus. **Aufzeichnung starten** zeigt den laufenden Vorgang und danach die aktualisierte Quellenübersicht an. Eine aktivierte Quelle beweist noch keine erfassten Ereignisse.

Eine geöffnete Ansicht prüft bei sichtbarem Tab regelmäßig einen lokalen Änderungsmarker. Wenn ein anderer Browser Quellen hinzufügt, beendet, deren gespeicherte Daten oder die gesamte Historie löscht, lädt sie die autorisierte Quellenübersicht erneut. Nach einer fehlgeschlagenen Sichtbarkeitsprüfung versucht sie die Prüfung mit begrenztem Abstand erneut. Wechselt die Control-Generation in einem anderen Tab, lädt sie die Auswahl erneut und erhält ein weiterhin sichtbares Control-/Zustandspaar. Bei bestätigter Sichtbarkeit und unverändertem Marker erfolgt keine zusätzliche Miniserver-Strukturabfrage. **Übersicht aktualisieren** ist während des Ladens gesperrt und zeigt danach fünf Sekunden lang eine Erfolgsmeldung; Fehler bleiben sichtbar.

Die Übersicht trennt konfigurierte Aufbewahrung und Größengrenze von gemessener Dateigröße und gespeicherter Evidenz. Ereigniszeiten bezeichnen den ältesten und jüngsten gespeicherten Wechsel, keine vollständige Historie. Letzte Erfassungsintervalle erscheinen getrennt; eine Lücke bleibt auch nach erneutem Hinzufügen bestehen. Die angezeigten Ereigniszahlen beziehen sich nur auf aktuell sichtbare Quellen; historische Details verborgener Quellen werden nicht ausgegeben. Für konfigurierte Quellen ohne prüfbare Sichtbarkeit zeigt die Ansicht nur die gespeicherten Kennungen und bietet das bestätigte Beenden der Aufzeichnung an. Die Bytes der gemeinsamen Datenbank lassen sich keiner einzelnen Quelle genau zurechnen. Können Speicher, Miniserver-Struktur oder laufender Recorder nicht geprüft werden, erscheinen die betroffenen Angaben als nicht verfügbar oder unbekannt.

**Aufzeichnung beenden** erhält gespeicherte Evidenz innerhalb der globalen Grenzen. **Gespeicherte Daten löschen** ist eine getrennt bestätigte Aktion für eine inaktive, sichtbare Quelle. **Gesamte Historie löschen** benötigt eine eigene Bestätigung und löscht Ereignisse und Abdeckung, während die Quellenauswahl erhalten bleibt. Nach unklarem Löschresultat prüfe die aktualisierte Übersicht vor einer weiteren Aktion.

## Notaus-Signal (virtueller Status)

Das optionale **Notaus-Signal (virtueller Status)** steht im Abschnitt
**MCP-Konfiguration**. Wähle nur einen sichtbaren, als digital konfigurierten
virtuellen Status des ausgewählten Miniservers. Die Vorgabe **Kein virtueller
Status ausgewählt** lässt alle MCP-Tool-Aufrufe zu.

Die Seite zeigt die gespeicherte Auswahl sofort. Mit **Verfügbare Signale
laden** fragst du den konfigurierten Miniserver nach den aktuellen Optionen ab;
ein vorübergehender Fehler der Abfrage löscht den gespeicherten Wert nicht.

Zusätzlich zeigt die Admin-Oberfläche das vom laufenden Dienst verwendete Signal
mit Name und UUID sowie dessen Zustand. Die Zustände entsprechen der MQTT-
Veröffentlichung: `not_configured`, `clear`, `active` und `unknown`. Eine noch
nicht gespeicherte Auswahl bleibt davon getrennt und wird als noch nicht vom
Dienst übernommene Änderung kenntlich gemacht. Ist der Dienst nicht erreichbar,
zeigt die Seite keinen erfundenen Zustand an.

Bei einer Auswahl gilt: Der Wert `1` erlaubt MCP-Tool-Aufrufe, der Wert `0`
sperrt sie. Ein beim Dienststart noch unbekannter Wert oder ein Verlust der
Miniserver-Verbindung sperrt ebenfalls sicherheitshalber. Stelle den virtuellen
Status wieder auf `1` oder entferne die Auswahl und speichere die Konfiguration,
um Tool-Aufrufe wieder freizugeben. Die Sperre betrifft nur Tool-Aufrufe; OAuth,
die Tool-Erkennung und der HTTP-Health-Endpunkt bleiben erreichbar.

## MQTT-Konfiguration (Health)

MQTT-Health ist standardmäßig deaktiviert. Standardmäßig verwendet das Plugin Host, Port und Zugangsdaten des LoxBerry MQTT-Gateways zur Laufzeit. Für einen eigenen Broker deaktivieren Sie **LoxBerry MQTT-Gateway verwenden** und geben Host, Port, Benutzername und Passwort ein. Eigene Broker werden immer per TLS mit normaler Zertifikats- und Hostnamenprüfung verbunden. Das Passwort wird getrennt verschlüsselt gespeichert, nie wieder angezeigt und nie in Diagnose- oder Logausgaben aufgenommen. Mit **Gespeichertes MQTT-Passwort löschen** entfernen Sie es bewusst. Das Root Topic lautet standardmäßig `mcpserver`; der Heartbeat läuft standardmäßig alle 60 Sekunden. Die retained Topics sind `mcpserver/health/heartbeat`, `mcpserver/health/system_state` und `mcpserver/health/substate`. Ein kontrolliertes Stoppen veröffentlicht `inactive` und `dead`; bei einem unerwarteten Prozess- oder Verbindungsverlust veröffentlicht das retained Fallback `unknown`. Der Zeitwert verwendet Loxone-Epoch-Sekunden.

Wenn MQTT-Health deaktiviert wird, sich das Root Topic ändert oder sich der konfigurierte Broker-Endpunkt beziehungsweise Transport ändern, entfernt das Plugin vor dem Start des Ersatzdienstes alle vier retained Plugin-Topics am bisherigen Ziel. Dies erfolgt best effort: Ist der bisherige Broker nicht erreichbar, bleibt die neue Konfiguration aktiv und die Admin-Oberfläche weist darauf hin, dass alte retained Werte verbleiben können. Eine Änderung nur der Broker-Zugangsdaten bei gleichem Endpunkt und Root entfernt keine Topics, weil der Ersatzdienst für denselben Topic-Baum autoritativ bleibt.

Ist MQTT-Health aktiviert, veröffentlicht das Plugin zusätzlich retained mit QoS
1 unter `<root>/emergency_stop/status` den Notaus-Status. Dieses Topic hat einen
eigenen Last Will und ist unabhängig von den `health/*`-Topics: Ohne ausgewähltes
Signal veröffentlicht es `not_configured`, beim konfigurierten Signalwert `1`
`clear`, bei `0` `active` und bei nicht verfügbarem Signal oder MQTT-Verlust
`unknown`. `active` und `unknown` bei konfiguriertem Signal sperren MCP-Tool-Aufrufe.

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
