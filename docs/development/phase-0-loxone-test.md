# Phase-0-Test: Loxone Gen. 1

Dieser gezielte Test bestätigt Grenzen, die Mocks nicht beweisen können. Er ist
kein allgemeiner Installationstest und verändert keine Steuerung. Verwendet wird
ein dedizierter, eingeschränkter Loxone-Benutzer auf dem vorhandenen
Miniserver Gen. 1 mit Firmware `17.1.7.27`.

## Voraussetzungen

- LoxBerry 4 auf Debian 13 und `arm64` im selben lokalen Netz
- Python 3.13 mit dem exakt fixierten Offline-Wheelhouse
- ein Control, das der Testbenutzer sehen darf
- ein anderes Control, das für den Testbenutzer unsichtbar ist
- beide Control-UUIDs, aber keine Strukturdatei oder Zugangsdaten im Repository

Das Passwort wird standardmäßig interaktiv und ohne Echo abgefragt. Für einen
lokalen Automationsprozess kann es mit `--password-stdin` als genau eine
umgeleitete Eingabezeile übergeben werden. Es wird niemals als Argument oder
Umgebungsvariable übergeben oder vom Test gespeichert. Während des Tests darf
der Benutzer ein sichtbares Control auf normalem Weg bedienen, damit ein
Zustands-Delta beobachtet werden kann; der Test selbst sendet keinen
Steuerbefehl.

## Ausführung

```text
python tools/test_loxone_target.py \
  --endpoint http://PRIVATE-IP \
  --username RESTRICTED-USER \
  --visible-control VISIBLE-UUID \
  --hidden-control HIDDEN-UUID
```

Der Test akzeptiert für Gen. 1 ausschließlich eine kanonische private IP-Adresse
über HTTP und verwendet für Anmeldung, Tokenoperationen und WebSocket-
Authentifizierung zusätzlich Loxone Command Encryption. Das kurzlebig gehaltene
Test-JWT wird auch nach einem Fehler bestmöglich mit `killtoken` widerrufen.

Ein erfolgreicher Bericht enthält nur Firmware, einen SHA-256-Fingerprint der
Seriennummer und benannte PASS-Zeilen. Passwort, JWT, interne Adresse,
Benutzernamen, Control-Namen und vollständige UUIDs werden nicht ausgegeben.

## Runtime-Nachweis für PR 1

Der aktualisierte Lockfile- und Runtime-Gate wurde am 2026-08-01 erneut auf
LoxBerry `4.0.0.14`, Debian 13, `aarch64`, Python `3.13.5` und Apache `2.4.68`
ausgeführt. Der plattformspezifische Download verwendete den vollständig
transitiv fixierten Lockfile mit `pip download --no-deps`, anschließend wurde
im isolierten Ziel-`venv` mit `--no-index --no-deps` installiert.

- 31 Wheels einschließlich des Projekt-Wheels, Wheelhouse: 9.360 KiB
- vollständiges `venv`: 53.836 KiB
- `websockets 17.0.1`, `mcp 1.28.1`, `cryptography 50.0.0` und `httpx 0.28.1`
- Health-Endpunkt nach 4.178 ms erreichbar
- RSS direkt danach 54.796 KiB, nach 30 Sekunden Idle 54.808 KiB

Der produktive System-Python und die produktive Apache-Konfiguration wurden
dabei nicht verändert. Der nachfolgende Miniserver-Test ergänzt diesen
Runtime-Nachweis um Anmeldung, Rechtefilterung, Ereignisse, Reconnect und
Tokenwiderruf.

Der reale Gen.-1-Endpunkt lieferte am selben Tag über `getcertificate` eine
X.509-Kette mit dem Loxone-Root-Zertifikat und einem RSA-Leaf-Zertifikat. Der
Adapter validiert Gültigkeitszeiträume, Ausstellerbeziehungen und Signaturen der
Kette gegen den fest hinterlegten SHA-256-Fingerprint des Loxone-Roots und nutzt
erst danach den öffentlichen Leaf-Schlüssel. Ein über diesen Schlüssel
vollständig per RSA/AES Command Encryption gesendeter `apiKey`-Probe antwortete
mit Code `200`. Außerdem serialisiert der Adapter Client-IDs im von Loxone
geforderten UUID-Format `8-4-4-16`. Fehler des HTTP-Unterbaus werden ohne die
möglicherweise sensitive verschlüsselte Request-URL weitergegeben.

Die reale WebSocket-Prüfung bestätigte anschließend `keyexchange`, das
verschlüsselte `getkey2` und die verschlüsselte JWT-Anforderung mit dem
vorgesehenen Testbenutzer. Der `apiKey`-Probe berücksichtigt dabei das
historische Gen.-1-Format, in dem `LL.value` ein flaches, einfach quotiertes
Objekt statt standardkonformem JSON enthält. `getkey2` bestimmt dynamisch SHA1
oder SHA256 für den Passwort- und Tokenhash. Jede Tokenauthentifizierung,
-erneuerung und -widerrufung bezieht über die jeweilige verschlüsselte
WebSocket-Verbindung einen frischen `getkey`-Einmalschlüssel.

Die im externen Testdatenordner ausgewählten sichtbaren und unsichtbaren
Controls bleiben bis zum vollständigen Strukturnachweis ausdrücklich
unbestätigt. Rechtefilterung, Statusereignisse und Reconnect sind noch offen;
der korrigierte Tokenwiderruf ist nach lokalem Regressionstest noch einmal am
Zielgerät zu bestätigen.
