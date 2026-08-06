# Phase-2-Abnahmenachweis

- **Stand:** 2026-08-06
- **Releasekandidat:** `0.2.0-alpha.1`
- **Ergebnis:** Phase 2 abgenommen
- **Release:** noch nicht veröffentlicht

Dieser Nachweis dokumentiert die bestätigten Realtests für die kontrollierte
Gen.-1-`Switch`-Steuerung. Er enthält keine Zugangsdaten, internen Adressen,
Identitäten, Steuerungsnamen, UUIDs oder Zustandswerte.

## Abgenommener Umfang

Phase 2 ergänzt das weiterhin standardmäßig deaktivierte MCP-Tool
`loxone_operate_control`. Abgenommen ist ausschließlich ein für die angemeldete
Loxone-Identität sichtbares und bedienbares Gen.-1-Control vom exakten Typ
`Switch` mit den expliziten Aktionen `on` und `off`.

Die Steuerung erfordert die bewusste Aktivierung im Plugin sowie eine neue
OAuth-Freigabe mit `loxone:read loxone:control`. Bestehende Read-only-Sitzungen
erhalten den Control-Scope nicht automatisch.

## Realer Switch-Test

Ein ausdrücklich freigegebener, unkritischer Gen.-1-`Switch` wurde real über
das MCP-Tool ein- und ausgeschaltet. Beide Aktionen bestätigten die vorgesehene
Funktionalität; anschließend wurde der vor dem Test bestehende Ausgangszustand
wiederhergestellt.

Der Test bestätigt den eng begrenzten realen End-to-End-Schreibpfad von der
autorisierten Werkzeugauswahl bis zur beobachteten Zustandsrückmeldung. Die
Loxone-Berechtigungsprüfung und verschlüsselte Gen.-1-Kommunikation sind
zusätzlich durch die Implementierungs- und Adaptertests abgedeckt. Daraus wird
keine Freigabe für andere Control-Typen oder beliebige Kommandos abgeleitet.

## Vollständiger Control-Client-Ablauf

Der vollständige Ablauf mit Claude Desktop und der lokalen `mcp-remote`-Bridge
wurde bestätigt:

1. öffentliche OAuth-Clientregistrierung,
2. Anmeldung und Consent mit `loxone:read loxone:control`,
3. Sichtbarkeit von `loxone_operate_control` nur mit aktivierter Steuerung und
   passendem Scope,
4. realer Werkzeugaufruf an einem freigegebenen Gen.-1-`Switch`,
5. Wiederherstellung des ursprünglichen Zustands.

Read-only bleibt der sichere und dokumentierte Standard. Die zusätzliche
Control-Berechtigung wird ausdrücklich ausgewählt und niemals stillschweigend
zu einer bestehenden Sitzung hinzugefügt.

## Automatisierte und installierte Nachweise

Die Implementierung wurde vor der formalen Abnahme durch das vollständige
deterministische Gate sowie durch native Upgrades auf dem autorisierten
LoxBerry-Testsystem geprüft. Dienst, Loopback-Healthcheck, Apache-Konfiguration,
OAuth-Metadaten und die Beibehaltung der vorhandenen Konfiguration wurden
read-only bestätigt. Die realen Steueraktionen waren auf den oben beschriebenen,
ausdrücklich freigegebenen Switch-Test begrenzt.

## Verbleibende Grenzen

- Der Releasekandidat `0.2.0-alpha.1` ist noch nicht auf GitHub veröffentlicht.
- Dimmer, Lichtsteuerungen, Jalousien und weitere Control-Typen sind nicht Teil
  dieser Phase-2-Abnahme.
- Gen. 2/Compact bleibt für Schreibzugriffe nicht freigegeben.
- Externer oder cloudbasierter MCP-Zugriff ist nicht freigegeben.
- Freie Kommandos, Bulk-Aktionen und schreibende LoxBerry-MCP-Tools bleiben
  ausgeschlossen.
