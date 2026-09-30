# Funktionsumfang und Grenzen

[English](capabilities.en.md)

## Unterstützter Umfang

Für WindowMonitor-Controls behält die vollständige Beschreibung die ersten 100
konfigurierten Positionen in der Quellreihenfolge der Liste oder des Mappings bei,
einschließlich fehlerhafter Platzhalter. `capabilities.model.window_monitor_summary`
meldet `total`, `returned`, `omitted` und `truncated`; nur erhaltene explizite Referenzen
können interne Controls zusätzlich zum Lesen sichtbar machen. Explizite unabhängige
Benutzerlinks behalten ihre bestehende Autorisierung; die reine Monitor-Lesefreigabe
übersteuert weder diese Links noch andere Nur-Lese-Beschränkungen. Fehlende/null-Sammlungen
sind leer. Ungültige Sammlungsformen melden `invalid_window_monitor_collection` mit
unbekannter (`null`) Gesamtzahl und ausgelassener Anzahl. Ordnen Sie `windowStates`
über den ursprünglichen nullbasierten Index zu; ausgelassene Positionen belegen keine
fehlenden Kontakte. Kompakte Ansichten enthalten diese Felder nicht. Eine vollständige
Konfigurationsdarstellung belegt keine physische Öffnungsabdeckung.

Jeder erhaltene Eintrag enthält eine sortierte Liste fester `diagnostics`-Codes ohne
zurückgewiesene Quellwerte. Die Codes unterscheiden fehlerhafte Einträge
(`invalid_window_monitor_entry`), ungültige Felder (`invalid_name`,
`invalid_install_place`, `invalid_control_reference`, `invalid_room_reference`),
fehlende Referenzen (`missing_control_reference`, `missing_room_reference`), nicht
verfügbare sichtbare Referenzen (`control_reference_unavailable`,
`room_reference_unavailable`) und explizite Raumkonflikte (`room_reference_mismatch`).
Fehlende optionale Namen/Installationsorte sind gültig; ungültige vorhandene Werte,
einschließlich null, werden diagnostiziert. Eine zurückgewiesene Referenz ohne gültigen
Fallback kann zusätzlich fehlen. Ein gültiger Mapping-Schlüssel bleibt als Fallback
nutzbar, auch wenn das explizite UUID-Feld ungültig ist.

`resolution_status` ist `resolved`, wenn Control und Eintragsraum aufgelöst sind,
`partially_resolved`, wenn genau eine Referenz aufgelöst ist, andernfalls `unresolved`.
Das Summary zählt diese Zustände ausschließlich für erhaltene Positionen; ihre Summe
entspricht `returned`. `room_consistency` ist separat `match`, `mismatch` oder `unknown`
und vergleicht ausschließlich explizite UUIDs bei sichtbarem Control und zwei sichtbaren
Räumen. Ein Konflikt ändert den Auflösungsstatus nicht. Verborgene und unbekannte Ziele
sind gleichermaßen nicht verfügbar; Namen belegen weder Identität noch Kontaktrollen
oder die physische Richtigkeit.

Der Server liest sichtbare Räume, Kategorien, Controls und Zustände. Optional sind begrenzte Historie, Statistiken, maskierte LoxBerry-Diagnosen sowie dokumentierte, typabhängige Aktionen für sichtbare Gen.-1-Controls verfügbar.

Für aktuelle Werte nach der Suche `loxone_describe_control(view="state_refs")` verwenden. Die Ansicht liefert nur Control-Identität, Sichtbarkeit und die vollständige normalisierte `states`-Liste mit Namen und UUIDs, ohne Raum-/Kategorie-Kontext, Fähigkeiten, Statistiken, Historie, Darstellung oder Beziehungen. Sie lädt die nutzergefilterte Struktur neu und liefert bei fehlgeschlagener Aktualisierung einen Fehler statt zwischengespeicherter Referenzen. `stale` kennzeichnet einen getrennten Ereignisstream; `observed_at` ist der Beschreibungszeitpunkt, kein Messzeitpunkt eines State-Werts. Nur benötigte UUIDs auswählen, Duplikate entfernen und `loxone_get_states` in Gruppen von höchstens 100 aufrufen; bei leerer Auswahl keinen Werte-Read ausführen. Für versteckte Controls bleibt `include_hidden=true` sowohl bei der Diagnose als auch beim Werte-Read erforderlich. `history_targets` dient der Historien-/Statistikauswahl, `operation_targets` der Bedienvorbereitung und `full` der weiterführenden Diagnose.

