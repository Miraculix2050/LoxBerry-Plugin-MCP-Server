# Konzept: LoxBerry MCP-Server-Plugin

- **Status:** Konzeptentwurf zur fachlichen und technischen Prüfung
- **Stand:** 2026-08-01
- **Basis:** [Recherche-Ergebnisse](../research/research-results.md) und
  [Implementierungsrichtlinien](implementation-guidelines.md)

## 1. Produktvision

Das Plugin stellt einen MCP-Server direkt auf dem LoxBerry bereit. Ein
KI-Assistent kann damit die für seinen Loxone-Benutzer freigegebenen Räume,
Kategorien, Steuerungen und Zustände verstehen und eng begrenzte Befehle an die
laufende Loxone-Installation senden. Zusätzlich kann er freigegebene Zustände
des LoxBerry und des Plugins abfragen.

Der Betrieb benötigt keinen eigenen Cloud-Dienst des Projekts. Lokale Clients
bleiben im LAN; Cloud-Clients können optional über eine vom Benutzer
bereitgestellte, standardkonforme HTTPS-Adresse verbunden werden.

Das Plugin programmiert weder den Miniserver neu noch bietet es eine allgemeine
Fernadministration des LoxBerry. Es ist eine kontrollierte Bedien- und
Diagnoseschnittstelle für eine bestehende Installation.

## 2. Zielgruppen und Nutzen

- **Loxone-Benutzer:** natürliche Abfragen und Bedienung mit den vorhandenen
  Raum-, Kategorie- und Steuerungsnamen
- **Miniserver-Gen.-1-Benutzer:** MCP-Zugang trotz fehlendem nativen
  Loxone-MCP-Plugin
- **LoxBerry-Betreiber:** lokale Diagnose von Plugin- und Systemzuständen
- **Automatisierungs- und Support-Agenten:** strukturierte, begrenzte Tools statt
  SSH oder einer allgemeinen Shell

## 3. Abgrenzung

Nicht zum Produktumfang gehören:

- Änderung der Loxone-Projektlogik, Benutzer oder Berechtigungen
- Loxone Config, Expertenmodus oder Automatik-Designer über MCP
- beliebige Miniserver-Webservicepfade
- allgemeine Shell-, Datei-, Paket- oder `sudo`-Kommandos auf dem LoxBerry
- ungeprüfte globale Aktionen auf alle Steuerungen
- eigener Cloud-Relay-, Konto- oder Telemetriedienst
- Garantie für Browser, Clients, Miniserver oder Architekturen ohne Testnachweis

## 4. Entscheidungsgrundsätze

1. Loxone und LoxBerry sind zwei getrennte Autorisierungsdomänen.
2. Der Server startet read-only; Schreibrechte werden bewusst hinzugefügt.
3. Sichtbarkeit und Bedienbarkeit von Loxone-Objekten werden mit dem jeweiligen
   Loxone-Benutzer am Miniserver durchgesetzt.
4. Ein Tool bietet nur semantisch bekannte Aktionen und Wertebereiche an.
5. UUIDs sind stabile Identitäten; Namen dienen Suche und Darstellung.
6. Der Dienst läuft ohne Root-Rechte und erhält keine breite `sudo`-Freigabe.
7. Externer Zugriff ist optional und ausschließlich über HTTPS vorgesehen.
8. Jede Produktzusage benötigt automatisierte oder dokumentierte reale Evidenz.

## 5. Empfohlener Technologie-Stack

### Kernruntime

Für den MVP wird ein eigenständiger Python-Dienst auf LoxBerry 4 unter Debian 13
(Trixie) bevorzugt:

- systemseitiges Python 3.13; das MCP-SDK selbst verlangt mindestens Python 3.10
- offizielles MCP-Python-SDK (Tier 1), auf eine geprüfte Hauptversion fixiert
- `asyncio`/ASGI mit Streamable HTTP auf einem Loopback-Port
- typisierte Ein- und Ausgabemodelle
- kleiner eigener Loxone-Adapter für den tatsächlich benötigten API-Umfang
- keine Datenbank im MVP; atomare JSON-Konfiguration und begrenzter RAM-Cache

Python passt gut, weil MCP-, HTTP- und WebSocket-Verarbeitung überwiegend auf
Netzwerk-I/O wartet. Es ist nicht mit den Perl-/PHP-Komponenten von LoxBerry
gekoppelt und läuft als eigener unprivilegierter Prozess. Die höhere
Runtime- und Speicherlast gegenüber einem Go-Binary ist zu messen, wird für den
kleinen Toolumfang aber nicht als grundsätzlicher Engpass erwartet.

Das Plugin installiert niemals Abhängigkeiten in das System-Python. Es erhält
ein eigenes virtuelles Environment und einen vollständig fixierten,
reproduzierbaren Abhängigkeitssatz. Dies respektiert das von Debian verwaltete
System-Python und PEP 668. Für jede unterstützte Architektur müssen vorgebaute
Wheels vorhanden oder im Paket mitgeliefert sein; die normale Installation darf
weder Compiler noch Rust-Toolchain benötigen.

