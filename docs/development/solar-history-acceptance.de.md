# Lokale Solarhistorie: Abnahmebedingungen

Die Normalisierung ist mit [PR #544](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/544) gemergt.
Aufzeichnung/PVPF: [PR #549](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/549).
Numerischer Laufzeitpfad: [PR #550](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/550).
Integrierter Abschlussstand: [PR #551](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/551).
Ausführliche datierte Geräte-/Browser-/MCP-/SSH- und Performancenachweise gehören
ins private Project-Data-Archiv des Owners, außerhalb öffentlicher Produktdokumentation.

#509 und #439 bleiben offen, bis ein echter erfolgreicher Zahlenvergleich eine
Referenz, drei geeignete historische Wetterpeers und belegten PV-Ertrag umfasst.
Für #439 zusätzlich direkten/kompatiblen Eigenverbrauch, abgeschlossene Stunden
laufender Tage, Rangfolge und erklärbare Grenzen abnehmen. Fixtures ersetzen
keine Geräteabnahme. Full-CI auf dem aktuellen Commit und Reviewgates erhalten;
nach drei erfolglosen Runden bleibt der betroffene PR offen. Spätere Korrekturen
benötigen vor dem Merge eine Prüfung.

Dokumentierter lokaler Quellenvertrag und repräsentative Probe genügen.
Unabhängige W/m²-Beobachtungen dürfen sichtbar geschätzte Wh/m² ergeben.
PV-abgeleitete zirkuläre Maßstäbe ausschließen; Temperaturaggregation und
Anbieterfrische kenntlich machen. Benötigte Testaufzeichnung darf mit privat
dokumentiertem Start weiterlaufen und erzeugt keine frühere Historie.
Unbeteiligte Konfiguration und Historie erhalten. Gleiche echte Historie vor/nach
Änderung sowie unabhängige Datenzugriffs-Phasenmessungen bleiben Abnahmegate;
Negativfall-Messzeiten allein erfüllen es nicht.

PVPF-Verfügbarkeit ist vom historischen Vergleich getrennt. Native Zykluszeiten
beschreiben die aktuelle Prognosestunde, keine vollständigen Periodenenergiegrenzen.
Istvergleich erst mit separat belegten Intervallen; keine Aufteilung von Tagesprognosen
auf unvollständige Isttage. Der getrennte Stundenadapter #542 ist ein möglicher
Integrationspunkt. #510 bleibt zukünftige Lastplanung; #501 wird hierdurch nicht
abgeschlossen. Siehe [Nutzervertrag](../user/comparable-days.de.md).
