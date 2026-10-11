# Fehlerbehebung

## OAuth-Sitzungen und Freigaben nachvollziehen

Wenn eine Sitzung verschwindet oder eine Freigabe inaktiv bleibt, nutze den
lokalen Diagnose-Download der Admin-UI. `auth_lifecycle` enthält die Anzahl
aufbewahrter widerrufener Sitzungsfamilien je Ursache und höchstens 20 aktuelle
Widerrufe mit Zeitpunkt, Quelle und maskierten Referenzen. Diese Diagnose gehört
zur lokalen LoxBerry-Administration; Loxone-Rechte gewähren keinen Zugriff.

Der erste Widerruf speichert `revoked_at`, `revocation_reason` und
`revocation_source` an der vorhandenen Familie. Wiederholte Widerrufe erhalten
diese erste Ursache. Historische Datensätze ohne Ursache bleiben `unknown`;
eine spätere Admin-Aktion wird ihnen nicht als ursprünglicher Auslöser
zugeordnet. Die Metadaten folgen der vorhandenen Aufbewahrung der Familie und
verschwinden bei deren Bereinigung.

| Ursache | Erfasster auslösender Pfad |
| --- | --- |
| `oauth_revocation` / `explorer_logout` | Expliziter OAuth-Widerruf / Explorer-Abmeldung |
| `refresh_reuse` / `refresh_invalid_state` | Erneute Nutzung eines verbrauchten Refresh-Tokens / ungültiger Refresh-Zustand mit Widerruf |
| `admin_session` / `admin_all_sessions` | Lokaler Admin widerruft eine / alle Sitzungen |
| `approval_read_removed` / `approval_operate_removed` | Lokaler Admin entfernt die passende LoxBerry-Freigabe |
| `scope_disabled` | Konfiguration deaktiviert eine berechtigte Fähigkeit |
| `unknown` | Ursprüngliche Ursache wurde nicht erfasst oder wird nicht unterstützt |

Plugin-Logs verwenden `component=auth_lifecycle` mit festen Feldern für Ereignis,
Ursache, Quelle, Fähigkeit, Ergebnis und Korrelation. `family_ref` ist ein durch
eigenen Namensraum getrennt berechneter Hash der zufällig ausgestellten opaken
Familien-ID und verbindet OAuth-, Laufzeit- und Remote-Bereinigungsereignisse.
`client_ref` wird mit einem installationsgebundenen Schlüssel berechnet;
`binding_ref` ist ein gesonderter Hash der vorhandenen opaken Bindung.
Referenzen vergeben keine Rechte und machen unterschiedlich registrierte Clients
nicht austauschbar. Quellen benennen den auslösenden Pfad, keinen nachgewiesenen
menschlichen Bediener.

Bei normalem INFO-Logging werden seltene Ereignisse erfasst: Registrierung,
Familienanlage und Widerruf, Ablauf/Entfernung, Freigabeänderungen,
Verbindungsaufbau/-ende, Dienststart/-stopp und Remote-Bereinigungsergebnisse.
DEBUG ergänzt erfolgreiche Token-Ausstellung/-Rotation, exakte Freigabezuordnung
je Fähigkeit, abgelehnte Refreshes, Schließanforderungen und
Bereinigungsversuche/-unterdrückung. Normale Store-Lesezugriffe erzeugen keine
Lebenszyklus-Einträge. Vorhandene Log-Level und Rotation gelten weiter;
ein Prozessabsturz kann keinen geordneten Stopp protokollieren, und fehlende
Logs beweisen nicht, dass ein Ereignis ausgeblieben ist.

Admin-Hilfsprozess-Ereignisse gelangen durch einen strikten Filter fester Felder
in das native LoxBerry-Admin-Log; dessen Plugin-Log-Level gilt weiter. Pro
Hilfsprozess werden höchstens sechs Detaileinträge plus Zählzusammenfassung
weitergegeben, damit die Pipe-Ausgabe begrenzt bleibt.

