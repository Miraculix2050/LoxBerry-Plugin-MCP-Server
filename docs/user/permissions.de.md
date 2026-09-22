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
| `loxberry:operate` | optional, mit `loxone:history` und lokaler Freigabe | plugin-eigenen Statistik-Cache löschen und ausdrücklich konfigurierte Quellen der lokalen Ereignishistorie verwalten |

Steuerung ist standardmäßig deaktiviert. Lokale LoxBerry-Freigaben sind an Client-Anwendung, Loxone-Identität, Miniserver und die konkrete Capability gebunden und ersetzen weder Loxone-Rechte noch OAuth-Zustimmung. Beim streng geprüften lokalen Tool Explorer kann eine neue OAuth-Anmeldung dessen Anwendungsfreigabe bis zur angezeigten Aufbewahrungsfrist wiederverwenden. Andere dynamisch registrierte Clients bleiben an ihre exakte OAuth-Clientkennung gebunden.

Project Intelligence ergänzt keinen Scope. Bei jedem Aufruf wird das Projekt erneut mit der
gebundenen Loxone-Identität abgerufen, um den Zugriff zu prüfen; zwischengespeicherte
Verarbeitungsergebnisse gewähren keinen Zugriff. Sie stellt begrenzten Graphstatus, Suche,
Objektbeschreibungen sowie vor- und nachgelagerte Signal- oder Referenzpfade bereit, aber keine
rohen Projektdateien und keine Projektänderung.
KNX/EIB-Metadaten sind eine erlaubnisgebundene, begrenzte Projektion desselben autorisierten
Projekts. Sie geben weder beliebige Projektattribute noch ETS-Daten, Busmonitoring oder
Konfigurationsschreibzugriffe frei.

Weiter: [Funktionsumfang](capabilities.de.md).
