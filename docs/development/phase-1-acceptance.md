# Phase-1-Abnahmenachweis

- **Stand:** 2026-08-04
- **Releasekandidat:** `0.1.0-alpha.1`
- **SHA-256:** `fe33a85aa52cae4e1cb4008d028f72b6abdd75fc811424b7d395e60fbd7329b5`

Dieser Nachweis trennt lokale Regressionen, reale Zielsystemtests und weiterhin
offene Grenzen. Er enthält keine Zugangsdaten, internen Adressen, Identitäten,
Steuerungsnamen, UUIDs oder Zustandswerte.

## Automatisiertes Gate

`PYTHONPATH=src .venv/Scripts/python.exe tools/test.py` wurde für den finalen
Quellstand vollständig ausgeführt:

- Ruff-Formatierung und Ruff-Lint erfolgreich
- mypy für 19 Quelldateien erfolgreich
- 172 Pytest-Tests erfolgreich
- bekannte, nicht blockierende Warnungen: Starlette-`httpx`-Deprecation und ein
  lokal nicht beschreibbarer Pytest-Cache

Die ergänzten Regressionen decken insbesondere ab:

- lokales Aufräumen eines Login-Tokens, wenn das entfernte `killtoken` nicht
  erreichbar ist
- Ausblenden bereits widerrufener Familien in der Administration
- administrativen Widerruf bei einem nicht mehr entschlüsselbaren historischen
  Tokenstore
- Erhalt von Konfiguration, Sessions, verschlüsselten Tokens und
  Installationsschlüssel über den nativen Upgradepfad

## Reales LoxBerry- und Gen.-1-Ergebnis

Getestet wurde LoxBerry `4.0.0.14` auf Debian 13/aarch64 über die native
Plugin-Verwaltung. Das reproduzierbare ZIP wurde unverändert übertragen; lokale
und entfernte SHA-256 stimmten überein.

- Offline-Venv wurde vollständig aus dem Paket aufgebaut.
- Der native Installer beendete das finale Upgrade mit Status 0 und
  `Everything seems to be OK`.
- systemd-Dienst und Loopback-Healthcheck waren aktiv.
- `schema_version: 1`, Aktivierung und Read-only-Toolfreigabe blieben erhalten.
- Installationsschlüssel, Sessionstore und verschlüsselter Tokenstore behielten
  ihre restriktiven Eigentümer- und Dateirechte.
- Eine neue OAuth-Anmeldung mit Claude Desktop und `mcp-remote 0.1.38` erhielt
  ausschließlich `loxone:read`.
- Genau die sechs Phase-1-Tools mit `readOnlyHint=true` und
  `destructiveHint=false` wurden veröffentlicht und real aufgerufen.
- Eine sichtbare Teststeuerung war auffindbar und beschreibbar; eine für den
  Testbenutzer unsichtbare Steuerung erschien nicht. Ein sichtbarer Zustand
  wurde lesend abgefragt.
- Nach einem weiteren nativen Upgrade desselben Artefakts funktionierten
  Toolliste und alle sechs Aufrufe ohne erneute Anmeldung. Damit sind der
  gemeinsame Erhalt von OAuth-Sitzung, Installationsschlüssel und
  verschlüsseltem Loxone-Token praktisch bestätigt.

Es wurden keine Steuerbefehle ausgeführt und keine Nutzsteuerung verändert.
Tokenanlage und Tokenlebenszyklus waren für die OAuth-Abnahme ausdrücklich
freigegeben.

## Reproduzierbarkeit

Das ZIP wurde zweimal aus demselben frisch aufgebauten arm64-Wheelhouse erzeugt.
Beide Dateien waren bytegleich und hatten die oben genannte SHA-256-Prüfsumme.

## Noch offene Grenzen

- Der vollständige Kernablauf wurde nicht mit browserweit deaktiviertem
  JavaScript real wiederholt. Die serverseitigen POST/Redirect/GET-Fallbacks
  sind automatisiert geprüft.
- Codex CLI wurde in diesem Abschlusslauf wegen der lokalen
  Windows-Ausführungsstörung nicht erneut abgenommen; dies blockiert den Server-
  und Claude-Nachweis nicht.
- Gen. 2 bleibt ohne unabhängigen vollständigen Hardwarebericht
  `experimental`.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