LoxBerry 3 und ältere Debian-Basen gehören nicht zur anfänglichen Support-Matrix.
Sie können später ergänzt werden, wenn Python-Version und Abhängigkeiten dafür
reproduzierbar bereitgestellt werden können. Diese optionale
Rückwärtskompatibilität blockiert den MVP nicht.

Go bleibt die dokumentierte Rückfalloption, falls Python-Wheels oder das
Ressourcenbudget auf einer erforderlichen LoxBerry-4-Architektur scheitern. Das
offizielle Go-SDK ist ebenfalls Tier 1; ein einzelnes Binary reduziert
Installations- und Abhängigkeitsrisiken, kostet aber mehr Implementierungsaufwand.

Vor der Festlegung beweist ein Spike:

- Python 3.13 und venv-Erstellung auf allen ausgewählten
  LoxBerry-4-/Debian-13-Architekturen
- Installation aller fixierten Abhängigkeiten ausschließlich aus verfügbaren
  oder mitgelieferten Wheels
- Paketgröße, Start sowie RAM- und CPU-Bedarf im Idle und bei Zustandsupdates
  auf den ausgewählten Architekturen
- Streamable HTTP/Origin-Prüfung hinter dem LoxBerry-Apache
- OAuth-Interoperabilität mit mindestens zwei relevanten Clients
- Loxone-Anmeldung, Rechtefilterung und WebSocket-Zustände auf dem verfügbaren
  Miniserver Gen. 1

Falls Python an einer erforderlichen Altplattform, fehlenden ARM-Wheels oder dem
Ressourcenbudget scheitert, wird Go verwendet. TypeScript bleibt eine weitere,
aber nicht bevorzugte Alternative. Das zusätzliche Express-Server-Plugin soll
nicht zur Pflicht des MCP-Kerndienstes werden.

### Protokollversion

Der erste öffentliche Release implementiert die finale MCP-Version
`2025-11-25` über die stabile v1-Linie des offiziellen Python-SDKs. Die konkrete
SDK-Version und ihre transitiven Abhängigkeiten werden im Build exakt fixiert;
die Protokollversion wird nicht durch eigene Konstanten am SDK vorbei erzwungen.

Die Revision `2026-07-28` bleibt solange außerhalb des produktiven Umfangs, bis
alle folgenden Bedingungen erfüllt sind:

1. die MCP-Spezifikation ist final veröffentlicht,
2. ein stabiles offizielles Python-SDK unterstützt sie vollständig,
3. die offizielle Conformance-Suite ist erfolgreich,
4. mindestens zwei relevante Clients sind real interoperabel getestet und
5. `2025-11-25` bleibt während einer dokumentierten Übergangsphase per
   Versionsaushandlung nutzbar.

Die interne Architektur wird dennoch auf den stateless Ansatz vorbereitet:
Tool-Handler sind wiedereintrittsfähig, fachlicher Zustand liegt nicht nur in
einer MCP-Transportsession, und der MVP hängt nicht von Roots, Sampling oder
MCP-Logging ab. Damit wird das spätere Upgrade kleiner, ohne einen Release
Candidate zum Produktionsvertrag zu machen.

## 6. Zielarchitektur

```text
MCP-Client
   │ HTTPS + OAuth 2.1
   ▼
LoxBerry Apache / Reverse Proxy
   │ Loopback, Streamable HTTP
   ▼
mcpserver-Dienst (Benutzer loxberry)
   ├── MCP-Transport und Tool-Registry
   ├── OAuth Resource-/Authorization-Server
   ├── Policy und Audit
   ├── Loxone-Adapter ── HTTP/WebSocket ── Miniserver
   ├── LoxBerry-Read-Adapter ── sichere lokale APIs/Dateien
   └── Konfiguration, Sessions und begrenzte Caches

LoxBerry Admin-UI (htmlauth)
   ├── Konfiguration, Scopes, Sessions, Status und Logs
   └── lokaler MCP Tool Explorer als eigenständiger OAuth-Client
```

### Komponenten

| Komponente | Verantwortung |
| --- | --- |
| MCP-Transport | Versionierung, Streamable HTTP, Sessions, Limits, Origin-Prüfung |
| Tool-Registry | stabile Namen, Schemas, Annotationen und Handlerzuordnung |
| OAuth-Schicht | Discovery, PKCE, Tokens, Scopes, Widerruf und Clientbindung |
| Policy Engine | Benutzer-, Scope-, Tool- und Zielprüfung vor jedem Aufruf |
| Loxone-Adapter | Authentifizierung, Struktur, Zustand, Statistik und Befehle |
| Control Registry | erlaubte Aktionen und Wertebereiche pro Loxone-Control-Typ |
| LoxBerry-Adapter | ausschließlich freigegebene, semantische Diagnoseoperationen |
| Audit | sicherheitsrelevante Ereignisse ohne Secrets oder unnötige Zustandswerte |
| Admin-UI | lokale Konfiguration, Betriebsdiagnose und ein flüchtiger Tool Explorer für den festen lokalen MCP-Endpunkt über LoxBerry `htmlauth` |

## 7. Netzwerk und Veröffentlichung

Der Dienst lauscht ausschließlich auf `127.0.0.1:8765`. Dieser feste interne
Port ist Teil des gemeinsam ausgelieferten Dienst-/Apache-Vertrags und wird vor
dem Dienststart auf Konflikte geprüft. Apache veröffentlicht den MCP-Endpunkt
verbindlich unter:

