# LoxBerry MCP Server 0.4.0-alpha.2

## Voraussetzungen

- LoxBerry 4.0.0 oder neuer; Referenzsystem ist 4.0.0.14 auf Debian 13/arm64.
- Ein eigener Loxone-Benutzer mit möglichst kleinen Lese- und, falls benötigt,
  gezielt vergebenen Rechten für die unterstützten Controls.
- Gen. 1: private lokale HTTP-Adresse. Gen. 2: gültige HTTPS-Adresse mit
  vertrauenswürdigem Zertifikat; derzeit experimentell.
- Keine Zugangsdaten in URLs. Basic Auth wird nicht unterstützt.

## Installation und Einrichtung

Installiere das ZIP über den normalen LoxBerry Plugin Manager. Das Paket bringt
alle Python-Wheels offline mit. Öffne danach **LoxBerry MCP Server**:

1. Trage die lokale HTTPS-Origin des LoxBerry ein, z. B.
   `https://loxberry.local`.
2. Wähle einen der in LoxBerry konfigurierten Miniserver. Alternativ kannst du
   „Endpunkt manuell eingeben“ wählen; nur dann wird das Feld für den
   kanonischen Endpunkt angezeigt. Gen. 1 verwendet beispielsweise
   `http://192.168.1.20`, Gen. 2 ausschließlich `https://miniserver.example`.
   Die Auswahl übernimmt keine in LoxBerry gespeicherten Zugangsdaten.
3. Prüfe die Verbindung, aktiviere den Dienst und speichere.
4. Verbinde Codex CLI oder Claude Desktop mit
   `https://loxberry.local/plugins/mcpserver/mcp` und folge dem OAuth-Login.

Die Hilfe der Plugin-Oberfläche zeigt die vollständige MCP-Adresse einmal mit
dem aktuellen LoxBerry-Hostnamen und einmal mit der lokalen IP-Adresse. Beide
lassen sich direkt kopieren. Die Hostname-Adresse ist die empfohlene Variante,
weil manche MCP-Clients eine private IP-Adresse nicht als OAuth-Server
akzeptieren. In jedem Fall muss das Webserver-Zertifikat genau zu der verwendeten
Adresse passen.

Für Claude Desktop steht eine kurze
[Schritt-für-Schritt-Anleitung](clients/claude-desktop.de.md) mit fertigem
Konfigurationsbeispiel und Fehlerhilfe bereit.

Für die ChatGPT-/Codex-Desktop-App beschreibt die
[direkte Streamable-HTTP-Einrichtung](clients/chatgpt-codex-desktop.de.md) das
Hinzufügen per URL, die Browser-Authentifizierung und die angeforderten Lese-
beziehungsweise Schreibrechte. Dafür wird keine lokale Node.js-Bridge benötigt.

Die Admin-Oberfläche zeigt die globale Funktionsfreigabe nach Zielsystem
gruppiert. Die Checkboxen vergeben keine OAuth-Berechtigung, sondern erlauben
die Funktion grundsätzlich. Der Client muss den angegebenen Scope zusätzlich
bei der Anmeldung anfordern und der Benutzer muss ihn bestätigen.

| Aktiv | Konfigurationsoption | Scope | Wirkung/Beschreibung |
| --- | --- | --- | --- |
| immer | Loxone-Lesezugriff | `loxone:read` | Freigegebene Struktur und aktuelle Zustände lesen |
| optional | Historie und Statistiken | `loxone:history` | Historische Werte und Statistikdaten lesen |
| optional | Miniserver steuern | `loxone:control` | Unterstützte sichtbare Loxone-Bausteine gezielt bedienen |
| optional | LoxBerry-Diagnose | `loxberry:read` | System- und Plugin-Diagnosen lesen; lokale Freigabe erforderlich |
| optional | Statistik-Cache verwalten | `loxberry:operate` | Plugin-eigenen Statistik-Cache löschen; benötigt `loxone:history` und lokale Freigabe |

Beim Deaktivieren einer optionalen Funktion werden passende Sitzungen
widerrufen; reine Lesesitzungen bleiben gültig. Bei einem Gen.-2-/HTTPS-Ziel
kann **Miniserver steuern** nicht aktiviert werden.

