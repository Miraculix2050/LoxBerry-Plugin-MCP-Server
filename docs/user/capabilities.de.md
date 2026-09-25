# Funktionsumfang und Grenzen

[English](capabilities.en.md)

## Unterstützter Umfang

Der Server liest sichtbare Räume, Kategorien, Controls und Zustände. Optional sind begrenzte Historie, Statistiken, maskierte LoxBerry-Diagnosen sowie dokumentierte, typabhängige Aktionen für sichtbare Gen.-1-Controls verfügbar.

Wenn ein Administrator sie aktiviert, kann der Server ausgewählte State-UUIDs zusätzlich als begrenzte lokale Ereignishistorie aufzeichnen. Sie ergänzt die native Loxone-Historie für kurzlebige Wechsel und erweitert nie die Sichtbarkeit der aufrufenden Identität.

Das Entfernen einer Quelle beendet die Aufzeichnung; gespeicherte Ereignisse bleiben lesbar, solange Control und State für den Aufrufer aktuell sichtbar sind. `loxone_get_state_history` meldet `recording_status`, `recording_ended_at`, `recording_notice` und die `coverage` des angefragten Zeitraums getrennt. `active` bedeutet für die Aufzeichnung konfiguriert; nur `coverage` belegt eine Erfassung im angefragten Zeitraum. Die Pause nach dem Entfernen gilt nie als durchgehend erfasst. Die globalen Alters- und Datenbankgrößenlimits gelten weiter. Ein freigegebener Client kann Ereignisse und Abdeckung einer inaktiven Quelle mit `loxberry_purge_event_history_source` und `confirm=true` endgültig löschen. Nach einem Timeout ist das Ergebnis unbekannt; der Aufruf darf nicht automatisch wiederholt werden.

