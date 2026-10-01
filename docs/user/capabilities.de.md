# Funktionsumfang und Grenzen

[English](capabilities.en.md)

## Unterstützter Umfang

`loxone_get_state_semantics` liest Semantikevidenz und gecachte Werte für ein
sichtbares Control mit `loxone:read` und frischer Sichtbarkeitsprüfung. Wählen Sie
1–100 eindeutige exakte `state_names` oder lassen Sie sie weg und paginieren Sie
alle normalisierten Zustände mit `offset` und `limit` (Standard/Maximum 100).
Folgen Sie `next_offset` mit derselben Auswahl. Unbekannte ausgewählte Zustände
führen gemeinsam zum Fehler; versteckte Controls sind ausgeschlossen.

Jeder Eintrag trennt den ursprünglichen `value`, optionalen `semantic_value`,
Beobachtungsqualität `quality` und `semantics`. `known` bedeutet, dass die
Interpretation durch die angegebene bestehende Decoderregel belegt ist;
`partial`, `unknown` und `invalid` erhalten Wissenslücken, fehlende Begleitwerte
und ungültige Quellkodierungen. Ein aktueller Wert kann eine unbekannte Bedeutung
haben; ein veralteter Wert kann weiterhin eine bekannte Interpretation besitzen.
Fehlende Dokument- oder Firmwareversionen bleiben null. Quellen je Feld benennen
Structure-Metadaten, begleitende Runtime-Zustände oder Decoderregeln;
Structure-Änderungszeiten sind keine Firmwareversion. Formate über 64 Zeichen
werden mit ursprünglicher/zurückgegebener Länge und expliziter Kürzungsangabe
weggelassen, ohne den Text zu verändern.

V1 umfasst bestehende Irrigation-/AlarmClock-Decoder, `value`-Anzeigeformate für
InfoOnlyAnalog/UpDownAnalog/Slider, UpDownAnalog-Bereiche und positionsgebundene
Status-/Input-Metadaten von StatusMonitor `inputStates`. Formate belegen keine
Einheit, Präzision oder Richtung; konfigurierte Bezeichnungen belegen keine
Schweregrade oder Haushaltsrollen. Kodierungs- und Positionslisten behalten
höchstens 100 Einträge, Quellen höchstens acht, jeweils mit Anzahl und
Vollständigkeit. Seitenvollständigkeit ist von Semantik- und Metadatenvollständigkeit
unabhängig. Es gibt keinen Projekt-Join, Download von Dokumentationsinhalten,
Hidden-Diagnose, Alarmquittierung oder installationsweite Semantikabdeckung.
Weitere Energie-, Zähler- oder Controllerbedeutungen können unbekannt bleiben.
Diese Abdeckung ist mit Fixtures geprüft und begründet keine neue Hardware- oder
Firmwarekompatibilität.


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

### Prüfung der Öffnungskontakt-Zuordnung

`loxone_analyze_opening_contacts` verbindet Monitorreferenzen mit exakten
Verbraucherpfaden in einem begrenzten Nur-Lese-Aufruf (`loxone:read`). Wählen Sie
`scope_type=monitor|room|contact|consumer` und eine exakte sichtbare `scope_uuid`.
Zusätzliche Kandidaten sind bis zu 100 eindeutige sichtbare `candidate_contact_uuids`;
ihre physische Kontaktrolle wird nicht bestätigt. `include_current_state=false`
ist der Standard. Die Trace-Grenzen sind standardmäßig Tiefe 6 und 100 Knoten/Kanten,
maximal 16 und 200. Ein Aufruf untersucht höchstens 100 Monitore, 100 Kontaktkandidaten,
100 Verbraucher und 200 Trace-Starts; die Antwort bleibt unter 65.536 Bytes.
Höchstens 200 Verbindungen und 200 Befunde werden materialisiert; weitere Einträge
werden getrennt gezählt und verhindern ein vollständiges Ergebnis.
Prüfen Sie getrennte Vollständigkeit für Monitore, Mapping, Graph und Zustände,
Warnungen und Auslassungszahlen. Zähler gelten für untersuchte erhaltene Positionen,
nicht für die gesamte Installation. Duplikate beruhen auf identischen Referenz-UUIDs.
Ohne Projektzugriff bleiben Monitorbefunde verfügbar. Angeforderte Zustände melden
Originalindizes, Vektorlänge und separate Zustandsfrische; `state_value` ist ein
uninterpretiertes numerisches Quelltoken. Die Zustandszeit ist eine Unix-Zeit und
unabhängig von der Analysezeit und dem verifizierten Projektmarker.