```text
https://<loxberry>/plugins/mcpserver/mcp
```

Dieser MCP-Pfad ist durch den realen Apache-Transport-Spike bestätigt und muss
GET und POST unterstützen. Der OAuth-Issuer liegt unter
`/plugins/mcpserver/oauth`; nur `/authorize`, `/token`, `/register` und
`/revoke` werden darunter weitergeleitet. Die Metadaten liegen ausschließlich
unter `/.well-known/oauth-protected-resource/plugins/mcpserver/mcp` und
`/.well-known/oauth-authorization-server/plugins/mcpserver/oauth`.
Prefix-Aliase und Trailing-Slash-Weiterleitungen sind nicht Teil des Vertrags.
Reverse-Proxy-Header werden nur von einem explizit vertrauten lokalen Proxy
akzeptiert.

Für externe Nutzung gilt:

- ausschließlich HTTPS mit öffentlich vertrauenswürdigem Zertifikat
- explizit konfigurierte externe Basis-URL
- kein automatisches Öffnen von Routerports
- vollständige Weiterleitung von MCP- und `/.well-known`-Pfaden
- Host-/Origin-Allowlist und Schutz vor DNS Rebinding
- dokumentierter Verbindungscheck vor Freigabe

Der erste öffentliche Test bietet noch keinen externen MCP-Zugriff. Er ist auf
lokale beziehungsweise LAN-Clients begrenzt. Die externe Veröffentlichung wird
erst nach einem eigenen Reverse-Proxy-, OAuth- und Sicherheitstest aktiviert.

LAN-Clients können direkt über die lokale HTTPS-Adresse arbeiten. stdio wird
nicht als zweiter Servermodus benötigt; ein lokaler Client kann bei Bedarf eine
generische Streamable-HTTP-zu-stdio-Bridge verwenden.

## 8. Authentifizierung und Autorisierung

### MCP-Client zum Plugin

Der HTTP-Endpunkt implementiert die MCP-Autorisierung mit OAuth 2.1:

- Protected Resource Metadata
- Authorization Server Metadata
- Authorization Code Flow mit PKCE
- Resource Indicator/Audience-Bindung
- kurzlebige Access Tokens
- rotierende, widerrufbare Refresh Tokens
- sichere Registrierung unterstützter öffentlicher Clients
- ausschließlich `token_endpoint_auth_method=none` und Scope `loxone:read`
- einmalige Codes mit fünf Minuten, Access Tokens mit zehn Minuten und
  rotierende Refresh-Token-Familien mit höchstens 30 Tagen Laufzeit

MCP-Tokens sind ausschließlich für das Plugin gültig. Sie werden nie an Loxone
oder andere Dienste weitergereicht.

### Plugin zum Miniserver

Beide Miniserver-Generationen werden direkt über die normale Loxone-Webservice-
und WebSocket-API angebunden. Das Plugin verwendet Loxone JSON Web Tokens; es
verwendet weder HTTP Basic Authentication noch die OAuth-Schnittstelle des
nativen Gen.-2-MCP-Servers. MCP-OAuth und Loxone-JWT bleiben getrennte
Sicherheitsdomänen.

| Merkmal | Miniserver Gen. 1 | Miniserver Gen. 2/Compact |
| --- | --- | --- |
| Transport | ausschließlich HTTP und WS | ausschließlich HTTPS und WSS für das Plugin |
| Serverauthentizität | keine TLS-Serveridentität; nur lokales, vertrauenswürdiges Netz | Zertifikats- und Hostnamenprüfung zwingend |
| Loxone-Anmeldung | JWT mit `getkey2`, HMAC und Loxone Command Encryption | JWT über die TLS-geschützte API |
| Anwendungskryptografie | RSA-Schlüsselaustausch und AES-256-CBC für Auth-/Steuerkommandos | ab Firmware 11.2 bei geprüftem TLS nicht erforderlich |
| HTTP Basic Auth | nicht unterstützt | nicht unterstützt |
| Reale Ausgangsbasis | Firmware `17.1.7.27` auf dem verfügbaren Testgerät bestätigt | Firmwarestände erst durch öffentliche Beta bestätigt |

Der Verbindungsaufbau beginnt lokal mit dem nicht sensitiven
`jdev/cfg/apiKey`-Probe. Der Adapter wertet Firmware und `httpsStatus` aus:

1. Meldet der Miniserver TLS-Unterstützung, sind HTTPS/WSS, ein zum Zertifikat
   passender Hostname und vollständige Zertifikatsprüfung Pflicht. Nach einem
   TLS-Fehler erfolgt kein stiller Rückfall auf HTTP/WS.
2. Fehlt TLS-Unterstützung, wird die Verbindung nur für Gen. 1 und nur zu einem
   lokalen Ziel zugelassen. Tokenanforderung, Tokenauthentifizierung und
   Steuerkommandos verwenden die Loxone Command Encryption.
3. Der Adapter verwendet den von `getkey2` gemeldeten Hashalgorithmus und darf
   SHA1 oder SHA256 nicht anhand der Generation fest annehmen.
