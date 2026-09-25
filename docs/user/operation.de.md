# Betrieb

[English](operation.en.md)

## Updates

Der Plugin Manager erkennt reguläre Updates über die stabile Releasequelle. Vorabversionen werden nur angeboten, wenn sie dort ausdrücklich zugelassen sind. Halte vor einem Update einer Vorabversion ein funktionierendes vorheriges Paket für einen Rückweg bereit.

## Sitzungen und Freigaben

Unter **Clients und Sitzungen** können Administratoren Sitzungen und lokale Diagnose- oder Operate-Freigaben prüfen und widerrufen. Auf schmalen Bildschirmen erscheinen alle Angaben und Aktionen je Sitzung oder Freigabe untereinander. Während eines Widerrufs wird die betroffene Zeile ausgegraut. Der Widerruf einer Freigabe beendet passende Sitzungen. Das Trennen des Tool Explorers widerruft nur dessen OAuth-Sitzung; seine lokale Freigabe kann für dieselbe Loxone-Identität und denselben Miniserver bis zur angezeigten Frist reaktiviert werden. Die inaktive Aufbewahrung ist von 1 bis 720 Stunden konfigurierbar und beträgt standardmäßig 72 Stunden.

Ein Sitzungswiderruf sperrt den MCP-Zugriff sofort. Die anschließende Loxone-Tokenbereinigung läuft im Hintergrund. Der Abschnitt zeigt aggregierte Warnungen, wenn die Bereinigung aussteht, der Miniserver Anmeldungen blockiert oder der Remote-Widerruf nach begrenzten Versuchen unbestätigt bleibt. Bei unbestätigtem Ergebnis kann ein Administrator die Loxone-Benutzerverwaltung prüfen; die Warnung nennt keine betroffene Identität.

Die zuletzt geladenen Notaus-Signale erscheinen beim Seitenaufruf sofort aus dem lokalen Cache; dabei wird keine neue Miniserver-Anmeldung gestartet. **Notaus-Signale aktualisieren** lädt die Liste ausdrücklich mit den in LoxBerry hinterlegten Zugangsdaten neu. Das kann einige Sekunden dauern. Gleichzeitige Admin-Anfragen warten auf dasselbe Ladeergebnis. Wenn eine Miniserver-Anmeldesperre die Aktualisierung verhindert, zeigt die Oberfläche den frühesten erneuten Versuch an. **Erneut versuchen** wird danach freigeschaltet und führt höchstens einen koordinierten Anmeldeversuch aus. Die zuletzt geladenen Signale werden als möglicherweise veraltet gekennzeichnet; der gespeicherte Notaus-Wert bleibt bei jedem Ladefehler erhalten.
Ist lediglich eine andere Anmeldung im Gange, erscheint stattdessen ein kurzer Wiederholungszeitpunkt. Auch die servergerenderte Fallback-Ansicht zeigt aggregierte Bereinigungswarnungen.

## Diagnose und Logs

Das Service-Log bleibt unter **Diagnose und Logs** direkt erreichbar. Der LoxBerry LogManager zeigt native Plugin-Logs erst, wenn ein tatsächliches Admin-Ereignis protokolliert und registriert wurde. Die Admin-Seite unterscheidet einen leeren LogManager-Eintrag von einem nicht erreichbaren LogManager und einem fehlgeschlagenen Nachladeaufruf. Das Öffnen der Logliste erzeugt keinen Logeintrag.

## Tool Explorer