Jeder gerichtete Evidenz-Trace liefert maximal 20 `gaps`, insgesamt maximal 200
je Aufruf. Ein Gap nennt den erreichten opaken Projektknoten, Richtung, sicheren
technischen Blocktyp und Connector-Key, festen Grund, Connector-Regelversion und
vorhandene Regelreferenzen. Ungültige oder zu lange Tokens sind null; Namen und
rohe Attribute fehlen. `gaps_omitted` zählt ausgelassene Fälle je Trace;
`max_gap_evidence` erhält die unvollständige Graph-Evidenz.
`parent_boundary_incomplete` beschreibt die bestehende konservative Parent-Prüfung;
daraus folgen weder die Relevanz eines benachbarten Ports noch ein Konfigurationsfehler.
Die bestehende Warning `unmodeled_internal_flow` bleibt erhalten.

Die erste Verbraucherregel ist exakt `AutoJalousie.Window`; `Dwc` wird nicht als
Alias angenommen. `Or.I1/I2 -> Q` und die Projektion einer aufgelösten expliziten
`InputRef`-Referenz auf einen eindeutigen `AQ` sind markierte abgeleitete Regeln.
Die begrenzten Trace-Starts berücksichtigen alle exakt zugeordneten Vorkommen
eines logischen KNX-Kontakts über interne Modellquellen hinweg; eine dabei erreichte
Grenze verhindert eine vollständige Graphaussage.
Zwischenlogik, Sperrquellen und Anschlusskontext bleiben in den Belegen sichtbar.
Unbekannte Semantik, Mehrdeutigkeit und erreichte Grenzen verhindern negative
Verbindungsaussagen. Verdrahtete Ein- oder Ausgänge außerhalb der geprüften
Anschlussregeln kennzeichnen die Blockevidenz ebenfalls als unvollständig;
unverdrahtete Zusatzanschlüsse dagegen nicht.
Ein `cross_assignment_review_candidate` vergleicht einen
belegt speisenden Kontakt mit einem weiteren nicht speisenden Kandidaten desselben
Raums; er entscheidet keine physische Zuordnung. `physical_opening_coverage`
bleibt `not_assessable`. Monitorumfang untersucht dessen erhaltene Einträge;
Raumumfang wählt Monitore über Monitor-/Eintragsraum und Kandidaten über exakte
Eintrags-/Controlräume. Kontaktumfang findet direkte oder explizit verlinkte
Monitorzuordnungen; Verbraucherumfang verwendet dessen Raum als Monitorkontext.
Raum- und Verbraucherumfang begrenzen auch die Verbraucher, Monitor- und
Kontaktumfang vergleichen die sichtbaren unterstützten Verbraucher.

Der kanonische Skill trennt Monitorabdeckung, konfigurierte Verbraucherverdrahtung
und physische Öffnungsabdeckung. Suchen Sie exakte sichtbare `WindowMonitor`-Controls,
verfolgen Sie Discovery-Seiten und verwenden Sie `loxone_describe_control(view="full")`.
Trennen Sie direkte Eintragsreferenzen von `relationships.linked_controls` (auch
Links aus Aggregatobjekten), exakten Project-Intelligence-Pfaden und reinen Namens-/
Raumkandidaten. Eine direkte Eintragsreferenz ist normalisiert und kann aus einem
expliziten UUID-Feld oder einem Mapping-Schlüssel als Fallback stammen; die
Auflösung allein identifiziert die Quelle nicht. Beschreiben Sie jedes aufgelöste
referenzierte Control separat mit `loxone_describe_control(control_uuid=..., view="full")`,
bevor Sie dessen `relationships.linked_controls` prüfen; der Monitor enthält nur
kompakte Eintragsreferenzen. Ein expliziter Link belegt eine indirekte Verknüpfung, keine direkte
Monitorzuordnung. Verwenden Sie Diagnosen und Originalindizes; fehlerhafte, nicht
verfügbare, raumwidersprüchliche und ausgelassene Einträge begrenzen Aussagen.
`partially_resolved` kann ausschließlich einen aufgelösten Raum bedeuten.
Auflösungszähler gelten nur für erhaltene Positionen. Wenn aktuelle Zustände relevant
sind, lesen Sie `windowStates` und melden Sie Index-/Vektorabweichungen.

