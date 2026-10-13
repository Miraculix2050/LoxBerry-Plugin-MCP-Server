# Beobachtete Lastzyklen

`loxone_analyze_history(operation="operating_phases")` kann beobachtete
Aktivitätsphasen beschreiben, wenn eine bestätigte Verbraucherbindung nutzbare
Betriebsgrenzen enthält und auf eine bestätigte Bindung eines binären
Betriebszustands verweist. Die historische Analyse liest nur. Sie plant oder
schaltet die Last nicht.

## Bestätigte Quellen auswählen

Richten Sie die genaue Verbraucher-Energiestatistik und ihre Betriebszustands-
Bindung im Anlagenprofil ein. Erklären Sie Zeitfenster, Zeitzone, spätesten
Abschluss, Laufdauer, Unterbrechbarkeit und Mindestlauf-/Sperrzeiten und bestätigen
Sie danach die gesamte Verbraucherbindung. Die Herkunft unterscheidet vollständige
gemessene Intervalle von einer erklärten Zyklusenergie in Wh. Rollen und Angaben
belegen keine technische Energieeinheit oder Intervallbedeutung. Benötigt werden
`loxone:read` und `loxone:history`, aktivierte Historie und vorhandene lokale
Zustandsaufzeichnung.

```json
{
  "operation": "operating_phases",
  "sources": [
    {"binding_id": "my-consumer", "granularity": "hour"},
    {"binding_id": "my-operating-state", "granularity": "raw"}
  ],
  "start": "2026-10-11T00:00:00+02:00",
  "end": "2026-10-12T00:00:00+02:00",
  "timezone": "Europe/Berlin"
}
```

Ersetzen Sie beide Beispielkennungen durch aktuell sichtbare bestätigte Bindungen.
Die Betriebsgrenzen des Verbrauchers müssen auf genau diese Betriebszustands-
Bindung verweisen. Der Zeitraum muss vergangen sein und darf höchstens 31 lokale
Tage berühren. Quellen lesen in einem gemeinsamen frisch autorisierten Kontext
mit den vorhandenen Punkte-/Zeitgrenzen. Ändert sich das Profil während der
Analyse, scheitert das Tool vor der Zyklusausgabe; lesen und prüfen Sie erneut.

## Belege und Grenzen verstehen

Prüfen Sie `comparison.load_cycles`. Aus-Ein-Aus-Grenzen innerhalb einer
kontinuierlichen Aufzeichnungsphase belegen eine vollständige beobachtete
Aktivitätsphase. Bereits aktive Anfangswerte, Abfragegrenzen, Aufzeichnungsneustarts,
fehlende/unbekannte Zustände und Lücken bleiben unvollständige Diagnostik.
Lokale Beobachtungsgrenzen belegen allein keine native Programmidentität.

Standard ist `active_episode_only`. Eine ausdrückliche `user_confirmed_cycle`-
Angabe wird als nutzererklärte Identität ausgewiesen, nicht als technisch belegte
Programmidentität. `native_lock_status="not_checked"` und
`planning_status="not_evaluated"` bleiben ausdrücklich sichtbar. Keine Sperre
wird als frei erklärt.

`energy_profile_complete` benötigt vollständig qualifizierte stündliche Wh-/kWh-
Energieintervalle, die die ganze Aktivitätsphase abdecken. Teilstunden werden
weder geteilt noch interpoliert. `observed_energy_wh` und Intervallenergien bleiben
bei unvollständigem Profil unbekannt. Erklärte Wh-Werte bleiben separat
gekennzeichnet und erzeugen keine gemessene Energie. Abweichungen bei Laufdauer
und Mindestlauf-/Sperrzeiten werden angezeigt. Zulässigkeit von Zeitfenstern und
native Sperren benötigen eine spätere qualifizierte Planungsmethode; diese Stufe
behauptet weder Verschiebbarkeit noch finanzielle Einsparung.

Maximal 16 Aktivitätsphasen und insgesamt 128 Energieintervalle werden ausgegeben.
Anzahl und getrennte Begrenzungsflags für Aktivitätsphasen/Energieprofile bleiben
sichtbar. Eine Ausgabegrenze macht ein Teilprofil nicht vollständig. Bestehende
aggregierte Ergebnisse für Betriebsphasen bleiben unabhängig verfügbar.

Native Tages-/Monats-/Jahres-Differenzaggregate werden nicht als stündliche Energie umgedeutet. Sie liefern `non_hourly_interval_energy_not_supported`; ausdrücklich angeforderte Rohwerte bleiben erhalten.
