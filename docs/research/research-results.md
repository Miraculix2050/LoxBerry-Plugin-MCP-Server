# Recherche-Ergebnisse: Loxone und LoxBerry MCP-Server

- **Stand:** 2026-08-01
- **Zweck:** Technische und konzeptionelle Grundlage für das LoxBerry MCP-Server-Plugin
- **Methode:** bereitgestellte Notizen, aktuelle Original-Repositories sowie offizielle Loxone-, LoxBerry- und MCP-Dokumentation

## 1. Kurzfazit

Ein MCP-Server auf dem LoxBerry ist technisch sinnvoll und unterscheidet sich
klar vom nativen Loxone-MCP-Server:

- Er kann auch Installationen adressieren, in denen der native MCP-Server nicht
  verfügbar ist, insbesondere Miniserver Gen. 1.
- Er kann Loxone- und LoxBerry-Informationen in einem bewusst begrenzten Server
  zusammenführen.
- Er kann unabhängig vom rotierenden Loxone-Cloud-Relay eine stabile lokale oder
  eigene HTTPS-Adresse anbieten.
- Er muss dafür Authentifizierung, Autorisierung und Tool-Grenzen selbst
  wesentlich sorgfältiger gestalten als ein reiner lokaler CLI-Wrapper.

Die beste Ausgangsarchitektur ist ein eigenständiger, unprivilegierter Dienst
mit Streamable HTTP, einem typsicheren Loxone-Adapter, einer pro Benutzer
getrennten Struktur-/Zustandssicht und einem kleinen, standardmäßig lesenden
Tool-Inventar. Beliebige Miniserver-Kommandos, globale Raumaktionen und
allgemeiner Shellzugriff gehören nicht in die erste Version.

Als technische Basis wird für die erste Referenzplattform Python bevorzugt: Das
Projekt zielt zunächst auf LoxBerry 4 unter Debian 13 (Trixie) mit Python 3.13.
Der Dienst ist vor allem I/O-lastig, das offizielle MCP-Python-SDK ist Tier 1
und bringt Streamable HTTP, Schemas sowie die Resource-Server-Seite der
OAuth-Integration mit. Ein Zielsystem-, Transport-, Abhängigkeits- und
OAuth-Spike muss noch die verfügbaren Wheels und den Ressourcenbedarf auf den
konkret unterstützten Architekturen bestätigen. Go bleibt eine
Paketierungsalternative, ist aber für den MVP keine gleichrangige
Vorentscheidung mehr.

## 2. Quellenlage und Grenzen

Die bereitgestellten Dateien wurden vollständig ausgewertet:

- `Loxone eigener MCP-Server.md`
- `Projekte mit Loxone MCP-Server.md`
- `Loxberry Plugin Konzept.md`

Die Notizen zum nativen Loxone-MCP-Server beschreiben Funktionen und
Einrichtung detaillierter als die derzeit öffentlich auffindbaren Loxone-
Webseiten. Die öffentliche Einführung und der Changelog bestätigen den
MCP-Server ab Loxone Config/Miniserver 17.1, enthalten aber nicht alle in der
Notiz beschriebenen Tool- und OAuth-Details. Diese Details sind deshalb als
bereitgestellte Produktdokumentation, nicht als unabhängig reproduzierte
Implementierungserkenntnis gekennzeichnet.

Vergleichsprojekte entwickeln sich schnell. Aussagen in dieser Recherche
beziehen sich auf den am 2026-08-01 sichtbaren Default-Branch. README, ältere
Architekturdokumente und aktueller Quellbaum widersprechen sich teilweise; in
diesen Fällen wurde der aktuelle Quellbaum höher gewichtet.

## 3. Nativer Loxone-MCP-Server

Loxone führte den nativen MCP-Server mit Config/Miniserver 17.1 für den
Miniserver Gen. 2 ein. Der öffentliche Changelog nennt KI-Integration,
Wetterprognosen, Systemstatusaktionen und UTC-Zeitstempel. Für Gen. 1 steht
dieser Pluginpfad nach den bereitgestellten Unterlagen nicht zur Verfügung.

