# Fehlerbehebung

[English](troubleshooting.en.md)

| Symptom | Sichere Prüfung |
| --- | --- |
| Client erreicht den Server nicht | Prüfe Dienststatus, lokale HTTPS-Adresse und Zertifikatsdiagnose. |
| OAuth-Anmeldung startet nicht | Öffne die HTTPS-Adresse; HTTP wird nicht für die Anmeldung verwendet. |
| Tool antwortet mit `permission_denied` | Prüfe Loxone-Rechte, angeforderten Scope und gegebenenfalls lokale Adminfreigabe. |
| Tool antwortet mit `emergency_stop_active` | Prüfe das ausgewählte Notaus-Signal: `1` gibt Tool-Aufrufe frei, `0` sperrt sie. Bei `unknown` kann der Dienst keinen sicheren Wert bestätigen. Stelle das Signal außerhalb von MCP auf `1` oder entferne die Auswahl; nicht automatisch wiederholen. Die Antwort enthält den aktuellen Status sowie UTC-Zeitpunkte für Beobachtung und Beginn der Sperre. |
| Keine aktuellen Werte | Prüfe Miniserver-Verbindung und ob der Loxone-Benutzer die Controls sehen darf. |
| Update fehlgeschlagen | Warte auf den terminalen Status im Plugin Manager und halte das vorherige Paket bereit. |

Exportiere oder teile keine Zugangsdaten, Tokens, privaten Adressen oder vollständigen Zustandsdaten. Nutze nur maskierte Plugin-Diagnosen.
