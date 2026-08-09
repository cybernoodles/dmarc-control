# Datenhaltung, Backup und Restore

Dieses Dokument definiert, welche Daten der parseDMARC-Stack besitzt, wo sie
liegen und welche Abhängigkeiten bei Backup und Wiederherstellung gelten. Es
beschreibt die implementierten Abläufe und die noch erforderlichen Restore-Tests aus
[Issue #2](https://github.com/cybernoodles/parsedmarc-stack/issues/2).

## Grundsatz: Datenebene und Steuerungsebene bleiben getrennt

Der Stack verwendet bewusst zwei unabhängige Persistenzebenen:

```text
Mailbox -> parsedmarc -> OpenSearch -> DMARC Control / Grafana
                              ^
                              | historische DMARC-Daten

Administrator -> DMARC Control -> SQLite + connection.key
                                  ^
                                  | Konfiguration und Workflowzustand
```

- **OpenSearch ist die Datenebene.** Dort liegen die von parsedmarc
  normalisierten DMARC-Beobachtungen und damit die historische Grundlage für
  Kennzahlen, Sending Hosts, Warnungen und Forensik.
- **SQLite ist die Steuerungsebene von DMARC Control.** Dort liegen
  Konfiguration, manuelle Entscheidungen und Zustellzustände, aber keine Kopie
  der historischen DMARC-Reports.
- **Die Trennung ist gewollt.** Ein Verlust der Dashboard-Steuerungsdaten darf
  die OpenSearch-Historie nicht löschen. Umgekehrt ersetzt eine intakte
  SQLite-Datenbank kein Backup der DMARC-Historie.

## Dateninventar

| Ebene | Inhalt | Persistenter Pfad | Kritikalität |
|---|---|---|---|
| OpenSearch | Aggregate in `dmarc_aggregate-*`, Forensic-/Failure-Daten in `dmarc_failure-*` und optional weitere aktivierte parsedmarc-Indizes | `data/opensearch/` | Primäre historische DMARC-Daten |
| DMARC Control SQLite | Read- und Admin-Hashes samt Sitzungen, Alertstatus, Hostklassifizierungen und Notizen, globale UI-Einstellungen, Mailboxrevisionen, Benachrichtigungskonfiguration, Zustellhistorie und Parserstatus | `data/dashboard/dashboard.db` | Steuerungs- und Workflowzustand |
| Verschlüsselungsschlüssel | AES-GCM-Schlüssel für Mailbox- und Benachrichtigungs-Secrets | `data/dashboard/connection.key` | Muss gemeinsam mit SQLite gesichert werden |
| Parser-Steuerung | Gemeinsames Token zwischen Dashboard und Parser-Supervisor | `data/parser-control/control.token` | Betriebsrelevant, aber bei kontrolliertem Neustart regenerierbar |
| Stack-Konfiguration | Compose-Datei, `.env`, optionale Legacy-Konfiguration und provisionierte Grafana-Dateien | Repository, `.env`, `config/` | Für reproduzierbaren Wiederaufbau erforderlich |
| Grafana-Laufzeitdaten | Benutzer, Sitzungen, lokale Präferenzen und weitere nicht provisionierte Grafana-Zustände | `data/grafana/` | Optional, solange nur die versionierten Provisioning-Dateien verwendet werden |
| Browserpräferenzen | Lokale Sprache und lokale Farbanpassung | Local Storage des jeweiligen Browsers | Nicht Bestandteil eines Server-Backups |
| Mailboxarchive | Originale beziehungsweise archivierte Report-E-Mails | Externes Mailboxsystem | Separate Datenquelle; kein Bestandteil des Stack-Backups |

`.env`, `connection.key`, `control.token` und eine optionale
`config/parsedmarc.ini` können Secrets enthalten. Sie gehören nicht ins Git
Repository und müssen im Backup verschlüsselt sowie zugriffsgeschützt liegen.

## Was genau liegt in SQLite?

`dashboard.db` enthält aktuell folgende logische Gruppen:

- **Zugriff und Administration:** Read- und Admin-Passwort-Hashes sowie aktive Sitzungen
- **Alert-Triage:** offen, bestätigt, behoben oder ignoriert
- **Sending-Host-Bewertung:** manueller Dienstname, Zuordnungsstatus und Notiz
- **Globale Darstellung:** serverweiter Standard für das UI-Farbprofil
- **Mailboxverwaltung:** versionierte Entwürfe, getestete und aktive Revision
  sowie verschlüsselte IMAP- oder Graph-Zugangsdaten
- **Parserstatus:** zuletzt gemeldeter Modus, Revision und Laufzeitstatus
- **E-Mail-Alerting:** Versandweg, Empfänger, Ereignisauswahl, verschlüsselte
  Secrets sowie persistente Zustell- und Fehlerzustände
- **Backup-Steuerung:** Intervall, Retention, Laufstatus, Manifestverweis und
  Fehlerhistorie der Online-Sicherungen

SQLite enthält **keine** DMARC-Nachrichten, keine OpenSearch-Dokumente und
keine Ersatzkopie der von parsedmarc importierten Reporthistorie.

## Abhängigkeiten und Teilwiederherstellungen

| Vorhandene Daten | Was funktioniert? | Was fehlt oder ist gefährdet? |
|---|---|---|
| OpenSearch + SQLite + Schlüssel | Vollständiger Normalbetrieb | Nichts, sofern Versionen und Konfiguration kompatibel sind |
| Nur OpenSearch | Historische Analysen bleiben grundsätzlich verfügbar; Grafana kann mit provisionierter Konfiguration neu aufgebaut werden | Read-/Admin-Setup, Alertstatus, Klassifizierungen, Mailbox- und Alerting-Konfiguration sowie Versand-Deduplizierung fehlen |
| SQLite + Schlüssel, aber kein OpenSearch | Konfiguration und Workflowzustand sind erhalten | Dashboard-Abfragen und Grafana liefern keine historischen Daten; der Stack ist fachlich nicht betriebsbereit |
| SQLite ohne `connection.key` | Nicht verschlüsselte Zustände wie Read-/Admin-Hashes, Alertstatus und Notizen bleiben lesbar | Mailbox- und Benachrichtigungs-Secrets können nicht entschlüsselt werden; der verwaltete Parser und Graph-/SMTP-Versand können dadurch ausfallen |
| `connection.key` ohne SQLite | Keine nutzbare Anwendungspersistenz | Der Schlüssel allein enthält weder Konfiguration noch Daten |
| Repository und Konfiguration ohne `data/` | Reproduzierbare Neuinstallation | Keine Historie und kein bisheriger Workflowzustand |
| OpenSearch + ältere SQLite-Sicherung | Historie ist vorhanden | Neuere Bestätigungen, Klassifizierungen und Versand-Deduplizierungen fehlen; alte Alerts können erneut offen erscheinen oder erneut versendet werden |
| SQLite + älterer OpenSearch-Snapshot | Steuerungszustand ist vorhanden | Neuere DMARC-Beobachtungen fehlen; SQLite-Einträge können vorübergehend auf nicht vorhandene Alerts verweisen |

Verwaiste Alert- oder Zustellzustände in SQLite sind nicht destruktiv. Kritisch
ist vor allem der umgekehrte Fall: Wird eine ältere SQLite-Sicherung zusammen
mit neueren OpenSearch-Daten restauriert, kann die Anwendung bereits bekannte
Ereignisse wieder als offen und noch nicht versendet behandeln.

## Besondere Abhängigkeit des Parsers

Bei einer GUI-verwalteten Mailbox liest der Parser-Supervisor seine aktive
Revision aus SQLite über die interne Dashboard-API.

- Ist das Dashboard nur vorübergehend nicht erreichbar, läuft ein bereits
  gestarteter Parser mit der zuletzt im Arbeitsspeicher bekannten
  Konfiguration weiter.
- Startet der Parser neu und kann keine Dashboard-Konfiguration lesen, versucht
  er die Legacy-Konfiguration aus `config/parsedmarc.ini` zu verwenden.
- Startet das Dashboard mit einer leeren SQLite-Datenbank, meldet es bewusst
  den Legacy-Modus. Ein laufender verwalteter Parser kann dann auf Legacy
  wechseln.
- Fehlt zusätzlich eine gültige Legacy-Konfiguration, kann keine Mailbox
  verarbeitet werden.

Bei einem Restore müssen deshalb `dashboard.db` und `connection.key`
vollständig wiederhergestellt sein, **bevor** Dashboard und Parser gemeinsam
in den Normalbetrieb gehen.

## Implementiertes Hybridmodell

DMARC Control verwendet zwei ergänzende Sicherungswege. Beide sichern
persistente Daten und Konfiguration, niemals Container oder Images als
Primärbackup.

| Verfahren | Betrieb | Inhalt | Typischer Einsatz |
|---|---|---|---|
| Online-Backup im GUI | OpenSearch, Dashboard und Parser laufen weiter | OpenSearch-Snapshot plus SQLite, `connection.key`, `control.token` und Manifest mit gemeinsamer Backup-ID | täglich oder alle 6/12 Stunden, schnelle historische Sicherung |
| Hostseitiges Cold-Backup | Stack wird kontrolliert gestoppt und danach wieder gestartet | vollständiges `data/` sowie Stack-Dateien und Konfiguration in getrennten Archiven | wöchentlich und vor Upgrades, vollständige Disaster-Recovery |

Der Browser spricht auch für Backups ausschließlich mit FastAPI. Das Dashboard
besitzt keinen Docker-Socket. Nur das separate hostseitige Werkzeug darf den
Stack für Cold-Backup oder Restore stoppen und starten.

## Drei getrennte Backup-Produkte

### 1. Historisches Datenbackup

Enthält einen erfolgreichen OpenSearch-Snapshot einschließlich der erwarteten
DMARC-Indizes und der für den Restore erforderlichen Metadaten. Ein bloßes
Kopieren von `data/opensearch/` während OpenSearch läuft ist kein gültiges
Backup.

OpenSearch-Snapshots sind für Sicherung und Cluster-Migration vorgesehen und
können über ein Dateisystem- oder Objektspeicher-Repository abgelegt werden.
Sie sind inkrementell und müssen über die OpenSearch-API verwaltet werden:
[OpenSearch Snapshot und Restore](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore).

### 2. Dashboard-Steuerungsbackup

Enthält mindestens:

- konsistente Sicherung von `dashboard.db`
- exakt zugehörige `connection.key`
- `control.token`
- für ein vollständiges DR-Paket zusätzlich `.env` und optionale
  Legacy-Konfiguration

Für eine Sicherung bei laufendem Dashboard muss die SQLite Online Backup API
verwendet werden. Alternativ wird der Dashboard-Container vor einer normalen
Dateikopie sauber gestoppt. Eine unkoordinierte Kopie der geöffneten
SQLite-Datei ist nicht der vorgesehene Produktionsweg:
[SQLite Online Backup API](https://www.sqlite.org/backup.html).

### 3. Vollständiges Disaster-Recovery-Paket

Verknüpft das historische Datenbackup und das Steuerungsbackup über eine
gemeinsame Backup-ID. Zusätzlich enthält es ein Manifest mit:

- UTC-Zeitpunkt und eindeutiger Backup-ID
- Git-Commit beziehungsweise Release-Version
- OpenSearch- und parsedmarc-Version
- Snapshotname, Snapshotstatus und enthaltene Indizes
- Dokumentanzahl pro relevantem Index
- Ergebnis von `PRAGMA integrity_check` für die SQLite-Sicherung
- Prüfsummen aller exportierten Dateien
- Information, ob Grafana-Laufzeitdaten enthalten sind

Secrets oder Klartext-Zugangsdaten dürfen nicht in das Manifest geschrieben
werden.

## Online-Backup im Dashboard einrichten

OpenSearch benötigt für ein Dateisystem-Repository einen statischen
`path.repo`. Compose bindet daher zwei Unterverzeichnisse desselben Zielpfads
ein:

```text
DMARC_BACKUP_ROOT/
├── opensearch/    # inkrementelles OpenSearch-Snapshot-Repository, UID 1000
└── control/       # SQLite-/Schlüssel-Bundles, UID 10001
```

Das Ziel sollte auf einem zweiten Datenträger, einem NAS-Mount oder einem
anderen verschlüsselten und zugriffsgeschützten Dateisystem liegen. Ein Backup
auf derselben Platte wie `data/` schützt nicht vor einem Plattenausfall.

Beispiel für die Vorbereitung auf dem Docker-Host:

```bash
sudo install -d -m 0700 -o 1000 -g 1000 /mnt/backup/parsedmarc/opensearch
sudo install -d -m 0700 -o 10001 -g 10001 /mnt/backup/parsedmarc/control
```

Danach in `.env` den Hostpfad setzen:

```dotenv
DMARC_BACKUP_ROOT=/mnt/backup/parsedmarc
```

`path.repo` ist eine statische OpenSearch-Einstellung. Bei der erstmaligen
Aktivierung muss deshalb der OpenSearch-Container einmal kontrolliert neu
erstellt werden. Die Daten unter `data/opensearch/` werden dabei nicht
gelöscht:

```bash
docker compose up -d --force-recreate opensearch
docker compose up -d --force-recreate dashboard
```

Anschließend kann ein Administrator unter **Einstellungen → Backup & Restore**:

- Online-Backups manuell starten,
- ein Intervall von 6, 12 oder 24 Stunden beziehungsweise einer Woche wählen,
- 2 bis 90 erfolgreiche Sicherungen aufbewahren,
- Status, Zeitpunkt, Auslöser und Fehler der letzten Läufe sehen.

Jeder erfolgreiche Lauf erzeugt eine gemeinsame Backup-ID. Unter
`control/<BACKUP-ID>/` liegen `dashboard.db`, vorhandene Schlüssel und Token
sowie `manifest.json`. Das Manifest enthält Prüfsummen, SQLite-Integrität,
OpenSearch-Version, Snapshotnamen und die enthaltenen Indizes. Die eigentlichen
OpenSearch-Snapshotdateien liegen im inkrementellen Repository daneben.

Retention löscht Snapshots ausschließlich über die OpenSearch-API. Dateien im
Repository dürfen nie manuell entfernt werden, weil mehrere inkrementelle
Snapshots gemeinsame Datenblöcke verwenden können.

## Cold-Backup und Restore

Das versionierte Wartungswerkzeug wird im Stack-Verzeichnis ausgeführt. Das
Ziel muss ein absoluter Pfad außerhalb des Stack-Verzeichnisses sein:

```bash
./scripts/dmarc-maintenance cold-backup /mnt/backup/parsedmarc-cold
```

Der Ablauf speichert den vorherigen Laufzustand, erfasst OpenSearch-Metadaten,
stoppt Parser, Dashboard/Grafana und zuletzt OpenSearch, prüft SQLite, erstellt
die Archive und startet OpenSearch zuerst sowie den Parser zuletzt. Bei einem
Fehler wird ein Best-Effort-Neustart der vorher laufenden Dienste versucht. Ein
noch laufender Online-Snapshot blockiert den Cold-Ablauf mit einer klaren
Fehlermeldung, statt OpenSearch während des Snapshots zu stoppen.

Ein Paket lässt sich vor einer Übertragung oder einem Restore separat prüfen:

```bash
./scripts/dmarc-maintenance verify \
  /mnt/backup/parsedmarc-cold/cold-20260804t020000z-12345678
```

Der Restore ist absichtlich nicht Teil des Web-GUI. Er verlangt eine explizite
Bestätigung und prüft Manifest, Prüfsummen, Archivpfade, SQLite und standardmäßig
die exakte OpenSearch-Image-ID:

```bash
./scripts/dmarc-maintenance cold-restore \
  /mnt/backup/parsedmarc-cold/cold-20260804t020000z-12345678 \
  --confirm
```

Standardmäßig werden nur die persistenten Daten restauriert. Mit
`--restore-config` werden zusätzlich Compose-Datei, `.env`, Konfiguration und
die zur Sicherung gehörenden Anwendungsquellen übernommen. Eine abweichende
OpenSearch-Image-ID wird nur mit `--allow-image-mismatch` akzeptiert; diese
Option ist ausschließlich nach einer geprüften Kompatibilitätsentscheidung zu
verwenden.

Vorhandene Daten werden nicht sofort gelöscht, sondern als
`data.pre-restore-<ZEITPUNKT>` neben dem Stack aufbewahrt. Sie können nach einer
fachlich erfolgreichen Prüfung manuell entfernt oder für einen Rollback
verwendet werden.

Die Cold-Archive enthalten Secrets und möglicherweise personenbezogene
Forensic-Daten. Der Zielmount muss daher Verschlüsselung im Ruhezustand,
restriktive Berechtigungen und eine geeignete externe Aufbewahrung bereitstellen.

## Wiederherstellung aus einem Online-Backup

Ein Online-Backup ist absichtlich kein einzelnes ZIP: OpenSearch-Snapshots sind
inkrementell und teilen Dateien. Für eine Wiederherstellung werden deshalb das
vollständige Verzeichnis `opensearch/` und genau das zugehörige
`control/<BACKUP-ID>/` benötigt.

- **Nur Historie:** Snapshot-Repository auf einem leeren oder kompatiblen
  OpenSearch registrieren und den im Manifest genannten Snapshot über die
  OpenSearch-Restore-API einspielen. Gleichnamige offene Indizes müssen vorher
  geschlossen, entfernt oder beim Restore umbenannt werden.
- **Nur Steuerung:** Parser und Dashboard stoppen, Prüfsummen und
  `PRAGMA integrity_check` prüfen und `dashboard.db` zusammen mit exakt dem
  zugehörigen `connection.key` wiederherstellen. `control.token` entweder
  gemeinsam übernehmen oder kontrolliert für Dashboard und Parser neu erzeugen.
- **Beides:** Parser, Dashboard und Mailversand gestoppt halten, zuerst den
  OpenSearch-Snapshot und danach das gleich bezeichnete Control-Bundle
  restaurieren. Erst nach den Prüfungen Dashboard und zuletzt Parser starten.

Für den normalen vollständigen Disaster-Recovery-Pfad ist das automatisierte
Cold-Restore-Werkzeug vorzuziehen. Ein selektiver Online-Restore bleibt bewusst
eine administrative Wartungsaktion, weil er bestehende Indizes oder die aktive
SQLite-Datenbank ersetzen kann.

## Konsistenzgrenze

OpenSearch und SQLite benötigen keine verteilte Transaktion. Für ein
vorhersagbares vollständiges Backup sollen sie dennoch eine gemeinsame
Konsistenzgrenze erhalten:

1. Parser kontrolliert pausieren, damit keine neuen Reports importiert werden.
2. OpenSearch-Snapshot erstellen und den Status `SUCCESS` abwarten.
3. SQLite über die Online Backup API sichern oder das Dashboard kurz stoppen.
4. Schlüssel, Token und Konfigurationsdateien übernehmen.
5. Manifest und Prüfsummen erzeugen.
6. Parser erst nach erfolgreicher Prüfung wieder starten.

Die häufigen GUI-Online-Backups pausieren den Parser bewusst nicht. OpenSearch
und SQLite liefern jeweils einen konsistenten Zeitpunkt; ihre Zeitstempel und
die gemeinsame Backup-ID dokumentieren die kurze zeitliche Grenze. Das
hostseitige Cold-Backup bildet die strengere gemeinsame Konsistenzgrenze für
vollständige Disaster-Recovery.

## Sichere Restore-Reihenfolge

1. Backup-Manifest, Prüfsummen, Snapshotstatus und Versionskompatibilität
   prüfen.
2. Parser und automatisches E-Mail-Alerting während der Wiederherstellung
   nicht in den Normalbetrieb starten.
3. OpenSearch bereitstellen, Snapshot registrieren und zunächst in einen
   leeren Cluster oder unter umbenannten Indizes restaurieren.
4. Indexzustand, Dokumentzahlen und erwartete Zeitbereiche prüfen.
5. Dashboard stoppen und `dashboard.db` zusammen mit der exakt zugehörigen
   `connection.key` wiederherstellen.
6. Eigentümer und Dateirechte des Dashboard-Datenverzeichnisses prüfen.
7. Gemeinsames Parser-Control-Token wiederherstellen oder kontrolliert für
   beide Container neu erzeugen.
8. Dashboard starten und Read-/Admin-Anmeldung, aktive Mailboxrevision,
   Alerting und Stichproben der historischen Daten prüfen.
9. Erst danach den einzelnen Parser-Prozess und gegebenenfalls den
   automatischen Mailversand wieder freigeben.

OpenSearch-Snapshots sind nur begrenzt zwischen Hauptversionen kompatibel. Die
Restore-Prüfung muss deshalb die Quell- und Zielversion berücksichtigen. Bei
Namenskonflikten mit bereits offenen Indizes muss in einen leeren Cluster oder
unter umbenannten Indizes restauriert werden.

## Grafana

Die Dashboards und Datasources werden aus dem Repository provisioniert. Ohne
`data/grafana/` kann Grafana deshalb grundsätzlich neu aufgebaut werden.
Verloren gehen dabei jedoch lokale Benutzer, Sitzungen, Präferenzen und nicht
versionierte Änderungen. Sobald Grafana mehr als ein optionales
Legacy-Frontend ist oder lokale Zustände behalten werden sollen, wird
`data/grafana/` Bestandteil des vollständigen Backups.

## Empfohlener Betriebsplan

- Online-Backup täglich, bei hohem Änderungsvolumen alle 6 oder 12 Stunden
- zunächst 14 erfolgreiche Online-Backups aufbewahren
- wöchentliches Cold-Backup und zusätzlich vor Stack-/OpenSearch-Upgrades
- mindestens eine Kopie außerhalb des Docker-Hosts aufbewahren
- monatlich automatische Prüfsummenprüfung
- Restore quartalsweise in einer isolierten Zielinstallation testen

Das wöchentliche Cold-Backup kann durch den Host-Scheduler unter einem Benutzer
mit Docker-Zugriff ausgeführt werden. Zielmount und Logverzeichnis müssen für
diesen Benutzer beschreibbar sein, beispielsweise:

```cron
15 3 * * 0 cd /opt/stacks/parsedmarc && ./scripts/dmarc-maintenance cold-backup /mnt/backup/parsedmarc-cold >> /mnt/backup/parsedmarc-cold/backup.log 2>&1
```

Issue #2 gilt erst nach einem erfolgreichen isolierten Test von Online-Snapshot
und Cold-Restore als betrieblich abgeschlossen. Die Werkzeuge sind vorhanden;
der Test darf nicht erstmals in der produktiven Installation stattfinden.
