# Native PV-Produktionsvorhersagen

Einen sichtbaren `PvProductionForecast` mit `loxone_find_controls` suchen und
`loxone_read_controls(targets=[{"control_uuid":"<gefundene UUID>"}], native_result_view="pv_forecast")` aufrufen.
Dieser Lesezugriff benötigt `loxone:read`, keine lokale LoxBerry-Dateifreigabe.
Steuerung und Konfiguration werden nicht verändert. Für EFM-Ansichten gelten
weiterhin deren eigene Voraussetzungen.

Der native Befehl `getForecasts` liefert stündliche kWh für heute, morgen und
übermorgen. Das Ergebnis normalisiert diese in Wh mit Unix-Stundengrenzen.
Aggregierte Zustände bleiben getrennt. Zustandszeitstempel verwenden die
Loxone-Epoche 2009, Prognosezeitstempel Unix. Fehlende Stunden werden nicht ergänzt.

Verfügbarkeit erfordert einen bereiten Baustein, Fehlerstatus null, einen höchstens
drei Stunden alten Prognosezeitstempel und nutzbare Stundenwerte. Ready=0 und
aggregierte Werte -1 bedeuten keine nutzbare Vorhersage. ErrorInfo ist eine native
Bitmaske: Bit 1 steht für WeatherServiceError, Bit 0 für InternetError. Das belegt
weder ein abgelaufenes Abonnement noch einen bestimmten Netzwerkfehler.
Veröffentlichungszeitpunkt des Anbieters und Prognosesicherheit fehlen.
Native Vorhersagen sind Modellschätzungen und berücksichtigen keine
Wechselrichterbegrenzungen; mit realer Produktion vergleichen.

PVPF benötigt einen aktiven Loxone-Wetterdienst und die konfigurierte installierte
kWp-Leistung. Fehlende Einrichtung erklären; nicht automatisch aktivieren,
abonnieren oder umkonfigurieren. Native Prognosen sind von der bestehenden
W/m²-Wetterorientierung getrennt.

Bei aktuellem nativem `ready=0` wird `not_ready` ohne Abruf nicht verfügbarer Stundenwerte zurückgegeben. Autorisierung und Quellensichtbarkeit werden weiterhin geprüft.