**LoxBerry-Diagnose über MCP** ist standardmäßig deaktiviert. Ein Client kann
`loxberry:read` trotzdem zusammen mit `loxone:read` und optionalen weiteren
Berechtigungen anfordern. Bis ein Administrator die Funktion global aktiviert
und die ausstehende
Diagnoseanfrage freigibt, enthält die Sitzung den bestätigten Scope, aber die
Diagnosewerkzeuge antworten weiter mit `permission_denied`.
Die Freigabe ist exakt an OAuth-Client, Loxone-Identität und Miniserver gebunden.
Nach der Freigabe funktionieren sie in derselben Verbindung. Die drei Diagnosen sind nur lesend,
starten oder reparieren nichts, zeigen keine Logs und lesen keine beliebigen
Dateien. Der Entzug beendet passende Sitzungen.

**Loxone-Historie und Statistiken** ist ebenfalls standardmäßig deaktiviert.
`loxone:history` darf bereits vorher angefordert und bestätigt werden; die
Historienwerkzeuge antworten bis zur globalen Aktivierung mit
`permission_denied`. **Statistik-Cache verwalten** ist davon getrennt, verlangt
`loxberry:operate` zusammen mit `loxone:history` und zusätzlich dieselbe lokale
Administratorfreigabe wie die Diagnose. Seine einzige Aktion löscht den
plugin-eigenen Statistik-Cache. Beim Deaktivieren werden passende Sitzungen
widerrufen.

## Agent Skill

Der Server liefert den Agent Skill
[`using-loxberry-mcp`](../src/mcpserver/skills/using-loxberry-mcp/SKILL.md)
direkt über MCP aus. Er beschreibt den sicheren Ablauf für Suche, Pagination,
Zustandsabfragen, mehrdeutige Namen und ausdrücklich angeforderte
Control-Aktionen. Die maschinenlesbaren JSON-Schemas bleiben Bestandteil der
MCP-Tools und werden im Skill nicht dupliziert.

Beim Verbindungsaufbau weist der Server den Client in seinen MCP-Instructions
auf `skill://using-loxberry-mcp/SKILL.md` hin. Ressourcenfähige Clients können
die Anleitung dann bei Bedarf laden. Für Clients, die MCP-Ressourcen nicht
verwenden, steht dasselbe Dokument über das immer lesende Tool
`loxone_get_skill_guide` bereit. Das ist automatische Bereitstellung und
Erkennung, aber keine stille Installation oder dauerhafte Prompt-Injektion auf
dem Client.

Eine lokale Installation ist optional. Sie ermöglicht Codex, Claude Code und
anderen Agent-Skills-kompatiblen Clients die native, implizite Aktivierung anhand
der Skill-Beschreibung, auch bevor eine MCP-Verbindung besteht:

```bash
npx skills add Miraculix2050/LoxBerry-Plugin-MCP-Server --skill using-loxberry-mcp
```

Alternativ kopiere den Ordner `using-loxberry-mcp` nach
`~/.agents/skills/using-loxberry-mcp` für Codex oder nach
`~/.claude/skills/using-loxberry-mcp` für Claude Code. In Claude Desktop und
Claude.ai kann derselbe Skill-Ordner als ZIP unter **Customize > Skills**
hochgeladen werden. Nach lokaler Installation wählt der Client den Skill bei
passenden LoxBerry-/Loxone-Anfragen automatisch aus; mit `$using-loxberry-mcp`
kann er ausdrücklich aktiviert werden.

Der einheitliche OAuth-Dialog zeigt den erforderlichen Lesezugriff und, falls
vom Client angefordert und im Plugin aktiviert, die optionale
Loxone-Steuerung als separate Auswahl. Ohne ausgewählte Steuerung wird nur
`loxone:read` freigegeben. Nach der Bestätigung übergibt der LoxBerry an den
registrierten Callback des MCP-Clients. Die dort angezeigte Abschlussmeldung
stammt vom Client, beispielsweise von Claude Code, und nicht vom Plugin.