Nach der Suche mit `loxone_find_controls` kann `loxone_describe_control` mit `view="history_targets"` nur die Control-Identität, State-Namen und -UUIDs, das Kennzeichen für native Control-Historie sowie IDs und Metadaten beworbener Statistikserien liefern. Der Standardwert `view="full"` behält die ausführliche Antwort bei. `native_statistics_truncated=true` in der kompakten Ansicht bedeutet, dass mehr als 128 gültige StatisticV2-Serien gefunden und einige ausgelassen wurden. Ein aufgeführtes Ziel belegt weder eine lokale Ereignisaufzeichnung noch die Abdeckung eines angefragten Zeitraums durch native Historie oder Statistik; dafür ist die jeweilige Historienantwort zu prüfen.

Für eine Control-Bedienung unmittelbar vor `loxone_operate_control` `view="operation_targets"` verwenden. Die Ansicht liefert nur die Control-Identität, aktuell sichtbare zulässige Aktionen und aktionsspezifische Ziele für die Parameter: Radio-Ausgänge, Szenen-IDs, Analogbereich, Override-Modi, Mood-List-State-Referenz und gegebenenfalls Temperaturgrenzen. Leere Zielfelder bedeuten, dass das Control diese Auswahlwerte nicht bewirbt. Für numerische Operationsparameter gelten weiterhin die Grenzen im Tool-Schema. State-Listen, Statistiken, Historie, Beziehungen und Darstellungsmetadaten entfallen; für Diagnosen bleibt `full` verfügbar. Diese Ansicht lädt die aktuelle nutzergefilterte Struktur neu; schlägt die Aktualisierung fehl, werden keine zwischengespeicherten Bedienziele zurückgegeben.

Wenn ein Administrator sie aktiviert, kann der Server ausgewählte State-UUIDs zusätzlich als begrenzte lokale Ereignishistorie aufzeichnen. Sie ergänzt die native Loxone-Historie für kurzlebige Wechsel und erweitert nie die Sichtbarkeit der aufrufenden Identität.

`loxone_list_event_history_sources` listet aktive und entfernte Quellen mit vorhandener Historie nur dann auf, wenn Control und State für den Aufrufer aktuell sichtbar sind. Dafür sind `loxone:read` und `loxone:history` nötig; ist die aktuelle Loxone-Sicht nicht verfügbar, liefert das Tool einen Fehler. `loxberry_list_event_history_sources` liefert den vollständigen Quellenbestand im selben seitenweisen Antwortschema und benötigt zusätzlich entweder aktiviertes `loxberry:read` mit genauer lokaler Read-Freigabe oder aktiviertes `loxberry:operate` mit genauer lokaler Operate-Freigabe. Scopes und Freigaben bleiben unabhängig. Beide Listen melden `recording_status` und einen bekannten `recording_ended_at`; mit `next_cursor` lassen sich alle Quellen abrufen. Das Auflisten erlaubt keine Änderungen: Add, Remove und Purge behalten ihre Operate-Anforderungen.

Das Entfernen einer Quelle beendet die Aufzeichnung; gespeicherte Ereignisse bleiben lesbar, solange Control und State für den Aufrufer aktuell sichtbar sind. `loxone_get_event_history` meldet `recording_status`, `recording_ended_at`, `recording_notice` und die `coverage` des angefragten Zeitraums getrennt. `active` bedeutet für die Aufzeichnung konfiguriert; nur `coverage` belegt eine Erfassung im angefragten Zeitraum. Die Pause nach dem Entfernen gilt nie als durchgehend erfasst. Die globalen Alters- und Datenbankgrößenlimits gelten weiter. Ein freigegebener Client kann Ereignisse und Abdeckung einer inaktiven Quelle mit `loxberry_purge_event_history_source` und `confirm=true` endgültig löschen. Ist das Purge-Ergebnis unbekannt, etwa nach einem Timeout oder einem Nachpflegefehler nach dem Commit, darf der Aufruf nicht automatisch wiederholt werden.

