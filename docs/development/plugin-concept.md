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

Bevorzugt wird ein eigenständiger Python-Dienst, sofern der Runtime-Spike die
Support-Matrix bestätigt:

- Python 3.10 oder neuer
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
reproduzierbaren Abhängigkeitssatz. Auf Debian 12 verhindert dies zugleich
Konflikte mit PEP 668. Für jede unterstützte Architektur müssen vorgebaute
Wheels vorhanden oder im Paket mitgeliefert sein; die normale Installation
darf weder Compiler noch Rust-Toolchain benötigen.

Diese Empfehlung bedeutet zunächst auch: LoxBerry-/Debian-Kombinationen mit
Python 3.9 sind nicht automatisch unterstützt. Soll insbesondere Debian 11 zur
ersten Support-Matrix gehören, werden drei Optionen im Spike verglichen:

1. Support-Basis auf Systeme mit Python 3.10 oder neuer begrenzen,
2. eine plugin-eigene Python-Runtime sicher und wartbar mitliefern oder
3. den Kerndienst als statisches Go-Binary bauen.

Go ist damit die dokumentierte Rückfalloption. Das offizielle Go-SDK ist
ebenfalls Tier 1; ein einzelnes Binary reduziert Installations- und
Abhängigkeitsrisiken, kostet aber mehr Implementierungsaufwand.

Vor der Festlegung beweist ein Spike:

- Python-Version und venv-Erstellung auf allen ausgewählten LoxBerry-Basen
- Installation aller fixierten Abhängigkeiten ausschließlich aus verfügbaren
  oder mitgelieferten Wheels
- Paketgröße, Start sowie RAM- und CPU-Bedarf im Idle und bei Zustandsupdates
  auf den ausgewählten Architekturen
- Streamable HTTP/Origin-Prüfung hinter dem LoxBerry-Apache
- OAuth-Interoperabilität mit mindestens zwei relevanten Clients
- Loxone-Anmeldung, Rechtefilterung und WebSocket-Zustände auf Gen. 1 und Gen. 2

Falls Python an einer erforderlichen Altplattform, fehlenden ARM-Wheels oder dem
Ressourcenbudget scheitert, wird Go verwendet. TypeScript bleibt eine weitere,
aber nicht bevorzugte Alternative. Das zusätzliche Express-Server-Plugin soll
nicht zur Pflicht des MCP-Kerndienstes werden.

### Protokollversion

Der erste Release zielt auf die stabile MCP-Version `2025-11-25` und nutzt die
Versionsaushandlung des SDK. Eine noch nicht finale Protokollrevision darf
zusätzlich unterstützt werden, aber niemals die einzige kompatible Version
sein.

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
   └── Konfiguration, Scopes, Sessions, Status und Logs
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
| Admin-UI | lokale Konfiguration und Betriebsdiagnose über LoxBerry `htmlauth` |

## 7. Netzwerk und Veröffentlichung

Der Dienst lauscht ausschließlich auf `127.0.0.1` an einem konfigurierten,
konfliktgeprüften Port. Apache veröffentlicht den MCP-Endpunkt unter einem
Pluginpfad, beispielsweise:

```text
https://<loxberry>/plugins/mcpserver/mcp
```

Der genaue Pfad wird im Transport-Spike festgelegt. Er muss GET und POST sowie
die zugehörige OAuth-Discovery unterstützen. Reverse-Proxy-Header werden nur von
einem explizit vertrauten lokalen Proxy akzeptiert.

Für externe Nutzung gilt:

- ausschließlich HTTPS mit öffentlich vertrauenswürdigem Zertifikat
- explizit konfigurierte externe Basis-URL
- kein automatisches Öffnen von Routerports
- vollständige Weiterleitung von MCP- und `/.well-known`-Pfaden
- Host-/Origin-Allowlist und Schutz vor DNS Rebinding
- dokumentierter Verbindungscheck vor Freigabe

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

MCP-Tokens sind ausschließlich für das Plugin gültig. Sie werden nie an Loxone
oder andere Dienste weitergereicht.

### Plugin zum Miniserver

Im Autorisierungsablauf meldet sich der Benutzer mit einem dedizierten
Loxone-Konto am ausgewählten Miniserver an. Das Passwort wird nur zur Anmeldung
verwendet und nicht gespeichert. Nach erfolgreicher Anmeldung verwendet das
Plugin, soweit vom Miniserver unterstützt, ein erneuerbares Loxone-Token.

