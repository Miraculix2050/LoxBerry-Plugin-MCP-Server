# ADR 0001: Phase-0-Grundarchitektur

- **Status:** Angenommen
- **Datum:** 2026-08-01
- **Geltung:** Runtime, Transport, Authentifizierung, Persistenz und erster
  ausführbarer Stand

## Kontext

Vor dem ersten ausführbaren Commit müssen die teuren oder sicherheitskritischen
Grundentscheidungen des Plugins feststehen. Die Phase-0-Spikes dürfen diese
Entscheidungen anhand realer Evidenz korrigieren, aber nicht durch zufällige
Implementierungsdetails ersetzen.

## Entscheidung

### Runtime und Paketierung

- Referenzplattform ist LoxBerry 4 auf Debian 13 (`arm64`) mit Python 3.13.
- Der Dienst verwendet das offizielle MCP-Python-SDK `1.28.1` aus der stabilen
  v1-Linie und MCP `2025-11-25`.
- Alle Laufzeitabhängigkeiten werden exakt fixiert. Das Releasepaket installiert
  sie ohne Netzwerkzugriff und ohne Kompilierung aus einem geprüften Wheelhouse
  in ein plugin-eigenes `venv`.
- Go wird nur neu bewertet, wenn ein notwendiges Wheel fehlt, das installierte
  Paket 150 MiB überschreitet, der Idle-RSS 150 MiB überschreitet oder einer von
  fünf Kaltstarts länger als fünf Sekunden bis zum Health-Status benötigt.

### Prozess und Transport

- Ein einzelner unprivilegierter Dienst läuft als `loxberry`, bindet nur an
  `127.0.0.1` und stellt Streamable HTTP bereit.
- Der öffentliche MCP-Pfad ist `/plugins/mcpserver/mcp`; der OAuth-Issuer ist
  `/plugins/mcpserver/oauth`. Apache leitet ausschließlich die vier exakten
  Issuer-Endpunkte `/authorize`, `/token`, `/register` und `/revoke` sowie die
  RFC-konformen Protected-Resource- und Authorization-Server-Metadaten unter
  `/.well-known/` weiter.
- Externer HTTPS-Zugriff bleibt im ersten öffentlichen Test deaktiviert.
- Proxy-Header werden nur vom lokalen Apache akzeptiert. Host und Origin werden
  gegen explizite Allowlisten geprüft.

### MCP- und OAuth-Autorisierung

- Der erste Umfang erteilt ausschließlich `loxone:read`.
- Der Server verwendet Authorization Code mit PKCE S256, audience-gebundene
  opaque Access Tokens, rotierende Refresh Tokens, Clientregistrierung und
  expliziten Widerruf.
- Access- und Refresh Tokens werden serverseitig nur gehasht gespeichert.
  Client- und Sessionzustand liegt in einer atomar ersetzten Datei mit Modus
  `0600`; eine Datenbank ist für den MVP nicht erforderlich.
- Authorization Codes sind einmalig und fünf Minuten gültig. Opaque Access
  Tokens gelten zehn Minuten. Refresh Tokens rotieren bei jeder Verwendung;
  ihre Familie endet spätestens nach 30 Tagen. Die Wiederverwendung eines
  rotierten Refresh Tokens widerruft die gesamte Familie.
- Codex CLI und Claude Desktop sind die beiden Phase-0-Interoperabilitätsclients.
  Nicht standardkonformes Clientverhalten führt nicht zu einem unsicheren
  Server-Sonderweg.

### Anmeldung des Ressourceninhabers und Einwilligung

- Jeder MCP-Client startet den Authorization-Code-Flow in einem Browser. Die
  Anmeldeseite wird ausschließlich vom lokalen Plugin ausgeliefert und verlangt
  ein dediziertes Loxone-Benutzerkonto; ein LoxBerry-Login gilt dafür nicht.
- Der Benutzername und das Passwort werden nur für die unmittelbare, mit Command
  Encryption geschützte erste Loxone-Tokenanforderung verwendet. Das Passwort
  wird weder gespeichert noch protokolliert oder in einen MCP-Token übernommen.