`loxone_get_project_status`, `loxone_find_project_objects`,
`loxone_describe_project_object`, `loxone_trace_project_logic` und
`loxone_analyze_project` stellen begrenzte,
schreibgeschützte Project Intelligence für ein durch die gebundene Loxone-Identität abrufbares
Projekt bereit. Sie liefern Graph-Evidenz statt rohem XML: Ein Signal- oder Referenzpfad beschreibt
strukturellen Einfluss, nicht eine beobachtete historische Ursache. Ergebnisse sind begrenzt und
melden Abschneiden explizit; unbekannte Blocktypen und unaufgelöste Beziehungen bleiben ohne
erfundene Semantik sichtbar. Ein Trace begrenzt unaufgelöste Beziehungen unabhängig und meldet
dies über `unresolved_truncated`.
Bestätigte KNX/EIB-Projektobjekte ergänzen begrenzte, quellengestützte Metadaten für Buslinien,
Endpunkte und KNX-Logikblöcke. Die Endpunktrichtung lautet `bus_to_loxone` oder
`loxone_to_bus`; sie ist keine Aussage über die physische Gerätefunktion. Gruppenadressen
behalten ihren Originaltext und erhalten nur bei gültigem Format eine kanonische Form. `EIBType`
bleibt ein unaufgelöster Quellcode, keine geratene DPT. Gleiche Gruppenadressen erzeugen keine
Graphbeziehung und beweisen keine Kausalität. Suche und Trace liefern nur eine kompakte
KNX-Zusammenfassung; den Originalwert, Segmente, Namen und den DPT-Rohwert liefert gezielt
`loxone_describe_project_object`. Projekt-Suchseiten und Traces sind zusätzlich auf 64 KiB
begrenzt und melden eine Größenkürzung über `truncated` und `truncation_reason`.
`project_parts` zählt intern eingelesene Modellquellen, nicht Loxone-Config-Projekte. Status
liefert opake `model_sources`; identische KNX-Quellvorkommen aus getrennten Modellquellen werden
einmal als logisches Objekt mit `source_occurrence_count` und `model_source_ids` dargestellt.
Gleiche Titel oder Gruppenadressen führen nie zu einer solchen Zusammenführung.
Wenn eine exakt geprüfte Block-/Connector-Regel vorliegt, liefert Describe zusätzlich eine oder
mehrere getrennte KNX-Signalnutzungsbeobachtungen. Trace liefert getrennt markierte abgeleitete
Connectorkanten sowie begrenzte Pfade `knx_to_loxone`, `loxone_to_knx` oder `knx_to_knx`.
Unbekanntes Block- oder Connector-Verhalten wird nicht geraten. Diese Ergebnisse beschreiben
statische Projektpfade, keine Bus-Telegramme und keine historische Ursache einer Aktion.
`loxone_analyze_project` Version 3 fasst begrenzte, projektlokale KNX-Evidenz zusammen:
Adress- und Quellnamensmuster, Wiederverwendung von Rohdatentypen, geprüfte Unterschiede der
Signalnutzung, Kontext aus exakten Runtime-Mappings, lokale Peer- und Graph-Ausreißer,
Pfadzähler und Endpunkte ohne beobachtete Projektbeziehung. Runtime-Namen und Control-Typen werden
nur bei exaktem UUID-Mapping verwendet; Namen erzeugen nie ein Mapping.
Findings sind Prüffakten, keine Qualitätsurteile. Feste Limitierungs-Codes kennzeichnen fehlende
normalisierte DPTs, Semantikdomänen, geprüfte Signalnutzung oder Runtime-Mappings. Die Analyse
behauptet weder DPT-Kompatibilität noch ETS-Abdeckung, Busaktivität oder physische
Geräteverwendung; die Evidenz eines zurückgegebenen Projektknotens lässt sich mit Describe oder
Trace vertiefen.
`loxone_analyze_observability` bewertet getrennt einen begrenzten, ausdrücklich angefragten
Zeitraum für ein Projektziel. Es verbindet nur exakte UUID-gemappte strukturelle Erreichbarkeit,
Verfügbarkeit aktueller States, beworbene native Statistikserien und die Abdeckung der lokalen
Ereignishistorie. Erreichbarkeit beweist keine historische Ursache; konfigurierte Statistikserien
sind zeitlich nicht geprüft, und fehlende oder partielle lokale Abdeckung beweist nicht, dass ein
State nicht eingetreten ist. Pro Control werden höchstens 20 Statistikserien zurückgegeben;
ausgelassene Metadaten markiert `native_statistics_truncated`. State-Namen sind auf 200 UTF-8-
Bytes begrenzt; ausgelassenen Text markiert `state_names_truncated`. Control-Namen und -Typen
haben dieselbe Begrenzung; ausgelassenen Text markiert `control_metadata_truncated`.
Die mitgelieferte Anleitung `using-loxberry-mcp` verbindet diese vorhandenen Tools
zu einem Diagnoseablauf: Ziel bestimmen, aktuelle Beobachtungen samt Zeitstempel
prüfen, historische Abdeckung für den angefragten Zeitraum belegen und strukturelle
Pfade von Ereignisbelegen und möglichen Ursachen trennen. Ein nach der
Wiederverbindung beobachteter Wert verrät nicht, wann er während der Unterbrechung
gewechselt hat.
Für jeden State ohne vollständige lokale Abdeckung empfiehlt `recommendations`
anhand beobachtbarer Werte und Control-Metadaten native Statistik, lokale
Aufzeichnung bei Änderung oder `undetermined`.
Für dokumentierte Schaltzustände von `InfoOnlyDigital`, `Switch`, `Pushbutton`,
`PresenceDetector` und weiteren unterstützten Control-Typen kann bei beobachtetem
Wert 0/1 eine Aufzeichnung bei Änderung auch ohne `is_analog` empfohlen werden.
Der dokumentierte `value`-State von `InfoOnlyAnalog`, `UpDownAnalog`,
`LeftRightAnalog` und `Slider` wird auch ohne `details.analog` als analog
behandelt; ein kleiner Wertebereich macht ihn nicht zu einem digitalen State.
Widerspricht ein ausdrücklich gesetztes `details.analog=false`, bleibt die
Empfehlung unbestimmt.
Beim `Daytimer` gilt `is_analog` nur für den State `value`, nicht für Modus oder
Zeitwerte. Für `Daytimer` wird keine lokale Aufzeichnung empfohlen, weil lokale
Event-History-Quellen diesen Control-Typ nicht unterstützen. Eine aktive native Serie hat nur dann Vorrang, wenn ihr Output dem
State zugeordnet werden kann. Fehlt bei einer Legacy-Serie die State-UUID,
bleibt die Empfehlung unbestimmt. Die zeitliche Abdeckung muss weiterhin geprüft
werden. Teilweise lokale Aufzeichnung ist eine Abdeckungslücke,
kein Anlass für eine zweite Quelle. Ohne Nachweis der Signaldynamik nennt die
Intervall-Empfehlung keine festen Minutenwerte. Das Tool ändert keine
Aufzeichnungseinstellungen.
`source_diagnostics` meldet begrenzte Quelllücken wie Parseranomalien, ungültige KNX-Felder und
nicht modellierte Attribute. Dies sind keine Konfigurationsurteile; unbekannte Quellwerte werden
nicht ausgegeben, sondern nur feste Codes, Feldnamen, Wertformen und Projektknotenreferenzen.
Kann die Projektquelle gar nicht verarbeitet werden, enthält das normale Fehlerergebnis einen
festen, wertfreien `diagnostic_code`, der ungültige, nicht unterstützte, begrenzte, abgelaufene
und sonst fehlgeschlagene Quellenverarbeitung unterscheidet.

