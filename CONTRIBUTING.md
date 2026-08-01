# Mitwirken

Dieses Dokument beschreibt den Git-Workflow. Die fachlichen und technischen
Vorgaben stehen in den
[Implementierungsrichtlinien](docs/development/implementation-guidelines.md),
die Testauswahl in der
[Teststrategie](docs/development/test-strategy.md).

## Grundsatz

`master` soll jederzeit einen nachvollziehbaren und grundsätzlich
veröffentlichbaren Stand enthalten. Code, Konfiguration und ausführbare
Artefakte werden über einen Feature-Branch und einen Pull Request geändert.
Änderungen bleiben klein und thematisch zusammenhängend.

## Kleine Dokumentationsänderungen durch AI-Agenten

Auch kleine Änderungen werden nicht direkt nach `master` gepusht. Wenn ein
Benutzer eine kleine, eindeutig abgegrenzte Dokumentationsänderung beauftragt,
darf ein AI-Agent den vollständigen Git-Ablauf jedoch ohne zusätzliche
Bestätigungsfragen ausführen:

1. Branch `agent/<kurze-beschreibung>` erstellen
2. nur die beauftragten Dateien committen und pushen
3. einen zur Prüfung bereiten Pull Request nach `master` anlegen
4. verfügbare Pflichtprüfungen und Mergefähigkeit kontrollieren
5. den Pull Request mergen, den Remote-Branch löschen und den lokalen `master`
   per Fast-forward aktualisieren

Diese Autorisierung gilt für:

- Rechtschreibung, Grammatik und Zeichensetzung
- defekte oder eindeutig falsche Links
- redaktionelle Klarstellungen ohne geändertes Verhalten
- ausdrücklich beauftragte kleine Ergänzungen oder Korrekturen einer
  Spezifikation ohne unmittelbare Code-, Konfigurations- oder Laufzeitwirkung

Der Agent fragt nicht noch einmal nach Commit, Push, Pull Request oder Merge,
wenn der ursprüngliche Auftrag die Änderung bereits eindeutig verlangt. Er
stoppt dagegen bei Widersprüchen, fehlenden fachlichen Entscheidungen,
Sicherheits- oder Berechtigungsauswirkungen, Mergekonflikten, fehlgeschlagenen
Pflichtprüfungen oder unerwarteten fremden Änderungen. Ein Auftrag wie „nur
prüfen“, „noch nichts ändern“ oder „nicht pushen“ hebt die Automatik auf.

Ändert eine Spezifikation Produktverhalten, Sicherheits-, Berechtigungs-,
Konfigurations-, Kompatibilitäts- oder Abnahmeanforderungen, ist ein normales
Review erforderlich und der PR wird nicht automatisch gemergt.

## Pull Requests

Ein Pull Request ist erforderlich für:

- Laufzeitcode, Weboberfläche, Installations- und Lifecycle-Skripte
- Konfigurationsstruktur, Defaults, Migrationen oder Berechtigungen
- MCP-Tools, Tool-Schemas und deren sichtbares Verhalten
- Tests, CI, Abhängigkeiten, Packaging und Releases
- neue oder geänderte normative Anforderungen
- Änderungen, deren Wirkung nicht sicher rein redaktionell ist

Vor dem Merge müssen die für den Diff ausgewählten Tests erfolgreich sein,
Review-Diskussionen aufgelöst und betroffene Dokumentation aktualisiert sein.
Squash oder Rebase hält die Historie linear; Merge-Commits werden nicht genutzt.

## Commits

- Formuliere die Commit-Nachricht im Imperativ und beschreibe den Zweck.
- Vermische keine unabhängigen Änderungen.
- Committe keine Zugangsdaten, Tokens, privaten Schlüssel, Gerätedaten oder
  lokale Testkonfiguration.
- Prüfe vor Commit und Push mindestens `git status --short` und den tatsächlichen
  Diff.

## Releases

Ein Release wird erst eingerichtet, wenn Plugin-Metadaten, Installationslayout,
Upgradepfad und reproduzierbare Paketprüfung feststehen. Bis dahin werden keine
automatischen Veröffentlichungen oder scheinbar stabilen Versionszusagen
benötigt.
