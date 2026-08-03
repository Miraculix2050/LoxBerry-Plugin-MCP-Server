# Support-Matrix

- **Stand:** Abschluss Phase 0, 2026-08-03
- **Nächster Meilenstein:** Phase 1, Read-only Alpha

Diese Matrix unterscheidet reale Nachweise von implementierten, aber noch nicht
real bestätigten Kombinationen. Sie ist keine Freigabe eines Installationspakets;
Pluginlayout, Lifecycle und Admin-UI entstehen erst in Phase 1.

## Plattformen und Geräte

| Komponente | Getesteter Stand | Status | Nachweis und Grenze |
| --- | --- | --- | --- |
| LoxBerry | `4.0.0.14`, Debian 13, `aarch64` | `maintainer-tested` | [Python-3.13-Runtime, Offline-Wheels, Apache-Transport und Ressourcenbudgets real bestätigt](phase-0-oauth-test.md#automatisierte-und-zielsystem-nachweise) |
| LoxBerry 3 und ältere Debian-Basen | nicht getestet | `unsupported` | nicht Teil des anfänglichen Umfangs |
| Miniserver Gen. 1 | Firmware `17.1.7.27` | `maintainer-tested` | [lokale HTTP-/WS-Anbindung, Command Encryption, JWT, Rechtefilterung, Snapshot, Delta und Reconnect real bestätigt](phase-0-loxone-test.md#runtime-nachweis-für-pr-1) |
| Miniserver Gen. 1 mit älterer Firmware | nicht getestet | `experimental` | keine Kompatibilitätszusage ohne passenden Nachweis |
| Miniserver Gen. 2/Compact | keine Maintainer-Hardware | `unsupported` | der Phase-0-Adapter weist TLS-fähige Miniservers ab; Phase 1 beginnt die read-only Implementierung und öffentliche Beta |

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

## Nicht abgedeckt

- Es gibt noch kein installierbares Alpha-Paket und keine Lifecycle-Abnahme.
- Es gibt noch keine Admin-UI und daher keine Browser-Supportaussage.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
- Es gibt noch keine veröffentlichten Loxone- oder LoxBerry-Domain-Tools.
- Schreibende MCP-Tools sind nicht Bestandteil von Phase 0 oder Phase 1.
