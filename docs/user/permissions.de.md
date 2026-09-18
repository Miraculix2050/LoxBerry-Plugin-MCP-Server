# Berechtigungen

[English](permissions.en.md)

## Prinzip

Nutze für jeden Assistenten ein eigenes Loxone-Konto. Der Server zeigt nur Elemente, die dieser Benutzer sehen oder bedienen darf.

| Scope | Freigabe | Wirkung |
| --- | --- | --- |
| `loxone:read` | immer | Struktur und aktuelle Zustände lesen; erlaubt bei Aufruf eine interne Projektanalyse mit derselben Loxone-Identität |
| `loxone:history` | optional | Historie und Statistiken lesen |
| `loxone:control` | optional | dokumentierte sichtbare Controls bedienen |
| `loxberry:read` | optional, lokal freigeben | maskierte Plugin- und Systemdiagnosen |
| `loxberry:operate` | optional, mit `loxone:history` und lokaler Freigabe | nur plugin-eigenen Statistik-Cache löschen |

Steuerung ist standardmäßig deaktiviert. Lokale LoxBerry-Freigaben sind exakt an Client, Loxone-Identität und Miniserver gebunden und ersetzen weder Loxone-Rechte noch OAuth-Zustimmung.

Die interne Projektanalyse ergänzt kein öffentliches Tool. Bei jedem Aufruf wird das Projekt erneut mit der gebundenen Loxone-Identität abgerufen, um den Zugriff zu prüfen; zwischengespeicherte Verarbeitungsergebnisse gewähren keinen Zugriff.

Weiter: [Funktionsumfang](capabilities.de.md).
