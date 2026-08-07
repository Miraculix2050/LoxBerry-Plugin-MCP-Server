# Phase-3-Abnahmenachweis

- **Stand:** 2026-08-07
- **Release:** `0.3.0-alpha.1`
- **Ergebnis:** Phase 3 abgenommen

Dieser Nachweis dokumentiert die bestätigten Realtests für die optionalen,
rein lesenden LoxBerry-Diagnosen. Er enthält keine Zugangsdaten, internen
Adressen, Identitäten, Tokens, Konfigurationsinhalte oder Roh-Systemwerte.

## Abgenommener Umfang

Phase 3 ergänzt die drei optionalen MCP-Werkzeuge
`loxberry_get_system_status`, `loxberry_get_plugin_status` und
`loxberry_get_service_health`. Sie sind standardmäßig nicht sichtbar und
werden nur mit aktiviertem `loxberry:read` veröffentlicht. Sie lesen weder
Logs noch beliebige Dateien und führen keine LoxBerry-Aktionen aus.

`loxone:read` bleibt erforderlich. Ein Client kann `loxberry:read` zusammen
mit `loxone:control` anfordern. Bis der lokale Administrator die Bindung für
genau diesen OAuth-Client, die Loxone-Identität und den Miniserver freigibt,
antworten die Diagnosewerkzeuge mit `permission_denied`. Die Freigabe wirkt
live auf die bestehende Verbindung; ein erneutes Anmelden ist nicht nötig.

## OAuth-, Admin-UI- und Explorer-Abnahme

Der vollständige Ablauf wurde auf dem autorisierten LoxBerry-Testsystem
bestätigt:

1. Der deaktivierte Standardzustand veröffentlicht weder Scope noch
   Diagnosewerkzeuge.
2. Nach Aktivierung kann ein Client `loxone:read`, `loxone:control` und
   `loxberry:read` gemeinsam anfordern.
3. Vor der lokalen Freigabe bleibt der Diagnosezugriff bei `permission_denied`.
4. Die Admin-UI bietet die Freigabe an der ausstehenden Sitzung an und zeigt
   die zugehörige Bindung mit Client-Klarname und kurzem pseudonymem
   Verbindungsfingerprint.
5. Die Freigabe erscheint und bleibt bei der automatischen
   Sitzungsaktualisierung sichtbar. Danach funktionieren die drei Diagnosen in
   derselben OAuth-Verbindung.
6. Der Einzelentzug sperrt die passende Verbindung wieder. Globale Deaktivierung
   beendet Diagnose-Sitzungen, ohne gespeicherte Bindungen zu löschen.

Die betroffenen Admin-, OAuth- und Explorer-Oberflächen wurden durch den
Maintainer im Browser abgenommen. Die unabhängige Review-Schleife einschließlich
der OAuth-/UI-Nachträge wurde abgeschlossen.

## Automatisierte und installierte Nachweise

- Der finale Commit bestand das vollständige deterministische CI-Gate unter
  Python 3.13, einschließlich Format, Lint, Typprüfung, Vertrags- und
  Regressionstests.
- Die geänderten Plugin-Dateien wurden gezielt auf LoxBerry-Test übertragen.
  Atomarer Austausch, Dienstneustart und Loopback-Healthcheck waren erfolgreich.
- Die Paket- und Upgradegrenze bleibt durch den vorhandenen nativen
  Plugin-Manager-Nachweis für die Phase-3-Basisversion abgedeckt. Das offizielle
  `0.3.0-alpha.1`-Paket wird ausschließlich durch den Release-Workflow aus dem
  gemergten Commit erzeugt und verifiziert.

## Verbleibende Produktgrenzen

- Schreibende LoxBerry-Werkzeuge, Reparaturen, Neustarts, fremde Dienste,
  beliebige Pfade, Logs, Netzwerkdaten, Prozesse und Telemetrie bleiben
  ausdrücklich außerhalb von Phase 3.
- Ein vollständig gestoppter MCP-Dienst kann seinen eigenen Zustand nicht über
  MCP melden.
- Die Abnahme erweitert keine zugesagten LoxBerry-, Browser- oder
  Miniserver-Kompatibilitäten über die Support-Matrix hinaus.