Store-Zustandsänderungen werden nach erfolgreicher dauerhafter Speicherung
protokolliert. Eine Sammeländerung erzeugt höchstens 32 Detaileinträge plus
Zählzusammenfassung; gespeicherte Erstursachen bleiben unabhängig von der
Logrotation verfügbar. Remote-Warteschlange, bestätigtes Beenden, bereits
ungültiger Token, nomineller Ablauf und unbestätigtes Ergebnis bleiben getrennt.
Ein Verbindungsende ist kein Widerruf der OAuth-Familie. Diese Diagnose ergänzt
keine Tokens, rohen Client-/Familien-IDs, Namen, Endpunkte, Zugangsdaten oder
beliebigen Exception-Texte.

Ein Start ohne erste Zustandsnachricht endet mit `initial_state_timeout`;
die anschließende Abbruchanforderung macht daraus kein normales lokales
Verbindungsende. OAuth-Ablauf und Refresh-Widerrufsursachen werden an das
zugehörige Laufzeitende weitergegeben.

Der Diagnose-Download im Browser benötigt JavaScript. Er nutzt den Same-Origin-
AJAX-Pfad und speichert das maskierte JSON lokal; die strikte Origin-Prüfung
und die no-referrer-Richtlinie bleiben aktiv.

## Wiederholte Miniserver-Authentifizierungsablehnung

Drei eindeutige Ablehnungen innerhalb von fünf Minuten pausieren neue Anmeldungen
für 60 Sekunden. Öffentliche OAuth-Passwortfehler haben ein eigenes Budget und
pausieren nur öffentliche Anmeldungen. Dienst- und Token-Ablehnungen teilen ein
zweites Budget; dessen Pause gilt auch für die Token-Phase öffentlicher Anmeldungen.
Eine öffentliche Passwortpause blockiert weder Dienstverbindungen noch Token-Widerrufe.
Tatsächliche IP-Sperren gelten weiterhin global. Erneut abgelehnte Prüfversuche verdoppeln
die Pause bis auf 60 Minuten. Netzwerkfehler, Timeouts, Anmeldekonkurrenz und
verweigerte Projektberechtigungen verbrauchen dieses Budget nicht. Bestehende
authentifizierte Verbindungen bleiben offen. Diese Plugin-Policy garantiert keine
bestimmte Miniserver-IP-Sperrschwelle.

Der Abschnitt Sitzungen zeigt Schutzgrund und verbleibende Wartezeit. Ein lokaler
Administrator kann ausdrücklich eine Anmeldung mit den in LoxBerry konfigurierten
Zugangsdaten prüfen, frühestens 60 Sekunden nach dem vorherigen Versuch. Den
Warnhinweis beachten: Eine weitere Ablehnung kann die Pause verlängern oder eine
IP-Sperre auslösen. Automatische Wiederholungen und MCP-Clients dürfen die Pause
nicht umgehen; eine bestätigte Miniserver-IP-Sperre hat Vorrang.

Bei nicht verfügbarer Schutzpersistenz stoppen neue Anmeldungen. Den Zugriff auf
die private Plugin-Zustandsdatei wiederherstellen und nach Behebung der Ursache
den Dienst neu starten; einen aktiven Schutzstatus nicht nur für weitere Versuche
löschen. Ein abgebrochener Prozess hinterlässt eine konservative Reservierung von bis zu einer Stunde.
Eine bestehende Source-IP-Wiederanlaufpolicy kann eine längere Reservierung erfordern und hat Vorrang.
Zugangsdaten und Tokenwerte erscheinen nicht im Status. Eine umfassende
Token-Bereinigung wird nicht angeboten; ihre Folgen werden getrennt untersucht.

Ein noch ungeklärtes Authentifizierungsergebnis reserviert zusätzlich den vorhandenen globalen IP-Wiederanlaufabstand. Bei einem Absturz oder nicht speicherbaren Ergebnis kann dieser Schutz alle neuen Anmeldungen vorübergehend zurückstellen; normale gespeicherte Passwortablehnungen lösen ihn nicht aus. Bereits ausgestellte Token werden bei unterdrücktem Anmeldeabschluss verschlüsselt für den koordinierten Widerruf gespeichert. Scheitert auch dies, bleibt der Token in der Transaktion erhalten und eine neue Ausstellung ist bis zur Bereinigung gesperrt.

