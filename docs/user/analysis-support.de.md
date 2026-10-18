# Analysefragen: Support und Grenzen

Für die erneute Abnahme in #485 gelten Bytes, vollständige Aufrufzahlen,
Kalt-/Warm-Laufzeiten und fachliche Antwortqualität. Tokenwerte sind optional;
aus Bytes werden keine Token- oder Kosteneinsparungen abgeleitet. Die bestätigte
Obergrenze bleibt bei 50 Antwortdatensätzen. Diese Änderung der Kriterien ist
keine bestandene Abnahme; frühere Messungen behalten ihre belegten Grenzen.

PR 6 ergänzt [qualitative Strahlungsklassen-Peers](comparable-days.de.md) mit
einer ausdrücklich angenommenen nativen Zuordnung. Unerwartete Werte bleiben
in der Historie und erscheinen als begrenzte Diagnostik mit KI-Warnung und
korreliertem sanitisiertem Log. Solar-20-22 und numerische Einstrahlungssemantik
sind dadurch nicht vollständig umgesetzt.

Energy & solar PRs 4–5 ergänzen bestätigte Wetterquellenbindungen, optionale
deklarierte PV-Parameter und eine getrennt aktivierbare
[lokale Wetteraufzeichnung](weather-history.de.md). Solar-20–22 benötigen weiterhin
numerische Strahlungssemantik und die numerische Vergleichsmethode; frühere Tage werden nicht
aufgefüllt. Bestehende Wetterstatistiken und Zustände behalten ihre
tatsächliche Abdeckung und Semantik.

Die ursprünglichen 25 Fragen bleiben im versionierten Abnahmekatalog erhalten. Zwei später ergänzte KNX-Fälle sind getrennte Erweiterungen. Stand: Analysis foundation PR 1–8, 11. Oktober 2026. Die Labels beschreiben den belegten Antwortumfang, keine vollständige Geräteabdeckung oder 75 unabhängige KI-Läufe.

Unterstützt: begrenzter vorhandener Leseworkflow. Bedingt: benötigte Quelle, Bedeutung, Zuordnung und Abdeckung müssen vorliegen. Nicht verfügbar: benötigte Funktion gehört zu offenen externen Arbeitspaketen. Experimentell: Beratung benötigt zusätzliche Nutzerevidenz und fachliche Prüfung. Gen. 2/Compact bleiben experimentell ohne passende Geräteabnahme.

