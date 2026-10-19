# Daten für numerische Solartagesvergleiche

Numerische Vergleiche benötigen historische Strahlungsenergie und Temperatur
sowie getrennte PV-Ertragsdaten. Geeignete lokale Quellen werden zuerst auf
Einheit, Zeitbezug und Anlagenzuordnung geprüft. Ein dokumentierter Vertrag und
eine reale Datenprobe genügen; eine allgemeine Gerätequalifizierung ist nicht
erforderlich.

Direkte stündliche Strahlungsenergie in Wh/m² oder MJ/m² wird bevorzugt. Bei
beobachteten W/m²-Werten darf das Plugin die Energie trapezförmig schätzen.
Lücken über dem Doppelten der Abtastperiode, höchstens 60 Minuten, werden nicht
überbrückt; außerhalb vorhandener Messpunkte wird nicht extrapoliert.
Berechnete Energie bleibt ausdrücklich eine Schätzung. Unvollständige Stunden
werden ausgeschlossen statt mit Null aufgefüllt.

Aus der zu bewertenden PV-Leistung berechnete Strahlung ist kein unabhängiger
Wettermaßstab. Prognosen, Lux und Strahlungsklassen ersetzen ebenfalls keine
beobachtete Strahlungsenergie. Ohne geeignete lokale Quelle bleibt der numerische
Vergleich nicht verfügbar. Die vorhandene qualitative Klassenmethode bleibt
nutzbar. Die interne Stundenaufbereitung allein aktiviert noch keine Quelle oder
Aufzeichnung; technische Quellenlese-/Modellabnahme belegt keine empirische Anlagenvalidierung
(siehe [Abschlusskriterien](../development/solar-history-acceptance.de.md)).

Die Solaraufzeichnung benötigt die Historienfreigabe. Vor dem Entzug dieser
Freigabe in der Hauptkonfiguration muss die Solaraufzeichnung deaktiviert werden.
Scheitert die regelmäßige Quellenprüfung, pausiert die Solaraufzeichnung bis zur
erfolgreichen Wiederholung; die gewöhnliche Ereignishistorie zeichnet ohne
Neuaufbau ihrer Verbindung weiter auf.
Ist nur die Solaraufzeichnung aktiv, meldet ihr Laufzeitstatus unverfügbar,
solange die Quellenprüfung die Erfassung verhindert.
