# Support-Matrix

- **Stand:** Runtime-/Strukturhärtung, 2026-08-13
- **Vorbereiteter Pre-Release:** `0.4.0-alpha.8`
- **Nächster Meilenstein:** gezielte reale Abnahme der noch unbestätigten
  Phase-4-Aktionen und V1-Varianten

Diese Matrix unterscheidet reale Nachweise von implementierten, aber noch nicht
real bestätigten Kombinationen. Phase 1, Phase 2 und Phase 3 sind abgenommen;
`0.4.0-alpha.8` bleibt wegen seines Vorabversionsstatus ein Pre-Release.
Phase 4 ist implementiert und für die lesenden Statistik-/Historienpfade, die
eng begrenzte plugin-eigene Cache-Operation und ausgewählte, reversible
Control-Aktionen auf Hardware abgenommen; siehe
[Phase-4-Abnahmebericht](phase-4-acceptance.md).

Die versionsmarkerbasierte Strukturaktualisierung ist zudem für geänderten
Anzeigenamen, Control-Hinweis und Bewertung auf der autorisierten Testfixture
hardware-abgenommen. Die separate Favoriten-Markierung bleibt ungetestet; siehe
denselben Abnahmebericht.

## Plattformen und Geräte

| Komponente | Getesteter Stand | Status | Nachweis und Grenze |
| --- | --- | --- | --- |
| LoxBerry | `4.0.0.14`, Debian 13, `aarch64` | `maintainer-tested` | [Python-3.13-Runtime, Offline-Wheels, Apache-Transport und Ressourcenbudgets real bestätigt](phase-0-oauth-test.md#automatisierte-und-zielsystem-nachweise) |
| LoxBerry 3 und ältere Debian-Basen | nicht getestet | `unsupported` | nicht Teil des anfänglichen Umfangs |
| Miniserver Gen. 1 | Firmware `17.1.7.27` | `maintainer-tested` | [lokale HTTP-/WS-Anbindung, Command Encryption, JWT, Rechtefilterung, Snapshot, Delta und Reconnect real bestätigt](phase-0-loxone-test.md#runtime-nachweis-für-pr-1) |
| Miniserver Gen. 1 mit älterer Firmware | nicht getestet | `experimental` | keine Kompatibilitätszusage ohne passenden Nachweis |
| Miniserver Gen. 2/Compact | keine Maintainer-Hardware | `experimental` | HTTPS/WSS ohne Klartext-Fallback ist implementiert und automatisiert negativ prüfbar; reale Bestätigung erfordert den [vollständigen unabhängigen Betabericht](gen2-beta-test.md) |

`maintainer-tested` gilt nur für die exakt dokumentierte Kombination. Weitere
Architekturen, LoxBerry-Versionen und Firmwarestände werden nicht daraus
abgeleitet.

## MCP-Clients

| Client | Getesteter Stand | Ergebnis | Bekannte Grenze |
| --- | --- | --- | --- |
| Claude Desktop mit `mcp-remote` | Desktop `1.24012.9`, Bridge `0.1.38` | [Read-only-Ablauf sowie Registrierung, Consent, Werkzeugsichtbarkeit und realer Phase-2-Control-Aufruf bestätigt](phase-2-acceptance.md#vollständiger-control-client-ablauf) | lokale Bridge mit `http-only`; kein Nachweis für den cloudbasierten Connector |
| Codex CLI | `0.146.0` | [Login, MCP-Initialisierung und authentifizierter Aufruf erfolgreich](phase-0-oauth-test.md#reale-clientabnahme) | Refresh sendet keinen verpflichtenden RFC-8707-Parameter `resource`; Logout löscht nur lokale Credentials und ruft `/revoke` nicht auf |

Die Codex-Grenzen sind bestätigtes Clientverhalten und werden für den Abschluss
von Phase 0 ausdrücklich akzeptiert. Der Server lockert weder Audience-Bindung
noch Widerrufsregeln. Codex-Benutzer müssen sich nach Ablauf des Access Tokens
erneut anmelden; serverseitige Testsitzungen werden administrativ oder durch
ihren Ablauf beendet. Phase 1 dokumentiert den späteren operativen
Sessionwiderruf für reguläre Installationen.

## Phase-1-Paketnachweis

Der vollständige maskierte Nachweis steht im
[Phase-1-Abnahmebericht](phase-1-acceptance.md).

- Das Plugin wurde auf LoxBerry `4.0.0.14`, Debian 13/aarch64 über die native
  Plugin-Verwaltung installiert und aktualisiert; Offline-Venv, Icon,
  systemd-Start und Admin-UI waren erfolgreich.
- Der Dienst wurde als aktiv bestätigt. Der deaktivierte Defaultzustand lässt
  nur den Loopback-Healthcheck zu und beantwortet den veröffentlichten MCP-Pfad
  fail-safe mit HTTP 503.
- Die responsive deutsche und englische Admin-UI wurde bei `1280x800`,
  `900x768`, `390x844`, `360x800` und `320x568` ohne Seitenoverflow geprüft.
  AJAX-Status, Verbindungstest, Widerrufe und sichtbarer Tastaturfokus wurden
  ebenfalls real bestätigt.
- Das ZIP wurde zweimal byteidentisch gebaut und durch seine SHA-256-Prüfsumme
  abgesichert.
- Eine frische Claude-OAuth-Anmeldung mit ausschließlich `loxone:read`, exakt
  sechs Read-only-Tools, alle sechs realen Toolaufrufe und die reale
  Sichtbarkeitsgrenze wurden auf dem installierten Alpha-Paket bestätigt.
- Nach dem nativen Upgrade desselben finalen Artefakts blieb die Sitzung ohne
  Neuanmeldung nutzbar. Konfiguration, Sessions, verschlüsselte Tokens und der
  zugehörige Installationsschlüssel wurden gemeinsam erhalten.
- Native Formularaktionen und serverseitige POST/Redirect/GET-Abläufe für
  Speichern, Status, Verbindungstest, Widerruf und Diagnose bestätigten den
  funktionalen No-JavaScript-Fallback.

## Phase-2-Abnahmenachweis

Der vollständige maskierte Nachweis steht im
[Phase-2-Abnahmebericht](phase-2-acceptance.md).

- Ein ausdrücklich freigegebener, unkritischer Gen.-1-`Switch` wurde real mit
  `on` und `off` bedient; der Ausgangszustand wurde wiederhergestellt.
- Der vollständige Control-Client-Ablauf mit Registrierung, Consent für
  `loxone:read loxone:control`, Werkzeugsichtbarkeit und realem Aufruf wurde
  bestätigt.
- Steuerung bleibt standardmäßig deaktiviert und auf sichtbare, bedienbare
  Gen.-1-Controls vom Typ `Switch` sowie die Aktionen `on` und `off` begrenzt.

## Phase-3-Abnahmenachweis

Der vollständige maskierte Nachweis steht im
[Phase-3-Abnahmebericht](phase-3-acceptance.md).

- Die drei LoxBerry-Diagnosewerkzeuge sind standardmäßig deaktiviert und bleiben
  auf maskierte System-, Plugin- und Dienststatuswerte beschränkt.
- `loxberry:read` kann zusammen mit Loxone-Lesen und -Steuern angefordert
  werden; bis zur lokalen Adminfreigabe antworten die Diagnosewerkzeuge mit
  `permission_denied` und funktionieren danach in derselben OAuth-Verbindung.
- Die Admin-UI zeigt zu jeder pseudonymen Diagnosebindung den Client-Klarnamen
  und einen kurzen Verbindungsfingerprint; Freigabe und Entzug aktualisieren
  ohne Seitenreload.

## Verbleibende Grenzen

- Die globale JavaScript-Berechtigung von Chrome durfte die Browserautomation
  nicht verändern. Der funktionale Fallback ist real über native Formular- und
  PRG-Pfade sowie automatisierte Tests bestätigt.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
- Codex CLI wurde im finalen Abschlusslauf wegen der lokalen
  Windows-Ausführungsstörung nicht erneut abgenommen; der bekannte Clientfehler
  ist für den Server- und Claude-Nachweis nicht blockierend.
- `Dimmer` (`set_level`, `off`), `LightControllerV2` (`set_mood`) und
  `TimedSwitch` (`on`, `off`) sind an ausdrücklich freigegebenen, harmlosen
  Fixtures real bestätigt und jeweils in den Ausgangszustand zurückgeführt.
- `Jalousie`-`open`, `set_position` und `enable_auto` sind auf der ausdrücklich
  freigegebenen Rolladen-Fixture über ihre sichtbaren Rückmeldungen bestätigt.
  `close`, `shade`, `stop` und der erste `disable_auto`-Aufruf wurden nur
  akzeptiert; ein abschließendes `disable_auto` wurde bestätigt und stellte den
  ursprünglichen Automatikzustand wieder her. Lamellen- und Kombinationsaktionen
  werden für diesen Modus nicht angeboten. Die frühere kombinierte
  Positionsrückführung blieb unbestätigt; es wurde kein weiterer Befehl
  automatisch wiederholt.
  `LightsceneRGB` (`on`, `off`), `Radio` (`reset`) und `Pushbutton` (`pulse`)
  bleiben lediglich akzeptiert. Alle übrigen Aktionen bleiben entsprechend der
  User-Doku unverified.
- Die klassische Binärstatistik (`statistic.outputs`, Rohabruf), eine
  `StatisticV2`-Serie und die Control-Historie sind an sichtbaren Controls real
  lesend bestätigt. Die lokal freigegebene, ausschließlich plugin-eigene
  Cache-Leerung ist ebenfalls bestätigt. Ein `ColorPickerV2`-Subcontrol ohne
  eigene Raum-/Kategoriezuordnung ist über seinen beidseitig zugeordneten
  `LightControllerV2`-Parent real mit `set_color_hsv` bestätigt und in den
  Ausgangszustand zurückgeführt. `ColorPicker` (V1) und nicht ausgeführte
  Aktionen bleiben unverified. Control-Hinweise sind durch einen begrenzten
  realen Abruf bestätigt. Legacy-XML und FTP-Statistik sind nicht aktiv.
- Die lokale Python-3.13-Full-Prüfung mit 466 Tests und das finale PR-CI-Gate
  sind bestanden. Die Clients-/Sitzungen-Bindungstabellen wurden mit einer
  authentifizierten Admin-Sitzung bei allen dokumentierten fünf Viewports ohne
  horizontalen Seiten-Overflow abgenommen.
- Der generische Lesepfad wurde über den verbundenen MCP auf 351 sichtbaren
  Controls in vier Seiten geprüft; alle in der User-Doku als installationsweit
  lesbar markierten V2-/Bestandstypen waren vorhanden. Die V1-Varianten fehlten.
- Es wird genau ein Miniserver-Ziel unterstützt. Die Voraussetzungen für eine
  spätere Mehrziel-Unterstützung stehen in
  [Multiple Miniserver support](multi-miniserver.md).