- Eine Freigabe entsteht erst nach erfolgreicher Loxone-Anmeldung und einer
  Einwilligungsseite, die MCP-Client, Miniserver, Loxone-Identität und die
  beantragten Scopes anzeigt. Der Authorization Code bindet genau diese Werte
  sowie Redirect-URI und PKCE-Challenge.
- Eine Session ist unveränderlich an diese Loxone-Identität gebunden. Ein anderer
  Loxone-Benutzer benötigt eine neue Anmeldung; gemeinsame vorkonfigurierte
  Tokens und eine nachträgliche Identitätsumschaltung sind nicht zulässig.
- Jeder LAN-Client darf den Flow initiieren, kann ihn aber ohne gültige Loxone-
  Zugangsdaten nicht abschließen. Fehlversuche werden begrenzt und auditierbar
  erfasst. LoxBerry-Administratoren können MCP-Sessions widerrufen, erhalten
  dadurch aber keine Loxone-Rechte und können keine Loxone-Identität zuweisen.

### Loxone-Anbindung und Secrets

- Gen. 1 wird ausschließlich im lokalen Netz über HTTP/WS angebunden. Anmeldung,
  Tokenanforderung und spätere Steuerkommandos verwenden Loxone-JWT und Command
  Encryption; HTTP Basic Authentication wird nicht implementiert.
- Das Loxone-Passwort lebt nur während der Tokenanforderung im Speicher. Im
  Phase-0-Browser-Spike bleibt auch das Loxone-Token ausschließlich in der
  einmaligen RAM-Transaktion und wird vor Ausgabe oder Ablehnung des
  Authorization Codes mit `killtoken` widerrufen. Erst Phase 1 führt den
  getrennten AES-GCM-geschützten Loxone-Token-Speicher ein.
- Der Installationsschlüssel wird durch einen Root-Hook erzeugt, ist nicht Teil
  von Konfiguration, Diagnose oder Backup und unterstützt atomare Rotation mit
  Erhalt des letzten gültigen Secret-Stands.
- Struktur- und Zustandscaches sind pro Loxone-Benutzer getrennt.

### Persistente Ablage

- Alle plugin-eigenen Pfade werden zur Laufzeit über die von LoxBerry ermittelten
  Verzeichnisse des tatsächlich vergebenen Pluginordners bezogen; `mcpserver`
  wird nicht als Installationsordner hart codiert. `LBPCONFIGDIR` und
  `LBPDATADIR` bezeichnen hier die so ermittelten absoluten LoxBerry-Pfade und
  keine vorausgesetzten Prozess-Umgebungsvariablen.
- Die autoritative normale Konfiguration liegt in
  `LBPCONFIGDIR/mcpserver.json` und gehört `loxberry:loxberry` mit Modus
  `0600`.
- OAuth-Clients und Sessions liegen atomar in
  `LBPDATADIR/auth/sessions.json`, verschlüsselte Loxone-Tokens getrennt in
  `LBPDATADIR/auth/loxone-tokens.json.enc`. Das Verzeichnis `auth` hat Modus
  `0700`, beide Dateien gehören `loxberry:loxberry` und haben Modus `0600`.
- Der Root-Hook erzeugt den Installationsschlüssel unter
  `LBPDATADIR/auth/install.key` als `root:loxberry` mit Modus `0640`. Er wird
  weder durch die UI exportiert noch in Plugin-Backups aufgenommen. Bei einer
  Wiederherstellung ohne Schlüssel werden vorhandene Sessions und Loxone-Tokens
  verworfen und neu autorisiert, statt unentschlüsselbar weiterverwendet zu
  werden.
- Für Phase 0 wird der Pfad der Sessiondatei ausdrücklich injiziert. Der Spike
  beweist Dateisperre, atomaren Austausch sowie Modus `0700` für das Verzeichnis
  und `0600` für Datei und Lock, ohne das spätere Pluginlayout vorwegzunehmen.

