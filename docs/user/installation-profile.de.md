# Bestätigtes Anlagenprofil

**Wetterkontext** bindet eine genaue aktuelle oder prognostizierte Wetterquelle
und eine Wettergröße. Diese Quelle hat eine eigene Sichtbarkeitsprüfung und keine
Kontroll-UUID. Formate sind Darstellungsmetadaten; Einheiten und die Kodierung von
`solar_radiation` bleiben ungeprüft. Aktuelle Quellenwerte sind nicht automatisch
gemessene Beobachtungen; Prognosen sind keine historischen Messungen. Bestehende
Wetterbindungen an Zustände oder Statistiken behalten ihre ursprüngliche Abdeckung.
Strukturierte Wetterhistorie ist bis zur gesondert aktivierbaren Aufzeichnung
nicht verfügbar. Geänderte relevante Formate oder Quellenregeln erfordern eine
Prüfung; Anbieter-, Stations- und Standortwechsel sind nicht vollständig erkennbar.

Erzeugungsbindungen können **PV-Anlagenparameter** enthalten: installierte kWp,
Breiten- und Längengrad gemeinsam sowie bis zu 16 eindeutig gekennzeichnete
Teilanlagen mit optionaler Leistung, Ausrichtung (Nord 0°, im Uhrzeigersinn),
Neigung und einer Beschreibung der Verschattung. Alle Angaben sind Nutzeraussagen
und benötigen bei jedem Speichern die Bestätigung der gesamten Bindung. Entwürfe
und zu prüfende Bindungen liefern keine nutzbaren bestätigten Parameter. Unbekannte
Geometrie verhindert einfache Vergleiche nicht pauschal. Teilanlagenleistungen
sind unabhängige Angaben; Vollständigkeit, Summengleichheit, gemessene Einzelerträge
und Verschattungsverluste werden nicht abgeleitet. Bei einer unzugänglichen oder
ungültigen Erzeugungsquelle werden die zugehörigen PV-Angaben zurückgehalten.

Fehlende Wetterquellen blenden die gesamte Bindung aus. Beim Ersetzen einer Kennung
prüft MCP alte und neue Quelle, auch bei einem Wechsel der Quellenart. Eine
unzugängliche alte Wetterbindung kann MCP nicht löschen; ein authentisierter
lokaler Admin darf verwaiste lokale Metadaten entfernen. Überschreitet eine
vollständige MCP-Seite 64 KiB, fragen Sie mit kleinerem `limit` erneut ab.

Profilversion 1 wird zunächst nach ihrem ursprünglichen Vertrag geprüft und nur
im Speicher zu Version 2 migriert. Lesen verändert den Dateiinhalt nicht. Die
nächste autorisierte Revisionstransaktion schreibt Version 2. Ältere Pluginversionen
können Version 2 nicht lesen: Für einen Binär-Rollback nach einem Profilschreibzugriff
muss zusammen mit dem älteren Code die vorherige Profilsicherung wiederhergestellt
werden. Unbekannte Versionen werden ohne Überschreiben abgelehnt.

Öffnen Sie **Bestätigtes Anlagenprofil** auf der Plugin-Hauptseite. Wählen Sie
eine sichtbare Messstelle oder einen Zustand und ordnen Sie eine Rolle zu.
Optional können Sie Messgrenze, Richtung und Begründung als Nutzerangaben ergänzen.
Ohne das Feld **Diese Zuordnung ausdrücklich bestätigen** bleibt die Zuordnung
ein Entwurf. Beim Bearbeiten müssen Sie eine Bestätigung erneut setzen.

Mehrere Erzeuger, Zähler und Verbraucher sind möglich; Speicher und einzelne
Geräte sind optional. Es werden keine Rollen aus Namen oder Kategorien abgeleitet.
Eine bestätigte Rolle beweist keine Einheit, Aggregation oder physische Messgrenze.
Technische Semantik wird separat geprüft. Das Profil enthält keine eigenen
Energie- oder Historienberechnungen.