4. Das Passwort lebt nur für die erstmalige Tokenanforderung im Speicher und
   wird weder gespeichert noch protokolliert. Das erneuerbare Loxone-JWT wird
   im geschützten Secret-Speicher abgelegt, erneuert und bei Widerruf mit
   `killtoken` invalidiert.

Command Encryption ersetzt auf Gen. 1 kein TLS. Insbesondere Strukturdateien,
Statusereignisse und Teile der Antworten besitzen keine garantierte
Ende-zu-Ende-Vertraulichkeit. Deshalb sind Gen.-1-Verbindungen auf das lokale
Netz beschränkt, verwenden einen dedizierten Benutzer mit Minimalrechten und
werden in der UI als transportseitig unverschlüsselt gekennzeichnet.

Jede Server-Session bindet mindestens:

- MCP-Client-ID
- Loxone-Miniserver
- Loxone-Benutzeridentität
- erteilte Scopes
- Token-Audience
- Ausgabe- und Ratenlimits

Struktur- und Zustandscaches werden nicht zwischen Benutzern mit möglicherweise
unterschiedlichen Rechten geteilt.

### Scopes

Vorgesehene Scopes:

| Scope | Bedeutung | Default |
| --- | --- | --- |
| `loxone:read` | freigegebene Struktur und Zustände lesen | an |
| `loxone:history` | freigegebene Historie/Statistik lesen | später/optional |
| `loxone:control` | einzelne freigegebene Steuerungen bedienen | aus |
| `loxberry:read` | freigegebene LoxBerry-/Plugin-Diagnose lesen | aus |
| `loxberry:operate` | eng begrenzte LoxBerry-Aktionen | nicht im MVP |

Ein Loxone-Benutzer allein kann `loxberry:*` nicht erteilen. Diese Scopes
benötigen eine zusätzliche lokale Freigabe durch den LoxBerry-Administrator und
eine Allowlist für Loxone-Benutzer beziehungsweise MCP-Clients.

### Mehrschichtige Begrenzung

Ein Aufruf wird nur ausgeführt, wenn alle Ebenen zustimmen:

1. gültiges, audience-gebundenes MCP-Token
2. erforderlicher Scope
3. Tool im Plugin aktiviert
4. Benutzer/Client in der lokalen Policy erlaubt
5. Ziel im vom Miniserver gelieferten Benutzermodell sichtbar
6. Aktion für den erkannten Control-Typ zulässig
7. Eingabewerte im erlaubten Bereich
8. Rate Limit und Parallelitätsgrenze nicht überschritten

Clientseitige Toolfilter und MCP-Annotationen sind zusätzliche Hinweise, keine
Autorisierung.

## 9. Loxone-Datenmodell

### Struktur

Der Adapter lädt die benutzerspezifische Loxone-Struktur und normalisiert:

- Räume
- Kategorien
- Controls und Subcontrols
- Control-Typ
- Action-UUID und State-UUIDs
- lesbare Namen
- vom Typ unterstützte Fähigkeiten

Die rohe Strukturdatei wird nicht vollständig an das Modell ausgegeben.
Benutzer-, Programm-, Verdrahtungs- und andere für die Bedienung unnötige Daten
werden nicht exponiert.

### Zustände

Aktuelle Zustände werden bevorzugt über eine authentifizierte
WebSocket-Verbindung bezogen. Der Cache ist:

- pro Loxone-Benutzer getrennt
- im RAM
- mit Zeitstempel und Frischekennzeichnung versehen
- größenbegrenzt
- nach Reconnect zunächst unvollständig, bis Snapshot oder Events vorliegen

Antworten unterscheiden `current`, `stale`, `unknown` und `unavailable`, statt
fehlende Werte als `0` oder `false` zu interpretieren.

### Namen und Identitäten

Suchtools akzeptieren Namen, Räume und Kategorien. Schreibtools verwenden die
zuvor aufgelöste UUID. Bei mehreren Treffern wird eine Kandidatenliste
zurückgegeben; der Server wählt nie willkürlich den ersten Treffer.

### Control Registry

Jeder unterstützte Control-Typ definiert:

- lesbare Zustände und Einheiten
- erlaubte Actions
- erforderliche Parameter und Wertebereiche
- Zuordnung zum konkreten Loxone-Kommando
- Read-/Write-, Destructive- und Idempotenz-Metadaten
- Tests und bestätigte Miniserver-Versionen

Nicht bekannte Typen bleiben lesbar, sofern ihre Zustände sicher darstellbar
sind. Sie erhalten keine generische Schreibmöglichkeit.

## 10. MCP-Tool-Inventar

### MVP: Loxone lesen

| Tool | Zweck |
| --- | --- |
| `loxone_get_system_status` | Erreichbarkeit, Version, Verbindung und Cachefrische |
| `loxone_list_rooms` | sichtbare Räume mit expliziter Raumgruppenreferenz, paginiert |
| `loxone_list_categories` | sichtbare Kategorien, paginiert |
| `loxone_find_controls` | Suche/Filter nach Name, Raum, Kategorie und Typ |
| `loxone_describe_control` | Fähigkeiten, erlaubte Actions sowie State- und Darstellungsmetadaten |
| `loxone_get_control_notes` | begrenzte, nicht vertrauenswürdige Hinweise eines sichtbaren Controls |
| `loxone_get_states` | aktuelle Zustände einer begrenzten UUID-Liste |

