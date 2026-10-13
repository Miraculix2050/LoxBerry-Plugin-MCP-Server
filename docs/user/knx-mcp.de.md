# KNX-Informationen über MCP

Das aktuelle Tool-Schema prüfen und `loxone_get_skill_guide(section="core")`,
für KNX anschließend `section="knx"` abrufen. Entsprechende Ressourcen sind
`skill://using-loxberry-mcp/core.md` und `skill://using-loxberry-mcp/knx.md`.
Der Toolaufruf ohne Argumente und `skill://using-loxberry-mcp/SKILL.md` liefern
weiterhin die vollständige Anleitung. Kennt der Client das Abschnittsargument
noch nicht, die vollständige Anleitung verwenden und keine unbekannten Argumente
erraten. Bei fehlender Anleitung den betroffenen Ablauf stoppen. Andere Abläufe
und Schreibaktionen benötigen weiterhin die vollständige Anleitung.

Die Projektsuche berücksichtigt auch importierte ETS- und manuelle KNX-Namen/
Beschreibungen einschließlich von Overrides verdeckter Werte. Sie liefert
autorisierte Projektobjekte, nicht jede eigenständige lokale Adresse oder jedes
Präfixlabel. Loxone-Namen bleiben primär. Eine bekannte Adresse gezielt suchen,
die gefundenen Objekte beschreiben und nur für nötigen Strukturkontext verfolgen.

Für den eigenständigen lokalen Bestand das entdeckte `loxberry_get_knx_catalog`
verwenden: `kind="addresses"` liest ETS-/manuelle Datensätze;
`kind="prefix_labels"` aktive darstellungsgebundene Labels auch ohne Adressen.
Erforderlich sind separate OAuth-Zustimmung zu `loxberry:knx:read`, Aktivierung
auf der KNX-Admin-Seite und ausdrückliche Freigabe für den konkreten Client,
die Identität, den Miniserver und das lokale Ziel. Standardmäßig ausgeschaltet.
Loxone-Anmeldung, Diagnose- und Bedienfreigaben gewähren diesen Zugriff nicht.
Administratoren können Kandidaten aktualisieren und Freigaben entfernen.
Explorer-Freigaben nutzen die konfigurierte Inaktivitätsfrist. Ein Zielwechsel
übernimmt keine Freigabe eines anderen Ziels. Deaktivierung erhält Freigaben,
blockiert aber Abfragen.

Die KNX-Admin-Badges für Lese- und Entwurfszugriff zeigen die gespeicherte
Aktivierung, keine ungespeicherten Checkbox-Änderungen. Sichtbare Tabs prüfen
diese Freigaben alle zehn Sekunden und bei Rückkehr zum Tab. Externe Änderungen
aktualisieren das Badge; offene Eingaben und ihre ursprüngliche Konfliktrevision
bleiben erhalten. Ein nicht abrufbarer Status wird ausdrücklich angezeigt.
Das Adresslabel-Badge zählt gespeicherte eindeutige Adressformat-/Präfixpaare
einschließlich importierter Labels; manuelle/importierte Paare zählen einmal.

Der Projektabgleich teilt die OAuth-Browsersitzung mit dem MCP Tool Explorer.
Die Anmeldung bietet dieselben optionalen Scopes: erforderlicher Loxone-Lesezugriff
ist ausgewählt, weitere Rechte erfordern eine ausdrückliche Auswahl. Trennen
meldet alle verbundenen Explorer-/KNX-Tabs ab. Logout-Fehler bleiben sichtbar;
Refresh stellt eine erfolgreich getrennte Sitzung nicht wieder her.
Der lokale Dateivergleich benötigt keine OAuth-Anmeldung.

Geöffnete und geschlossene Abschnittsboxen einschließlich ETS-Import bleiben
beim Neuladen in diesem Browser erhalten, sofern der Browserspeicher verfügbar ist.
Formulare und Schaltflächen passen sich auch schmalen mobilen Ansichten an;
breite Tabellen bleiben innerhalb ihres Rahmens horizontal scrollbar.
Leere Tabellen behalten Spaltenköpfe, eine dezente Leerfläche und einen passenden
Hinweis außerhalb der Tabelle. Verwerfen benötigt ausgewählte Dateien, Entwürfe
oder Ergebnisse. Der XML-Korrekturexport benötigt einen aktuellen Projektabgleich
mit geeigneten Einträgen, eine ausdrückliche Auswahl und eine erfolgreiche
Vorschau. Die Experimentell-Checkbox bestätigt einen einzelnen Download;
sie ist keine gespeicherte Aktivierung.

