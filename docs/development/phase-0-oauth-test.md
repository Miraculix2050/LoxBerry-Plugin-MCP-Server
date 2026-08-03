# Phase-0-Test: OAuth und Clientinteroperabilität

Dieser Nachweis prüft den unveröffentlichten OAuth-Spike über die lokale
HTTPS-Adresse des LoxBerry. Er veröffentlicht noch keinen dauerhaften
MCP-Toolvertrag. Zugangsdaten, Tokens, interne Adressen, Callback-Parameter und
lokale Testpfade werden nicht in diesen Bericht übernommen.

## Vertrag

- MCP: `/plugins/mcpserver/mcp`
- Issuer: `/plugins/mcpserver/oauth`
- Endpunkte: `/authorize`, `/token`, `/register`, `/revoke`
- Protected Resource Metadata und Authorization Server Metadata ausschließlich
  unter den dokumentierten `/.well-known/`-Pfaden
- Authorization Code mit PKCE S256; öffentliche Clients ohne Client Secret
- ausschließlich Scope `loxone:read` und exakt die MCP-URL als `resource`
- Code fünf Minuten, Access Token zehn Minuten, rotierende Refresh-Token-Familie
  höchstens 30 Tage

Die Browsertransaktion lebt einmalig für höchstens fünf Minuten im RAM, ist mit
CSRF-Token und sicherem Cookie gebunden und erlaubt höchstens fünf
Anmeldeversuche. Das Loxone-Passwort wird nur unmittelbar für Command Encryption
verwendet. Das dabei erzeugte Loxone-JWT wird vor Freigabe, Ablehnung oder
Testabschluss bestmöglich mit `killtoken` widerrufen.

## Automatisierte und Zielsystem-Nachweise

Am 2026-08-03 liefen Formatprüfung, Ruff, striktes mypy und 132 Pytests lokal
erfolgreich. Die Tests umfassen DCR, Redirect-Grenzen, Scope, Audience, PKCE,
CSRF, Ablauf, Code-Replay, Refresh-Rotation, Familien-Replay, Widerruf,
pseudonymisierte Identität und das Fehlen roher Credentials im Store.

Ein unabhängiger Sicherheitsreview ergänzte Regressionen für begrenzte
Streaming-Request-Bodies, DCR-Kapazität und -Drosselung, transaktionsübergreifende
Loginbegrenzung, parallele Einmaltransaktionen, Store-Bereinigung sowie
Dateirechte bereits vorhandener Stores.

Auf LoxBerry `4.0.0.14`, Debian 13, `aarch64`, Python `3.13.5` und Apache
`2.4.68` wurden zusätzlich bestätigt:

- 31 Wheels, 9.372 KiB Wheelhouse und erfolgreiche Offline-Installation
- Laufzeit-`venv` 53.932 KiB
- fünf OAuth-Kaltstarts zwischen 4.604 und 4.772 ms
- RSS 64.364 bis 64.384 KiB; nach 30 Sekunden Idle 64.368 KiB
- Apache-Syntax sowie exakte MCP-, OAuth- und beide Well-known-Pfade
- DCR, geschützte MCP-Ressource, Host-/Origin-Abweisung und keine
  Trailing-Slash- oder Prefix-Aliase

Die produktive Apache-Konfiguration wurde für diese Nachweise nicht verändert.

## Verbleibende reale Abnahme vor Merge

| Client | Version | Callback | Login | Probe | Refresh | Revoke |
| --- | --- | --- | --- | --- | --- | --- |
| Codex CLI | `0.146.0` | dynamischer IPv4-Loopback mit pfadgebundener Callback-ID | erfolgreich | erfolgreich | extern blockiert | lokal abgemeldet; Client sendet keinen Widerruf |
| Claude Desktop mit `mcp-remote@0.1.38` | `1.24012.9` | `localhost`-Loopback; Port anonymisiert | erfolgreich | erfolgreich | erfolgreich | erfolgreich |

Für Node-basierte Clients wird die Windows-System-CA mit
`NODE_USE_SYSTEM_CA=1` verwendet. Zertifikatsprüfung, Hostnamenprüfung und TLS
werden nicht deaktiviert. Nach beiden Läufen werden OAuth-Widerruf,
Loxone-`killtoken`, Dateirechte und ein Secret-Scan der maskierten Logs geprüft.

Der reale Codex-Lauf bestätigte außerdem zwei Interoperabilitätsgrenzen: Aktuelle
Codex-Versionen registrieren öffentliche native Clients mit dem Standardfeld
`application_type`, das die fixierte Python-SDK-Version noch nicht modelliert. Der
Provider validiert deshalb ausschließlich `native` oder `web` und normalisiert
weiterhin strikt auf `token_endpoint_auth_method=none`. Browser-Formulare verwenden
`Referrer-Policy: strict-origin`; ihre CSP erlaubt neben dem eigenen Issuer nur die
exakt registrierte Callback-Origin. Pfad, OAuth-Code und Query werden nicht in CSP-
oder Referrer-Header übernommen.

Nach natürlichem Ablauf des zehnminütigen Access Tokens versuchte Codex CLI
`0.146.0` zweimal eine Aktualisierung. Der Client ließ dabei den für alle
Tokenrequests verpflichtenden RFC-8707-Parameter `resource` weg; der Server wies
beide Requests daher erwartungsgemäß mit `invalid_request` ab. Dieser bekannte
Clientfehler darf nicht durch eine Lockerung der Audience-Bindung auf Serverseite
umgangen werden. `codex mcp logout` entfernte anschließend lediglich die lokalen
OAuth-Credentials und rief den veröffentlichten Widerrufsendpunkt nicht auf. Die
betroffene, nur für diesen Nachweis angelegte serverseitige Testablage wird beim
Abbau der isolierten Testinstanz vollständig entfernt.

Der reale Claude-Desktop-Lauf verwendete die lokale stdio-Bridge aus dem exakt
installierten npm-Paket `mcp-remote@0.1.38` mit der Transportstrategie
`http-only`. Nach DCR, Browseranmeldung und Einwilligung stellte die Bridge eine
Streamable-HTTP-Verbindung her. Claude initialisierte MCP, listete die Werkzeuge
und rief `phase0_identity_probe` erfolgreich auf; die Antwort enthielt genau die
vier vorgesehenen pseudonymisierten Felder und den Scope `loxone:read`. Ein
zuvor verwaister Bridge-Prozess belegte den registrierten Loopback-Port und wurde
anhand des Client-`stderr` als `EADDRINUSE` identifiziert und gezielt beendet.
Nach natürlichem Ablauf des Access Tokens baute Claude die Verbindung neu auf.
Der Token-Endpunkt akzeptierte den Refresh, der Store markierte die alte
Refresh-Generation als verbraucht und legte eine neue aktive Generation an.
Der abschließende RFC-7009-Widerruf markierte die gesamte Testfamilie sowie alle
zugehörigen Access- und Refresh-Tokens als widerrufen.