| ID | Frage / Operation | Status | Ablauf und zulässige Grenzen |
| --- | --- | --- | --- |
| lighting-01 | Analysiere die Raumstruktur und liste Räume ohne klare Lichtszene auf. | bedingt | `loxone_get_structure_overview` → `loxone_describe_control`; Nur sichtbare Szenen; fehlende Sichtbarkeit belegt keine fehlende Konfiguration. |
| lighting-02 | Welche Lichtkreise wirken doppelt oder unlogisch benannt? | unterstützt | `loxone_find_controls` → `loxone_describe_control`; Nur Benennungskandidaten; keine behaupteten doppelten Stromkreise. |
| lighting-03 | Fasse alle Präsenzmelder und zugehörigen Lichtfunktionen raumweise zusammen. | bedingt | `loxone_find_project_objects` → `loxone_trace_project_logic`; Explizite Projektverbindungen nötig; Raumzugehörigkeit ist keine Verbindung. |
| lighting-04 | Welche Räume könnten von Tunable White oder besser getrennten Lichtzonen profitieren? | experimentell | `loxone_get_installation_profile` → `loxone_describe_control`; Planungsberatung benötigt Nutzerabsicht und Leuchtenbestand; keine automatische Eignungsprüfung. |
| lighting-05 | Prüfe, ob Nachtlicht, Orientierungslicht und Abwesenheitsszenen konsistent benannt sind. | bedingt | `loxone_get_installation_profile` → `loxone_describe_control`; Szenenrollen müssen bestätigt sein; Namen belegen keine technischen Rollen. |
| lighting-06 | Das Projekt ist ein Einfamilienhaus mit Küche, offenem Wohnbereich, Büro, Elternbad und Garage. Schwerpunkt ist hochwertige Lichtsteuerung mit Loxone und 24V-Leuchten. Prüfe die Konfiguration aus Sicht Lichtplanung und Bedienbarkeit. | experimentell | `loxone_find_project_objects` → `loxone_get_installation_profile`; Qualifizierte Planungsbewertung; spezielle Lichtprüfung bleibt außerhalb dieser Grundlage. |
| basic-07 | Wie hoch war gestern die durchschnittliche Temperatur im Wohnzimmer? | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; temperature_summary: Isttemperatur mit Einheit und UTC-Stichproben; Stichprobenmittel ist nicht zeitgewichtet. |
| basic-08 | Wie viel Energie hat die Wärmepumpe letzte Woche verbraucht? | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; energy: optionaler Verbraucher mit bestätigter Messgrenze; Zählerdifferenzen bleiben bei unbekannten Resets teilweise. |
| basic-09 | Was ist in Loxone gerade eingeschaltet? | bedingt | `loxone_find_controls` → `loxone_get_state_semantics`; Nur belegte Betriebszustände; unbekannte Controls verhindern eine vollständige Anlagenantwort. |
| basic-10 | Wie warm ist es zu Hause? | unterstützt | `loxone_find_controls` → `loxone_get_state_semantics`; Exakte aktuelle Isttemperaturen mit Aktualität und Einheit; kein abgeleiteter Hausmittelwert. |
| basic-11 | Ist das Licht in der Küche eingeschaltet? | bedingt | `loxone_find_controls` → `loxone_get_state_semantics`; Sichtbares Küchen-Control mit belegtem Betriebszustand; keine Ableitung aus Namen oder beliebigen Zahlen. |
| basic-12 | Wie warm ist es in diesem Raum? | unterstützt | `loxone_find_controls` → `loxone_get_state_semantics`; Raumauswahl muss ausdrücklich sein; Isttemperatur getrennt vom Sollwert ausgeben. |
| basic-13 | Ist die Tür offen? | bedingt | `loxone_find_controls` → `loxone_read_controls`; Exakter autorisierter Kontakt und belegte Richtung; heutige Konfiguration ist kein historischer Zustand. |
| solar-14 | Wie viel Energie hat unsere Solaranlage heute erzeugt? Vergleiche mit gestern und dem bisherigen Tagesdurchschnitt dieses Monats. | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; energy je lokalem Zeitraum; bestätigte Erzeugungszuordnung und vollständige Evidenz nötig für Tagesaussagen. |
| solar-15 | Wie viel unseres Solarstroms haben wir gestern selbst verbraucht, wie viel eingespeist und wie viel Strom aus dem Netz bezogen? | nicht verfügbar | `loxone_describe_control`; Native EFM-Zeitraumbilanz hängt von #436/#363/#364 ab; kein paralleler Bilanzrechner. |
| solar-16 | Zeige mir für gestern den Verlauf von Solarleistung und Hausverbrauch. Wann hatten wir Überschuss und wann mussten wir Strom beziehen? | bedingt | `loxone_analyze_history`; pv_load_overlap und optionale getrennte UTC-Rohdatenseiten; Stundenenergie ist keine Momentanleistung oder Netzbilanz. |
| solar-17 | Vergleiche die Solarerzeugung mit unseren einzeln gemessenen Verbrauchern. Welche liefen überwiegend während der Solarproduktion? | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; pv_load_overlap mit optionalem beobachtetem Freigabesignal; nur ganze aktive Stunden, Obergrenze statt exakter Solarzuordnung. |
| solar-18 | Welche gemessenen Verbraucher haben gestern am meisten Energie benötigt? Stelle ihren Verbrauch dem Solarertrag gegenüber. | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; consumer_ranking benötigt ausdrückliche Vergleichbarkeitsbestätigung; Eltern-/Kindüberlappung ausschließen, Rangwerte nicht summieren. |
| solar-19 | Welche Verbrauchsvorgänge der letzten Woche hätten zeitlich besser zu unserem Solarüberschuss gepasst? | nicht verfügbar | `loxone_analyze_history`; Historische Beobachtungen können eine Teilantwort stützen; Lastverschiebung bleibt #440. |
| solar-20 | Vergleiche gestern mit Tagen ähnlicher Sonneneinstrahlung, Jahreszeit und Temperatur. Waren Ertrag und Eigenverbrauch auffällig? | nicht verfügbar | `loxone_get_statistics`; Qualitative Klassenpeers über comparable_days liefern eine Wetter-Teilantwort; numerische wetterbereinigte Ertrags-/Eigenverbrauchsvergleiche bleiben #439. |
| solar-21 | Warum war unser Eigenverbrauch gestern niedriger als an vergleichbaren Tagen? | nicht verfügbar | `loxone_get_statistics`; Keine kausale Eigenverbrauchserklärung ohne native EFM-Werte, Wetterhistorie und Kontext (#436/#439). |
| solar-22 | Gab es in den letzten vier Wochen Tage mit ungewöhnlich niedrigem Solarertrag, obwohl die Wetterbedingungen vergleichbar waren? | nicht verfügbar | `loxone_get_statistics`; Wetterbereinigte Auffälligkeiten und Anlagenparameter bleiben #439. |
| solar-23 | Wie hoch ist unser nächtlicher Grundverbrauch, und wie viel Energie benötigt er täglich im Verhältnis zum Solarertrag? | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; baseload nutzt belegte stündliche Energie als mittlere Leistung im lokalen Fenster 00-05; Tageshochrechnung ist eine Schätzung des gewählten Kanals. |
| solar-24 | Erstelle einen Solarbericht für die letzte Woche: Erzeugung, Hausverbrauch, Eigenverbrauch, Einspeisung, Netzbezug und auffällige Tage. | bedingt | `loxone_get_installation_profile` → `loxone_analyze_history`; Nur qualifizierter Komponentenbericht; nativer Eigenverbrauch/Einspeisung/Netzbezug bleiben #436, Lücken und unbekannte Restlast/Speicher bleiben ausdrücklich. |
| solar-25 | Welche Zeitfenster sind morgen voraussichtlich günstig, um unsere verschiebbaren Verbraucher mit Solarstrom zu betreiben? | nicht verfügbar | `loxone_get_weather`; Verbrauchs-/PV-Prognosen und Betriebsgrenzen bleiben #440; Wetter allein belegt keinen Zeitplan. |

Numerische Referenzen: Stichprobenmittel 21 °C; Zählerdifferenz 3 kWh; Rangfolge 3/2 kWh; gemischtes Stundenfenster 3600 s; Nachtmedian 100 W und geschätzte 2,4 kWh/Tag. Die Transformation belegter synthetischer Leistungsintervalle in ganze Stundenenergien ist ein Fixture-Vertrag, kein neuer Decoder. Details und Messgrenzen: [Abnahmebericht](../development/analysis-acceptance.md).

Korrekt begründete Teilantworten gelten bei fehlenden Quellen als zulässig. Keine Rollen aus Namen, nachträgliche Anfangswerte, verborgene Identitäten, Steuerbefehle oder kausale Solarzuordnung. Tokenbedarf und 20-Prozent-Tokenziel bleiben mangels verfügbarer Tokenmesswerte unvollständig; Antwortbytes sind keine Tokens.