Diese Tools erhalten `readOnlyHint: true`, `destructiveHint: false` und passende
Ausgabeschemas.

### MVP: Loxone bedienen

Nach erfolgreicher Read-only-Phase folgt genau ein semantisch begrenztes Tool:

`loxone_operate_control`

- Ziel ausschließlich per UUID
- Action als Enum aus der Control Registry
- typisierte Parameter statt freiem String
- optionaler erwarteter Vorzustand gegen verlorene Updates
- strukturierte Rückgabe von angenommenem Befehl und beobachtetem Nachzustand
- kein automatischer Retry, wenn Idempotenz nicht sicher ist

Bulk-Aktionen nach Raum, Kategorie oder „alle“ bleiben außerhalb des MVP. Eine
spätere Erweiterung benötigt Vorschau, maximale Zielanzahl und explizite
Bestätigung.

### Loxone-Historie

`loxone_get_statistics` folgt nach einem eigenen Spike zu API-Versionen,
Zeitzonen, Aggregation und Antwortgrößen. Rohhistorien werden zeitlich und
mengenmäßig begrenzt; serverseitige Aggregation wird bevorzugt.

### MVP: LoxBerry lesen

| Tool | Zweck |
| --- | --- |
| `loxberry_get_system_status` | Version, Uptime, CPU-/Speicher-/Datenträgerstatus in sicherem Umfang |
| `loxberry_get_plugin_status` | Zustand und Version dieses MCP-Plugins |
| `loxberry_get_service_health` | nur explizit freigegebene plugin-eigene Dienste |

Keine vollständigen Prozesslisten, Netzwerkdetails, Umgebungsvariablen,
Konfigurationsdateien oder Logs werden ungefiltert ausgegeben.

### Später: LoxBerry bedienen

Erste mögliche Aktion ist der Neustart ausschließlich des plugin-eigenen
MCP-Dienstes. Reboot, Shutdown, Paketverwaltung, fremde Dienste und beliebige
Kommandos bleiben gesperrt, bis ein eigener Sicherheits- und
Wiederherstellungsentwurf akzeptiert wurde.

## 11. Tool-Ergebnisse und Fehler

Jedes Ergebnis enthält, soweit sinnvoll:

- `ok`
- `data`
- `warnings`
- `observed_at` in UTC/ISO 8601
- `stale`
- `trace_id`

Fehler unterscheiden mindestens:

- `invalid_input`
- `unauthenticated`
- `permission_denied`
- `not_found`
- `ambiguous_target`
- `unsupported_control`
- `conflict`
- `rate_limited`
- `loxone_unreachable`
- `timeout`
- `temporarily_unavailable`
- `internal_error`

Interne Pfade, Stacktraces, Tokens und Passwörter erscheinen nicht im
MCP-Ergebnis.

## 12. Konfiguration und Dateien

### Normale Konfiguration

Vorgesehene Bereiche:

```text
schema_version
server.local_base_url
server.external_base_url
server.allowed_origins
loxone.host_or_serial
loxone.connection_timeout
tools.loxone_read_enabled
tools.loxone_control_enabled
tools.loxberry_read_enabled
policy.allowed_loxberry_users
limits.requests_per_minute
limits.max_parallel_calls
audit.retention_days
```

### Phase-0-Dienstvariablen

Der ausführbare Phase-0-Dienst liest die folgenden internen Variablen. Sie werden
später aus der validierten Plugin-Konfiguration in die systemd-Umgebung erzeugt
und sind kein Ersatz für die Admin-UI:

| Variable | Default | Vertrag |
| --- | --- | --- |
| `MCPSERVER_HOST` | `127.0.0.1` | ausschließlich exakt dieser Loopback-Host |
| `MCPSERVER_PORT` | `8765` | ausschließlich exakt dieser interne Port; Dienst und Apache teilen diesen Vertrag |
| `MCPSERVER_ALLOWED_HOSTS` | `127.0.0.1:<Port>,localhost:<Port>` | kommaseparierte exakte Host-/Port-Werte oder ein Host mit `:*`; mindestens ein Eintrag |
| `MCPSERVER_ALLOWED_ORIGINS` | leer | kommaseparierte kanonische `http`-/`https`-Origins ohne Pfad, Zugangsdaten, Query oder Fragment; Standardports und Unicode-Hostnamen werden nicht als alternative Schreibweise akzeptiert |
| `MCPSERVER_PUBLIC_ORIGIN` | leer | kanonische lokale HTTPS-Origin; aktiviert zusammen mit den beiden folgenden Werten den Phase-0-OAuth-Spike |
| `MCPSERVER_AUTH_STORE` | leer | absoluter injizierter Pfad einer JSON-Datei; Phase 1 setzt dafür `LBPDATADIR/auth/sessions.json` ein |
| `MCPSERVER_LOXONE_ENDPOINT` | leer | kanonischer privater Gen.-1-HTTP-Origin ohne Zugangsdaten oder Pfad |

Für einen später erzeugten lokalen Apache-Vertrag lautet ein schematisches
Beispiel:

