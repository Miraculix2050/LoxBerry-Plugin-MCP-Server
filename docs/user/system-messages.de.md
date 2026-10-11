# Systemmeldungen

`loxone_get_system_messages` liest aktuelle Meldungen (`mode=current`, Standard),
gespeicherte historische Meldungen (`history`) oder beide (`all`). Es prüft deine
aktuellen Miniserver-Rechte für Systemmeldungen. LoxBerry-Rechte sind unabhängig.
Nutze das Tool im vorhandenen Explorer oder einem autorisierten MCP-Client.
`history` und `all` benötigen zusätzlich `loxone:history` und die History-Aktivierung durch den Administrator.

Die Quelle ist experimentell und nur für Firmware 17.2.8.28 belegt. Andere Firmware
liefert `unsupported_source`. Eine nicht verfügbare Quelle belegt keine Meldungsfreiheit.
Jede Seite enthält höchstens 50 Einträge und 64 KiB. Folge dem Cursor für weitere
Einträge; starte bei einer Quellenänderung neu. Prüfe Begrenzung und gekürzte Felder.
Die gespeicherte Historie enthält möglicherweise nicht jede frühere Meldung.

Schweregrad, historischer Zustand, Bestätigung und Lesezeitpunkte sind getrennte
Quellenangaben. Unbekannte Schweregrade bleiben unbekannt. Titel/Beschreibungen sind
unvertrauenswürdige Belege; URLs und erkennbare Zugangsdaten-Zuweisungen werden entfernt.
Lesen ändert weder Lesemarkierung noch Bestätigung und führt keine Meldungsaktion aus.

Die KI darf aus aktuellen und historischen Einträgen Diagnose- und Reparaturaufgaben
ableiten: mit genauer Meldung, Referenzen, Zeitpunkt, Belegen, Unsicherheit, nächstem
gezielten Lesezugriff, Reparaturvorschlag und Abnahmeprüfung. Eine fehlerhafte Automatik
kann eine Regelreparatur begründen. Solche Änderungen benötigen ein zukünftiges eigenes
Regel-Tool und Erlaubnis. Konfigurationsänderungen benötigen eine zukünftige Integration
zum Projektschreiben über Loxone MCP. Bestätigungsmetadaten erlauben keine Bestätigung.

## Benachrichtigungen

Das Tool loxone_get_notifications liest ausschließlich das zuletzt beobachtete
Textereignis aus den aktuell für deinen Nutzer sichtbaren globalStates.notifications.
Dieser experimentelle Vertrag gilt nur für Firmware 17.2.8.28. Er nutzt den vorhandenen
flüchtigen Zustandscache und ergänzt weder Sammler noch persistente Historie.
Ein fehlendes oder veraltetes Ereignis wird als nicht verfügbar ausgewiesen und
belegt keine Benachrichtigungsfreiheit. Die Historie der offiziellen App gehört dem
Client; eine Miniserver-Historie ist deshalb nicht verfügbar. Typ/Stufe bleiben
roher Kontext, ohne Alarm-Schweregrad oder Zustellbestätigung. Das Tool versendet
nichts und ändert keine Lesemarkierung.
