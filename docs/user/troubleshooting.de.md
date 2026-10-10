# Fehlerbehebung

## Wiederholte Miniserver-Authentifizierungsablehnung

Drei eindeutige Passwort-/Token-Ablehnungen innerhalb von fünf Minuten pausieren
neue Plugin-Anmeldungen für 60 Sekunden. Erneut abgelehnte Prüfversuche verdoppeln
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
löschen. Ein abgebrochener Prozess hinterlässt eine 60-Sekunden-Reservierung.
Zugangsdaten und Tokenwerte erscheinen nicht im Status. Eine umfassende
Token-Bereinigung wird nicht angeboten; ihre Folgen werden getrennt untersucht.

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