### Konzept

- Der MCP-Server läuft direkt auf dem Miniserver.
- Er übernimmt Räume, Kategorien, Steuerungen und deren Namen aus der laufenden
  Installation.
- Lesen und Bedienen erfolgt mit den Berechtigungen des angemeldeten
  Loxone-Benutzers.
- Lesende und schreibende Tools sind für Clients unterscheidbar.
- Struktur, aktuelle Zustände, Historie und Statistiken werden angeboten.
- Programmierung, Benutzerverwaltung, Expertenmodus und Automatik-Designer
  bleiben außerhalb des MCP-Servers.
- Lokale und externe MCP-Adressen sind möglich; Cloud-Clients benötigen eine
  öffentlich erreichbare HTTPS-Adresse auf Port 443.
- Die Anmeldung verwendet einen browserbasierten OAuth-Ablauf. Bei Reverse-
  Proxys müssen sowohl der MCP-Pfad als auch die zugehörigen `/.well-known`-
  Pfade erreichbar sein.

### Übertragbare Erkenntnisse

1. **Berechtigungen aus dem Zielsystem:** Der Miniserver sollte die tatsächlich
   sichtbaren und bedienbaren Elemente bestimmen. Eine zweite, selbst gepflegte
   Rechtekopie würde leicht auseinanderlaufen.
2. **Dedizierter Assistentenbenutzer:** Ein eigenes Loxone-Konto begrenzt die
   Folgen falsch verstandener Befehle und kann zentral deaktiviert werden.
3. **Read/Write-Trennung:** Tool-Metadaten und Scopes sollten lesende und
   schreibende Funktionen sichtbar trennen.
4. **Keine Neukonfiguration:** Der MCP-Server bedient die laufende Installation,
   ersetzt aber weder Loxone Config noch die Benutzerverwaltung.
5. **Standardkonforme Veröffentlichung:** OAuth-Discovery und MCP-Endpunkt
   müssen gemeinsam durch einen Reverse-Proxy geleitet werden.

### Unterschied zu unserem Plugin

Ein Loxone-Login kann nur Loxone-Rechte belegen. Er erteilt keine
administrativen Rechte auf dem LoxBerry. LoxBerry-Funktionen benötigen daher
eine eigene, explizite Autorisierung. Diese Grenze ist die wichtigste
zusätzliche Sicherheitsanforderung unseres Projekts.

## 4. Vergleichsprojekte

### 4.1 `reijosirila/loxone-mcp-server`

- **Technik:** TypeScript/Node.js, offizielles MCP-TypeScript-SDK, Express,
  `loxone-ts-api`
- **Transport:** stdio und Streamable HTTP
- **Loxone-Zugriff:** WebSocket für Ereignisse, `LoxApp3.json`/Strukturdatei,
  HTTP-Kommandos
- **MCP-Modell:** wenige generische Tools für Räume, Kategorien, Steuerungen,
  Einzelsteuerung und Statistik
- **HTTP-Schutz:** optionaler statischer API-Key; ohne Key ist der HTTP-Endpunkt
  offen
- **Lizenz:** AGPL-3.0

Positiv sind die klare Trennung in Connection-, State-, Control- und
Statistics-Services sowie eine Factory mit typspezifischen Steuerungsadaptern.
Die Struktur wird einmal geladen, Zustandsänderungen werden über WebSocket
eingepflegt und Reconnects verwenden begrenztes Backoff.

Für unser Plugin nicht ausreichend sind optionale Authentifizierung, fehlendes
HTTPS/WSS im verwendeten Loxone-Client und ein freies `command`-Feld im
Schreibtool. Außerdem ist AGPL-Code mit unserem Apache-2.0-Projekt nicht einfach
übernehmbar. Architekturideen dürfen untersucht werden; Quellcode wird nicht
kopiert.