Unter **Clients und Sitzungen** stehen der vom Client angegebene Anwendungsname
und eine kurze Client-Instanzkennung. So lassen sich beispielsweise Codex,
Claude und der MCP Tool Explorer sowie mehrere Registrierungen derselben
Anwendung unterscheiden. Der Anwendungsname ist eine reine Anzeigeangabe des
Clients; für die technische Zuordnung und Autorisierung bleibt die Client-ID
maßgeblich.

Die lokalen Freigaben werden darunter nach `loxberry:read` und
`loxberry:operate` getrennt angezeigt. Aktive Bindungen zeigen dieselbe
Anwendung, Client-Instanz und gekürzte Loxone-Identität wie die zugehörige
Sitzung. Die Bindungs-ID ist ein kurzer pseudonymer Fingerprint und macht die
Freigabe eindeutig zuordenbar. Eine Bindung selbst läuft nicht ab. Ohne aktive Sitzung bleibt sie als
Fingerprint-Zeile widerrufbar; dabei werden keine zusätzlichen Klartextdaten
gespeichert.

Claude-Benutzer finden die dafür notwendige Scope-Konfiguration im Abschnitt
[Optionale Loxone-Steuerung](clients/claude-desktop.de.md#optionale-loxone-steuerung).

Speichern, Verbindungstest und Sitzungswiderruf funktionieren auch ohne
JavaScript. Mit JavaScript werden Status, Test und Widerruf ohne Seitenwechsel
aktualisiert.

## Webserver-Zertifikat

Die Zertifikatsdiagnose liest ausschließlich das systemweite HTTPS-Zertifikat
des LoxBerry. Sie zeigt Aussteller, Ablauf, Anzahl der DNS- und IP-SANs sowie die
Prüfergebnisse für die konfigurierte MCP-Origin und den aktuellen
LoxBerry-Hostnamen. Die einzelnen SAN-Namen und privaten Adressen werden nicht
in Diagnoseexport oder Logs übernommen.

Ist das Zertifikat von der lokalen LoxBerry-CA ausgestellt und der installierte
Core unterstützt die benötigten Skripte, kann es über **Webserver-Zertifikat neu
ausstellen** erneuert werden. Die Aktion benötigt den SecurePIN und eine
zusätzliche Bestätigung. Sie übergibt keine frei wählbaren SANs, sondern lässt
den LoxBerry-Core das Zertifikat mit aktuellem Hostnamen, Reverse-DNS-Namen,
lokaler IP und den vorgesehenen Loopback-Einträgen neu erzeugen. Die bestehende
LoxBerry-CA bleibt erhalten; das bereits importierte `cacert.cer` bleibt deshalb
gültig. Apache wird kurz neu gestartet und bestehende HTTPS-Verbindungen werden
unterbrochen.

Für ein extern ausgestelltes Zertifikat bleibt die Aktion deaktiviert. Ein
Fehler oder Erfolg wird ohne SecurePIN, private Schlüssel oder SAN-Werte im
LoxBerry-Systemlog protokolliert. Die automatische Core-Prüfung erneuert ein
Zertifikat bei Ablauf oder geänderter lokaler IP, erkennt eine reine
Hostnamenänderung derzeit jedoch nicht; dafür ist die manuelle Neuausstellung
vorgesehen.

## MCP Tool Explorer

Über **MCP Tool Explorer öffnen** startet eine separate, nur administrativ
zugängliche Browserseite für den lokalen MCP-Endpunkt. Sie meldet sich wie jeder
andere MCP-Client mit einem Loxone-Benutzer an und übernimmt keine Rechte aus der
LoxBerry-Admin-Sitzung.

Nach der Anmeldung zeigt der Explorer die aktuell veröffentlichten Tools samt
Beschreibung, Schema und Read-/Write-Kennzeichnung. Argumente können entweder
als automatisch erzeugtes Formular oder als synchronisiertes JSON bearbeitet
werden. Antworten erscheinen als auswählbarer Baum und als Roh-JSON; ausgewählte
Werte lassen sich nur in schemakompatible Parameter eines neuen Aufrufs übernehmen.
Eine einzelne State-UUID wird bei der Übernahme in `loxone_get_states`
automatisch als Liste mit einem Eintrag eingesetzt.

Listen liefern höchstens die mit `limit` angeforderte Anzahl von Einträgen. Ein
nicht leerer `next_cursor` zeigt eine weitere Seite an. **Nächste Seite abrufen**
ruft sie mit denselben Filtern und demselben Limit direkt ab. Alternativ wird
`next_cursor` bei **Wert übernehmen** bevorzugt dem Feld `cursor` desselben Tools
zugeordnet; auch dabei bleiben die bisherigen Argumente erhalten. Der Cursor ist
ein nicht zu bearbeitender Fortsetzungswert und gilt nur für dasselbe Tool mit
denselben Filtern. Der Filter `control_type` vergleicht den vollständigen
Loxone-Typ ohne Beachtung der Groß-/Kleinschreibung, beispielsweise `Switch` oder
`switch`. Mit den optionalen Checkboxen `has_statistics` und `has_history`
liefert `loxone_find_controls` nur Controls mit sichtbaren StatisticV2- oder klassischen Statistikreihen
beziehungsweise Control-Historie. Sind beide aktiviert, muss ein Control beide
Fähigkeiten anbieten.
Cursor für Control-Historie und Statistik verwenden signierte Fortsetzungsanker mit
stabilen Vorkommensnummern. Dadurch bleiben Seiten auch bei gleichen Zeitstempeln
oder identischen History-Einträgen vollständig.

Der MCP-Transkriptbereich zeigt bereinigte JSON-RPC-Nachrichten, Status und Dauer.
Authorization-Header, OAuth-Werte und als geheim erkannte Argumente werden nicht
angezeigt. Access-Token, Entwürfe, Ergebnisse und der auf 50 Aufrufe begrenzte
Verlauf bleiben nur im Speicher des Tabs. Das Refresh-Token wird im
`sessionStorage` desselben Tabs gehalten, damit ein Neuladen die Anmeldung
wiederherstellen und das Token sofort rotieren kann. Eine Browser-Tab-Sperre
verhindert die automatische Wiederverwendung in einem duplizierten Tab. Andere
Seiten derselben LoxBerry-Admin-Origin sind keine Sicherheitsgrenze und müssen
aus vertrauenswürdigen Plugins stammen. Beim Schließen des Tabs
verwirft der Browser diesen lokalen Wert normalerweise, kann die Serversitzung
aber nicht zuverlässig sofort widerrufen. Explorer-Sitzungen laufen deshalb
spätestens nach acht Stunden ab. **Trennen und widerrufen** beendet sie sofort
und bleibt vor dem Schließen der zuverlässige Abmeldeweg.
Auch die öffentliche OAuth-Clientregistrierung ist auf den Tab und höchstens
acht Stunden begrenzt; veraltete Registrierungen früherer Plugin-Versionen
werden automatisch verworfen und neu angelegt.

Der Explorer fordert beim Start automatisch alle Berechtigungen an, die der
installierte Server anbietet. Die einzige sichtbare Auswahl erfolgt anschließend
im OAuth-Berechtigungsdialog nach der Anmeldung mit dem Loxone-Benutzer:
**Nur lesen** ist verpflichtend; Historie, Loxone-Steuerung,
LoxBerry-Diagnose und LoxBerry-Operate sind optionale Checkboxen. Operate kann
nur zusammen mit Historie bestätigt werden. Eine noch nicht administrativ
aktivierte oder lokal freigegebene Berechtigung darf bereits bestätigt werden;
das betroffene Werkzeug antwortet bis zur Freigabe mit `permission_denied`.
Jeder verändernde Aufruf zeigt direkt vor dem Senden noch einmal Werkzeug und
Argumente und muss bestätigt werden.
Der Link auf der Plugin-Hauptseite verwendet dieselbe Adresse, über die auch die
Plugin-Seite geöffnet wurde. Sowohl über die lokale IP-Adresse als auch über den
LoxBerry-Hostnamen verwendet der gesamte Explorer-Ablauf genau diese aktuelle
HTTPS-Adresse. Nur HTTP und nicht lokal
freigegebene Hosts bleiben geschlossen und bieten einen Link zur konfigurierten
HTTPS-Adresse an.

**Trennen und widerrufen** beendet die Explorer-Sitzung; nach einem Browserabsturz
oder Schließen ohne Widerruf kann sie weiterhin in **Clients und Sitzungen**
widerrufen werden.

Im Tool Explorer gruppiert die Liste die Werkzeuge nach Scope in
`loxone:read`, `loxone:history`, `loxone:control`, `loxberry:read` und
`loxberry:operate`; innerhalb jeder Gruppe folgt sie dem üblichen Ablauf. Jeder Werkzeugentwurf
bleibt nur im aktuellen Browser-Tab erhalten. Der Verlauf zeigt ein früheres
Ergebnis, ohne den aktuellen Entwurf zu ersetzen; **Aufruf als Entwurf laden**
ist die ausdrücklich bestätigte Wiederherstellung. Unter **Aus Verlauf** zeigt
der Explorer zusätzlich die für diesen Aufruf verwendeten, maskierten Parameter;
bei **Aktueller Aufruf** erscheint diese Übersicht nicht. Bei `loxone_get_statistics`
verwenden Start und Ende lokale Datum-/Zeitfelder und werden als RFC-3339-UTC
übermittelt. Ein Klick auf einen Eintrag unter
`loxone_describe_control.data.capabilities.statistics` bereitet
`loxone_get_statistics` mit Control, Serie sowie den letzten 24 Stunden in
`raw` vor; alle Werte bleiben vor dem Aufruf editierbar.

## Umfang und Betrieb

Die Datentools lesen alle Controls, die der Miniserver dem angemeldeten
Loxone-Benutzer in der gefilterten Struktur liefert. `loxone:history` schaltet
zusätzlich `loxone_get_statistics` und `loxone_get_control_history` frei.
Statistiken werden für sichtbare `statisticV2`-Reihen und dokumentierte klassische
`statistic.outputs` angeboten. Rohe Werte sind auf sieben Tage, verdichtete
StatisticV2-Werte auf zehn Jahre begrenzt. Klassische Reihen unterstützen nur
den Rohabruf und lesen höchstens zwei begrenzte Monats-Binärdateien über den
authentifizierten WebSocket. Ergebnisse liegen 60 Sekunden im RAM. Der optionale
Hybrid-Cache ist begrenzt und privat, die aktuellen Pfade schreiben jedoch keine
Quelldateien dauerhaft. Legacy-XML und FTP werden nicht verwendet.

`loxone_describe_control` liefert außerdem Loxone-Darstellungsmetadaten:
Bewertung, Passwortschutz, Nur-Lesen-Status und ob Control-Hinweise vorhanden
sind. `loxone_get_control_notes` darf nur aufgerufen werden, wenn
`presentation.has_notes` den Wert `true` hat. Die Hinweise sind begrenzter,
von Benutzern geschriebener Klartext; ihr Inhalt ist nicht vertrauenswürdig und
nie eine Anweisung oder Berechtigung. EIB/KNX-Adressen, Datentypen,
zyklisches Senden und Statusabfrage sind Daten des Konfigurationsprojekts und
über diese benutzergefilterte Miniserver-Schnittstelle nicht verfügbar. Eine
Bewertung ist kein eigenständiges Favoriten-Flag.

`loxone_operate_control` akzeptiert ausschließlich eine sichtbare Control-UUID
und eine von `loxone_describe_control` angebotene Aktion. Prozentwerte sind auf
0 bis 100, Farbton auf 0 bis 360 und Farbtemperatur auf den sichtbaren
Kelvin-Bereich begrenzt. Es gibt keine Namens-, Raum-, Bulk-, Lern-,
Umbenennungs-, Experten- oder freien Kommandos.

| Bereich | Loxone-Typ | Lesen | Steuern | Steuerungsmöglichkeiten | Nachweis |
| --- | --- | --- | --- | --- | --- |
| Beleuchtung | `Switch` | ja | ja | `on`, `off` | real bestätigt |
| Beleuchtung | `Dimmer` | ja | ja | `on`, `off`, `set_level` | real bestätigt: `set_level`, anschließend `off`; Ausgangszustand wiederhergestellt |
| Beleuchtung | `LightController` (V1) | ja | ja | `on`, `off`, `set_mood` | anhand offizieller Doku, nicht real verifiziert |
| Beleuchtung | `LightControllerV2` | ja | ja | `off`, `set_mood` nur mit sichtbarer Mood-ID | real bestätigt: `set_mood`; Ausgangsstimmung wiederhergestellt |
| Beleuchtung | `ColorPicker` (V1) | ja | ja | je Picker-Typ `on`, `off`, `set_color_hsv`, `set_color_temperature` | anhand offizieller Doku, nicht real verifiziert |
| Beleuchtung | `ColorPickerV2` | ja | ja | je Picker-Typ `set_color_hsv`, `set_color_temperature` | Lesen real bestätigt; Write nicht real bestätigt, weil der Picker keine direkte Testzuordnung besitzt |
| Beleuchtung | `LightsceneRGB` | ja | ja | `on`, `off`, `set_scene` nur mit sichtbarer Szenen-ID | Befehl real akzeptiert: `on`, `off`; Wirkung nicht über Feedback bestätigt |
| Beleuchtung | `Pushbutton` | ja | ja | `pulse` | Befehl real akzeptiert; Wirkung nicht über Feedback bestätigt |
| Beleuchtung | `Radio` | ja | ja | `select_output`; `reset` nur bei sichtbarem `allOff` | Befehl real akzeptiert: `reset`; `select_output` nicht real bestätigt |
| Beleuchtung | `TimedSwitch` | ja | ja | `on`, `off`, `pulse` | real bestätigt: `on`, `off`; Ausgangszustand wiederhergestellt; `pulse` Vertrag getestet |
| Beschattung | `Jalousie` | ja | ja | `open`, `close`, `shade`, `stop`, Position/Lamellen; Auto nur falls angeboten | Befehl real akzeptiert: `stop`; Wirkung nicht über Feedback bestätigt |
| Beschattung | `CentralJalousie` | ja | nein | – | Lesen real bestätigt |
| Klima/Lüftung | `IRoomControllerV2`, `IRCV2Daytimer`, `Ventilation`, `Daytimer` | ja | nein | – | in eigener Installation lesend prüfbar |
| Klima/Lüftung | `ClimateControllerUS` | ja | nein | – | Lesen real bestätigt |
| Klima/Lüftung | entsprechende V1-Typen, sofern vom Miniserver sichtbar | ja | nein | – | generischer Lesepfad, nicht real verifiziert |
| Sensorik/Status | `InfoOnlyAnalog`, `InfoOnlyDigital`, `InfoOnlyText`, `TextState`, `StatusMonitor`, `WindowMonitor`, `SmokeAlarm`, `Tracker` | ja | nein | – | in eigener Installation lesend prüfbar |
| Energie/sonstige | `Meter`, `EFM`, `PvProductionForecast`, `Slider`, `Webpage` | ja | nein | – | in eigener Installation lesend prüfbar |

„Lesen“ umfasst nur sichtbare Struktur und Zustände. Historie ist zusätzlich nur
verfügbar, wenn das Control `hasHistory`, `statisticV2` beziehungsweise `statistic` meldet und
der Client `loxone:history` erhalten hat. V1-Typen bleiben bewusst als **nicht
verifiziert** markiert, bis ein realer Abnahmetest vorliegt.

`loxberry:operate` verwendet denselben lokalen, an Client, Loxone-Identität und
Miniserver gebundenen Freigabemechanismus wie `loxberry:read`. Die einzige
Operate-Funktion ist `loxberry_clear_statistics_cache`; sie löscht ausschließlich
plugin-eigene Cache-Einträge und schreibt einen kompakten Audit-Eintrag. Basic
Auth bleibt ausgeschlossen. Ergebnisse und Aktionen entsprechen den Rechten des
angemeldeten Loxone-Benutzers. Es wird genau ein Miniserver unterstützt.

Der englische Healthcheck führt keine Reparatur aus:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Der LoxBerry-Selbsttest zeigt die Beschreibung **MCP-Server-Verfügbarkeit und
lokale Daten** und fasst die einzelnen, rein lesenden Prüfungen verständlich im
Ergebnis zusammen: Dienst aktiv, lokaler Health-Endpunkt erreichbar,
Konfiguration lesbar sowie OAuth-Datenverzeichnis vorhanden und beschreibbar.
Ein Fehler wird rot dargestellt und nennt die fehlgeschlagene Prüfung; der
Selbsttest nimmt keine Reparatur vor.

Das Dienstlog kann direkt aus der Statuskarte oder als Liste der aktiven Datei
und vorhandenen Backups im Unterabschnitt **Dienst-Log (service.log)** im
LoxBerry-Logviewer geöffnet werden. Es ist auf die aktive Datei und zwei
Rotationen mit jeweils 512 KiB,
also insgesamt ungefähr 1,5 MB, begrenzt. Einzelne Einträge sind auf 8 KiB
begrenzt. Unter **Diagnose und Logs** kann der ausschließlich für `service.log`
geltende Level dauerhaft auf **Aus**, **Fehler**, **Warnungen**,
**Informationen** oder **Debug** gestellt werden; voreingestellt sind
**Warnungen**. Normale HTTP-Zugriffe werden auch bei Debug nicht als Access-Log
geschrieben. Sicherheits-Audits für Steueraktionen bleiben selbst bei **Aus**
aktiv. Die Oberfläche fasst diese Einstellung im Unterabschnitt
**Dienst-Log (service.log)** zusammen.

Der darunter angezeigte native LoxBerry-Log-Level steuert getrennt davon
`admin-ui.log` und weitere Plugin-Logs. `admin-ui.log` wird nur bei relevanten
administrativen Aktionen oder Fehlern erweitert und erzeugt keine Datei pro
Seitenaufruf oder Aktion. Auch dieses Log ist auf die aktive Datei und zwei
Backups mit jeweils 512 KiB begrenzt. Diese Einstellungen stehen getrennt im
Unterabschnitt **Plugin-Logs (LoxBerry LogManager)**.

Der Diagnoseexport enthält nur Version,
Dienststatus, Transportart und maskierte Zähler. Sitzungen können einzeln oder
gemeinsam widerrufen werden; ein erreichbarer Miniserver erhält zusätzlich
best effort `killtoken`.

Die Statuskarte der Adminseite aktualisiert Zustand und PID automatisch. Bei
inaktivem Dienst steht **Starten** bereit; bei aktivem Dienst stehen **Stoppen**
und **Neu starten** bereit. Stoppen und Neustarten müssen bestätigt werden und
unterbrechen aktive MCP-Verbindungen. Diese Aktionen ändern weder die gespeicherte
Plugin-Konfiguration noch den systemd-Autostart. Sie steuern ausschließlich die
feste Unit `loxberry-mcpserver.service`.

Die Dienststeuerung ist eine administrative LoxBerry-Funktion und verleiht weder
Loxone- noch MCP-Berechtigungen. Die sudoers-Datei erlaubt dem Benutzer
`loxberry` ausschließlich die vollständigen `systemctl start`, `systemctl stop`
und `systemctl restart`-Befehle für diese feste Unit; freie Unterbefehle,
Argumente oder andere Units sind nicht erlaubt. Aktion und Ergebnis werden ohne
rohe `systemctl`-Ausgabe in der fortlaufenden `admin-ui.log` protokolliert.

Jeder Schreibversuch erzeugt einen kompakten maskierten Eintrag im bestehenden
Service-Log. Wiederholte identische Ablehnungen werden gedrosselt; eine separate
Auditdatei wird nicht angelegt.

## Rücksetzen

Stoppe zuerst den Dienst in der UI. Bei einer fehlerhaften Vorabversion
kann das vorherige Plugin-ZIP über den Plugin Manager erneut installiert
werden. Konfiguration, Sitzungen, verschlüsselte Loxone-Tokens und der lokale
Installationsschlüssel bleiben beim Upgrade gemeinsam erhalten, sodass eine
gültige Sitzung anschließend ohne erneute Anmeldung weiterverwendet werden
kann. Eine Deinstallation entfernt Dienst, Apache-Regel und die enge
sudoers-Regel nur, wenn sie eindeutig dem Plugin gehören.
