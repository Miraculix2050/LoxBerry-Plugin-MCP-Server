# Support-Matrix

- **Stand:** Implementierungsstand Phase 1, 2026-08-03
- **Nächster Meilenstein:** vollständige Gen.-1-End-to-End-Abnahme `0.1.0-alpha.1`

Diese Matrix unterscheidet reale Nachweise von implementierten, aber noch nicht
real bestätigten Kombinationen. Das Alpha-Paket bleibt ein Prerelease, bis alle
unten genannten Phase-1-Abnahmepunkte abgeschlossen sind.

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

| Client | Getesteter Stand | Phase-0-Ergebnis | Bekannte Grenze |
| --- | --- | --- | --- |
| Claude Desktop mit `mcp-remote` | Desktop `1.24012.9`, Bridge `0.1.38` | [Login, MCP-Initialisierung, authentifizierter Aufruf, Refresh und RFC-7009-Widerruf erfolgreich](phase-0-oauth-test.md#reale-clientabnahme) | lokale Bridge mit `http-only`; kein Nachweis für den cloudbasierten Connector |
| Codex CLI | `0.146.0` | [Login, MCP-Initialisierung und authentifizierter Aufruf erfolgreich](phase-0-oauth-test.md#reale-clientabnahme) | Refresh sendet keinen verpflichtenden RFC-8707-Parameter `resource`; Logout löscht nur lokale Credentials und ruft `/revoke` nicht auf |

Die Codex-Grenzen sind bestätigtes Clientverhalten und werden für den Abschluss
von Phase 0 ausdrücklich akzeptiert. Der Server lockert weder Audience-Bindung
noch Widerrufsregeln. Codex-Benutzer müssen sich nach Ablauf des Access Tokens
erneut anmelden; serverseitige Testsitzungen werden administrativ oder durch
ihren Ablauf beendet. Phase 1 dokumentiert den späteren operativen
Sessionwiderruf für reguläre Installationen.

## Phase-1-Paketnachweis

- Das Plugin wurde auf LoxBerry `4.0.0.14`, Debian 13/aarch64 über die native
  Plugin-Verwaltung installiert und aktualisiert; Offline-Venv, Icon,
  systemd-Start und Admin-UI waren erfolgreich.
- Der Dienst wurde als aktiv bestätigt. Der deaktivierte Defaultzustand lässt
  nur den Loopback-Healthcheck zu und beantwortet den veröffentlichten MCP-Pfad
  fail-safe mit HTTP 503.
- Die responsive deutsche und englische Admin-UI wurde bei `1280x800`,
  `900x768`, `390x844`, `360x800` und `320x568` ohne Seitenoverflow geprüft.
  AJAX-Status und sichtbarer Tastaturfokus wurden ebenfalls real bestätigt.
- Das ZIP wurde zweimal byteidentisch gebaut und durch seine SHA-256-Prüfsumme
  abgesichert.

## Noch nicht als vollständige Phase-1-Abnahme bestätigt

- Deinstallation und anschließende saubere Neuinstallation des finalen ZIPs
  stehen noch aus.
- Der vollständige Kernablauf mit im Browser deaktiviertem JavaScript steht noch
  aus; die serverseitigen POST/Redirect/GET-Fallbacks sind automatisiert geprüft.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
- Die sechs Phase-1-Loxone-Lesetools sind implementiert; ihre erneute reale
  Gen.-1-Abnahme im installierten Alpha-Paket steht aus.
- Schreibende MCP-Tools sind nicht Bestandteil von Phase 0 oder Phase 1.