Während einer Statusabfrage angeforderte Freigabeaktionen werden nacheinander ausgeführt; weitere Eingaben sind ab der ersten vorgemerkten Aktion gesperrt. Eine bereits erzeugte XML-Vorschau kann auch nach Abmeldung oder ungültig gewordenem Projektabgleich über **Abbrechen** verworfen werden. Während laufender Anfragen bleibt die Aktion gesperrt. Auch nach einer fehlgeschlagenen Lade- oder Vorschauanfrage werden möglicherweise gespeicherte Vergleichs- und XML-Entwürfe beim Verwerfen serverseitig bereinigt. Ein fehlgeschlagenes Verwerfen erhält den Zustand für einen erneuten Versuch.

Mit `view="summary"` beginnen, dann literale `query`, `source`,
`deviations_only` oder exakte `address` eingrenzen und Einträge abrufen
(Standard 50, Maximum 100). Adressen erlauben kein `:0`/`:1`. Summary lädt keine
Adresszeilen und hat keinen Cursor. Einträge behalten ausgesparte unbekannte
Import-/manuelle Felder, lokale Auflösung, unbestätigte DPT-Angaben und deduplizierten
Präfixkontext. Unbekannte Felder, bewusst leere Werte und `false` bleiben verschieden.
Präfixlabels belegen keine Signalbeziehung; `import_format` keine XML-Exportfähigkeit.
Kein Projektdownload und keine Loxone-Namen: Für aktuellen Projektabgleich die
autorisierten Projekttools nutzen.

`total_matching` und `count_scope` beziehen sich auf ausgewählte lokale Datensätze
oder aktive Präfixe. Auswahl und Seitengröße bei Folgeseiten wiederholen. Cursor
binden Aufrufer, Ziel und SQLite-/manuelle Labelrevision. Jeder neu ausgegebene
Cursor gilt fünf Minuten; erfolgreiche, frisch autorisierte Folgeseiten erneuern
den nächsten Cursor. Sie enden bei Neustart. Änderungen verlangen eine neue
Abfrage. Ganze Zeilen passen in 64 KiB; `page_truncated` kennzeichnet eine verkürzte
Seite. Strukturierte Ausgabe einmal verarbeiten, nicht zusätzlich den Textfallback.
Abfragen teilen die globale Parallelitätsgrenze und haben eine begrenzte Quote von
30 pro Minute und Familie. Speicherfehler liefern keinen erfolgreich leeren Bestand;
vor Rückgabe wird die Berechtigung erneut geprüft.

Für den Bestandsabgleich ausdrücklich `ets_project_comparison` mit KNX-Scope
auswählen. Die Standardanalysen bleiben unverändert. Ziel, Revision, Aktualität,
Abdeckung, Diagnoseauslassungen und erforderliche Seiten prüfen. Stichprobe und
vollständige angefragte Prüfung unterscheiden. `deviations` vergleicht manuelle
mit importierten Werten; `names_differ` vergleicht Loxone- mit ETS-Namen. Unbekannt
bedeutet nicht übereinstimmend; mehrere Namen erfordern eine Entscheidung.

DPT-Angaben behalten Herkunft und fehlenden/leeren/angegebenen Zustand. Eine
Syntaxprüfung beweist weder Registerzugehörigkeit noch Kompatibilität oder eine
`EIBType`-Zuordnung. Importzeit ist keine Exportzeit; die Admin-Zielzuordnung
beweist nicht das richtige ETS-Projekt. Namen, Adressen und Strukturpfade beweisen
weder Busaktivität noch physische Rollen oder historische Ursachen. Dateivergleich
und experimenteller XML-Download bleiben auf der KNX-Seite; dieser Leseablauf
kann kein Projekt korrigieren oder exportieren.

Die Abschnitte werden aus derselben gebündelten kanonischen Anleitung abgeleitet
und im laufenden Prozess zwischengespeichert. Ihr Abruf lädt kein Projekt/keinen
Katalog und erteilt keine Berechtigung. Tokenmessungen nennen Tokenizer/Modell/
Client und unterscheiden geladene Schemas, Anleitung und tatsächliche Ergebnisse.
Zeichenanzahlen sind keine Tokenzahlen. Bei Discovery-Abweichungen siehe
[Fehlerbehebung](troubleshooting.de.md).