Prüfen Sie bei Fragen zur richtigen Zuordnung `loxone_get_project_status`, lösen Sie
Kontakte und Verbraucher exakt mit `loxone_describe_project_object` auf, verfolgen
Sie Kontakte mit `loxone_trace_project_logic` downstream und den exakten
Verbraucheranschluss upstream, zunächst `AutoJalousie.Window`. Ermitteln Sie den
Anschluss über zurückgegebene Kindknoten-IDs und deren Beschreibungen; vergleichen
Sie exakte Graphknoten-IDs und Kantenendpunkte. Erhalten Sie `InputRef`, `Or`,
Sperrschalter und Anschlussnamen. Hierarchie und gemeinsame Erreichbarkeit sind
kein Signalfluss; erfinden Sie keine internen Kanten durch nicht modellierte
Bausteine. Prüfen Sie mehrdeutige Mappings, `truncated_fields`, Trace-Begrenzungen,
ungelöste Beziehungen und Aktualität. Fehlende Pfade bei unvollständiger Evidenz
beweisen keine fehlende Verdrahtung. Dieser manuelle Ablauf ergänzt die Belege
des Analyzers und hilft beim Verfeinern unvollständiger Ergebnisse.

Generisches Beispiel: `Dachfensterkontakt -> InputRef -> Or mit Sperrschalter ->
als Fenster benannte Jalousie.Window`, während ein anderer Fensterkontakt desselben
Raums im Monitor enthalten ist. Zeigen vollständige relevante Traces, dass dieser
den Anschluss nicht speist, melden Sie einen `cross_assignment_review_candidate`
mit exakten Belegen. Falsche Kontaktverdrahtung und irreführende Verbraucherbenennung
sind beide möglich; weder Namen noch Monitorzuordnung rechtfertigen eine physische
Korrektur. Sind nur einzelne Segmente verfügbar, melden Sie die Lücke. Verwenden Sie
klare Formulierungen wie „nicht aufgelöst“ und „indirekt verknüpft“. Ohne autoritatives
Inventar und exakte Identitätsverknüpfungen ist die physische Vollständigkeit „nicht
beurteilbar“ (`not_assessable`). Leiten Sie weder eine Öffnung pro Jalousie noch
Kontaktrollen aus Namen, Kategorien oder Raumzahlen ab.

### Laufzeit- und Projektfunktionen

Der Server liest sichtbare Räume, Kategorien, Controls und Zustände. Optional sind begrenzte Historie, Statistiken, maskierte LoxBerry-Diagnosen sowie dokumentierte, typabhängige Aktionen für sichtbare Gen.-1-Controls verfügbar.

Für bekannte sichtbare UUIDs bevorzugt `loxone_read_controls` für Identität und aktuelle Werte in einem Call nutzen, wie unten beschrieben. Für reine Referenzauswahl, explizite Diagnose versteckter Controls oder Server ohne dieses Tool nach der Suche `loxone_describe_control(view="state_refs")` verwenden. Die Ansicht liefert nur Control-Identität, Sichtbarkeit und die vollständige normalisierte `states`-Liste mit Namen und UUIDs, ohne Raum-/Kategorie-Kontext, Fähigkeiten, Statistiken, Historie, Darstellung oder Beziehungen. Sie lädt die nutzergefilterte Struktur neu und liefert bei fehlgeschlagener Aktualisierung einen Fehler statt zwischengespeicherter Referenzen. `stale` kennzeichnet einen getrennten Ereignisstream; `observed_at` ist der Beschreibungszeitpunkt, kein Messzeitpunkt eines State-Werts. Nur benötigte UUIDs auswählen, Duplikate entfernen und `loxone_get_states` in Gruppen von höchstens 100 aufrufen; bei leerer Auswahl keinen Werte-Read ausführen. Für versteckte Controls bleibt `include_hidden=true` sowohl bei der Diagnose als auch beim Werte-Read erforderlich. `history_targets` dient der Historien-/Statistikauswahl, `operation_targets` der Bedienvorbereitung und `full` der weiterführenden Diagnose.

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
`loxone_analyze_project` Version 8 fasst begrenzte, projektlokale KNX-Evidenz zusammen:
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

