# Lokale Wetterhistorie

Die Wetteraufzeichnung ist unabhÃ¤ngig **standardmÃ¤ÃŸig aus**. Unter Admin â†’
Konfiguration Loxone-Historie aktivieren, aktuelle Wetterquellen laden, Felder
auswÃ¤hlen, die Quelle speichern und anschlieÃŸend die Wetteraktivierung ausdrÃ¼cklich
mit der Konfiguration speichern. Die skalare Ereignisaufzeichnung kann aus bleiben.
Deaktivieren erhÃ¤lt gespeicherte Daten. Entfernen einer Quelle stoppt ihre Aufnahme;
die vollstÃ¤ndige HistorienlÃ¶schung lÃ¶scht auch Wetterdaten. Aufbewahrung und
GrÃ¶ÃŸenlimit werden mit der Ereignishistorie geteilt.

Der bestehende Recorder und die gemeinsame SQLite-Datenbank speichern nur gewÃ¤hlte
Felder. Aktuelle Quellenwerte und Prognosen behalten getrennte Modi. Ein empfangener
Wert belegt keine tatsÃ¤chliche Messung. Unbekannte Einheiten und Strahlungskodierung
bleiben unbekannt. FrÃ¼here Wetterdaten und Unterbrechungen werden nicht aufgefÃ¼llt.

`loxone_get_weather(mode="history", history_options=...)` benÃ¶tigt eine genaue,
aktuell sichtbare `state_uuid`, den `stored_mode` sowie `start`/`end` mit Zeitzonenoffset.
Der Zeitraum umfasst hÃ¶chstens 31 Tage auf der **lokalen Empfangszeitachse**; sein
exklusives Ende liegt in der Vergangenheit. Aktivierte Rechte `loxone:read` und
`loxone:history` werden je Seite geprÃ¼ft. Die konfigurierte Recorderquelle muss
weiterhin passen; die Aufnahme selbst darf deaktiviert sein.

Standardseiten zeigen Lieferungs-/Punktmetadaten und Aufnahmephasen. Numerische
Rohwerte benÃ¶tigen `include_raw=true`. HÃ¶chstens 96 Punktzeilen und 128 Aufnahmephasen
werden ausgegeben. Die gesamte Antwort bleibt unter 64 KiB; gegebenenfalls eine
kleinere Seite wÃ¤hlen. `next_cursor` unverÃ¤ndert weitergeben. LÃ¶schung, Aufbewahrung,
Quellen-/Feld-/FormatÃ¤nderung oder ein anderer Aufrufer machen ihn ungÃ¼ltig;
dann wieder mit Seite eins beginnen.

`received_at`, `point_at` und `reported_update_at` sind getrennte UTC-Unixsekunden.
ZukÃ¼nftige Prognosepunkte bleiben bei einer Abfrage frÃ¼herer Empfangszeiten Prognosen.
Die gemeldete Aktualisierung belegt keinen Prognose-Ausgabezeitpunkt. Aufnahmebereitschaft
und gelieferte Punktabdeckung sind getrennt; weder Liefertakt noch kontinuierliche
Beobachtung werden behauptet. Actual projiziert den ersten Punkt und schlieÃŸt Punkte
vor Aufnahmestart oder nach Empfang aus. UngÃ¼ltige oder zu groÃŸe Lieferungen erzeugen
eine ausdrÃ¼ckliche Unterbrechung, keinen behaupteten vollstÃ¤ndigen Teilerfolg.

Gelesen wird nur der aktuelle Anlagen-/Quellen-/Feld-/Metadatenfingerprint. Ã„ltere
Generationen behalten Aufbewahrung und LÃ¶schung, werden aber nicht still vermischt.
Formate ausgewÃ¤hlter Felder und Wettertyptexte belegen Herkunft, keine Einheit.
Stations-/Provider-/Standortwechsel sind nicht vollstÃ¤ndig erkennbar. Vergleichstage
und eine PV-Prognose werden durch diese Stufe noch nicht geliefert.

Das gemeinsame SQLite-Schema wird atomar und wiederholbar auf v8 migriert. Vor einem
Hotswap einen WAL-konsistenten v7-Snapshot Ã¼ber den vorhandenen Deployment-/Upgradehelfer
erstellen. Alter Code lehnt v8 ab; ein reiner Coderollback genÃ¼gt nicht. Vor Wiederherstellung
den aktuellen v8-Stand sichern. Der v7-Snapshot stellt seinen frÃ¼heren Datenstand wieder
her; spÃ¤tere Aufnahmen bleiben im getrennten v8-Backup. Hotswap belegt keine native
Installation oder UpgradefÃ¤higkeit.