## Optionale Aufgaben-Prompts

Clients mit MCP-Prompt-Unterstützung können `knx_ets_inventory_review` oder
`knx_address_explanation` über `prompts/list` auswählen und das Rezept über
`prompts/get` abrufen. Der Abruf liest kein Projekt und keinen Katalog und erteilt
keine Berechtigung. Die KI nutzt dieselben entdeckten read-only Tools mit frischer
Autorisierung. Prompts sind vom Nutzer gewählte Aufgabenstarts, keine
Hintergrundprüfungen oder automatische Aufgabenableitung. Ohne Prompt-Unterstützung
kann dieselbe Frage im normalen Chat gestellt werden.

Bestandsparameter: `focus` ist `all` (Standard), `names`, `coverage` oder `dpt`;
`detail` ist `summary` (Standard) oder `findings`; `language` ist `en` (Standard)
oder `de`. Beispielsweise startet `prompts/get` mit
`name="knx_ets_inventory_review"` und
`arguments={"focus":"names","detail":"findings","language":"de"}` eine
Benennungsprüfung. Die Antwort unterscheidet Zusammenfassung, Stichprobe und
vollständig geprüften angeforderten Umfang. Ein fehlender oder teilweiser Import
ist eine Einschränkung, kein Nachweis ungenutzter Adressen.

Die Adresserklärung benötigt eine gültige zwei-/dreistufige `address` und erhält
eine ausdrücklich angegebene Variante `:0`/`:1`; `language` ist wie oben optional.
Beispielsweise erhält `name="knx_address_explanation"`,
`arguments={"address":"1/2/3:1","language":"de"}` die Projektvariante und fragt
freigegebene lokale Metadaten über die Basisadresse `1/2/3` ab. Mehrere Objekte und
Namen bleiben ausdrücklich sichtbar. Beschreibung, DPT-Angaben und Präfixkontext
sind Zusatzquellen, kein Nachweis physischer Beziehungen oder Busaktivität.

Weichen Liste oder Argumente von dieser Referenz ab, über den unterstützten
Discovery-Ablauf des Clients neu verbinden. Fehlende Prompt-/Tool-Aufrufe nicht
erfinden. Fehlende Anleitung/Tools oder verweigerte Rechte beenden die betroffenen
Prüfungen; diese Prompts importieren keine Dateien, ändern keine Metadaten und
exportieren keine ETS-Korrekturen.
Für geschützte lokale `prompts/list`-Erfassungen unterstützt der Offline-
Discovery-Vergleich zusätzlich `--kind prompts`. Er vergleicht die angebotenen
Metadaten, keinen Rezepttext und keine erfolgreiche Aufgabenausführung im Client.

## Kompakter ETS-Abgleich

Ausdrücklich `analyses=["ets_project_comparison"]`, `scope="knx"` und
`view="summary"` für Zählwerte ohne einzelne Adressdetailabfragen wählen.
`view="findings"` liefert paginierte Quellenbefunde; `view="detail"` mit einer
genauen zwei-/dreistufigen `address` (ohne Variantensuffix) erklärt eine Adresse.
Die Projektobjekte behalten ihre ursprünglichen `:0`/`:1`-Varianten und Loxone-Namen.
Der weggelassene/standardmäßige `view="full"` und andere Analysen bleiben unverändert.

Kompakte Ansichten unterstützen `relation`, `names_differ`, `ambiguous_names` und
`address`. Ein falscher Namensabweichungsfilter berücksichtigt nur verglichene,
vollständige beobachtete Namen; unbekannte oder unvollständige Namen sind keine
Übereinstimmung. Filter stehen in der Vollansicht nicht zur Verfügung und lassen
sich nicht mit anderen Analysen mischen. Zusammenfassungen haben keinen Folgecursor.
Ansicht, alle Filter und `source_details` auf Folgeseiten unverändert lassen;
geänderte Ziel-, Projekt- oder KNX-Stände erfordern eine neue Abfrage.