Quelle: [Repository](https://github.com/reijosirila/loxone-mcp-server),
[Tool-Definitionen](https://github.com/reijosirila/loxone-mcp-server/blob/main/src/tools/loxone.ts),
[Connection Manager](https://github.com/reijosirila/loxone-mcp-server/blob/main/src/tools/loxone-system/services/ConnectionManager.ts)

### 4.2 `avrabe/mcp-loxone`

- **Technik:** asynchrones Rust, PulseEngine-MCP-Framework, optional zahlreiche
  Speicher-, Monitoring-, Discovery- und Sicherheitsmodule
- **Transport:** stdio, HTTP/SSE und Streamable HTTP
- **Modell:** schreibende Tools und zahlreiche lesende MCP-Ressourcen
- **Sicherheit:** Validierung, Rate Limits, TLS, Credential Registry und
  verschiedene Authentifizierungswege
- **Tests:** umfangreiche Unit-, Integrations-, Protokoll- und optionale
  Live-Miniserver-Tests
- **Lizenz:** wahlweise MIT oder Apache-2.0

Wertvoll sind die Trennung lesender Ressourcen von schreibenden Tools, strikte
UUID-/Eingabevalidierung, Request-Kontext, Rate Limiting, Circuit Breaker und
Mock-basierte Tests. Ein statisches Binary passt grundsätzlich gut zu einem
LoxBerry-Plugin.

Das Projekt ist für unseren Start deutlich zu groß. Default-Features ziehen
unter anderem Discovery, InfluxDB und Datenbanken ein. Einige
Architekturdokumente nennen Module oder Toolzahlen, die im aktuellen Quellbaum
nicht in dieser Form vorhanden sind. Deshalb eignet es sich als Ideensammlung,
nicht als Vorlage für einen Komplettimport.

Quelle: [Repository](https://github.com/avrabe/mcp-loxone),
[README](https://github.com/avrabe/mcp-loxone/blob/main/README.md),
[Cargo-Konfiguration](https://github.com/avrabe/mcp-loxone/blob/main/Cargo.toml)

### 4.3 `Smarteon/lox-mcp`

- **Technik:** Kotlin Multiplatform, Java 21/JAR sowie Linux-Builds,
  offizielles Kotlin-MCP-SDK und `loxone-client-kotlin`
- **Transport:** stdio und HTTP/SSE
- **Datenmodell:** semantisches Modell aus der Loxone-Strukturdatei plus
  WebSocket-Zustand
- **MCP-Modell:** wenige Schreibtools und viele hierarchische Ressourcen;
  Ressourcen können für Clients mit eingeschränktem Support als Tools
  gespiegelt werden
- **Konfiguration:** deklarative YAML-Definition der Tools und Ressourcen
- **Lizenz:** AGPL-3.0 oder separate kommerzielle Lizenz

Die deklarative Tool-Registry, hierarchische Ressourcen und die Option
„Resources as Tools“ sind gute Interoperabilitätsideen. Ebenso sinnvoll ist die
Trennung des Loxone-Adapters vom MCP-Server.

Nicht übernommen werden sollten `send_miniserver_command`, frei templatisierte
Kommandopfade, der vollständige Projekt-XML-Export oder globale Aktionen über
Räume/Kategorien in einer ersten Version. Diese Funktionen vergrößern
Angriffsfläche, Kontextmenge und mögliche Schadenswirkung erheblich. Java 21 ist
zudem für ein kleines LoxBerry-System eine unnötig schwere Mindestlaufzeit.

Quelle: [Repository](https://github.com/Smarteon/lox-mcp),
[Tool-Konfiguration](https://github.com/Smarteon/lox-mcp/blob/main/src/commonMain/resources/mcp-config.yaml),
[Loxone-Adapter](https://github.com/Smarteon/lox-mcp/blob/main/src/commonMain/kotlin/LoxoneAdapter.kt)

### 4.4 `discostu105/lox`

- **Technik:** statisches Rust-CLI ohne Laufzeitabhängigkeit
- **Ziel:** skript- und agentenfreundliche Loxone-Kommandozeile, kein MCP-Server
- **Datenzugriff:** Strukturcache, HTTP-Kommandos, WebSocket-Streaming,
  Tokenauthentifizierung und teilweise System-/Konfigurationszugriffe
- **Agentenfunktionen:** JSON-Ausgabe, Exitcodes, Dry-run, Trace-ID,
  nichtinteraktiver Modus, Schemas und verständliche Vorschläge bei mehrdeutigen
  Namen
- **Lizenz:** GPL-3.0-or-later und kommerzielle Lizenz; README-Badges waren zum
  Recherchezeitpunkt nicht vollständig konsistent mit Paketmetadaten/Lizenz

Für unser Tool-Design sind insbesondere strukturierte Fehler, Dry-run,
Korrelations-IDs, strikte UUID-Prüfung und die explizite Auflösung gleicher Namen
über Raum oder UUID wertvoll. Das Projekt blockiert außerdem Cross-Origin-
Redirects und maskiert Secrets in URLs.

Ein universelles Shell-Tool um das CLI herum wäre für unser Produkt trotzdem
ungeeignet: Es würde MCP-Schemas, Tool-Risiken und serverseitige Autorisierung
umgehen. Auch Konfigurationsdownload, Restore, FTP und allgemeine Systembefehle
gehören nicht in den MVP.

Quelle: [Repository](https://github.com/discostu105/lox),
[Agentenleitfaden](https://github.com/discostu105/lox/blob/main/docs/guides/ai-agents.md),
[Architektur](https://github.com/discostu105/lox/blob/main/docs/architecture.md)

### 4.5 `ivantichy/loxone-mcp-proxy`

- **Technik:** JavaScript auf Node.js 20, ohne externe Runtime-Abhängigkeiten
- **Ziel:** stabile stdio-Brücke zum nativen Loxone-MCP-Server
- **Aufgaben:** rotierendes Loxone-Relay auflösen, OAuth 2.1 mit PKCE
  nichtinteraktiv durchführen, Tokens erneuern und Sitzungen wiederherstellen
- **Sicherheit:** nur HTTPS-Redirects, dedizierter Benutzer, Token-Cache mit
  restriktiven Rechten, Logs auf stderr
- **Lizenz:** MIT

Das Projekt erklärt wichtige Eigenheiten des nativen Loxone-MCP-Pfads:
Relay-Adressen können wechseln, das OAuth-`resource` ist eine Audience und nicht
zwingend die tatsächlich erreichbare Adresse, und Verbindungs-/Tokenfehler
benötigen getrennte Wiederherstellung.

Unser LoxBerry-Dienst hat selbst eine stabile Adresse und benötigt den Proxy
nicht. Übertragbar sind jedoch HTTPS-only-Redirectvalidierung, rotierende
Refresh-Tokens, gecachte Discovery, begrenzte Wiederholungen und die strikte
Trennung von Protokollausgabe und Logs. Das automatisierte Absenden eines
HTML-Loginformulars ist empfindlich gegenüber Änderungen und sollte nicht die
primäre Architektur unseres Servers werden.

Quelle: [Repository](https://github.com/ivantichy/loxone-mcp-proxy),
[OAuth-Implementierung](https://github.com/ivantichy/loxone-mcp-proxy/blob/main/src/loxoneAuth.js),
[Resolver](https://github.com/ivantichy/loxone-mcp-proxy/blob/main/src/resolver.js)

## 5. LoxBerry-Plattform

Das aktuelle V4-Sample-Plugin bestätigt die maßgeblichen Paket- und
Lifecycle-Konventionen:

- `plugin.cfg`, `release.cfg` und `prerelease.cfg` liegen im Paket-Root.
- `AUTHOR.NAME`, `AUTHOR.EMAIL`, `PLUGIN.NAME` und `PLUGIN.FOLDER` werden nach
  dem ersten Release zu stabilen Update-Identitäten.
- `FOLDER` kann bei der Installation einen numerischen Suffix erhalten; Code
  darf den tatsächlichen Ordner nicht hardcodieren.
- Konfiguration, Daten, Logs, Binärdateien, Templates und Webfrontend verwenden
  die von LoxBerry bereitgestellten Pfade.
- Installationsschritte laufen teils als `loxberry`, Root-Hooks nur für eng
  begrenzte Systemarbeiten.
- Ein Boot-Daemon muss schnell zurückkehren und lang laufende Prozesse im
  Hintergrund beziehungsweise über einen Dienst starten.
- Die Weboberfläche soll das LoxBerry Design System, native Übersetzungen und
  LoxBerry-Logging nutzen.
- Plugin-Logs liegen in der LoxBerry-Logverwaltung; temporäre Logpfade können
  RAM-basiert und nach einem Neustart leer sein.

Die ältere Node.js-Anleitung setzt das zusätzliche Express-Server-Plugin voraus
und routet Pluginpfade über Port 3300. Diese Abhängigkeit ist für einen
sicherheitskritischen MCP-Kerndienst nicht ideal. Ein eigener, auf Loopback
gebundener Dienst hinter einem gezielten Apache-Reverse-Proxy ist konzeptionell
robuster; die konkrete Integration muss auf einem LoxBerry geprüft werden.

Quelle: [LoxBerry V4 Sample Plugin](https://github.com/mschlenstedt/LoxBerry-Plugin-SamplePlugin-V4),
[LoxBerry Entwicklerübersicht](https://wiki.loxberry.de/entwickler/start),
[Node.js Pluginentwicklung](https://wiki.loxberry.de/entwickler/node_js_plugin_entwicklung)

## 6. MCP-Anforderungen

Für HTTP-Server ist Streamable HTTP der aktuelle Standardtransport. Der Server
muss einen gemeinsamen GET-/POST-Endpunkt anbieten, den `Origin`-Header gegen
DNS-Rebinding prüfen und jede Verbindung authentifizieren. Die stabile
MCP-Spezifikation ist zum Recherchestand `2025-11-25`. Die Revision
`2026-07-28` wird im offiziellen Repository weiterhin als Release Candidate
geführt, obwohl ihre Finalisierung ursprünglich für den 28. Juli 2026 geplant
war. Sie verändert den Protokollkern grundlegend: stateless Requests ersetzen
den bisherigen Initialisierungs-/Session-Lifecycle, `server/discover` übernimmt
die Erkennung und Extensions werden stärker vom Kern getrennt.

Für das Plugin ist deshalb `2025-11-25` das richtige Produktionsziel. Der
stabile Python-SDK-Zweig v1 unterstützt diese Version; Python-SDK v2 ist zum
Recherchestand noch Alpha. `2026-07-28` sollte erst nach finaler Spezifikation,
stabilem Python-SDK, erfolgreicher Conformance-Suite und realen Clienttests
hinzukommen. Versionsaushandlung muss `2025-11-25` während einer dokumentierten
Übergangsphase erhalten.

Die Autorisierungsspezifikation verlangt für geschützte HTTP-Ressourcen OAuth-
Discovery über Protected Resource Metadata, OAuth 2.1, PKCE, Resource Indicators
und an die Server-Audience gebundene Tokens. Tokens für den MCP-Server dürfen
nicht als Token-Passthrough an den Miniserver weitergereicht werden.

Tool-Annotationen (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) helfen Clients bei der Risikodarstellung, sind aber keine
Sicherheitsgrenze. Autorisierung und Validierung müssen serverseitig erfolgen.

Das offizielle Python-SDK ist Tier 1, unterstützt Streamable HTTP, typisierte
Ausgabeschemas und die Einbindung eines OAuth-Token-Verifiers. Es setzt Python
3.10 oder neuer voraus. Seine stabile v1-Linie befindet sich zum
Recherchestand im Wartungsmodus, während v2 noch als Vorabversion geführt wird;
eine Implementierung muss deshalb die gewählte Hauptversion und alle
Abhängigkeiten explizit fixieren.

Python passt fachlich gut: MCP-, HTTP- und WebSocket-Verarbeitung sind in diesem
Plugin überwiegend I/O-lastig, nicht rechenintensiv. Es gibt auch keinen
technischen Konflikt mit den Perl-/PHP-Bestandteilen von LoxBerry, wenn der
Python-Dienst als eigener unprivilegierter Prozess läuft.

Als erste Referenzbasis wird LoxBerry 4 unter Debian 13 (Trixie) festgelegt.
Debian 13 liefert Python 3.13 und erfüllt damit die Anforderung des MCP-SDKs.
Plugin-Abhängigkeiten gehören wegen der Trennung vom verwalteten System-Python
trotzdem in ein eigenes virtuelles Environment. Zusätzlich müssen Wheels für
alle unterstützten Architekturen verfügbar sein; ein Compiler- oder Rust-Build
auf dem Zielgerät ist kein akzeptabler normaler Installationsweg.

Ältere LoxBerry-3-/Debian-11-Systeme liefern möglicherweise nur Python 3.9.
Ihre Unterstützung ist daher eine spätere, eigene Kompatibilitätsentscheidung
und blockiert den Python-basierten MVP auf LoxBerry 4 nicht.

Das offizielle Go-SDK ist ebenfalls Tier 1, unterstützt Streamable HTTP und
mehrere Protokollversionen. Ein statisches Go-Binary vereinfacht Installation,
Start und Architekturpaketierung, erhöht aber den Implementierungsaufwand und
bietet weniger dynamische Schema-Ergonomie. Das Rust-SDK ist Tier 2.

Quelle: [MCP-Transporte](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[MCP-Autorisierung](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization),
[MCP-SDKs](https://modelcontextprotocol.io/docs/sdk),
[MCP-Spezifikations-Releases](https://github.com/modelcontextprotocol/modelcontextprotocol/releases),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[MCP Go SDK](https://github.com/modelcontextprotocol/go-sdk),
[LoxBerry-Installation](https://wiki.loxberry.de/installation_von_loxberry/die_installation_von_loxberry/start),
[Debian-13-Versionshinweise](https://www.debian.org/releases/trixie/release-notes/whats-new.de.html)

## 7. Lizenzbewertung

| Projekt/Quelle | Lizenzlage | Konsequenz für dieses Apache-2.0-Projekt |
| --- | --- | --- |
| `reijosirila/loxone-mcp-server` | AGPL-3.0 | Konzepte analysieren, keinen Code übernehmen |
| `avrabe/mcp-loxone` | MIT oder Apache-2.0 | Codeübernahme prinzipiell möglich, aber nur gezielt mit Attribution und Herkunftsnachweis |
| `Smarteon/lox-mcp` | AGPL-3.0 oder kommerziell | Konzepte analysieren, keinen Code ohne passende Lizenz übernehmen |
| `discostu105/lox` | GPL-3.0-or-later und kommerziell | Konzepte analysieren, keinen Code übernehmen |
| `ivantichy/loxone-mcp-proxy` | MIT | gezielte Übernahme prinzipiell möglich, Attribution erforderlich |
| LoxBerry V4 Sample Plugin | keine erkannte Repository-Lizenz | Struktur als Dokumentation verwenden; Code nicht ungeprüft kopieren |
| LoxBerry Wiki | Seite nennt Public Domain, sofern nicht anders bezeichnet | Fakten und Konventionen nutzbar; Quelle weiterhin nennen |
| Loxone-Dokumentation | proprietäre Produktdokumentation | zusammenfassen und verlinken, keine umfangreiche Vervielfältigung |

Für später tatsächlich übernommenen Fremdcode werden Datei, Commit, Lizenz,
Änderungen und erforderliche Notices im Repository dokumentiert. Diese
Recherche selbst übernimmt keinen Fremdcode.

## 8. Empfohlene Muster

- ein kleiner, stabiler Tool-Katalog statt vieler überlappender Tools
- lesende Entdeckung vor jeder schreibenden Aktion
- UUID als Identität, Name/Raum/Kategorie nur zur Suche und Darstellung
- Fehler bei mehrdeutigen Namen statt willkürlicher Auswahl
- typspezifische Actions und Wertebereiche statt freier Befehlsstrings
- pro Benutzer getrennte Struktur-, Zustands- und Berechtigungscaches
- WebSocket für aktuelle Zustände, HTTP für Struktur und Befehle
- strukturierte Ergebnisse, Tool-Ausgabeschemas und Korrelations-ID
- optionale Vorschau für größere oder riskantere Aktionen
- kurze Timeouts, begrenzte Retries, Backoff und Circuit Breaker
- standardmäßig read-only, schreibende Tools separat aktivierbar
- MCP-Annotationen zusätzlich zu echter serverseitiger Autorisierung
- Mock-/Fixture-Tests plus wenige gezielte Tests am echten Miniserver
- isolierter, vollständig fixierter Python-Runtime-Stack oder statisches Binary

## 9. Nicht empfohlene Muster

- optional ungeschützter HTTP-Endpunkt
- ein allgemeines Shell-, URL-, Pfad- oder Raw-Command-Tool
- vollständiger Projekt-XML- oder Benutzerexport an das Sprachmodell
- globale Aktionen auf alle Geräte oder ganze Räume im MVP
- ein gemeinsamer Cache für Benutzer mit unterschiedlichen Loxone-Rechten
- Basic-Auth-Zugangsdaten in MCP-Client-Konfiguration oder Prozessargumenten
- Vertrauen auf Tool-Annotationen oder clientseitige Toolfilter als
  Sicherheitsgrenze
- ungeprüftes Folgen von Redirects oder fremden OAuth-Metadaten-URLs
- persistente Speicherung des Loxone-Passworts, wenn ein erneuerbares Token
  ausreicht
- Datenbank, Telemetrie, Dashboards oder Discovery ohne konkreten MVP-Bedarf
- Übernahme eines Gesamtprojekts mit inkompatibler Lizenz oder veralteten
  Dokumentationsannahmen

## 10. Offene Forschungsfragen

Folgende Punkte benötigen vor der Implementierung einen reproduzierbaren Spike
auf echten Zielsystemen:

1. Welche LoxBerry-4-/Debian-13-Architekturen soll das erste Release tatsächlich
   tragen?
2. Lassen sich alle fixierten Python-3.13-Abhängigkeiten ohne Kompilierung in
   ein plugin-eigenes venv installieren?
3. Wie wird Streamable HTTP einschließlich SSE durch den LoxBerry-Apache ohne
   Buffering- oder Timeoutprobleme weitergeleitet?
4. Filtert `LoxApp3.json` bei Gen. 1 und in unabhängigen öffentlichen
   Gen.-2-Betatests exakt nach dem angemeldeten Benutzer?
5. Welche Tokenauthentifizierung ist für Gen. 1 lokal und für Gen. 2 durch
   reproduzierbare Beta-Berichte bei den jeweiligen Firmwareständen bestätigt?
6. Welche OAuth-Clients müssen für den ersten Release interoperabel sein?
7. Wie werden LoxBerry-Scopes durch einen LoxBerry-Administrator erteilt und
   widerrufen, ohne Loxone- und LoxBerry-Rechte zu vermischen?
8. Bleiben Paketgröße, Startzeit und Speicherbedarf des Python-Prototyps auf der
   ältesten unterstützten LoxBerry-4-Hardware im festgelegten Budget?
9. Welche externen HTTPS-/Reverse-Proxy-Varianten können sicher unterstützt und
   real getestet werden?

Die vorgeschlagene Antwort auf diese Fragen und ein gestufter MVP stehen im
[Plugin-Konzept](../development/plugin-concept.md).
