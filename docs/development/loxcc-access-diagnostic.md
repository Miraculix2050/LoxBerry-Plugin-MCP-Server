# LoxCC access diagnostic / LoxCC-Zugriffsdiagnose

## English

`tools/diagnose_loxcc_access.py` is an opt-in developer diagnostic for the
authorized test target. Run it with the installed plugin Python environment and
the service's `MCPSERVER_*` settings, as the service user. It is not an MCP tool.

The probe selects an unexpired, non-revoked `loxone:read` MCP session. Explorer
sessions are excluded by default; pass `--tool-explorer` to select an active
Explorer session explicitly. Multiple distinct identities/Miniservers cause a
stop; for multiple sessions of the same identity it uses the latest family expiry.
It reuses the encrypted stored token without rotation or remote revocation and
does not acquire credentials or fall back to another identity.

The diagnostic uses the existing adapter and ProjectService for three read-only
passes: load the user-filtered structure, access the bounded project graph,
query it and run a KNX analysis. Each fresh structure pass has a 30-second
deadline. Project bytes stay in memory. Output contains bounded counts and
phase times, never project content, identifiers, endpoints or credentials.

`pipeline_verified` means the bounded project query and KNX analysis completed;
it does not establish which specific user right permitted project access. A
401/403 response means this request was rejected, not proof of which permission
is missing. Exit 0 means the diagnostic completed; exit 2 means unavailable,
rejected or incomplete.

Run regression tests with `python -m pytest tests/test_loxcc_diagnostic.py`.
Real access, permission variants and revocation require separate target evidence.
Do not change user rights as part of this diagnostic.

## Deutsch

`tools/diagnose_loxcc_access.py` ist eine freiwillige Entwicklerdiagnose für das
autorisierte Testsystem, kein MCP-Tool. Sie läuft als Dienstbenutzer mit dem
installierten Plugin-Python und den `MCPSERVER_*`-Einstellungen des Dienstes.

Der Test verwendet eine gültige, nicht widerrufene MCP-Sitzung mit `loxone:read`;
Explorer-Sitzungen sind standardmäßig ausgeschlossen. Mit `--tool-explorer` kann
stattdessen ausdrücklich eine aktive Explorer-Sitzung ausgewählt werden. Mehrere
unterschiedliche Identitäten oder Miniserver führen zum Abbruch. Bei mehreren Sitzungen derselben Identität
wird die mit dem spätesten Familienablauf gewählt. Der gespeicherte Token wird
weder rotiert noch widerrufen. Es gibt keine neue Anmeldung oder Ersatzidentität.

Die Diagnose führt mit dem bestehenden Adapter und ProjectService drei lesende
Durchläufe aus: benutzergefilterte Struktur laden, begrenzten Projektgraphen
abrufen, abfragen und eine KNX-Analyse durchführen. Jeder frische Strukturabruf
hat ein 30-Sekunden-Zeitlimit. Projektbytes verbleiben im Arbeitsspeicher.
Die Ausgabe enthält begrenzte Zählwerte und Phasenzeiten, keine Projektinhalte,
Identitäten, Adressen oder Zugangsdaten.

`pipeline_verified` bestätigt, dass begrenzte Projektabfrage und KNX-Analyse
abgeschlossen wurden; das konkret benötigte Benutzerrecht ist dadurch nicht
bestimmt. 401/403 bedeutet eine Ablehnung dieses Aufrufs, ohne die fehlende
Berechtigung zu bestimmen. Exitcode 0 bedeutet abgeschlossene Diagnose,
Exitcode 2 fehlende oder unvollständige Evidenz. Regressionstests:
`python -m pytest tests/test_loxcc_diagnostic.py`.
Rechtevarianten und Rechteentzug benötigen separate Geräteprüfungen.
Dieser Test verändert keine Benutzerrechte.

## Production integration / Produktintegration

The fixed HTTP operation now lives in the Loxone adapter. ProjectService checks
the supplied OAuth identity before and after each download; ordinary live calls
never download projects. No raw project is returned through MCP.

Die feste HTTP-Operation liegt im Loxone-Adapter. ProjectService prüft die
übergebene OAuth-Identität vor und nach jedem Download. Normale Live-Abfragen
laden keine Projekte; Rohprojekte werden nicht über MCP ausgegeben.