Der [MCP Tool Explorer](https://loxberry/admin/plugins/mcpserver/explorer.cgi) ist ein lokaler administrativer Testclient. Er meldet sich mit einem Loxone-Benutzer an und erhält keine Rechte aus der LoxBerry-Admin-Sitzung. Ersetze `loxberry` im Link bei Bedarf durch den Hostnamen deiner Installation. Ändernde Aufrufe verlangen vor dem Senden eine Bestätigung.
Nach der Anmeldung zeigt die Verbindungskarte die tatsächlich gewährten OAuth-Scopes der Sitzung. Als **Nicht gewährt** markierte Scopes wurden dieser Sitzung nicht gewährt; lokale LoxBerry-Freigaben und weitere Berechtigungsprüfungen bleiben getrennt. Beim Ende der Sitzung verschwindet die Liste.
Die Verbindungskarte ist zunächst geöffnet, damit die Anmeldung sofort sichtbar ist. Nach der Anmeldung lässt sie sich für mehr Platz einklappen. Ihre OAuth-Scope-Liste ist zunächst geschlossen; die Links zur Einrichtung und Schema-Referenz bleiben oberhalb der Karte sichtbar. Beide Aufklappzustände bleiben bei einem Reload und in neuen Tabs desselben Browsers erhalten.
RFC-3339-Zeitfelder werden als lokale Datum-/Zeitfelder angezeigt und als UTC übermittelt.
Zeitbereich-Schnellwahl und Referenzen aus bisherigen Ergebnissen erleichtern häufige
Abfragen; technische Seitenparameter stehen unter **Erweiterte Optionen**.
Die verfügbaren Werkzeuge lassen sich nach Name oder Beschreibung durchsuchen
und im aufklappbaren Filter nach einer oder mehreren Gruppen filtern. **Alle**
setzt die Gruppenauswahl zurück. Die Filterung erfolgt lokal;
das ausgewählte Werkzeug und sein ungesendeter Entwurf bleiben erhalten.
Werkzeuge ohne bekannten Explorer-Darstellungshinweis erscheinen unter **Weitere Tools**;
Formular und Aufruf verwenden weiterhin die Schemas aus `tools/list`.
Beim ausgewählten Werkzeug zeigt der Explorer die Lese-/Schreib-Einstufung und
explizit gemeldete MCP-Hinweise. Bei unvollständigen oder widersprüchlichen Angaben
erscheint vorsichtig **Schreibzugriff möglich**. Die Hinweise sind keine
Sicherheitsgarantie; die vollständigen Annotationen stehen unter
**Technische MCP-Metadaten**.
Daneben stehen die für bekannte Werkzeuge benötigten OAuth-Scopes. Die tatsächlich
gewährten Scopes dieser Sitzung bleiben in der Verbindungskarte sichtbar.
Lange Werkzeugbeschreibungen lassen sich in der kompakten Zusammenfassung aufklappen.
**Ausgewähltes Tool** und **Ergebnis** lassen sich einklappen und öffnen sich bei
einer passenden Auswahl beziehungsweise einem neuen Ergebnis wieder. Bei einem
Verlaufsergebnis stehen **Verwendete Parameter** in einem eigenen Aufklappbereich.
Ergebnisse und Verlaufseinträge erscheinen als aufklappbarer Baum. Große Zweige zeigen
jeweils 100 Einträge; **Weitere anzeigen** lädt die nächsten. Der Pfeil öffnet einen
Zweig, die separate Wert-Schaltfläche übernimmt dessen unveränderten Wert und Pfad.
Objekte in Listen zeigen nach Möglichkeit einen kurzen Namen, Typ, Bezeichner oder
bei Beziehungen Quelle und Ziel. Zeitangaben sind der letzte Ersatz, wenn nichts
Aussagekräftigeres vorhanden ist. `null` erscheint im Baum als `-`; beim Kopieren
und Übernehmen bleibt der ursprüngliche Wert erhalten.
Die vollständige Antwort bleibt unter **JSON** sichtbar und über **JSON kopieren** verfügbar.
Der Aufrufverlauf zeigt lokale Uhrzeit, Dauer, Ergebnis und eine kurze,
geschwärzte Parameterübersicht, soweit das Werkzeugschema sie erlaubt. Die
Auswahl eines Eintrags öffnet weiterhin sein Ergebnis und erlaubt, den Aufruf
als Entwurf zu laden. Fortschritt und Ergebnis des aktuellen Aufrufs erscheinen
bei **Aufruf ausführen**; der Verbindungsstatus bleibt in der Verbindungskarte.
Der separate Bereich **MCP-Protokoll / Debug** enthält das begrenzte Anfrage-
und Antworttranskript zur Fehlersuche. Aufgeklappte Einträge zeigen kompakt
**Datum/Uhrzeit** über HTTP-Status und Dauer. Verlauf und Transkript bleiben im
aktuellen Tab und werden beim Ende seiner Sitzung gelöscht.

MCP-Clients erhalten die auf der konkreten Installation veröffentlichten Werkzeugbeschreibungen sowie deren Ein- und Ausgabeschemas über die MCP-Methode `tools/list`. Der Tool Explorer liest genau diese Antwort und visualisiert sie. Unter **Hilfe** stehen außerdem eine statische HTML-Referenz des vollständigen Werkzeugvertrags dieser Plugin-Version und dieselben Daten als JSON-Download bereit.

Weiter: [Fehlerbehebung](troubleshooting.de.md).