## Kompakte Reads bekannter Controls

Nutze `loxone_read_controls`, wenn sichtbare Control-UUIDs bereits bekannt sind;
ermittle sie sonst zuerst mit `loxone_find_controls`. Beispiel:

```json
{"targets":[{"control_uuid":"<visible-control-uuid>","state_names":["value"]}]}
```

Die Antwort verbindet `identity` (Name, Typ, Sichtbarkeit, Raum und Kategorie) mit
benannten `values` (UUID, Rohwert, Freshness und Beobachtungszeit) in einem Call.
Ohne `state_names` werden alle States des ausgewählten Controls gelesen. Namen
müssen exakt passen. Erlaubt sind 1–25 eindeutige Controls und insgesamt höchstens
100 benannte States; Identifier/Namen sind auf 128 Zeichen begrenzt. Aliase zählen
einzeln. Versteckte/unbekannte Controls oder unbekannte State-Namen weisen den
gesamten Batch zurück.

`include_semantics=true` ergänzt optional dasselbe Evidenz- und Qualitätsmodell
wie `loxone_get_state_semantics`. Beziehungen, Notizen, Historie, Statistiken,
Aktionen und Projektdaten werden nicht expandiert. Bestehende Detailtools bleiben
verfügbar. `complete` und angeforderte/zurückgegebene Anzahlen beschreiben die
Auslieferung der Auswahl einschließlich unverfügbarer oder veralteter Werte;
sie beweisen weder Aktualität noch vollständige Semantikkenntnis. Semantikmetadaten
besitzen eigene Completeness-Felder. Die strukturierte Antwort ist auf 64 KiB
begrenzt; `response_too_large` liefert keine Teilwerte. Teile die Targets auf oder
wähle weniger States.

Gegenüber vollständigen Beschreibungen sinkt die Antwortgröße bei Controls mit
vielen Beziehungen deutlich. Für ein einzelnes kleines Control kann
`describe_control(view="state_refs")` plus `get_states` weniger Bytes benötigen,
braucht aber weiterhin zwei Calls.

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


### Aktive sichtbare Alarme

`loxone_get_active_alerts` liefert einen begrenzten read-only Überblick aus einer
frisch autorisierten sichtbaren Struktur und erfassten Cache-Beobachtungen. V1
wertet ausschließlich `AalEmergency.status` aus: 0 Normalbetrieb, 1 ausgelöster
Alarm, 2 aktiver Reset, 3 vorübergehend deaktiviert (Structure File 17.1, Seite 26).
Ganzzahlige numerische Werte werden akzeptiert; Booleans, Strings und unbekannte
Codes sind ungültig. Nur aktuelle verfügbare Werte belegen Aktivität/Inaktivität.
Daraus folgt keine Firmware-Kompatibilitätszusage.

Prüfen Sie `coverage.complete` unabhängig von `truncated`/`complete`. Leere
partielle Ergebnisse belegen keine Alarmfreiheit. V1 klassifiziert StatusMonitor-
und WindowMonitor-Zustände nicht als Alarme. Verwenden Sie Quell-Control und
State-Referenzen für gezielte Lesungen; Namen/Farben belegen weder Gefahr noch
Ursache oder Schweregrad. Der Snapshot ist kein Alarmierungsdienst und quittiert
keine Alarme. `limit` erlaubt 1–50 Befunde (Standard 50), ohne Cursor/Familienfilter.
Die Abdeckung gilt nur für bekannte Kandidatenfamilien, nie für die physische
Installation; `total_active` bleibt bei partieller Auswertung null.