```text
MCPSERVER_HOST=127.0.0.1
MCPSERVER_PORT=8765
MCPSERVER_ALLOWED_HOSTS=127.0.0.1:8765,loxberry.local
MCPSERVER_ALLOWED_ORIGINS=https://loxberry.local
MCPSERVER_PUBLIC_ORIGIN=https://loxberry.local
MCPSERVER_AUTH_STORE=/absolute/private/test/path/sessions.json
MCPSERVER_LOXONE_ENDPOINT=http://PRIVATE-IP
```

Origins mit internationalisierten Domains werden in der vom Browser gesendeten
IDNA-ASCII-Schreibweise eingetragen, beispielsweise
`https://xn--bcher-kva.example`. Zugangsdaten, Tokens oder Sessionwerte gehören
in keine dieser Variablen.

Der interne Loopback-Port `8765` ist nicht benutzerkonfigurierbar. Eine Änderung
erfordert eine synchronisierte Migration beider Komponenten.

### Secrets und Sessions

- getrennt von normaler Konfiguration
- Eigentümer `loxberry`, Modus höchstens `0600`
- atomare Schreibvorgänge
- Signing-/Encryption-Key bei Installation kryptografisch erzeugt
- Refresh Tokens serverseitig nur gehasht, soweit das Verfahren dies erlaubt
- Codes, Access Tokens und Refresh Tokens ausschließlich als SHA-256-Digests
- Rotation mit familienweitem Widerruf bei Refresh-Token-Replay
- keine Secrets in Backups/Diagnosen ohne ausdrückliche, dokumentierte Regel
- Widerruf einzelner Clients und aller Sessions über die Admin-UI

Konfigurationsänderungen werden vollständig validiert und atomar aktiviert. Ein
Fehler erhält die letzte gültige Laufzeitkonfiguration.

## 13. LoxBerry-Integration

### Paketstruktur

Das Plugin folgt dem V4-Layout mit mindestens:

```text
plugin.cfg
release.cfg
prerelease.cfg
bin/
config/
templates/
templates/lang/
webfrontend/htmlauth/
install-/upgrade-/uninstall-hooks
```

Architekturabhängige Binaries werden reproduzierbar gebaut und eindeutig
ausgewählt. Plugin-Identität und Ordnername werden vor dem ersten Paket
festgelegt und danach nicht geändert.

Die dauerhafte Plugin-Identität lautet:

```ini
[PLUGIN]
NAME=mcpserver
FOLDER=mcpserver
TITLE=LoxBerry MCP Server
```

Code ermittelt weiterhin den tatsächlich von LoxBerry vergebenen Ordner, da
bei einer Namenskollision ein numerischer Suffix ergänzt werden kann.

### Dienst

- eigener systemd-Dienst oder nachweislich gleichwertiger nativer
  LoxBerry-Dienstmechanismus
- läuft als `loxberry`, nicht als Root
- restriktive `UMask`
- Loopback-Bindung
- automatischer Start nur bei gültiger, aktivierter Konfiguration
- Health-Check und begrenztes Restart-Verhalten
- Root-Hooks installieren nur Unit, Proxy-Regel und erforderliche Rechte

Für privilegierte spätere Aktionen wird kein breites `sudo systemctl *` oder
Shellrecht vergeben. Falls nötig, erhält jede erlaubte Operation einen eigenen,
argumentlosen oder streng validierenden Helper.

### Weboberfläche

Die LoxBerry-authentifizierte Admin-UI bietet:

- Einrichtungsassistent und Miniserver-Verbindungstest
- lokalen und externen MCP-Endpunkt mit Erreichbarkeitsstatus
- Read-/Write-Toolsets und LoxBerry-Scope-Policy
- registrierte Clients/Sessions und Widerruf
- Dienststatus, Version und letzte Fehler
- Audit-Ansicht ohne Geheimnisse
- Links zu deutscher und englischer Anleitung

Desktop und Mobile besitzen denselben Funktionsumfang gemäß
[Implementierungsrichtlinien](implementation-guidelines.md).

## 14. Logging und Audit

Technische Logs nutzen die LoxBerry-Logverwaltung und enthalten Komponente,
Schweregrad und Trace-ID. Wiederholte Verbindungsfehler werden gedrosselt.

Das getrennte Audit erfasst für schreibende oder abgewiesene Aufrufe:

- UTC-Zeit
- MCP-Client-ID
- pseudonymisierte oder angemessen dargestellte Benutzeridentität
- Tool und Ziel-UUID
- Action, nicht-sensitive Parameter und Ergebnis
- Trace-ID

Aktuelle Raumzustände, Passwörter, Tokens und vollständige Tool-Payloads werden
nicht pauschal protokolliert. Aufbewahrung und Löschung sind konfigurierbar und
begrenzt.

## 15. Robustheit und Limits

- feste Maximalgröße für HTTP- und JSON-RPC-Nachrichten
- Pagination und Ergebnislimits
- Timeouts pro Loxone-Aufruf
- begrenzte Parallelität pro Benutzer und global
- Backoff mit Jitter bei Verbindungsfehlern
- Circuit Breaker bei wiederholtem Miniserver-Ausfall
- kein automatischer Retry nicht-idempotenter Schreibaktionen
- Graceful Shutdown und Abbruch laufender lesender Aufrufe
- atomare Konfiguration und Sessionpersistenz
- Statusantworten bleiben auch bei Miniserver-Ausfall verfügbar