Im Bereich **MCP-Profilpflege freigeben** können Sie die standardmäßig gesperrte
MCP-Pflege aktivieren und aktive Clients einzeln freigeben oder widerrufen.
Die Freigabe gilt für den exakten Client, Nutzer und Miniserver. Anzeigenamen
sind nur Beschriftungen. Neue Explorer-Clients benötigen erneut eine Freigabe.
Allgemeine LoxBerry-Betriebsrechte erlauben allein keine Profiländerung.

`loxberry_save_installation_profile` speichert eine exakte Zuordnung;
`loxberry_delete_installation_profile` löscht eine Zuordnung oder das gesamte
Profil. Beide benötigen `loxone:read`, `loxberry:operate`, die allgemeine lokale
Betriebsfreigabe und die eigene Profilfreigabe. Die bestehende Betriebs-Scope
setzt außerdem `loxone:history` voraus. Die KI muss zuerst den konkreten Vorschlag
oder Löschumfang erläutern und Ihre ausdrückliche Bestätigung im Chat einholen.
Dann übergibt sie `confirm=true` und `expected_revision` aus einem frischen Lesen.
Der Server speichert die Bestätigungsangabe des Clients; er kann den Chatinhalt
nicht unabhängig beweisen. Ein Entwurf bleibt auch nach dem Speichern ein Entwurf.
Bei `write_outcome_uncertain` gespeicherten Stand prüfen und nicht automatisch
wiederholen. Eine neue Revision erfordert erneutes Lesen und bei geändertem
Vorschlag eine neue Bestätigung. Gesamtlöschung über MCP ist gesperrt, wenn eine
betroffene Zuordnung außerhalb der aktuellen Sichtbarkeit liegt. Anlagenwechsel
werden im Admin zurückgesetzt.

`loxone_get_installation_profile` benötigt `loxone:read` und liefert maximal 100
Zuordnungen pro Seite. Folgen Sie `next_offset`, bis es leer ist. Jeder Aufruf
prüft die aktuelle Sichtbarkeit erneut. Verborgene Steuerungen und deren
Zuordnungen werden nicht ausgegeben; es gibt keine globale Anzahl aller Bindings.
Fehlt eine alte Quelle an einer weiterhin sichtbaren Steuerung, wird eine
bereinigte ungültige Zuordnung ohne alte Quellen-ID angezeigt.

Technische Quellenänderungen ergeben **Erneut prüfen**; reine Umbenennungen
ändern die Bestätigung nicht. Profilseiten und Antworten unterscheiden
**Entwurf**, **Bestätigt**, **Erneut prüfen** und **Quelle nicht mehr verfügbar**.
Nicht verfügbare Daten dürfen nicht als fehlende Anlage interpretiert werden.

Das Profil ist an Miniserver-Endpunkt und Serienidentität gebunden. Bei einem
Anlagenwechsel werden alte Zuordnungen nicht übernommen. Löschen Sie das alte
Profil ausdrücklich und erstellen Sie neue Zuordnungen. Einzelne Zuordnungen
und das gesamte Profil sind löschbar. Ein HTML-Dialog benennt den Löschumfang;
**Abbrechen** oder Escape schließen ihn ohne Änderung. Löschung erhält eine Revision als Schutz
gegen veraltete Schreibzugriffe. Bei einem Konflikt laden Sie neu; bei ungewisser
Persistenz prüfen Sie den gespeicherten Stand statt automatisch zu wiederholen.

Gespeichert wird nur minimale Profilmetadaten in `installation-profile.json`
im plugin-eigenen Datenverzeichnis, mit maximal 256 Bindings und 1 MiB. Die native
Dienstkonfiguration bestimmt das Datenverzeichnis über den bestehenden KNX-
Storepfad. Keine Zugangsdaten, Messwerte oder vollständigen Strukturen werden
im Profil gespeichert. Upgrade erhält das Profil; unbekannte Schemaversionen
werden abgewiesen und nicht überschrieben.

Die Admin-Quellenauswahl ist auf 500 Einträge begrenzt. Bei größeren Anlagen
können exakte IDs aus dem Explorer eingegeben werden; sie werden vor dem Speichern
erneut gegen die aktuelle Admin-Sichtbarkeit geprüft. Admin-Sichtbarkeit erlaubt
keinem MCP-Client zusätzliche Loxone-Zugriffe.
