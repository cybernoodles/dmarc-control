# Datenhaltung, Backup und Restore

Dieses Dokument definiert, welche Daten DMARC Control besitzt, wo sie liegen
und wie die automatisierten Backup- und Restore-Abläufe aus
[Issue #2](https://github.com/cybernoodles/dmarc-control/issues/2) betrieben
werden.

## Grundsatz: Datenebene und Steuerungsebene bleiben getrennt

Der Stack verwendet bewusst zwei unabhängige Persistenzebenen:

```text
Mailbox -> parsedmarc -> OpenSearch -> DMARC Control / optionales Grafana
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
| Backup-Recovery-Key | Separater AES-256-GCM-Schlüssel für das verschlüsselte Steuerungsbackup | `data/dashboard/backup.key` | Muss getrennt vom Backup-Verzeichnis sicher verwahrt werden |
| Parser-Steuerung | Gemeinsames Token zwischen Dashboard und Parser-Supervisor | `data/parser-control/control.token` | Betriebsrelevant, aber bei kontrolliertem Neustart regenerierbar |
| Stack-Konfiguration | Compose-Datei, `.env` inklusive der Profilwahl, optionale Legacy-Konfiguration und provisionierte Grafana-Dateien | Repository, `.env`, `config/` | Für reproduzierbaren Wiederaufbau erforderlich |
| Grafana-Laufzeitdaten | Benutzer, Sitzungen, lokale Präferenzen und weitere nicht provisionierte Grafana-Zustände | `data/grafana/` | Nur bei aktiviertem Profil `grafana`; optional, solange nur die versionierten Provisioning-Dateien verwendet werden |
| Browserpräferenzen | Lokale Sprache und lokale Farbanpassung | Local Storage des jeweiligen Browsers | Nicht Bestandteil eines Server-Backups |
| Mailboxarchive | Originale beziehungsweise archivierte Report-E-Mails | Externes Mailboxsystem | Separate Datenquelle; kein Bestandteil des Stack-Backups |
| Integrierte Backups | OpenSearch-Repository, Manifeste und verschlüsselte Steuerungsarchive | `backups/` beziehungsweise `DMARC_BACKUP_ROOT` | Nicht zusammen mit den Primärdaten als einzige Kopie auf demselben Datenträger belassen |

`.env`, `connection.key`, `backup.key`, `control.token` und eine optionale
`config/parsedmarc.ini` können Secrets enthalten. Sie gehören nicht ins Git
Repository und müssen im Backup verschlüsselt sowie zugriffsgeschützt liegen.

## Verpflichtende Backup-Strategie im Setup

DMARC Control startet nicht stillschweigend mit einer angenommenen Strategie.
Bei einer Neuinstallation wird zusammen mit Read- und Admin-Zugang eine der
folgenden Optionen gewählt. Bestehende Installationen werden nach dem nächsten
Read-Login einmalig zu derselben administrativen Entscheidung geführt:

| Strategie | Verhalten |
|---|---|
| **Integrierte Dumps** | Der `backup`-Dienst erstellt sofort das erste Steuerungsbackup und danach täglich nach dem konfigurierten UTC-Zeitplan; vorhandene DMARC-Indizes werden jeweils per Snapshot ergänzt. |
| **Externe Sicherung** | Der Dienst bleibt inaktiv, weil VM oder Host bereits anwendungskonsistent gesichert werden. |
| **Kein Backup** | Der Dienst bleibt inaktiv. Diese Auswahl ist ausschließlich für bewusst kurzlebige Testsysteme vorgesehen. |

Es gibt keine vorausgewählte Option. Die Strategie kann später unter
**Einstellungen → Backup & Wiederherstellung** geändert werden. Beim Aktivieren
der integrierten Dumps wird ein erster Sicherungsversuch ausgelöst. Beim
Deaktivieren bleiben vorhandene Backups unverändert erhalten.

Eine Sicherung des Container-Images oder ein `docker export` ist keine externe
Datensicherung: Die produktiven Daten liegen in Bind-Mounts auf dem Host. Eine
gültige externe Sicherung muss mindestens `data/`, `.env`, die Compose-Datei
und die installationsspezifische Konfiguration erfassen. Wird die VM im
laufenden Betrieb gesichert, muss die Sicherung OpenSearch und SQLite
anwendungskonsistent behandeln; der kontrollierte Stack-Stopp ist die
einfachste belastbare Konsistenzgrenze.

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

SQLite enthält **keine** DMARC-Nachrichten, keine OpenSearch-Dokumente und
keine Ersatzkopie der von parsedmarc importierten Reporthistorie.

## Abhängigkeiten und Teilwiederherstellungen

| Vorhandene Daten | Was funktioniert? | Was fehlt oder ist gefährdet? |
|---|---|---|
| OpenSearch + SQLite + Schlüssel | Vollständiger Normalbetrieb | Nichts, sofern Versionen und Konfiguration kompatibel sind |
| Nur OpenSearch | Historische Analysen bleiben grundsätzlich verfügbar; optionales Grafana kann mit provisionierter Konfiguration neu aufgebaut werden | Read-/Admin-Setup, Alertstatus, Klassifizierungen, Mailbox- und Alerting-Konfiguration sowie Versand-Deduplizierung fehlen |
| SQLite + Schlüssel, aber kein OpenSearch | Konfiguration und Workflowzustand sind erhalten | Dashboard-Abfragen und optionales Grafana liefern keine historischen Daten; der Stack ist fachlich nicht betriebsbereit |
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

## Drei getrennte Backup-Produkte

### 1. Historisches Datenbackup

Enthält einen erfolgreichen OpenSearch-Snapshot aller nicht systeminternen
Indizes einschließlich der für den Restore erforderlichen Metadaten. Dadurch
werden neben `dmarc_aggregate-*` und `dmarc_failure-*` auch weitere bewusst
aktivierte parsedmarc-Datentypen erfasst. Der globale Clusterzustand wird nicht
gesichert, damit ein Restore keine Sicherheitseinstellungen oder anderen
Zielclusterzustand überschreibt. Ein bloßes Kopieren von `data/opensearch/`
während OpenSearch läuft ist kein gültiges Backup.

OpenSearch-Snapshots sind für Sicherung und Cluster-Migration vorgesehen und
können über ein Dateisystem- oder Objektspeicher-Repository abgelegt werden.
Sie sind inkrementell und müssen über die OpenSearch-API verwaltet werden:
[OpenSearch Snapshot und Restore](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore).

### 2. Dashboard-Steuerungsbackup

Enthält mindestens:

- konsistente Sicherung von `dashboard.db`
- exakt zugehörige `connection.key`
- `control.token`
- verschlüsselte Kopie von `.env`, Compose-Datei und optionaler
  Legacy-Konfiguration

Der integrierte Dienst verwendet bei laufendem Dashboard die SQLite Online
Backup API und prüft die Kopie anschließend mit `PRAGMA integrity_check`.
`dashboard.db`, `connection.key`, `control.token`, `.env`, Compose-Datei und
optionale Legacy-Konfiguration werden gemeinsam als Tar-Archiv erzeugt und mit
einem separaten 256-Bit-Schlüssel per AES-256-GCM authentifiziert verschlüsselt.
Eine unkoordinierte Kopie der geöffneten SQLite-Datei ist nicht der vorgesehene
Produktionsweg:
[SQLite Online Backup API](https://www.sqlite.org/backup.html).

Der Recovery-Key liegt unter `data/dashboard/backup.key` und wird **nicht** in
das Backup-Archiv aufgenommen. Sein Fingerprint ist im Manifest und im UI
sichtbar. Der Schlüssel muss separat exportiert und beispielsweise im
Passwortsafe oder Offline-Tresor verwahrt werden:

```bash
docker compose exec backup dmarc-backup export-key
```

Ohne diesen Schlüssel bleibt die OpenSearch-Historie mit den Optionen
`verify --history-only` und `restore --history-only` restaurierbar, das
verschlüsselte Steuerungsarchiv kann jedoch nicht entschlüsselt werden.

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

Die aktuelle Manifestversion ist `dmarc-control.backup.v1`. Zu jedem Manifest
existiert eine SHA-256-Datei; das verschlüsselte Steuerungsarchiv besitzt eine
eigene SHA-256-Prüfsumme. Wenn historische Indizes vorhanden sind, wird die
Snapshotvollständigkeit zusätzlich über die OpenSearch-API, den Zustand
`SUCCESS`, die Shardanzahl, das Indexinventar und die Dokumentzahlen geprüft.

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

Für reine häufige OpenSearch-Snapshots muss der Parser nicht zwingend pausiert
werden. Die gemeinsame Pause ist für ein vollständiges, zusammengehöriges
Disaster-Recovery-Paket vorgesehen.

## Ablage, Zeitplan und Aufbewahrung

Standardmäßig wird unter `./backups` gesichert. Dieses Verzeichnis ist von Git
ausgeschlossen. Für Schutz vor einem Host- oder Datenträgerverlust muss
`DMARC_BACKUP_ROOT` auf ein getrenntes, zuverlässig eingebundenes Dateisystem
zeigen oder das Verzeichnis nach jedem erfolgreichen Lauf extern repliziert
werden. Eine zweite Kopie auf demselben Primärdatenträger ist kein vollständiger
Disaster-Recovery-Schutz.

Vor dem ersten Compose-Start werden die Pfade mit den Container-IDs
vorbereitet:

```bash
mkdir -p backups/opensearch/repository backups/manifests backups/control
sudo chown -R 10001:10001 backups
sudo chmod 0770 backups backups/manifests backups/control
sudo chmod 2770 backups/opensearch backups/opensearch/repository
```

Die Standardwerte stehen in `.env.example`:

```dotenv
DMARC_BACKUP_ROOT=./backups
DMARC_BACKUP_SCHEDULE="0 2 * * *"
DMARC_BACKUP_RETENTION_DAYS=30
```

Der Zeitplan ist aktuell ein täglicher UTC-Cronausdruck mit numerischer Minute
und Stunde. Beim ersten Wechsel auf **Integrierte Dumps** wird nicht bis zum
nächsten Zeitfenster gewartet. Gibt es noch keinen historischen Index, entsteht
trotzdem ein vollständiges, verschlüsseltes Steuerungsbackup; das Manifest
kennzeichnet den OpenSearch-Snapshot dann als nicht erforderlich. So ist die
Konfiguration ab dem Setup gesichert, ohne einen leeren Verlauf fälschlich als
gesicherte DMARC-Historie auszugeben.

Abgelaufene Snapshots werden ausschließlich über die OpenSearch-API gelöscht.
Dateien im inkrementellen Repository dürfen niemals manuell entfernt werden,
weil mehrere Snapshots gemeinsame Datenblöcke verwenden können. Mindestens ein
erfolgreiches Backup bleibt unabhängig von der Aufbewahrungsfrist erhalten.

## CLI-Betrieb

Das CLI läuft im bereits gestarteten Backup-Container:

| Zweck | Befehl |
|---|---|
| Strategie und Laufzeitstatus | `docker compose exec backup dmarc-backup status` |
| Erfolgreiche Backups auflisten | `docker compose exec backup dmarc-backup list` |
| Sofort sichern | `docker compose exec backup dmarc-backup now` |
| Backup vollständig prüfen | `docker compose exec backup dmarc-backup verify latest` |
| Aufbewahrung jetzt anwenden | `docker compose exec backup dmarc-backup prune` |
| Recovery-Key für getrennte Ablage ausgeben | `docker compose exec backup dmarc-backup export-key` |
| Verschlüsselte Stack-Konfiguration zur Prüfung extrahieren | `docker compose exec backup dmarc-backup extract-config latest` |

`now` verweigert den Lauf bei der Strategie **Externe Sicherung** oder **Kein
Backup**. Ein bewusstes einmaliges Backup ist mit `now --force` möglich, ohne
die gespeicherte Strategie zu verändern. Gleichzeitige Backup-, Prune- und
Restore-Operationen werden durch einen exklusiven Lock verhindert.

## Sichere Restore-Reihenfolge

Vor einem Restore müssen Backup-Verzeichnis und der separat verwahrte
`backup.key` verfügbar sein. Bei einer neuen Installation wird der Recovery-Key
vorübergehend als `data/dashboard/backup.key` mit Eigentümer 10001 und Modus
`0600` abgelegt.

Zunächst Parser, Dashboard und den automatischen Backup-Dienst stoppen; nur
OpenSearch bleibt aktiv:

```bash
docker compose stop parsedmarc dashboard backup
docker compose up -d opensearch
```

Danach das ausgewählte Paket prüfen und restaurieren:

```bash
docker compose run --rm --no-deps backup verify latest
docker compose run --rm --no-deps backup restore latest
```

Ein neuer oder leerer Cluster wird direkt restauriert. Existieren Zielindizes
mit denselben Namen, bricht das Tool standardmäßig ab. Für eine bewusst
ersetzende Wiederherstellung ist die ausdrückliche Option erforderlich:

```bash
docker compose run --rm --no-deps backup restore latest --replace-existing
```

Vor dem Löschen kollidierender Indizes erzeugt das Tool einen zusätzlichen
`pre-restore-*`-Snapshot. Anschließend werden Snapshotstatus, Shards,
Indexinventar und Dokumentzahlen geprüft. Bei einem vollständigen Restore
werden `dashboard.db`, `connection.key`, `backup.key` und `control.token`
atomar eingesetzt; vorhandene Zieldateien werden zuvor unter
`backups/restore-safety/` abgelegt. `.env` und Compose-Datei werden nicht
automatisch überschrieben. Sie können mit `extract-config` entschlüsselt und
vor der manuellen Übernahme verglichen werden.

Der Restore lässt `backup.lock` absichtlich bestehen. Dadurch bleiben Parser
und automatischer Mailversand gesperrt, während das Dashboard geprüft wird:

```bash
docker compose up -d dashboard
# Read-/Admin-Anmeldung, aktive Mailboxrevision, Alerting und Historie prüfen
docker compose run --rm --no-deps backup release
docker compose up -d backup parsedmarc
```

OpenSearch-Snapshots sind nur begrenzt zwischen Versionen kompatibel. Das Tool
verweigert einen Restore in eine andere Hauptversion sowie in eine ältere
Zielversion. `--history-only` restauriert ausschließlich OpenSearch; diese
Option verändert weder SQLite noch Schlüssel und ist für eine gezielte
Datenebenen-Wiederherstellung vorgesehen.

## Optionales Grafana-Profil

Grafana wird nur mit dem Compose-Profil `grafana` betrieben. Die Dashboards und
Datasources werden aus dem Repository provisioniert. Ohne `data/grafana/` kann
Grafana deshalb grundsätzlich neu aufgebaut werden. Verloren gehen dabei jedoch
lokale Benutzer, Sitzungen, Präferenzen und nicht versionierte Änderungen.
Das integrierte Backup enthält bewusst keine Grafana-Laufzeitdaten. Sobald
lokale Grafana-Benutzer oder nicht provisionierte Zustände erhalten werden
müssen, ist `data/grafana/` zusätzlich über die externe VM-/Host-Sicherung zu
schützen. Bei Installationen ohne Grafana-Profil existiert dieses Backup-Objekt
nicht.

## Typische Fehlerfälle

| Meldung oder Zustand | Ursache und sichere Reaktion |
|---|---|
| `Backup strategy is not configured` | Die verpflichtende Auswahl im Setup oder unter Einstellungen abschließen. |
| Manifest enthält keinen Snapshot | Erwartet, wenn beim Lauf noch kein fachlicher OpenSearch-Index vorhanden war; das Steuerungsbackup bleibt gültig. |
| Snapshot-Repository nicht beschreibbar | Eigentümer und Modus von `DMARC_BACKUP_ROOT/opensearch` prüfen; OpenSearch verwendet UID 1000 und die zusätzliche Gruppe 10001. |
| Parser bestätigt die Pause nicht | Parserstatus und Logs prüfen. Der Lauf bricht ab und entfernt seinen eigenen Wartungs-Lock. |
| Snapshotzustand nicht `SUCCESS` | Dump nicht verwenden; Shard- und OpenSearch-Fehler beheben und neu sichern. |
| Manifest- oder Archiv-Prüfsumme falsch | Paket als beschädigt behandeln und eine andere Kopie verwenden. |
| Recovery-Key-Fingerprint falsch | Den separat zu dieser Installation exportierten Schlüssel bereitstellen; keine Entschlüsselungsversuche mit anderen Schlüsseln. |
| Zielindizes existieren | Zunächst Ziel und Backup-ID prüfen; nur bei bewusstem Ersetzen `--replace-existing` verwenden. |
| Dashboard läuft beim vollständigen Restore | Dashboard, Parser und Backup-Dienst stoppen; niemals die geöffnete SQLite-Datei überschreiben. |
| Restore abgebrochen, `backup.lock` bleibt liegen | Ursache prüfen und Restore fortsetzen oder nach nachgewiesen konsistentem Zustand bewusst `dmarc-backup release` ausführen. |
