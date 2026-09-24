# Betrieb

[English](operation.en.md)

## Updates

Der Plugin Manager erkennt reguläre Updates über die stabile Releasequelle. Vorabversionen werden nur angeboten, wenn sie dort ausdrücklich zugelassen sind. Halte vor einem Update einer Vorabversion ein funktionierendes vorheriges Paket für einen Rückweg bereit.

## Sitzungen und Freigaben

Unter **Clients und Sitzungen** können Administratoren Sitzungen und lokale Diagnose- oder Operate-Freigaben prüfen und widerrufen. Auf schmalen Bildschirmen erscheinen alle Angaben und Aktionen je Sitzung oder Freigabe untereinander. Während eines Widerrufs wird die betroffene Zeile ausgegraut. Der Widerruf einer Freigabe beendet passende Sitzungen. Das Trennen des Tool Explorers widerruft nur dessen OAuth-Sitzung; seine lokale Freigabe kann für dieselbe Loxone-Identität und denselben Miniserver bis zur angezeigten Frist reaktiviert werden. Die inaktive Aufbewahrung ist von 1 bis 720 Stunden konfigurierbar und beträgt standardmäßig 72 Stunden.

Ein Sitzungswiderruf sperrt den MCP-Zugriff sofort. Die anschließende Loxone-Tokenbereinigung läuft im Hintergrund. Der Abschnitt zeigt aggregierte Warnungen, wenn die Bereinigung aussteht, der Miniserver Anmeldungen blockiert oder der Remote-Widerruf nach begrenzten Versuchen unbestätigt bleibt. Bei unbestätigtem Ergebnis kann ein Administrator die Loxone-Benutzerverwaltung prüfen; die Warnung nennt keine betroffene Identität.

Die Notaus-Auswahlliste wird mit den in LoxBerry hinterlegten Zugangsdaten direkt vom Miniserver geladen. Das kann einige Sekunden dauern. Wenn die Optionen wegen einer Miniserver-Anmeldesperre nicht geladen werden, zeigt die Oberfläche den frühesten erneuten Versuch an. **Erneut versuchen** wird danach freigeschaltet und führt höchstens einen koordinierten Anmeldeversuch aus. Der gespeicherte Notaus-Wert bleibt bei jedem Ladefehler erhalten.
Ist lediglich eine andere Anmeldung im Gange, erscheint stattdessen ein kurzer Wiederholungszeitpunkt. Auch die servergerenderte Fallback-Ansicht zeigt aggregierte Bereinigungswarnungen.

## Diagnose und Logs

Das Service-Log bleibt unter **Diagnose und Logs** direkt erreichbar. Der LoxBerry LogManager zeigt native Plugin-Logs erst, wenn ein tatsächliches Admin-Ereignis protokolliert und registriert wurde. Die Admin-Seite unterscheidet einen leeren LogManager-Eintrag von einem nicht erreichbaren LogManager und einem fehlgeschlagenen Nachladeaufruf. Das Öffnen der Logliste erzeugt keinen Logeintrag.

## Tool Explorer

Der [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) ist ein lokaler administrativer Testclient. Er meldet sich mit einem Loxone-Benutzer an und erhält keine Rechte aus der LoxBerry-Admin-Sitzung. Ersetze `loxberry` im Link bei Bedarf durch den Hostnamen deiner Installation. Ändernde Aufrufe verlangen vor dem Senden eine Bestätigung.
RFC-3339-Zeitfelder werden als lokale Datum-/Zeitfelder angezeigt und als UTC übermittelt.
Zeitbereich-Schnellwahl und Referenzen aus bisherigen Ergebnissen erleichtern häufige
Abfragen; technische Seitenparameter stehen unter **Erweiterte Optionen**.
Die verfügbaren Werkzeuge lassen sich nach Name oder Beschreibung durchsuchen
und zusätzlich nach den vorhandenen Gruppen filtern. Die Filterung erfolgt lokal;
das ausgewählte Werkzeug und sein ungesendeter Entwurf bleiben erhalten.

MCP-Clients erhalten die auf der konkreten Installation veröffentlichten Werkzeugbeschreibungen sowie deren Ein- und Ausgabeschemas über die MCP-Methode `tools/list`. Der Tool Explorer liest genau diese Antwort und visualisiert sie. Unter **Hilfe** stehen außerdem eine statische HTML-Referenz des vollständigen Werkzeugvertrags dieser Plugin-Version und dieselben Daten als JSON-Download bereit.

Weiter: [Fehlerbehebung](troubleshooting.de.md).
