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

## Wiederholte Miniserver-Authentifizierungsablehnung

Drei eindeutige Ablehnungen innerhalb von fÃ¼nf Minuten pausieren neue Anmeldungen
fÃ¼r 60 Sekunden. Ã–ffentliche OAuth-Passwortfehler haben ein eigenes Budget und
pausieren nur Ã¶ffentliche Anmeldungen. Dienst- und Token-Ablehnungen teilen ein
zweites Budget; dessen Pause gilt auch fÃ¼r die Token-Phase Ã¶ffentlicher Anmeldungen.
Eine Ã¶ffentliche Passwortpause blockiert weder Dienstverbindungen noch Token-Widerrufe.
TatsÃ¤chliche IP-Sperren gelten weiterhin global. Erneut abgelehnte PrÃ¼fversuche verdoppeln
die Pause bis auf 60 Minuten. Netzwerkfehler, Timeouts, Anmeldekonkurrenz und
verweigerte Projektberechtigungen verbrauchen dieses Budget nicht. Bestehende
authentifizierte Verbindungen bleiben offen. Diese Plugin-Policy garantiert keine
bestimmte Miniserver-IP-Sperrschwelle.

Der Abschnitt Sitzungen zeigt Schutzgrund und verbleibende Wartezeit. Ein lokaler
Administrator kann ausdrÃ¼cklich eine Anmeldung mit den in LoxBerry konfigurierten
Zugangsdaten prÃ¼fen, frÃ¼hestens 60 Sekunden nach dem vorherigen Versuch. Den
Warnhinweis beachten: Eine weitere Ablehnung kann die Pause verlÃ¤ngern oder eine
IP-Sperre auslÃ¶sen. Automatische Wiederholungen und MCP-Clients dÃ¼rfen die Pause
nicht umgehen; eine bestÃ¤tigte Miniserver-IP-Sperre hat Vorrang.

Bei nicht verfÃ¼gbarer Schutzpersistenz stoppen neue Anmeldungen. Den Zugriff auf
die private Plugin-Zustandsdatei wiederherstellen und nach Behebung der Ursache
den Dienst neu starten; einen aktiven Schutzstatus nicht nur fÃ¼r weitere Versuche
lÃ¶schen. Ein abgebrochener Prozess hinterlÃ¤sst eine konservative Reservierung von bis zu einer Stunde.
Eine bestehende Source-IP-Wiederanlaufpolicy kann eine lÃ¤ngere Reservierung erfordern und hat Vorrang.
Zugangsdaten und Tokenwerte erscheinen nicht im Status. Eine umfassende
Token-Bereinigung wird nicht angeboten; ihre Folgen werden getrennt untersucht.

Ein noch ungeklÃ¤rtes Authentifizierungsergebnis reserviert zusÃ¤tzlich den vorhandenen globalen IP-Wiederanlaufabstand. Bei einem Absturz oder nicht speicherbaren Ergebnis kann dieser Schutz alle neuen Anmeldungen vorÃ¼bergehend zurÃ¼ckstellen; normale gespeicherte Passwortablehnungen lÃ¶sen ihn nicht aus. Bereits ausgestellte Token werden bei unterdrÃ¼cktem Anmeldeabschluss verschlÃ¼sselt fÃ¼r den koordinierten Widerruf gespeichert. Scheitert auch dies, bleibt der Token in der Transaktion erhalten und eine neue Ausstellung ist bis zur Bereinigung gesperrt.

[English](troubleshooting.en.md)

| Symptom | Sichere PrÃ¼fung |
| --- | --- |
| Client erreicht den Server nicht | PrÃ¼fe Dienststatus, lokale HTTPS-Adresse und Zertifikatsdiagnose. |
| OAuth-Anmeldung startet nicht | Ã–ffne die HTTPS-Adresse; HTTP wird nicht fÃ¼r die Anmeldung verwendet. |
| Tool antwortet mit `permission_denied` | PrÃ¼fe Loxone-Rechte, angeforderten Scope und gegebenenfalls lokale Adminfreigabe. |
| Tool antwortet mit `emergency_stop_active` | PrÃ¼fe das ausgewÃ¤hlte Notaus-Signal: `1` gibt Tool-Aufrufe frei, `0` sperrt sie. Bei `unknown` kann der Dienst keinen sicheren Wert bestÃ¤tigen. Stelle das Signal auÃŸerhalb von MCP auf `1` oder entferne die Auswahl; nicht automatisch wiederholen. Die Antwort enthÃ¤lt den aktuellen Status sowie UTC-Zeitpunkte fÃ¼r Beobachtung und Beginn der Sperre. |
| Keine aktuellen Werte | PrÃ¼fe Miniserver-Verbindung und ob der Loxone-Benutzer die Controls sehen darf. |
| Update fehlgeschlagen | Warte auf den terminalen Status im Plugin Manager und halte das vorherige Paket bereit. |