`loxone_get_structure_overview` liefert eine begrenzte erste Übersicht der für
den angemeldeten Loxone-Benutzer sichtbaren Räume, Kategorien und Control-Typen.
Sie enthält keine aktuellen Zustände, Historie, Zahlen zu versteckten Objekten
oder Config-Projektdaten; Details liefern die gezielten Discovery-Tools. Jede
Aufschlüsselung enthält höchstens 50 Einträge, und das vollständige Ergebnis-
Envelope ist mit expliziten Vollständigkeitsangaben auf 64 KiB begrenzt.

Für die erste Orientierung ersetzt dies getrennte Aufrufe von
`loxone_list_rooms`, `loxone_list_categories` und einem ungefilterten
`loxone_find_controls`-Aufruf, die nur deren aggregierte Verteilung ermitteln
sollen. Ein Client kann beispielsweise mit einem Overview-Aufruf sehen, dass
seine autorisiert sichtbare Struktur 18 Controls in vier Räumen und drei
Kategorien enthält, und anschließend `loxone_find_controls` nur für den
gewählten Raum, die Kategorie oder den Typ verwenden. Die gezielten Aufrufe
bleiben nötig, wenn einzelne Controls, Beschreibungen oder aktuelle Zustände
benötigt werden.

## Grenzen

- Genau ein Miniserver-Ziel wird unterstützt.
- Externer oder cloudbasierter MCP-Zugriff gehört nicht zum unterstützten Betrieb.
- Gen. 2/Compact bleibt experimentell, bis unabhängige Kompatibilitätsnachweise vorliegen.
- Nicht bestätigte Control-Aktionen werden nicht als hardwareverifiziert zugesagt.
- Keine freien Befehle, Loxone-Config-Verwaltung oder allgemeine LoxBerry-Systemadministration.

## Hardwarebestätigte Steuerung

Nur folgende Gen.-1-Aktionen wurden an ausdrücklich freigegebenen, harmlosen
Testfixtures bestätigt: `Switch.on`, `Switch.off`, `Dimmer.set_level`,
`Dimmer.off`, `TimedSwitch.on`, `TimedSwitch.off`, `LightControllerV2.set_mood`,
`Jalousie.open`, `Jalousie.set_position`, `Jalousie.enable_auto` und
`ColorPickerV2.set_color_hsv`. Diese Bestätigung überträgt sich nicht auf andere
Controls, Aktionen oder Installationen.

Die aktuelle Zuordnung von Plattformen, Clients und Nachweisstatus steht in der [Support-Matrix](../development/support-matrix.md).
