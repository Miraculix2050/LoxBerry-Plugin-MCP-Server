# Lokale Wetterhistorie

Die Wetteraufzeichnung ist unabhängig **standardmäßig aus**. Unter Admin →
Konfiguration Loxone-Historie aktivieren, aktuelle Wetterquellen laden, Felder
auswählen, die Quelle speichern und anschließend die Wetteraktivierung ausdrücklich
mit der Konfiguration speichern. Die skalare Ereignisaufzeichnung kann aus bleiben.
Deaktivieren erhält gespeicherte Daten. Entfernen einer Quelle stoppt ihre Aufnahme;
die vollständige Historienlöschung löscht auch Wetterdaten. Aufbewahrung und
Größenlimit werden mit der Ereignishistorie geteilt.

Der bestehende Recorder und die gemeinsame SQLite-Datenbank speichern nur gewählte
Felder. Aktuelle Quellenwerte und Prognosen behalten getrennte Modi. Ein empfangener
Wert belegt keine tatsächliche Messung. Unbekannte Einheiten und Strahlungskodierung
bleiben unbekannt. Frühere Wetterdaten und Unterbrechungen werden nicht aufgefüllt.

`loxone_get_weather(mode="history", history_options=...)` benötigt eine genaue,
aktuell sichtbare `state_uuid`, den `stored_mode` sowie `start`/`end` mit Zeitzonenoffset.
Der Zeitraum umfasst höchstens 31 Tage auf der **lokalen Empfangszeitachse**; sein
exklusives Ende liegt in der Vergangenheit. Aktivierte Rechte `loxone:read` und
`loxone:history` werden je Seite geprüft. Die konfigurierte Recorderquelle muss
weiterhin passen; die Aufnahme selbst darf deaktiviert sein.

Standardseiten zeigen Lieferungs-/Punktmetadaten und Aufnahmephasen. Numerische
Rohwerte benötigen `include_raw=true`. Höchstens 96 Punktzeilen und 128 Aufnahmephasen
werden ausgegeben. Die gesamte Antwort bleibt unter 64 KiB; gegebenenfalls eine
kleinere Seite wählen. `next_cursor` unverändert weitergeben. Löschung, Aufbewahrung,
Quellen-/Feld-/Formatänderung oder ein anderer Aufrufer machen ihn ungültig;
dann wieder mit Seite eins beginnen.

`received_at`, `point_at` und `reported_update_at` sind getrennte UTC-Unixsekunden.
Zukünftige Prognosepunkte bleiben bei einer Abfrage früherer Empfangszeiten Prognosen.
Die gemeldete Aktualisierung belegt keinen Prognose-Ausgabezeitpunkt. Aufnahmebereitschaft
und gelieferte Punktabdeckung sind getrennt; weder Liefertakt noch kontinuierliche
Beobachtung werden behauptet. Actual projiziert den ersten Punkt und schließt Punkte
nach Empfang aus. Neu empfangene ältere Punkte tragen `point_predates_capture=true`;
sie belegen keine Aufnahmeabdeckung vor Aufzeichnungsbeginn. Ungültige oder zu große
Lieferungen erzeugen eine ausdrückliche Unterbrechung, keinen behaupteten vollständigen
Teilerfolg.

Gelesen wird nur der aktuelle Anlagen-/Quellen-/Feld-/Metadatenfingerprint. Ältere
Generationen behalten Aufbewahrung und Löschung, werden aber nicht still vermischt.
Formate ausgewählter Felder und Wettertyptexte belegen Herkunft, keine Einheit.
Stations-/Provider-/Standortwechsel sind nicht vollständig erkennbar. Vergleichstage
und eine PV-Prognose werden durch diese Stufe noch nicht geliefert.

Das gemeinsame SQLite-Schema wird atomar und wiederholbar auf v8 migriert. Vor einem
Hotswap einen WAL-konsistenten v7-Snapshot über den vorhandenen Deployment-/Upgradehelfer
erstellen. Alter Code lehnt v8 ab; ein reiner Coderollback genügt nicht. Vor Wiederherstellung
den aktuellen v8-Stand sichern. Der v7-Snapshot stellt seinen früheren Datenstand wieder
her; spätere Aufnahmen bleiben im getrennten v8-Backup. Hotswap belegt keine native
Installation oder Upgradefähigkeit.
