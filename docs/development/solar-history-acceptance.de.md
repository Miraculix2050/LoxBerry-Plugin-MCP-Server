# Lokale Solarhistorie: technische Abnahme

Der Owner hat die Abschlusskriterien am 20. Oktober 2026 geändert. Technische
Quellenlese- und Rechennachweise ersetzen den positiven Vergleich realer
historischer Tage als Abschlussgate für #439/#509. Reale Vergleichstage,
mehrtägige Datensammlung und passende positive Realhistorien-Performancemessungen
sind keine Abschlussbedingungen mehr. Die Eingangsqualifikation und das Verhalten
bei fehlenden Daten im Produkt bleiben unverändert.

Gelieferte Stufen: [#544](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/544)
Normalisierung, [#549](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/549)
lokale Aufzeichnung/PVPF, [#550](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/550)
numerische Laufzeit, [#551](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/551)
Abnahmegrenzen und [#577](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/pull/577)
nativer EFM-Eigenverbrauch und begrenzte Phasendiagnostik.

## Erforderliche Abschlussnachweise

| Kriterium | Nachweis |
| --- | --- |
| Reale Quellenlesezugriffe | Reservierte lesende Zugriffe auf natives Wetter/Strahlung/Temperatur und stündliche PV-/EFM-Werte, deklarierte Einheiten, Erfassungs-/Zeitverträge und bestätigte Anlagenzuordnung. Bestehende Browser-/MCP-/SSH-Evidenz darf wiederverwendet werden. |
| Normalisierung | `test_solar_history.py`: bekannte Integrations-/Umrechnungsergebnisse, keine Extrapolation, begrenzte Lücken, Dubletten-/Quellenregeln und sichtbare Schätzungen. |
| Auswahl und Abweichungen | `test_comparable_days.py`: inklusive Toleranzen, Dreiergruppen, strikte Auffälligkeitsschwelle, Nullnenner, feste abgeschlossene Stunden und Zeitumstellungsausschlüsse. |
| Integrierte Berechnung | `test_numerical_day_tools.py`: handgerechnete PV-/Eigenverbrauchsmediane und Rangfolge bei vollständigen/laufenden Tagen, passende/unpassende Einspeisebilanz, fehlende Evidenz, Quellenisolation und ein Zugriff je Quelle/Zeitraum. |
| Rechte und Ressourcen | Bestehende Vertragsregressionen für Rechteentzug, Quellenwechsel, Grenzen, Fristen/Abbruch, kompakte Ausgabe und unveränderte Klassenaufrufe; vorhandene begrenzte Zeit-/Größenmessungen und korrelierte Phasentests. |
| Lieferung | Full-CI auf aktuellem Commit, aufgelöste relevante Review-Findings, DE/EN-Anleitung und technische Browser-/MCP-/SSH-Abnahme im geprüften Umfang. |

Synthetische Referenzfälle belegen Rechenlogik und Softwareverträge, keine
empirisch validierte Anlage, kalibrierte Wettermessung oder Fehlerdiagnose.
Eine repräsentative native Probe belegt Lesbarkeit, keine physische
Beobachtungsherkunft. Wetterservicewerte behalten ihre Herkunftskennzeichnung;
unbekannte Anbieterzeit-/Messdetails bleiben unbekannt. Prognosen und aus PV
abgeleitete Strahlung werden nicht zu unabhängigen Beobachtungen umgedeutet.
Unqualifizierte oder fehlende Laufzeiteingänge liefern weiterhin eine erklärte
Nichtverfügbarkeit. Aufzeichnung erzeugt keine frühere Historie, schreibt keine
Ausfallnullen um und macht Empfangsabdeckung nicht zu Messabdeckung.

Detaillierte datierte Evidenz bleibt im privaten Project-Data-Archiv des Owners.
Erfolgreiche unveränderte Zielprüfungen werden wiederverwendet; dieser
Dokumentations-/Testabschluss verlangt keine erneute Installation,
Aufzeichnungsänderung oder mehrtägige Kampagne.

PVPF-Prognose-/Istabgleich und positive zukünftige Planung bleiben separat in
#510. Aggregierte Zykluszeiten belegen keine vollständigen Periodenenergiegrenzen;
Tagesprognosen werden nie auf unvollständige Isttage verteilt. #501 wird weder
abgeschlossen noch erlassen. Siehe [Nutzervertrag](../user/comparable-days.de.md).