`summaries.ets_project_comparison.counts` zählt die gesamte begrenzte Beobachtung.
`selection.counts` zählt erhaltene gefilterte Beobachtungen; `selection.complete`
ist falsch, wenn die Beobachtungsbegrenzung weitere Treffer verbergen kann.
Quellenvollständigkeit, ausgelassene Gruppen und Diagnosezählwerte bleiben auf
jeder kompakten Seite separat sichtbar. `source_details=true` nur bei Bedarf für
vollständige Diagnose-/Quellengruppen verwenden. Das Protokoll liefert weiterhin
strukturierte und Text-Fallback-Ergebnisse; Clients sollten eine Darstellung
nutzen und nicht beide in den KI-Kontext aufnehmen.

## Gemeinsame Korrekturvorschläge

Nach Abstimmung konkreter Änderungen kann eine KI über
`loxberry_prepare_knx_corrections` einen begrenzten Entwurf vorbereiten. Dafür
sind eine eigene OAuth-Zustimmung zu `loxberry:knx:drafts`, ausdrückliche
Admin-Aktivierung und eine genaue zielgebundene Freigabe auf der KNX-Seite nötig,
zusätzlich zur lokalen Katalog-Lesefreigabe. Beide Fähigkeiten sind unabhängig
standardmäßig deaktiviert. Ein Loxone-Login gewährt keine davon. Deaktivierung
erhält Freigaben und Vorschläge, blockiert aber den MCP-Zugriff.

Lokale Metadaten oder experimentelle ETS-Exportziele ausdrücklich auswählen.
Importierte Quellenwerte bleiben unverändert. Ein Vorschlag verändert keine
Overrides, Exportziele, ETS oder Loxone-Projekte. Die authentifizierte KNX-Seite
zeigt denselben gespeicherten Vorschlag mit getrennten Quellen; sie übernimmt
keine Loxone-Projektzugangsdaten des OAuth-Clients. Der aktuelle Projektstand
ist dort ausdrücklich ungeprüft. Die Admin-Seite kann ausgewählte Zielwerte bearbeiten
und einzelne Änderungen annehmen, ablehnen oder auf vorgeschlagen zurücksetzen.
Bearbeiten setzt die betroffene Entscheidung zurück; Identität und unveränderte Quellen
bleiben erhalten. Der ursprüngliche Projektstand bleibt gebunden; Zustimmung bestätigt
weder Projektzugriff noch eine Übernahme. MCP zeichnet konkret abgestimmte
Entscheidungen mit `loxberry_prepare_knx_corrections(mode="review",
decisions=[{"change_id": "...", "decision": "accepted"}])` auf: `changes` weglassen,
aktuelle Ziel-/Katalog-/Präfix-/Entwurfsrevisionen und eine stabile Request-ID angeben.
Nicht ausgewählte Entscheidungen bleiben erhalten. Lokales Schreiben und bestätigte
Exportübergabe folgen getrennt.

Entwürfe gelten absolut 24 Stunden, enthalten höchstens 50 Änderungen und teilen
die globale Grenze von acht Entwürfen/32 MiB mit Importen, Vergleichen und
XML-Vorschauen. Bearbeitung verlängert die Laufzeit nicht. MCP sieht nur eigene
zielgebundene Entwürfe; Admin-Ansicht überträgt anderen Clients kein Eigentum.
Veraltete Entwürfe bleiben einsehbar; ein geänderter Quellenstand benötigt einen
neuen Vorschlag.

Zuerst kompakte Übersichten lesen, anschließend ausgewählte Seiten (Standard
zehn, höchstens zwanzig); Folgeseiten mit der zurückgegebenen Entwurfsrevision
abrufen. Werte über 128 Zeichen werden als gekürzt markiert; vollständige
Details wählen eine Zeile. Nach ungewissem Anlegen über die feste Anfrage-ID
nachsehen; nach ungewissem Bearbeiten über die bekannte Entwurfs-ID. Ein fehlendes
Ergebnis bei möglicherweise noch laufendem Worker beweist keinen Fehlschlag.
Nie automatisch wiederholen. Identische Vorbereitung ist idempotent; abweichende
Wiederverwendung einer Anfrage-ID wird abgewiesen. Lesen und Vorbereitung teilen
begrenzte Worker-Plätze und lokale Leseraten. Normale Entwurfsabfragen verarbeiten
keine Dateien und laden keine vollständigen Kataloge.

Jeder Entwurf hält höchstens 128 gehashte Bearbeitungs-/Entscheidungsbelege ohne Verdrängung; weitere Bearbeitung wird an dieser Grenze abgewiesen. So bleiben Einzelprüfungen und Bearbeitung im 50er-Änderungspaket innerhalb der globalen Bytegrenze möglich.
