# Systemmeldungen

## Genau eine Meldung bestätigen

Administratoren können in den Berechtigungseinstellungen
`tools.loxone_message_confirmation_enabled` aktivieren; die Funktion ist
standardmäßig aus. Zusätzlich muss der optionale OAuth-Scope
`loxone:messages:confirm` separat erteilt werden. Control-, History- oder
LoxBerry-Freigaben ersetzen diese Berechtigung nicht.

Zuerst `loxone_preview_system_message_confirmation(entry_uuid)` aufrufen und die
genaue Meldung samt Wirkung prüfen. Erst nach ausdrücklicher Freigabe
`loxone_confirm_system_message(preview_id, user_approved=true)` ausführen.
Die Vorschau ist an Identität und Ziel gebunden, gilt 120 Sekunden und ist einmalig
nutzbar. Vor dem Senden werden Berechtigung, Aktivierung, aktueller Meldungszustand
und native Aktion erneut geprüft. Pro OAuth-Familie sind höchstens drei
Bestätigungsversuche pro Minute erlaubt.

Bei der geprüften manuellen Warnung (Ereignis 1121) historisiert „Okay“ / 1003 die
Meldung: Sie bleibt in der vorgehaltenen Historie, `confirmed_at` bleibt leer.
Die native Aktion 1005 bestätigt. Aktionen hängen von der Quelle ab; andere
manuelle Stufen bleiben bis zur Prüfung ihrer Wirkung unzulässig.
`acknowledgement_available` behält seine bisherige Bedeutung für 1005;
`confirmation_action_id` und `confirmation_effect` beschreiben die Vorschauaktion.

Das Ergebnis unterscheidet Senden, Annahme und beobachtete Wirkung. Einen unklaren
Schreibaufruf niemals automatisch wiederholen. Den Lebenszyklus genau dieser
Meldung lesend abgleichen und vor einem neuen Versuch erneut die Freigabe einholen.
Es gibt keine Sammelbestätigung, Löschung, Lesemarkierung, Benachrichtigungsversendung
oder Reparatur. Eine entfernte aktive Meldung beweist keinen gesunden Systemzustand.

`loxone_get_attention_overview` liefert eine begrenzte Übersicht mit drei getrennten
Quellen: Baustein-Alarme, Systemmeldungen und das zuletzt beobachtete
Benachrichtigungsereignis. Abdeckung, Fehler, Zeitpunkte und Bedeutung jeder Quelle
bleiben erhalten. Die Abfragen erfolgen nacheinander; eine vollständige globale
Entwarnung ist nicht möglich. `limit` ist 1–10 (Standard 5); `include_history=true`
ergänzt gespeicherte Systemmeldungen mit History-Freigabe. Bei Teilergebnissen,
einem Cursor oder Details oberhalb des Übersichtsbudgets den jeweiligen Leser
nutzen. Das vorhandene Active-Alerts-Tool bleibt unverändert.

Die KI soll konkrete Aufgaben ableiten, statt nur den Gesundheitszustand zu
beschreiben. Jede Aufgabe nennt das beobachtete Problem, genaue Belege/Referenzen,
Zeitpunkt und Quellrevision, aktuellen oder historischen Zustand, Unsicherheit,
nächste gezielte Abfrage, vorgeschlagene Korrektur, fehlendes Schreibwerkzeug bzw.
Erlaubnis und Abnahmekriterium. Ein Automatik-Regelfehler führt zur Identifikation
der Regel und ungültigen Bedingung sowie zur Vorbereitung einer Korrektur; eine
unbekannte Regelidentität bleibt offen. Ein eigener Regel-Leser/-Schreiber ist
Folgearbeit. Konfigurationskandidaten führen zur autorisierten Projektprüfung und
einer belegten Übergabe an einen zukünftigen projektändernden Loxone-MCP-Server.
Historische Wiederholungen können Diagnoseaufgaben begründen, ohne aktuelle Alarme
zu sein. Eine Meldungsbestätigung ist keine Reparatur und belegt keine Fehlerbehebung.

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