## 16. Testkonzept

Zusätzlich zur allgemeinen [Teststrategie](test-strategy.md) sind folgende
Nachweise erforderlich:

### Automatisiert

- MCP-Conformance für unterstützte Protokollversionen
- JSON-Schemas und Tool-Annotationen
- OAuth-Discovery, PKCE, Audience, Ablauf, Refresh und Widerruf
- Scope- und Policy-Matrix einschließlich negativer Fälle
- Strukturparser mit anonymisierten Gen.-1-/Gen.-2-Fixtures
- Control Registry und Wertebereiche
- Namensmehrdeutigkeit und UUID-Validierung
- Redirect-, Origin-, Path- und Injection-Angriffe
- Secret-Maskierung und Auditfelder
- Reconnect, Timeout, Backoff und nicht-idempotente Fehlerpfade
- Konfigurationsmigrationen und atomare Aktivierung

### Reale Systeme

- Miniserver Gen. 1 wird auf dem verfügbaren eigenen Zielsystem geprüft
- Miniserver Gen. 2 wird mangels eigener Hardware ausschließlich durch
  freiwillige Dritte in einer öffentlichen Beta geprüft
- eingeschränkter Loxone-Testbenutzer: unsichtbare Controls bleiben unsichtbar
- erlaubte und verbotene Schreibaktionen
- WebSocket-Zustand und Reconnect
- LoxBerry-Installation, Upgrade, Deinstallation und Dienstrechte
- Apache-Proxy mit Streamable HTTP und OAuth-Discovery
- ausgewählte lokale und cloudbasierte MCP-Clients
- Desktop-/Mobile-Admin-UI nach der risikobasierten Viewport-Matrix

Reale Zugangsdaten und Strukturdateien werden nicht in Fixtures oder CI
übernommen.

### Öffentliche Gen.-2-Beta

Die öffentliche Beta ist ein eigener, reproduzierbarer Testkanal und kein
Ersatz für automatisierte Tests. Sie beginnt read-only. Betatester erhalten:

- ein eindeutig versioniertes Pre-Release-Paket mit Prüfsumme
- eine kurze Installations-, Rücksetz- und Deinstallationsanleitung
- einen Testplan für Anmeldung, Rechtefilterung, Struktur, Zustände und Reconnect
- eine Liste der für die Beta vorgesehenen MCP-Clients; über alle Berichte
  sollen mindestens zwei unterschiedliche Clients abgedeckt werden
- die Vorgabe, einen dedizierten Loxone-Benutzer mit Minimalrechten zu verwenden
- einen lokalen Diagnoseexport, der Secrets, interne Adressen, Namen und
  Strukturinhalte standardmäßig maskiert
- ein öffentliches GitHub-Issue-Formular für strukturierte Ergebnisse

Ein Beta-Bericht nennt mindestens LoxBerry-Version, CPU-Architektur,
Miniserver-Generation und -Firmware, Pluginversion, MCP-Client/-Version,
ausgeführte Testfälle und Ergebnis. Passwörter, Tokens, komplette
Strukturdateien und unmaskierte Logs werden weder angefordert noch veröffentlicht.

Gen.-2-Schreibtests folgen erst nach erfolgreicher Read-only-Beta. Sie sind
separat opt-in, verwenden unkritische Teststeuerungen und dokumentieren
Ausgangszustand, erwartete Aktion, Ergebnis und Wiederherstellung. Das Projekt
greift nicht ohne separate ausdrückliche Zustimmung remote auf Systeme von
Betatestern zu.

Die Support-Matrix unterscheidet:

- `maintainer-tested`: selbst auf vorhandener Hardware geprüft
- `community-confirmed`: mindestens ein vollständiger, nachvollziehbarer
  Beta-Bericht eines unabhängigen Dritten
- `experimental`: implementiert, aber ohne ausreichenden realen Nachweis
- `unsupported`: nicht angeboten oder bekanntermaßen inkompatibel

Ohne erfolgreichen Gen.-2-Betabericht wird Gen. 2 nicht als bestätigt
unterstützt bezeichnet. Ein Release kann dann Gen. 1 unterstützen und Gen. 2
weiterhin als experimentell ausweisen.

## 17. Umsetzungsphasen

### Phase 0: Architektur-Spikes

**Status:** abgeschlossen am 2026-08-03. Die bestätigten Kombinationen und
bekannten Clientgrenzen stehen in der [Support-Matrix](support-matrix.md).

- Python-Version, venv und Wheels auf allen Zielarchitekturen
- kleiner Go-Vergleichsbuild nur, falls Wheels oder Ressourcenbudget kritisch
  sind
- MCP Streamable HTTP hinter Apache
- OAuth-End-to-End mit zwei Clients
- Loxone-Tokenauth und Rechtefilterung auf Gen. 1
- WebSocket-Snapshot-/Delta-Verhalten
- Ressourcenverbrauch

**Ergebnis:** bestätigte oder korrigierte Technologieentscheidung und
Support-Matrix.

### Phase 1: Read-only Alpha

