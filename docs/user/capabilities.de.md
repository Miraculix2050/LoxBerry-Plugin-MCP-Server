# Funktionsumfang und Grenzen

[English](capabilities.en.md)

## Unterstützter Umfang

Der Server liest sichtbare Räume, Kategorien, Controls und Zustände. Optional sind begrenzte Historie, Statistiken, maskierte LoxBerry-Diagnosen sowie dokumentierte, typabhängige Aktionen für sichtbare Gen.-1-Controls verfügbar.

`loxone_get_project_status`, `loxone_find_project_objects`,
`loxone_describe_project_object` und `loxone_trace_project_logic` stellen begrenzte,
schreibgeschützte Project Intelligence für ein durch die gebundene Loxone-Identität abrufbares
Projekt bereit. Sie liefern Graph-Evidenz statt rohem XML: Ein Signal- oder Referenzpfad beschreibt
strukturellen Einfluss, nicht eine beobachtete historische Ursache. Ergebnisse sind begrenzt und
melden Abschneiden explizit; unbekannte Blocktypen und unaufgelöste Beziehungen bleiben ohne
erfundene Semantik sichtbar. Ein Trace begrenzt unaufgelöste Beziehungen unabhängig und meldet
dies über `unresolved_truncated`.

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