[English](troubleshooting.en.md)

| Symptom | Sichere Prüfung |
| --- | --- |
| Client erreicht den Server nicht | Prüfe Dienststatus, lokale HTTPS-Adresse und Zertifikatsdiagnose. |
| OAuth-Anmeldung startet nicht | Öffne die HTTPS-Adresse; HTTP wird nicht für die Anmeldung verwendet. |
| Tool antwortet mit `permission_denied` | Prüfe Loxone-Rechte, angeforderten Scope und gegebenenfalls lokale Adminfreigabe. |
| Tool antwortet mit `emergency_stop_active` | Prüfe das ausgewählte Notaus-Signal: `1` gibt Tool-Aufrufe frei, `0` sperrt sie. Bei `unknown` kann der Dienst keinen sicheren Wert bestätigen. Stelle das Signal außerhalb von MCP auf `1` oder entferne die Auswahl; nicht automatisch wiederholen. Die Antwort enthält den aktuellen Status sowie UTC-Zeitpunkte für Beobachtung und Beginn der Sperre. |
| Keine aktuellen Werte | Prüfe Miniserver-Verbindung und ob der Loxone-Benutzer die Controls sehen darf. |
| Update fehlgeschlagen | Warte auf den terminalen Status im Plugin Manager und halte das vorherige Paket bereit. |

Exportiere oder teile keine Zugangsdaten, Tokens, privaten Adressen oder vollständigen Zustandsdaten. Nutze nur maskierte Plugin-Diagnosen.

## Vorübergehend nicht verfügbare Leseaufrufe

Bewahre bei `temporarily_unavailable` die Felder `error`, `message`,
`diagnostic_code` und `trace_id` zusammen mit Tool und autorisiertem Zielkontext
auf. Erhalte auch `availability_phase` und `retry_after_seconds`.
`local_rate_limit` bezeichnet das lokale Aufrufbudget des Aufrufers; nur diese
Ursache liefert eine aufgerundete Wartezeit von 1–60 Sekunden. Warte mindestens
so lange und wiederhole einen Leseaufruf höchstens einmal. Kapazität wird nicht
reserviert. Nutze erfolgreiche Beschreibungen erneut und reduziere parallele
Aufrufe. Wiederhole ungewisse Schreibvorgänge niemals automatisch.

