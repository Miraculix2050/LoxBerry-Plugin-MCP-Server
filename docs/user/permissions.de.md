# Berechtigungen

[English](permissions.en.md)

## Prinzip

Nutze für jeden Assistenten ein eigenes Loxone-Konto. Der Server zeigt nur Elemente, die dieser Benutzer sehen oder bedienen darf.

| Scope | Freigabe | Wirkung |
| --- | --- | --- |
| `loxone:read` | immer | Struktur, aktuelle Zustände und begrenzte Project Intelligence mit derselben Loxone-Identität lesen |
| `loxone:history` | optional | Historie und Statistiken lesen |
| `loxone:control` | optional | dokumentierte sichtbare Controls bedienen |
| `loxberry:read` | optional, lokal freigeben | maskierte Plugin- und Systemdiagnosen |
| `loxberry:operate` | optional, mit `loxone:history` und lokaler Freigabe | nur plugin-eigenen Statistik-Cache löschen |

Steuerung ist standardmäßig deaktiviert. Lokale LoxBerry-Freigaben sind exakt an Client, Loxone-Identität und Miniserver gebunden und ersetzen weder Loxone-Rechte noch OAuth-Zustimmung.

Project Intelligence ergänzt keinen Scope. Bei jedem Aufruf wird das Projekt erneut mit der
gebundenen Loxone-Identität abgerufen, um den Zugriff zu prüfen; zwischengespeicherte
Verarbeitungsergebnisse gewähren keinen Zugriff. Sie stellt begrenzten Graphstatus, Suche,
Objektbeschreibungen sowie vor- und nachgelagerte Signal- oder Referenzpfade bereit, aber keine
rohen Projektdateien und keine Projektänderung.

Weiter: [Funktionsumfang](capabilities.de.md).
