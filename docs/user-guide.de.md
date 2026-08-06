# LoxBerry MCP Server 0.2.0-alpha.1

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

Die sechs lesenden Loxone-Datentools und das lesende Skill-Guide-Tool bleiben
standardmäßig aktiv. Wähle unter **Zugriff auf den Miniserver über den MCP
Server** die Option **Lesen und schalten**, um zusätzlich unterstützte
Gen.-1-Controls bedienen zu können. Danach ist eine neue OAuth-Freigabe mit `loxone:control`
erforderlich. Beim Zurückwechseln auf **Nur lesen** werden bestehende
Control-Sitzungen widerrufen; reine Lesesitzungen bleiben gültig. Bei einem
Gen.-2-/HTTPS-Ziel kann **Lesen und schalten** nicht aktiviert werden.

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
`switch`.

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

Im Berechtigungs-Dropdown ist **Nur lesen** vorausgewählt. **Lesen und steuern**
ist nur bei global aktivierter Loxone-Steuerung auswählbar und erfordert
einen neuen Consent mit `loxone:control`. Jeder verändernde Aufruf zeigt direkt
vor dem Senden noch einmal Werkzeug und Argumente und muss bestätigt werden.
Der Link auf der Plugin-Hauptseite verwendet dieselbe Adresse, über die auch die
Plugin-Seite geöffnet wurde. Sowohl über die lokale IP-Adresse als auch über den
LoxBerry-Hostnamen verwendet der gesamte Explorer-Ablauf genau diese aktuelle
HTTPS-Adresse. Nur HTTP und nicht lokal
freigegebene Hosts bleiben geschlossen und bieten einen Link zur konfigurierten
HTTPS-Adresse an.

**Trennen und widerrufen** beendet die Explorer-Sitzung; nach einem Browserabsturz
oder Schließen ohne Widerruf kann sie weiterhin in **Clients und Sitzungen**
widerrufen werden.

## Umfang und Betrieb

Die Alpha veröffentlicht sechs dokumentierte Loxone-Datentools, das lesende
`loxone_get_skill_guide` und optional `loxone_operate_control`. Das Schreibtool
akzeptiert ausschließlich eine sichtbare Control-UUID und eine von
`loxone_describe_control` ausdrücklich angebotene Aktion. Unterstützt werden
`Switch`, `Dimmer`, `LightController`, `LightControllerV2` und `Jalousie`;
Automatikaktionen einer Jalousie werden nur bei `details.isAutomatic=true`
angeboten. Prozentwerte sind auf 0 bis 100 begrenzt, Lichtstimmungen auf
dokumentierte Szenen- beziehungsweise die aktuell sichtbaren numerischen
`moodList`-IDs. Es gibt keine Namens-, Raum-,
Bulk- oder freien Kommandos und keine Lern-, Umbenennungs- oder Expertenbefehle.
Historie, LoxBerry-Tools und
Basic Auth bleiben ausgeschlossen. Ergebnisse und Aktionen entsprechen den
Rechten des angemeldeten Loxone-Benutzers.

Der englische Healthcheck führt keine Reparatur aus:

```bash
LBPCONFIG=/actual/config/path LBPDATA=/actual/data/path /actual/bin/healthcheck
```

Logs erscheinen im LoxBerry-Logviewer. Der Diagnoseexport enthält nur Version,
Dienststatus, Transportart und maskierte Zähler. Sitzungen können einzeln oder
gemeinsam widerrufen werden; ein erreichbarer Miniserver erhält zusätzlich
best effort `killtoken`.

Jeder Schreibversuch erzeugt einen kompakten maskierten Eintrag im bestehenden
Service-Log. Wiederholte identische Ablehnungen werden gedrosselt; eine separate
Auditdatei wird nicht angelegt.

## Rücksetzen

Deaktiviere zuerst den Dienst in der UI. Bei einer fehlerhaften Vorabversion
kann das vorherige Plugin-ZIP über den Plugin Manager erneut installiert
werden. Konfiguration, Sitzungen, verschlüsselte Loxone-Tokens und der lokale
Installationsschlüssel bleiben beim Upgrade gemeinsam erhalten, sodass eine
gültige Sitzung anschließend ohne erneute Anmeldung weiterverwendet werden
kann. Eine Deinstallation entfernt Dienst, Apache-Regel und die enge
sudoers-Regel nur, wenn sie eindeutig dem Plugin gehören.
