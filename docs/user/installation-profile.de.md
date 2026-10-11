# Bestätigtes Anlagenprofil

Öffnen Sie **Bestätigtes Anlagenprofil** auf der Plugin-Hauptseite. Wählen Sie
eine sichtbare Messstelle oder einen Zustand und ordnen Sie eine Rolle zu.
Optional können Sie Messgrenze, Richtung und Begründung als Nutzerangaben ergänzen.
Ohne das Feld **Diese Zuordnung ausdrücklich bestätigen** bleibt die Zuordnung
ein Entwurf. Beim Bearbeiten müssen Sie eine Bestätigung erneut setzen.

Mehrere Erzeuger, Zähler und Verbraucher sind möglich; Speicher und einzelne
Geräte sind optional. Es werden keine Rollen aus Namen oder Kategorien abgeleitet.
Eine bestätigte Rolle beweist keine Einheit, Aggregation oder physische Messgrenze.
Technische Semantik wird separat geprüft. Die erste Profilstufe enthält keine
Energie- oder Historienberechnung und keine MCP-Schreibfunktion.

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
und das gesamte Profil sind löschbar. Löschung erhält eine Revision als Schutz
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
