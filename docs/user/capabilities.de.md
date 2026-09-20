# Funktionsumfang und Grenzen

[English](capabilities.en.md)

## Unterstützter Umfang

Der Server liest sichtbare Räume, Kategorien, Controls und Zustände. Optional sind begrenzte Historie, Statistiken, maskierte LoxBerry-Diagnosen sowie dokumentierte, typabhängige Aktionen für sichtbare Gen.-1-Controls verfügbar.

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
Wenn eine exakt geprüfte Block-/Connector-Regel vorliegt, liefert Describe zusätzlich eine oder
mehrere getrennte KNX-Signalnutzungsbeobachtungen. Trace liefert getrennt markierte abgeleitete
Connectorkanten sowie begrenzte Pfade `knx_to_loxone`, `loxone_to_knx` oder `knx_to_knx`.
Unbekanntes Block- oder Connector-Verhalten wird nicht geraten. Diese Ergebnisse beschreiben
statische Projektpfade, keine Bus-Telegramme und keine historische Ursache einer Aktion.
`loxone_analyze_project` fasst begrenzte, projektlokale KNX-Evidenz zusammen: Adressmuster,
Wiederverwendung von Rohdatentypen, geprüfte Unterschiede der Signalnutzung, Pfadzähler und
Endpunkte ohne beobachtete Projektbeziehung. Findings sind Prüffakten, keine Qualitätsurteile.
Sie behaupten weder DPT-Kompatibilität noch ETS-Abdeckung, Busaktivität oder physische
Geräteverwendung; die Evidenz eines zurückgegebenen Projektknotens lässt sich mit Describe oder
Trace vertiefen.

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