Exportiere oder teile keine Zugangsdaten, Tokens, privaten Adressen oder vollstÃ¤ndigen Zustandsdaten. Nutze nur maskierte Plugin-Diagnosen.

## VorÃ¼bergehend nicht verfÃ¼gbare Leseaufrufe

Bewahre bei `temporarily_unavailable` die Felder `error`, `message`,
`diagnostic_code` und `trace_id` zusammen mit Tool und autorisiertem Zielkontext
auf. Erhalte auch `availability_phase` und `retry_after_seconds`.
`local_rate_limit` bezeichnet das lokale Aufrufbudget des Aufrufers; nur diese
Ursache liefert eine aufgerundete Wartezeit von 1â€“60 Sekunden. Warte mindestens
so lange und wiederhole einen Leseaufruf hÃ¶chstens einmal. KapazitÃ¤t wird nicht
reserviert. Nutze erfolgreiche Beschreibungen erneut und reduziere parallele
Aufrufe. Wiederhole ungewisse SchreibvorgÃ¤nge niemals automatisch.

Der Runtime-Sitzungsaufbau wartet innerhalb des konfigurierten Verbindungszeitlimits
auf lokale Authentifizierungskoordination; Warten und Login teilen dieses Budget.
Cancellation beendet das Warten. Frische MCP-Sichtbarkeit erfordert weiterhin die
authentifizierte Struktur des Aufrufers; die Admin-IdentitÃ¤t oder eine alte gecachte
Struktur kann sie nicht ersetzen. `structure_refresh_auth_cooldown` bezeichnet die
vorbeugende Schutzpause oder
unsichere Schutzpersistenz vor einem Netzwerkzugriff. `structure_refresh_auth_busy`
bedeutet, dass die
lokale Koordination ihr Wartebudget vor dem Login ausgeschÃ¶pft hat.
`structure_refresh_source_ip_suppressed` bezeichnet Source-IP-Blocking oder den
persistent gespeicherten Breaker. Diese Kategorien bezeichnen nicht das Aufrufbudget des Clients.
Transportfehler und entfernte Sitzungslimits bleiben getrennt; ein Fehler der
Verbindungskategorie allein belegt kein Miniserver-Sitzungslimit. Diese Diagnosen
erlauben keine Zuordnung Ã¤lterer Fehler ohne erhaltene zugrunde liegende Exception (#332).

`structure_refresh_connection`, `structure_refresh_protocol`,
`structure_refresh_token` und `structure_refresh_timeout` unterscheiden bestÃ¤tigte
Refresh-Exception-Kategorien. Token-Fehler umfassen fehlende Tokens und Fehler des
Token-Speichers. Die Phase bezeichnet Token-Abfrage, Sitzungsaufbau,
VersionsprÃ¼fung, Strukturladen oder SitzungsschlieÃŸen. `structure_refresh_unknown`
und `availability_unknown` lassen die Ursache ausdrÃ¼cklich unbekannt. DafÃ¼r gibt
es keine Wiederholungsfrist; erfinde keine und leite sie nicht aus einem gesunden
Dienst ab.

Nutze fÃ¼r Support autorisierte, maskierte Dienstdiagnosen mit der Trace-ID der
Antwort. Warnungen werden je Kategorie und Phase 60 Sekunden unterdrÃ¼ckt;
Ereigniszahlen zÃ¤hlen keine fehlgeschlagenen Aufrufe, fehlende Ereignisse benennen
keine Ursache.

### Admin-Discovery-Verbindung

Event History und die Emergency-Stop-Auswahl verwenden eine eigene Verbindung mit
der in LoxBerry konfigurierten Miniserver-IdentitÃ¤t. Jede neue Auswahl-Anfrage lÃ¤dt
weiterhin die vollstÃ¤ndige Struktur. Aufgezeichnete History und normale MCP-Clients
behalten ihre eigenen Autorisierungsgrenzen. Bei gestopptem Dienst oder einem
Discovery-Fehler beginnt der CGI-Helfer keine neue Anmeldung. Die gespeicherte
Auswahl bleibt erhalten; nach Behebung der Ursache ausdrÃ¼cklich erneut versuchen.
ZurÃ¼ckbehaltene Emergency-Stop-Optionen sind als veraltet gekennzeichnet und
autorisieren keine Aktionen.

Die Verbindung verfÃ¤llt nach 60 Sekunden InaktivitÃ¤t oder fÃ¼nf Minuten Nutzung.
Ã„nderungen an Zugangsdaten oder Konfiguration sowie Verbindungsfehler verwerfen sie.
Eine akzeptierte EinschrÃ¤nkung bleibt: Teilweise RechteÃ¤nderungen wirken eventuell
erst nach Trennung oder Ersatz einer noch offenen Miniserver-Sitzung. Ein neuer
Strukturabruf beweist deshalb keinen universellen sofortigen Rechteentzug. MCP-Clients
erhalten Ã¼ber den Auswahl-Endpunkt niemals die Rechte dieser DienstidentitÃ¤t.