Falls das Ergebnis zum Speichern der Entfernungsmarkierung unbekannt ist, vor einem manuellen erneuten `remove` die Quellenliste und Historie prüfen. Der erneute Aufruf kann die Markierung nachtragen; `recording_ended_at` bleibt leer, wenn der ursprüngliche Endzeitpunkt nicht belegbar ist.

`loxone_get_project_status`, `loxone_find_project_objects`,
`loxone_describe_project_object`, `loxone_trace_project_logic` und
`loxone_analyze_project` stellen begrenzte,
schreibgeschützte Project Intelligence für ein durch die gebundene Loxone-Identität abrufbares
Projekt bereit. Sie liefern Graph-Evidenz statt rohem XML: Ein Signal- oder Referenzpfad beschreibt
strukturellen Einfluss, nicht eine beobachtete historische Ursache. Ergebnisse sind begrenzt und
melden Abschneiden explizit; unbekannte Blocktypen und unaufgelöste Beziehungen bleiben ohne
erfundene Semantik sichtbar. Ein Trace begrenzt unaufgelöste Beziehungen unabhängig und meldet
dies über `unresolved_truncated`.
Bestätigte KNX/EIB-Projektobjekte ergänzen begrenzte, quellengestützte Metadaten für Buslinien,
Endpunkte und KNX-Logikblöcke. Die Endpunktrichtung lautet `bus_to_loxone` oder
`loxone_to_bus`; sie ist keine Aussage über die physische Gerätefunktion. Gruppenadressen
behalten ihren Originaltext und erhalten nur bei gültigem Format eine kanonische Form. `EIBType`
bleibt ein unaufgelöster Quellcode, keine geratene DPT. `EIBextsensor` und `EIBtextsensor`
führen vom Bus zu Loxone; `EIBextactor` und `EIBtextactor` führen von Loxone zum Bus.
Gültige Adressvarianten `:0` und `:1` bleiben für die beiden externen Typen getrennt;
die Adresse nennt `EibAddr` oder nur bei `EIBextsensor`, falls dieses Feld fehlt,
`EibAddrPulse` als Quelle. Das Suffix
belegt keine physische Flankenrichtung. Eine exakte Variantensuche findet nur diese Variante;
die Suche nach der kanonischen Basis kann beide liefern. Gleiche Gruppenadressen erzeugen keine
Graphbeziehung und beweisen keine Kausalität. Suche und Trace liefern eine kompakte
KNX-Zusammenfassung mit Original- und kanonischer Adresse, Quellfeld und Variante. Segmente,
Namen, einen vorhandenen Rohdatentyp sowie begrenzte Connector-IDs und -Schlüssel mit
Anzahlen ein- und ausgehender Signalverbindungen liefert `loxone_describe_project_object`.
Fehlendes `EIBType` bei den neu modellierten Typen lässt den Datentyp unbekannt.
Der Filter `knx_group_address` akzeptiert gültige zwei- oder dreistufige Adressen und die
Varianten `:0`/`:1`. Ungültige Syntax oder Zahlenbereiche liefern `invalid_input`; eine gültige
Adresse ohne Treffer ergibt eine erfolgreiche leere Suchseite. Auch gültige Originalformen
werden nur exakt mit Original- oder kanonischer Adresse verglichen.
Projekt-Suchseiten und Traces sind zusätzlich auf 64 KiB
begrenzt und melden eine Größenkürzung über `truncated` und `truncation_reason`.
`project_parts` zählt intern eingelesene Modellquellen, nicht Loxone-Config-Projekte. Status
liefert opake `model_sources`; identische KNX-Quellvorkommen aus getrennten Modellquellen werden
einmal als logisches Objekt mit `source_occurrence_count` und `model_source_ids` dargestellt.
Gleiche Titel oder Gruppenadressen führen nie zu einer solchen Zusammenführung.
Wenn eine exakt geprüfte Block-/Connector-Regel vorliegt, liefert Describe zusätzlich eine oder
mehrere getrennte KNX-Signalnutzungsbeobachtungen. Trace liefert getrennt markierte abgeleitete
Connectorkanten sowie begrenzte Pfade `knx_to_loxone`, `loxone_to_knx` oder `knx_to_knx`.
Unbekanntes Block- oder Connector-Verhalten wird nicht geraten. Diese Ergebnisse beschreiben
statische Projektpfade, keine Bus-Telegramme und keine historische Ursache einer Aktion.
`loxone_analyze_project` Version 7 fasst begrenzte, projektlokale KNX-Evidenz zusammen:
Adress- und Quellnamensmuster, Wiederverwendung von Rohdatentypen, geprüfte Unterschiede der
Signalnutzung, Kontext aus exakten Runtime-Mappings, lokale Peer- und Graph-Ausreißer,
Pfadzähler und Endpunkte ohne direkte konfigurierte Verdrahtung. Graph-Ausreißer benennen den
rohen Kantengrad und zeigen Signal- und Referenzkanten sowie getrennt abgeleitete semantische
Kanten mit begrenzten Konnektorbelegen. Ein Konnektivitätsbefund unterscheidet direkte
Signalverdrahtung von Referenzen und nennt die geprüften Konnektoren. „Kein direkt konfigurierter
Verbraucher gefunden“ (bei einem Ausgang: „keine direkt konfigurierte Eingangsquelle gefunden“)
bezieht sich nur auf die statische Projektverdrahtung; daraus folgt weder eine unbenutzte
Gruppenadresse noch ein inaktives Gerät. Runtime-Namen und Control-Typen werden
nur bei exaktem UUID-Mapping verwendet; Namen erzeugen nie ein Mapping.
Findings sind Prüffakten, keine Qualitätsurteile. Feste Limitierungs-Codes kennzeichnen fehlende
normalisierte DPTs, Semantikdomänen, geprüfte Signalnutzung oder Runtime-Mappings. Die Analyse
behauptet weder DPT-Kompatibilität noch ETS-Abdeckung, Busaktivität oder physische
Geräteverwendung; die Evidenz eines zurückgegebenen Projektknotens lässt sich mit Describe oder
Trace vertiefen.
Projektstatus und Analyse liefern außerdem `coverage_by_source_type`. Rohe
Quellobjekt-Vorkommen werden getrennt von logischen Endpunkt-, Logikblock- und
Linienzahlen gezählt; zusätzliche, über Modellquellen zusammengefasste Vorkommen
sind eigens ausgewiesen. Unklare KNX-Kandidaten und ausgelassene Typgruppen machen
die Abdeckung unvollständig. Objektdetails kennzeichnen `EIBType` als rohen
Loxone-Config-Wert und melden, dass normalisierte DPT-Evidenz derzeit fehlt.
Mit `address_hierarchy` lassen sich gemessene ein-, zwei- und dreistufige
Adresspräfixe seitenweise abrufen. Jeder Präfixeintrag trennt logische Endpunkte,
rohe Modellquellenvorkommen, kanonische Adressen und Flankenvarianten und zeigt
begrenzte Beispiele der Originaladressen. Direkte Verdrahtung bedeutet eine
beobachtete Signal- oder Referenzbeziehung im Projekt; ungeklärte Beziehungen
bleiben getrennt. Muster und Ausreißer nennen ihre lokale Vergleichsgruppe,
bewerten aber keine Konfiguration. Optionale KNX-Adresslabels aus der
Admin-Konfiguration gelten nur für den konfigurierten Miniserver, erscheinen als
`admin_configured`-Metadaten, erfordern ein explizites zwei- oder dreistufiges
Adressformat und ändern keine Projektfakten. Namen und
Adressformen belegen weder Etagen, Funktionen, DPTs, ETS-Bedeutung noch Busaktivität.
`loxone_analyze_observability` bewertet getrennt einen begrenzten, ausdrücklich angefragten
Zeitraum für ein Projektziel. Es verbindet nur exakte UUID-gemappte strukturelle Erreichbarkeit,
Verfügbarkeit aktueller States, beworbene native Statistikserien und die Abdeckung der lokalen
Ereignishistorie. Erreichbarkeit beweist keine historische Ursache; konfigurierte Statistikserien
sind zeitlich nicht geprüft, und fehlende oder partielle lokale Abdeckung beweist nicht, dass ein
State nicht eingetreten ist. Pro Control werden höchstens 20 Statistikserien zurückgegeben;
ausgelassene Metadaten markiert `native_statistics_truncated`. State-Namen sind auf 200 UTF-8-
Bytes begrenzt; ausgelassenen Text markiert `state_names_truncated`. Control-Namen und -Typen
haben dieselbe Begrenzung; ausgelassenen Text markiert `control_metadata_truncated`.
Die mitgelieferte Anleitung `using-loxberry-mcp` verbindet diese vorhandenen Tools
zu einem Diagnoseablauf: Ziel bestimmen, aktuelle Beobachtungen samt Zeitstempel
prüfen, historische Abdeckung für den angefragten Zeitraum belegen und strukturelle
Pfade von Ereignisbelegen und möglichen Ursachen trennen. Ein nach der
Wiederverbindung beobachteter Wert verrät nicht, wann er während der Unterbrechung
gewechselt hat.
Für jeden State ohne vollständige lokale Abdeckung empfiehlt `recommendations`
anhand beobachtbarer Werte und Control-Metadaten native Statistik, lokale
Aufzeichnung bei Änderung oder `undetermined`.
Für dokumentierte Schaltzustände von `InfoOnlyDigital`, `Switch`, `Pushbutton`,
`PresenceDetector` und weiteren unterstützten Control-Typen kann bei beobachtetem
Wert 0/1 eine Aufzeichnung bei Änderung auch ohne `is_analog` empfohlen werden.
Der dokumentierte `value`-State von `InfoOnlyAnalog`, `UpDownAnalog`,
`LeftRightAnalog` und `Slider` wird auch ohne `details.analog` als analog
behandelt; ein kleiner Wertebereich macht ihn nicht zu einem digitalen State.
Widerspricht ein ausdrücklich gesetztes `details.analog=false`, bleibt die
Empfehlung unbestimmt.
Beim `Daytimer` gilt `is_analog` nur für den State `value`, nicht für Modus oder
Zeitwerte. Für `Daytimer` wird keine lokale Aufzeichnung empfohlen, weil lokale
Event-History-Quellen diesen Control-Typ nicht unterstützen. Eine aktive native Serie hat nur dann Vorrang, wenn ihr Output dem
State zugeordnet werden kann. Fehlt bei einer Legacy-Serie die State-UUID,
bleibt die Empfehlung unbestimmt. Die zeitliche Abdeckung muss weiterhin geprüft
werden. Teilweise lokale Aufzeichnung ist eine Abdeckungslücke,
kein Anlass für eine zweite Quelle. Ohne Nachweis der Signaldynamik nennt die
Intervall-Empfehlung keine festen Minutenwerte. Das Tool ändert keine
Aufzeichnungseinstellungen.
`source_diagnostics` meldet begrenzte Quelllücken wie Parseranomalien, ungültige KNX-Felder und
nicht modellierte Attribute. Dies sind keine Konfigurationsurteile; unbekannte Quellwerte werden
nicht ausgegeben, sondern nur feste Codes, Feldnamen, Wertformen und Projektknotenreferenzen.
Kann die Projektquelle gar nicht verarbeitet werden, enthält das normale Fehlerergebnis einen
festen, wertfreien `diagnostic_code`, der ungültige, nicht unterstützte, begrenzte, abgelaufene
und sonst fehlgeschlagene Quellenverarbeitung unterscheidet.

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