### Produktabgrenzung

- Phase 1 bleibt read-only. Das erste spätere Schreibziel ist der Loxone-
  Control-Typ `Switch` mit ausschließlich explizitem `on` und `off`.
- `loxberry:read` folgt erst in Phase 3 mit einer eigenen lokalen Freigabe.
- Phase-0-Probe-Tools sind keine veröffentlichten MCP-Verträge und werden vor
  dem ersten Paket entfernt.

### Qualität und Lieferung

- Der kanonische lokale Testbefehl lautet nach Installation der exakt fixierten
  Runtime- und Entwicklungsabhängigkeiten `python tools/test.py`. Er führt
  Formatprüfung, Lint, strikte Typprüfung, Unit- und MCP-Vertragstests aus.
- GitHub Actions verwendet `ubuntu-24.04` und CPython 3.13. Derselbe Befehl läuft
  bei Pull Requests sowie bei Pushes nach `master`; echte LoxBerry- oder
  Miniserver-Ziele sind kein Bestandteil dieser öffentlichen CI.
- Ausführbare, normative und sicherheitsrelevante Änderungen werden über normale
  Review-Pull-Requests geliefert und nicht automatisch gemergt.

## Ausgangsevidenz

Der erste Runtime-Spike wurde am 2026-08-01 auf einem LoxBerry 4 mit Debian 13,
`aarch64` und Python 3.13.5 ausgeführt. MCP `1.28.1` und alle transitiven
Abhängigkeiten ließen sich als 29 Binär-Wheels laden und anschließend offline
installieren. Das Wheelhouse belegte 9 MiB, das vollständige `venv` 51 MiB.

Der Minimaldienst wurde aus demselben Abhängigkeitssatz fünfmal gestartet. Der
Health-Endpunkt war nach 4,088 bis 4,386 Sekunden erreichbar. Der RSS lag direkt
danach zwischen 53.428 und 53.452 KiB und nach zehn Minuten Idle bei 53.448 KiB.
Damit sind Paket-, Startzeit- und Speichergrenze erfüllt.

Der Transport-Spike lief auf demselben Zielsystem mit Apache 2.4.68 als zweite,
unprivilegierte Instanz auf einem hohen Loopback-Port. Die Konfiguration war
syntaktisch gültig, MCP-Initialisierung über `/plugins/mcpserver/mcp` gelang,
eine fremde Origin wurde abgewiesen und die SSE-Verbindung blieb 120 Sekunden
offen. Die produktive System-Apache-Konfiguration wurde dabei nicht verändert.

Der OAuth-Spike wurde am 2026-08-03 mit demselben Python-3.13-/arm64-Ziel erneut
aus einem Offline-Wheelhouse installiert. Einschließlich Projekt-Wheel waren 31
Wheels mit 9.372 KiB erforderlich; das Laufzeit-`venv` belegte 53.932 KiB. Fünf
Starts mit aktiviertem OAuth waren nach 4.604 bis 4.772 ms gesund. Der RSS lag
zwischen 64.364 und 64.384 KiB und blieb nach 30 Sekunden bei 64.368 KiB.

Die isolierte Apache-2.4.68-Instanz bestätigte die exakten MCP-, OAuth- und
Well-known-Pfade, Host-/Origin-Abweisung, DCR, geschützte MCP-Ressource und
fehlende Alias- beziehungsweise Trailing-Slash-Weiterleitungen. Die
deterministische Negativmatrix und der Browserablauf sind automatisiert; die
beiden realen Clientnachweise bleiben vor dem Merge dieses Spikes Pflicht.

## Folgen

Python, Apache-Transport, Gen.-1-Loxone und WebSocket sind für die
Referenzplattform bestätigt; ein vorsorglicher paralleler Go-Build entfällt.
OAuth ist automatisiert und hinter einer isolierten realen Apache-Instanz
bestätigt. Die Interoperabilitätsaussage folgt erst nach den dokumentierten
Codex-CLI- und Claude-Desktop-Tests.
