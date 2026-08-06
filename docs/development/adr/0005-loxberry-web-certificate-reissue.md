# ADR 0005: LoxBerry-Webserver-Zertifikat diagnostizieren und neu ausstellen

- Status: angenommen
- Datum: 2026-08-06

## Kontext

Der MCP-Endpunkt verwendet die systemweite HTTPS-Origin des LoxBerry. Ändert
sich der LoxBerry-Hostname nach Ausstellung des Core-Zertifikats, bleibt die
Vertrauenskette gültig, der neue Hostname fehlt aber im Subject Alternative
Name. Der LoxBerry-Core 4.0.0.14 erneuert das Zertifikat bei Ablauf oder
geänderter lokaler IP, nicht allein aufgrund einer Hostnamenänderung.

Das Plugin soll den Fehler sichtbar machen und eine gezielte Reparatur anbieten,
ohne eine zweite CA, frei wählbare SANs oder eine eigene dauerhafte
Zertifikatsverwaltung einzuführen.

## Entscheidung

Die authentifizierte Plugin-UI zeigt eine lesende, maskierte Diagnose des
LoxBerry-Webserver-Zertifikats. Sie veröffentlicht nur Ausstellerklasse,
Ablaufzeit, SAN-Anzahlen und boolesche Übereinstimmungen mit der konfigurierten
MCP-Origin und dem aktuellen Systemhostname. SAN-Werte und private Adressen
bleiben aus Diagnoseexport und Logs entfernt.

Eine Neuausstellung ist ausschließlich in der lokalen LoxBerry-Admin-UI
verfügbar, niemals als MCP-Tool. Sie erfordert gleichzeitig:

1. einen Same-Origin-POST aus `htmlauth`,
2. einen vierstelligen SecurePIN, der erst im festen Root-Helper über die
   offizielle LoxBerry-Funktion geprüft wird,
3. eine ausdrückliche Bestätigung der systemweiten Wirkung,
4. ein von der bestehenden lokalen LoxBerry-CA signiertes Zertifikat,
5. vorhandene, root-eigene Core-Skripte ohne Symlinks.

Der SecurePIN wird nur über Standard-Eingabe weitergegeben. Die enge
`sudoers`-Regel erlaubt ohne Argumente ausschließlich einen root-eigenen Helper
unter `/usr/local/sbin`. Dieser plant eine feste transiente systemd-Unit ein;
dadurch kann der LoxBerry-Core Apache neu starten, ohne den ausführenden Prozess
zusammen mit dem aktuellen CGI abzubrechen. Freie Pfade, Befehle, SANs,
Hostnamen oder sonstige Argumente werden nicht akzeptiert.

Der Worker ruft nur `revokewwwcert.sh` und `makewwwcert.sh` des LoxBerry-Core auf.
Danach prüft er Signaturkette und aktuellen Hostnamen. Gleichzeitige Läufe werden
per Lock und systemd-Unit abgewiesen. Start, Abschluss und maskierte Fehlerklasse
werden protokolliert; SecurePIN, Schlüssel, SAN-Werte und private Adressen nicht.

Die bestehende LoxBerry-CA wird nicht neu erzeugt. Externe Zertifikate bleiben
unangetastet und deaktivieren die Aktion.

## Folgen

- Die Plugin-UI erkennt den für OAuth und MCP relevanten Hostnamenfehler direkt.
- Der Core bleibt alleiniger Erzeuger der SAN-Zusammenstellung.
- Der zusätzliche Root-Helper und die `sudoers`-Regel erweitern den
  Installations- und Sicherheitstestumfang.
- Die Aktion ist nicht idempotent: Ein erneuter bestätigter Lauf erzeugt bewusst
  erneut Schlüssel und Zertifikat. Ein bereits laufender Vorgang wird dagegen
  abgelehnt.
- Änderungen an den internen Core-Skripten benötigen eine erneute
  Kompatibilitätsprüfung; es wird keine Unterstützung jenseits der geprüften
  LoxBerry-Version behauptet.