Zu prüfen ist, wie das Token auf den unterstützten Generationen sicher erneuert
und widerrufen wird. Bis dieser Nachweis vorliegt, ist eine erneute Anmeldung
nach Dienstneustart akzeptabler als persistente Passwortspeicherung.

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
| `loxone_list_rooms` | sichtbare Räume, paginiert |
| `loxone_list_categories` | sichtbare Kategorien, paginiert |
| `loxone_find_controls` | Suche/Filter nach Name, Raum, Kategorie und Typ |
| `loxone_describe_control` | Fähigkeiten, erlaubte Actions und State-Metadaten |
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
server.listen_port
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

### Secrets und Sessions

- getrennt von normaler Konfiguration
- Eigentümer `loxberry`, Modus höchstens `0600`
- atomare Schreibvorgänge
- Signing-/Encryption-Key bei Installation kryptografisch erzeugt
- Refresh Tokens serverseitig nur gehasht, soweit das Verfahren dies erlaubt
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

- mindestens ein bestätigter Miniserver Gen. 1 und Gen. 2
- eingeschränkter Loxone-Testbenutzer: unsichtbare Controls bleiben unsichtbar
- erlaubte und verbotene Schreibaktionen
- WebSocket-Zustand und Reconnect
- LoxBerry-Installation, Upgrade, Deinstallation und Dienstrechte
- Apache-Proxy mit Streamable HTTP und OAuth-Discovery
- ausgewählte lokale und cloudbasierte MCP-Clients
- Desktop-/Mobile-Admin-UI nach der risikobasierten Viewport-Matrix

Reale Zugangsdaten und Strukturdateien werden nicht in Fixtures oder CI
übernommen.

## 17. Umsetzungsphasen

### Phase 0: Architektur-Spikes

- Python-Version, venv und Wheels auf allen Zielarchitekturen
- kleiner Go-Vergleichsbuild, falls Altplattform oder Ressourcenbudget kritisch
  sind
- MCP Streamable HTTP hinter Apache
- OAuth-End-to-End mit zwei Clients
- Loxone-Tokenauth und Rechtefilterung Gen. 1/2
- WebSocket-Snapshot-/Delta-Verhalten
- Ressourcenverbrauch

**Ergebnis:** bestätigte oder korrigierte Technologieentscheidung und
Support-Matrix.

### Phase 1: Read-only Alpha

- Pluginlayout, Dienst und Admin-UI-Grundgerüst
- OAuth und Sessionwiderruf
- Struktur, Suche, Beschreibung und Zustände
- nur `loxone:read`
- lokale/LAN-Nutzung
- deterministische Tests und CI

### Phase 2: Kontrollierte Loxone-Schreibaktionen

- erste getestete Control-Typen
- `loxone_operate_control`
- Audit und Rate Limits
- explizite Aktivierung von `loxone:control`
- optionaler externer HTTPS-Betrieb nach Sicherheitstest

### Phase 3: LoxBerry Read-only

- separater `loxberry:read`-Freigabefluss
- sichere System- und Plugin-Diagnose
- keine fremden Logs oder Konfigurationsinhalte

### Phase 4: Erweiterungen

- Historie/Statistik
- weitere bestätigte Control-Typen
- eng begrenzte plugin-eigene LoxBerry-Aktion
- mehrere Miniserver nur bei nachgewiesenem Bedarf

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

## 19. Noch zu entscheidende Punkte

Vor der Implementierung benötigt das Review Entscheidungen zu:

1. endgültiger Plugin-ID und Installationsordner
2. erste LoxBerry-Versionen und CPU-Architekturen
3. verbindliche Python-/Go-Entscheidung nach dem Runtime- und Paketierungsspike
4. exakter öffentlicher Pluginpfad und Apache-Integration
5. OAuth-Clientregistrierung und Sessionpersistenz
6. Mindestfirmware für Miniserver Gen. 1 und Gen. 2
7. erste unterstützte Control-Typen
8. Zeitpunkt und konkreter Umfang von `loxberry:read`
9. ob externer HTTPS-Zugriff bereits im ersten öffentlichen Test enthalten ist

Diese Punkte sind absichtlich sichtbar offen. Sie werden nicht durch zufällige
Implementierungsdetails vorweggenommen.
