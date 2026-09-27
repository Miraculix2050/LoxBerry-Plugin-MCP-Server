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
| `loxberry:operate` | optional, mit `loxone:history` und lokaler Freigabe | plugin-eigenen Statistik-Cache löschen, Quellen der lokalen Ereignishistorie verwalten und gespeicherte Historie einer inaktiven Quelle ausdrücklich endgültig löschen |

Steuerung ist standardmäßig deaktiviert. Lokale LoxBerry-Freigaben sind an Client-Anwendung, Loxone-Identität, Miniserver und die konkrete Capability gebunden und ersetzen weder Loxone-Rechte noch OAuth-Zustimmung. Beim streng geprüften lokalen Tool Explorer kann eine neue OAuth-Anmeldung dessen Anwendungsfreigabe bis zur angezeigten Aufbewahrungsfrist wiederverwenden. Andere dynamisch registrierte Clients bleiben an ihre exakte OAuth-Clientkennung gebunden.

Project Intelligence ergänzt keinen Scope. Bei jedem Aufruf werden die gebundene Identität
geprüft und die aktuell sichtbare Loxone-Struktur über eine authentifizierte Sitzung gelesen.
Ihr Projektänderungsmarker und die frische Sichtbarkeitsprüfung bestimmen die Gültigkeit des Caches.
Bei unverändertem Marker kann ein begrenzter Graph im Arbeitsspeicher wiederverwendet
werden; bei geändertem oder nicht verfügbarem Marker wird er verworfen. Das Projekt wird erneut
geladen, wenn der Graph neu aufgebaut werden muss. Zwischengespeicherte Ergebnisse gewähren
keinen OAuth-Zugriff. Sie stellt begrenzten Graphstatus, Suche,
Objektbeschreibungen sowie vor- und nachgelagerte Signal- oder Referenzpfade bereit, aber keine
rohen Projektdateien und keine Projektänderung.
Folgeseiten der Projektsuche und -analyse verwenden begrenzte geordnete Ergebnisse bis zu fünf Minuten lang.
Ein Cursor verfällt, wenn dieses Ergebnis verdrängt wird oder sich Projekt, sichtbare Struktur,
Identität oder Analyseauswahl ändern. In diesem Fall muss die erste Seite erneut geladen werden.
KNX/EIB-Metadaten sind eine erlaubnisgebundene, begrenzte Projektion desselben autorisierten
Projekts. Sie geben weder beliebige Projektattribute noch ETS-Daten, Busmonitoring oder
Konfigurationsschreibzugriffe frei.
Native Loxone-Historie und Statistiken prüfen vor der Datenausgabe die aktuelle Sichtbarkeit,
auch bei einem Treffer im Statistik-Cache. Bei vorhandener Sitzungsstruktur prüfen sie den
authentifizierten Projektmarker und verwenden die Struktur derselben OAuth-Familie nur bei
unverändertem Marker. Bei einer Änderung wird sie erneut geladen; schlägt die Markerprüfung
fehl, werden keine zwischengespeicherten History-Daten ausgegeben. Ohne vorhandene
Sitzungsstruktur wird sie frisch geladen. Die lokale Ereignishistorie prüft die Sichtbarkeit
weiterhin durch einen frischen Strukturabruf.

Weiter: [Funktionsumfang](capabilities.de.md).
