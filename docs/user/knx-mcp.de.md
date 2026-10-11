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
