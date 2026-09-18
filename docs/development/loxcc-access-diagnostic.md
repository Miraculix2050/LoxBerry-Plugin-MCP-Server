# LoxCC access diagnostic / LoxCC-Zugriffsdiagnose

## English

`tools/diagnose_loxcc_access.py` is an opt-in developer diagnostic for the
authorized test target. Run it with the installed plugin Python environment and
the service's `MCPSERVER_*` settings, as the service user. It is not an MCP tool.

The probe selects an unexpired, non-revoked `loxone:read` MCP session. Explorer
sessions are excluded. Multiple distinct identities/Miniservers cause a stop;
for multiple sessions of the same identity it uses the latest family expiry.
It reuses the encrypted stored token without rotation or remote revocation and
does not acquire credentials or fall back to another identity.

The only requested resource is `dev/fsget/prog/sps.LoxCC`, over an isolated
authenticated WebSocket using the existing adapter. Select `--transport http` for
HTTP token authentication (encrypted commands on Gen. 1, validated TLS on Gen. 2).
There is one attempt per invocation, a 20-second
operation deadline and an 8 MiB response limit. Project bytes stay in memory.
Output contains only fixed status categories, format and sizes, never response
text, project content, identifiers, endpoints or credentials.

`download_verified` means a LoxCC magic/header and exact compressed payload
length were received. It does **not** verify LoxCC decompression or its CRC, nor
establish which specific user right permitted access. ZIP responses are bounded
to 32 entries and 64 MiB aggregate member size; project members undergo ZIP CRC
and LoxCC header/length validation in memory. A 401/403 response means this request
was rejected, not proof of which user or token permission is missing. Exit 0
means download evidence; exit 2 means unavailable, rejected or incomplete.

Run regression tests with `python -m pytest tests/test_loxcc_diagnostic.py`.
Real access, permission variants and revocation require separate target evidence.
Do not change user rights as part of this diagnostic.

## Deutsch

`tools/diagnose_loxcc_access.py` ist eine freiwillige Entwicklerdiagnose für das
autorisierte Testsystem, kein MCP-Tool. Sie läuft als Dienstbenutzer mit dem
installierten Plugin-Python und den `MCPSERVER_*`-Einstellungen des Dienstes.

Der Test verwendet eine gültige, nicht widerrufene MCP-Sitzung mit `loxone:read`;
Explorer-Sitzungen sind ausgeschlossen. Mehrere unterschiedliche Identitäten
oder Miniserver führen zum Abbruch. Bei mehreren Sitzungen derselben Identität
wird die mit dem spätesten Familienablauf gewählt. Der gespeicherte Token wird
weder rotiert noch widerrufen. Es gibt keine neue Anmeldung oder Ersatzidentität.

Abgerufen wird ausschließlich `dev/fsget/prog/sps.LoxCC` über eine separate,
authentifizierte WebSocket-Verbindung des bestehenden Adapters. Mit
`--transport http` wird HTTP-Tokenauthentifizierung verwendet. Gen. 1 verwendet
Befehlsverschlüsselung, Gen. 2 geprüftes TLS. Ein Versuch, 20 Sekunden Zeitlimit
und maximal 8 MiB begrenzen den Abruf. Projektbytes verbleiben im Arbeitsspeicher.
Die Ausgabe enthält nur feste Statuskategorien, Format und Größen, keine Inhalte,
Identitäten, Adressen oder Zugangsdaten.

`download_verified` bestätigt LoxCC-Kennung, Header und genaue komprimierte
Nutzdatenlänge. LoxCC-Dekomprimierung und deren CRC sind nicht geprüft; das konkret
benötigte Benutzerrecht ist dadurch nicht bestimmt. ZIP-Antworten sind auf 32
Einträge und insgesamt 64 MiB begrenzt; Projektdateien werden im Speicher auf
ZIP-CRC und LoxCC-Header/Länge geprüft. 401/403 bedeutet eine Ablehnung dieses
Aufrufs, ohne die fehlende Benutzer- oder Tokenberechtigung zu bestimmen.
Exitcode 0 bedeutet Downloadnachweis, Exitcode 2 fehlende oder unvollständige
Evidenz. Regressionstests: `python -m pytest tests/test_loxcc_diagnostic.py`.
Rechtevarianten und Rechteentzug benötigen separate Geräteprüfungen.
Dieser Test verändert keine Benutzerrechte.

## Production integration / Produktintegration

The fixed HTTP operation now lives in the Loxone adapter. ProjectService checks
the supplied OAuth identity before and after each download; ordinary live calls
never download projects. No raw project is returned through MCP.

Die feste HTTP-Operation liegt im Loxone-Adapter. ProjectService prüft die
übergebene OAuth-Identität vor und nach jedem Download. Normale Live-Abfragen
laden keine Projekte; Rohprojekte werden nicht über MCP ausgegeben.