Der Runtime-Sitzungsaufbau wartet innerhalb des konfigurierten Verbindungszeitlimits
auf lokale Authentifizierungskoordination; Warten und Login teilen dieses Budget.
Cancellation beendet das Warten. Frische MCP-Sichtbarkeit erfordert weiterhin die
authentifizierte Struktur des Aufrufers; die Admin-Identität oder eine alte gecachte
Struktur kann sie nicht ersetzen. `structure_refresh_auth_cooldown` bezeichnet die
vorbeugende Schutzpause oder
unsichere Schutzpersistenz vor einem Netzwerkzugriff. `structure_refresh_auth_busy`
bedeutet, dass die
lokale Koordination ihr Wartebudget vor dem Login ausgeschöpft hat.
`structure_refresh_source_ip_suppressed` bezeichnet Source-IP-Blocking oder den
persistent gespeicherten Breaker. Diese Kategorien bezeichnen nicht das Aufrufbudget des Clients.
Transportfehler und entfernte Sitzungslimits bleiben getrennt; ein Fehler der
Verbindungskategorie allein belegt kein Miniserver-Sitzungslimit. Diese Diagnosen
erlauben keine Zuordnung älterer Fehler ohne erhaltene zugrunde liegende Exception (#332).

`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token` und `structure_refresh_timeout` unterscheiden bestätigte
Refresh-Exception-Kategorien. Token-Fehler umfassen fehlende Tokens und Fehler des
Token-Speichers. Die Phase bezeichnet Token-Abfrage, Sitzungsaufbau,
Versionsprüfung, Strukturladen oder Sitzungsschließen. `structure_refresh_unknown`
und `availability_unknown` lassen die Ursache ausdrücklich unbekannt. Dafür gibt
es keine Wiederholungsfrist; erfinde keine und leite sie nicht aus einem gesunden
Dienst ab.

Nutze für Support autorisierte, maskierte Dienstdiagnosen mit der Trace-ID der
Antwort. Warnungen werden je Kategorie und Phase 60 Sekunden unterdrückt;
Ereigniszahlen zählen keine fehlgeschlagenen Aufrufe, fehlende Ereignisse benennen
keine Ursache.

### Admin-Discovery-Verbindung

Event History und die Emergency-Stop-Auswahl verwenden eine eigene Verbindung mit
der in LoxBerry konfigurierten Miniserver-Identität. Die Notaus-Liste prüft zuerst
im Hintergrund den Projekt-Änderungsmarker `LoxAPPversion3`, wie der Projektcache.
Erst danach werden passende gespeicherte Namen angezeigt. Bei geändertem oder fehlendem Marker,
fehlendem oder veraltetem Cache wird die vollständige Struktur geladen. Eine
offene sichtbare Seite prüft nach dem konfigurierten Struktur-Aktualisierungsintervall
(mindestens 60 Sekunden) erneut. „Notaus-Signale laden/aktualisieren“ erzwingt einen
vollständigen Abruf. Ein Fehler stoppt automatische Versuche; Auswahl und letzte
bereits bestätigte Liste bleiben erhalten und werden gegebenenfalls als veraltet markiert.
Der Marker bestätigt keine Zugriffsrechte. Event-History-Auswahl-Anfragen laden
weiterhin die vollständige Struktur. Aufgezeichnete History und normale MCP-Clients
behalten ihre eigenen Autorisierungsgrenzen. Bei gestopptem Dienst oder einem
Discovery-Fehler beginnt der CGI-Helfer keine neue Anmeldung. Die gespeicherte
Auswahl bleibt erhalten; nach Behebung der Ursache ausdrücklich erneut versuchen.
Zurückbehaltene Emergency-Stop-Optionen sind als veraltet gekennzeichnet und
autorisieren keine Aktionen.

Die Verbindung verfällt nach 60 Sekunden Inaktivität oder fünf Minuten Nutzung.
Änderungen an Zugangsdaten oder Konfiguration sowie Verbindungsfehler verwerfen sie.
Eine akzeptierte Einschränkung bleibt: Teilweise Rechteänderungen wirken eventuell
erst nach Trennung oder Ersatz einer noch offenen Miniserver-Sitzung. Ein neuer
Strukturabruf beweist deshalb keinen universellen sofortigen Rechteentzug. MCP-Clients
erhalten über den Auswahl-Endpunkt niemals die Rechte dieser Dienstidentität.

### Fehler bei der Admin-Discovery

Wenn Notaus-Signale nicht aktualisiert werden können, die `request_id` im
Admin-CGI-Log mit `component=admin_discovery` im Dienstlog abgleichen. Nur bei
Fehlern werden eine feste `phase` und ein `code`, Gesamtdauer, Wartezeiten für
Discovery und Auth-Koordination, Zeiten für Token/Session-Aufbau sowie Anzahl
laufender Discovery-Anfragen und neue/gehaltene Session mit Alter protokolliert.
Eine fehlende Request-ID erscheint als `-`. Die Anzahl umfasst nur lokale
Admin-Discovery-Anfragen und misst nicht den gesamten Miniserver-Datenverkehr.
`connection_failed` in der UI bleibt ein allgemeiner Fehler. Die korrelierte
Dienstkategorie unterscheidet Timeout, Verbindungsabbruch, Protokoll,
Authentifizierung und Identitäts-/Lifecycle-Invalidierung; `unknown` bleibt
ungeklärt. Keine Exception-Texte, Payloads, Credentials, Tokens, Signalnamen oder
Objektidentitäten werden protokolliert. Die Diagnose wiederholt keine Anfragen
und verändert die Autorisierung nicht.
