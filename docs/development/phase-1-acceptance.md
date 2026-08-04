# Phase-1-Abnahmenachweis

- **Stand:** 2026-08-04
- **Releasekandidat:** `0.1.0-alpha.1`
- **SHA-256:** `d024cde3a497cdacef1e6dc6e10d6e396dd13cc8468272c4b74e6aeac9d27e37`
- **Ergebnis:** Phase 1 abgenommen

Dieser Nachweis trennt lokale Regressionen, reale Zielsystemtests und bewusst
verbleibende Produktgrenzen. Er enthält keine Zugangsdaten, internen Adressen,
Identitäten, Steuerungsnamen, UUIDs oder Zustandswerte.

## Automatisiertes Gate und Reproduzierbarkeit

Das vollständige Gate wurde für den finalen Quellstand ausgeführt:

- Ruff-Formatierung und Ruff-Lint erfolgreich
- mypy für 19 Quelldateien erfolgreich
- 184 Pytest-Tests erfolgreich
- bekannte, nicht blockierende Warnungen: Starlette-`httpx`-Deprecation und ein
  lokal nicht beschreibbarer Pytest-Cache

Der Releasekandidat wurde in zwei getrennten vollständigen Läufen aus dem
arm64-Wheelhouse gebaut. Beide ZIP-Dateien waren bytegleich. Paketmanifest,
LF-Zeilenenden, ausführbare Hooks, Offline-Wheels und Prüfsumme wurden zusätzlich
mit `tools/verify_plugin.py` geprüft.

## Reales LoxBerry-Ergebnis

Getestet wurde LoxBerry `4.0.0.14` auf Debian 13/aarch64 über den nativen
Plugin-Manager-Lifecycle. Lokale und entfernte SHA-256 stimmten überein.

- Der native Installer beendete das finale Upgrade mit Status 0 und
  `Everything seems to be OK`.
- Das Python-3.13-Venv wurde ausschließlich aus dem Offline-Wheelhouse aufgebaut;
  `pip check` meldete keine defekten Abhängigkeiten.
- systemd-Dienst und Autostart sind aktiv. Der Dienst läuft als `loxberry`, mit
  `UMask=0077` und ausschließlich auf `127.0.0.1:8765`.
- Loopback-Healthcheck und Apache-Konfiguration (`Syntax OK`) waren erfolgreich.
- `schema_version: 1`, Aktivierung, Ziel und Read-only-Toolfreigabe blieben über
  die Upgrades erhalten.
- Konfiguration, Sessionstore, verschlüsselter Tokenstore und
  Installationsschlüssel behielten ihre vorgesehenen restriktiven Rechte.
- Eine gültige OAuth-Sitzung und der zugehörige verschlüsselte Loxone-Token
  blieben nach dem finalen nativen Upgrade ohne Neuanmeldung nutzbar.

## Reale MCP- und Gen.-1-Abnahme

Claude Desktop blieb mit der vorhandenen `mcp-remote 0.1.38`-Konfiguration
eingerichtet. Für die Abnahme wurde OAuth bei Bedarf neu autorisiert; der Scope
blieb ausschließlich `loxone:read`.

- Genau die sechs Phase-1-Tools wurden veröffentlicht.
- Alle Tools tragen `readOnlyHint=true` und `destructiveHint=false` sowie
  konkrete Eingabe- und Ausgabeschemas.
- Alle sechs Tools wurden real aufgerufen, einschließlich Pagination,
  Beschreibung und lesender Zustandsabfrage.
- Eine für den Testbenutzer sichtbare Steuerung war auffindbar und
  beschreibbar. Eine nicht sichtbare Steuerung erschien weder in der Suche noch
  über den direkten Beschreibungsaufruf.
- Einzel- und Gesamtwiderruf wurden real geprüft. Danach wurde eine
  funktionsfähige Claude-Sitzung wiederhergestellt und auf dem Testsystem
  belassen.

Es wurden keine Steuerbefehle ausgeführt und keine Nutzsteuerung verändert.

## Admin-UI-Abnahme

Deutsch und Englisch wurden request-lokal real gerendert. Die englische
Sprachvorschau wurde während der Abnahme korrigiert, erneut paketiert und über
den nativen Upgradepfad installiert.

- Die Viewports `1280x800`, `900x768`, `390x844`, `360x800` und `320x568`
  bestanden in beiden Sprachen ohne horizontales Seitenoverflow oder außerhalb
  liegende Aktionen.
- Tastaturnavigation erzeugte einen sichtbaren `:focus-visible`-Zustand.
- AJAX-Status und Verbindungstest sperrten die Schaltfläche, setzten
  `aria-busy`, zeigten Fortschritt und endeten mit einer strukturierten
  Erfolgsmeldung.
- AJAX-Einzel- und Gesamtwiderruf funktionierten real; die Sitzung wurde danach
  wiederhergestellt.
- Der serverseitige Speichervorgang und der maskierte Diagnoseexport liefen als
  native Formularaktionen ohne AJAX.
- Status, Verbindungstest und Einzelwiderruf wurden zusätzlich als echte
  serverseitige POST/Redirect/GET-Abläufe ohne AJAX ausgeführt.

Die Browsersteuerung durfte die globale Chrome-JavaScript-Berechtigung aus
Sicherheitsgründen nicht ändern. Der funktionale No-JavaScript-Vertrag wurde
daher durch die realen nativen Formular-/PRG-Pfade sowie die automatisierten
Fallbacktests abgenommen, nicht durch eine dauerhafte Browser-Einstellung.

## Verbleibende Produktgrenzen

- Codex CLI wurde wegen der bekannten lokalen Windows-Ausführungsstörung nicht
  erneut abgenommen. Dies ist als externe Clientgrenze akzeptiert und lockert
  keine Serverprüfung.
- Gen. 2 bleibt ohne vollständigen unabhängigen Hardwarebericht
  `experimental`.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
- Schreibende Tools, Historie, LoxBerry-Tools, Basic Auth und generische
  Kommandos bleiben außerhalb von Phase 1.
