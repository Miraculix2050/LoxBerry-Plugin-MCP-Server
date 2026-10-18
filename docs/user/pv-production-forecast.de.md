# Native PV-Prognosen und Solaraufzeichnung

Beschreiben Sie den sichtbaren Baustein `PvProductionForecast` und lesen Sie seine
benannten Zustände mit Semantik. `period`, `today`, `tomorrow` und `after` sind
Prognosen in kWh. `ready=0`, Prognosewerte -1 oder Fehlerflags bedeuten keine
verfügbare Vorhersage. Prognosezeit und Zyklusgrenzen sind von der Empfangszeit
getrennt; ein frisch gelesener Zustand garantiert keine neue Prognose.

In Admin unter „Solarbeobachtungen und PV-Prognosen“ zuerst die Quellen laden,
Anlagenzuordnung, Einheit und Quellenvertrag prüfen und bestätigen. Quellen zur
Auswahl hinzufügen, bei Bedarf die Aufzeichnung aktivieren und anschließend
„Solaraufzeichnung speichern und anwenden“ wählen. Die Auswahl allein startet
keine Aufzeichnung. Loxone-Historie muss aktiviert sein. Konkurrierende Änderungen
erfordern erneutes Laden. Gespeicherte Daten bleiben nach Entfernen einer Quelle
bis zur gemeinsamen Aufbewahrungsgrenze oder vollständigen Löschung erhalten.
Gespeicherte Auswahl, Abschalten und Entfernen sind auch ohne erreichbaren
Miniserver verfügbar; neue Quellen und das Einschalten benötigen eine aktuelle
Sichtbarkeitsprüfung.

Es werden nur ausgewählte aktuelle Strahlungs-/Temperaturzustände oder
zusammengehörige PV-Prognosesnapshots aufgezeichnet. Standardmäßig gilt ein
60-Sekunden-Abstand. Zustandsstichproben sind keine kontinuierlichen physikalischen
Messungen; bei Verbindungsabbruch wird keine alte Verbindung fortgeschrieben.
Prognosen bleiben Prognosen und erhalten keine rückwirkende Historie. Aus der
bewerteten PV-Leistung berechnete Strahlung ist kein unabhängiger Wettermaßstab.
PVPF ersetzt weder beobachtete Strahlungshistorie noch einen Speicherbilanzansatz.

Das gemeinsame SQLite-Historienformat wird auf V9 erweitert. Vor einem
Datei-Hotswap die Datenbank konsistent sichern; für eine Rückkehr zu V8 müssen
passende Programmdateien und Datenbanksicherung gemeinsam wiederhergestellt werden.