- Pluginlayout, Dienst und Admin-UI-Grundgerüst
- OAuth und Sessionwiderruf
- OAuth-Store-Lifecycle mit harten Gesamt-/Pro-Client-Grenzen, administrativer
  Wiederherstellung und belastbarer Größenüberwachung
- feinere, installationsweite Quoten für erfolgreiche Autorisierungen und
  langfristige DCR-Bereinigung
- Struktur, Suche, Beschreibung und Zustände
- nur `loxone:read`
- lokale/LAN-Nutzung
- deterministische Tests und CI
- versioniertes öffentliches Gen.-2-Betapaket samt Testplan und maskiertem
  Diagnoseexport

### Phase 2: Kontrollierte Loxone-Schreibaktionen

- ausschließlich eng dokumentierte Aktionen für Gen.-1-`Switch`, `Dimmer`,
  `LightController`, `LightControllerV2` und `Jalousie` gemäß ADR 0005
- `loxone_operate_control` mit UUID-Ziel und beobachteter Zustandsbestätigung
- kompaktes Audit im bestehenden Service-Log und separates Control-Rate-Limit
- explizite Aktivierung und neuer OAuth-Consent für `loxone:control`
- kein externer MCP-Betrieb und keine Gen.-2-Schreibfreigabe

### Phase 3: LoxBerry Read-only

- separater `loxberry:read`-Freigabefluss
- sichere System- und Plugin-Diagnose
- keine fremden Logs oder Konfigurationsinhalte

### Phase 4: Erweiterungen

- `loxone:history` für sichtbare StatisticV2-Reihen und begrenzte Control-Historie
- weitere eng typisierte Control-Verträge gemäß ADR 0007
- `loxberry:operate` ausschließlich zum Löschen des plugin-eigenen Statistik-Caches
- mehrere Miniserver erst in Phase 5 oder später; Bedingungen und Topologien sind
  in [Multiple Miniserver support](multi-miniserver.md) festgehalten

## 18. Abnahmekriterien für den ersten öffentlichen Test

- Installation und Upgrade über den normalen LoxBerry Plugin Manager
- Dienst läuft ohne Root und ausschließlich auf Loopback
- MCP-Conformance und CI erfolgreich
- OAuth funktioniert mit mindestens zwei dokumentierten Clients
- Loxone-Rechtefilterung ist mit eingeschränktem Benutzer real bestätigt
- keine Write-Tools ohne Scope und explizite Aktivierung
- keine freien Kommandopfade oder LoxBerry-Shell
- Secrets fehlen in Logs, HTML, Prozessargumenten und Diagnoseexport
- lokaler Endpunkt und Sessionwiderruf sind verständlich dokumentiert
- Admin-UI funktioniert auf Desktop und Mobile
- Support-Matrix nennt nur tatsächlich geprüfte Kombinationen
- Gen. 2 ist bis zu einem vollständigen unabhängigen Betanachweis ausdrücklich
  als `experimental` gekennzeichnet
- erster Test auf LoxBerry 4, Debian 13 und `arm64`
- Gen. 1 mindestens Firmware `17.1.7.27`; ältere Versionen sind unbestätigt
- externer MCP-Zugriff ist nicht konfigurierbar

## 19. Entscheidungen vor dem ersten ausführbaren Commit

| Nr. | Thema | Entscheidung/Status |
| --- | --- | --- |
| 1 | Plugin-ID und Ordner | festgelegt: `NAME=mcpserver`, `FOLDER=mcpserver`, `TITLE=LoxBerry MCP Server` |
| 2 | erste CPU-Architektur | festgelegt: LoxBerry 4 auf Debian 13, `arm64` |
| 3 | Runtime | festgelegt: Python 3.13 und MCP-SDK 1.28.1; Wheel-, Start- und RAM-Gates erfolgreich |
| 4 | öffentlicher Pluginpfad/Apache | exakte MCP-, OAuth- und Well-known-Pfade mit Apache 2.4.68 real bestätigt |
| 5 | MCP-OAuth-Clientregistrierung und Sessionpersistenz | implementiert und automatisiert bestätigt: öffentliche Registrierung, PKCE S256, audience-gebundene opaque Tokens, Replay-Widerruf und atomare dateibasierte Persistenz; Claude Desktop vollständig real bestätigt; Codex Login und authentifizierter Aufruf bestätigt, Refresh und Revoke als dokumentierte Client-Limitierungen akzeptiert |
| 6 | Miniserver-Firmware | Gen. 1 mindestens `17.1.7.27`; Gen.-2-Stände werden durch die öffentliche Beta bestätigt |
| 7 | erste unterstützte Control-Typen | festgelegt für Phase 2: `Switch`, `Dimmer`, `LightController`, `LightControllerV2` und `Jalousie` mit den engen Aktionen aus ADR 0005 |
| 8 | Zeitpunkt und Umfang von `loxberry:read` | festgelegt: erst Phase 3 mit eigener lokaler Freigabe |
| 9 | externer HTTPS-Zugriff im ersten Test | festgelegt: nicht enthalten, erster Test nur lokal/LAN |

Offene Punkte bleiben bewusst sichtbar und werden nicht durch zufällige
Implementierungsdetails vorweggenommen.

Die zusammenhängenden Architekturentscheidungen und ihre Evidenz stehen in
[ADR 0001](adr/0001-phase-0-foundation.md).
