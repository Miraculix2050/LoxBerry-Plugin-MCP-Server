# Lokale Strahlungsprognosen

Das bestehende Wettertool kann eine qualifizierte lokale Prognose erkennen und
zukünftige Zeitfenster anhand von Strahlungsprognosepunkten vergleichen. Das ist
Wetterorientierung in W/m² ohne Aussage über PV-Ertrag, Überschuss, zulässige
Geräteschaltung oder Einsparungen. Lux lässt sich nicht allgemein in W/m²
umrechnen. Native ganzzahlige Loxone-Wetterfelder bleiben unqualifiziert.

Unter Admin → Konfiguration → Lokale Strahlungsprognose die lokale stündliche
VisualCrossing-Quelle von Weather4Lox prüfen. Standort und Zeitzone mit der
konfigurierten Miniserver-Anlage abgleichen. Diese Zuordnung ausdrücklich
bestätigen, die Quelle aktivieren und speichern. Standardmäßig ist sie aus.
Das maximale Alter der lokalen Dateiveröffentlichung beträgt standardmäßig
180 Minuten; dies ist kein belegtes Prognosemodellalter. Nach einer Änderung
von Standort, Zeitzone oder Miniserver ist eine erneute Bestätigung erforderlich.
Deaktivieren erhält die Quelldatei. Dieser Adapter stellt keine Cloud-Anfragen
und akzeptiert keine frei wählbaren Quellpfade oder URLs.

Der MCP-Client benötigt außerdem `loxone:read`, separat aktivierte LoxBerry-Lese-
zugriffe, `loxberry:read` und eine aktuelle lokale Administratorfreigabe für
diesen Client. Ein Loxone-Login allein erlaubt keinen lokalen Dateizugriff.
Mit `loxone_get_weather(mode="forecast_sources")` beginnen. Nur die registrierte
lokale Quelle wird geprüft. Deaktivierte oder nicht freigegebene Quellen werden
nicht gelesen. Fehlende, nicht unterstützte, geänderte und veraltete Quellen
werden unterschieden. Die Konfigurationshinweise und den Nutzen qualifizierter
Prognosepunkte für den Vergleich künftiger Zeitfenster erläutern. Ein späterer
Config-MCP-Import erfordert einen separaten ausdrücklichen Benutzerauftrag.

Für `mode="solar_windows"` in `future_options` zukünftige `start`/`end`-Zeitpunkte
mit UTC-Offset, eine IANA-`timezone`, `duration_hours` (1–24) und optional einen
nichtnegativen `minimum_sample_irradiance_w_m2` angeben. Der Zeitraum berührt
höchstens 31 lokale Kalendertage. Bis zu 16 nicht überlappende Beispiele werden
nach dem Mittelwert der Prognosepunkte und anschließend nach dem frühesten
Zeitpunkt geordnet. `include_samples=true` liefert optional die Punkte mit.
Cursor und History-Optionen gelten hier nicht. Die bisherigen Modi actual,
forecast und history sowie ihr Standardverhalten bleiben verfügbar.

Die stündlichen Werte sind Punktprognosen. Nominelle Fensterenden und Mittelwerte
belegen weder Bedingungen zwischen den Punkten noch eine mittlere Strahlung
über ein Zeitintervall. Daraus weder Wh/m² integrieren noch PV Wh ableiten.
Lokale Veröffentlichung, gemeldete Quellgenerierung, unbekannter Ausgabezeitpunkt
des Anbieters und unbekannte Prognosesicherheit bleiben getrennt. Ungeeignete
Werte werden aus nutzbaren Fenstern ausgeschlossen, mit begrenzter Diagnostik
und einem korrelierten Warnlog. Die Originaldatei bleibt erhalten. Bei nicht
unterstützter Zahlengenauigkeit bleibt die rein numerische Originaldarstellung
bis 256 Zeichen sichtbar. Diese Grenzen dem Benutzer mitteilen, ohne einen
belegten Gerätefehler zu behaupten. Lücken werden nicht interpoliert. Für eine
PV-Ertragsplanung fehlen weiterhin qualifizierte Anlagen- und Lastnachweise;
native Sperren und zulässige Lastpläne bleiben unbekannt.
Die vollständige Planung wird in [#510](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/510) weitergeführt.
