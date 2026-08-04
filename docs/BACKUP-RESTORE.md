# Datenhaltung, Backup und Restore

Dieses Dokument definiert, welche Daten der parseDMARC-Stack besitzt, wo sie
liegen und welche Abhängigkeiten bei Backup und Wiederherstellung gelten. Es
ist die fachliche Grundlage für die noch zu automatisierenden Abläufe aus
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
| DMARC Control SQLite | Admin-Hash, Alertstatus, Hostklassifizierungen und Notizen, globale UI-Einstellungen, Mailboxrevisionen, Benachrichtigungskonfiguration, Zustellhistorie und Parserstatus | `data/dashboard/dashboard.db` | Steuerungs- und Workflowzustand |
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

- **Administration:** Passwort-Hash und aktive Admin-Sitzungen
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
| Nur OpenSearch | Historische Analysen bleiben grundsätzlich verfügbar; Grafana kann mit provisionierter Konfiguration neu aufgebaut werden | Admin-Setup, Alertstatus, Klassifizierungen, Mailbox- und Alerting-Konfiguration sowie Versand-Deduplizierung fehlen |
| SQLite + Schlüssel, aber kein OpenSearch | Konfiguration und Workflowzustand sind erhalten | Dashboard-Abfragen und Grafana liefern keine historischen Daten; der Stack ist fachlich nicht betriebsbereit |
| SQLite ohne `connection.key` | Nicht verschlüsselte Zustände wie Admin-Hash, Alertstatus und Notizen bleiben lesbar | Mailbox- und Benachrichtigungs-Secrets können nicht entschlüsselt werden; der verwaltete Parser und Graph-/SMTP-Versand können dadurch ausfallen |
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
- verschlüsselte Kopie von `.env` und optionaler Legacy-Konfiguration

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
8. Dashboard starten und Admin-Anmeldung, aktive Mailboxrevision, Alerting und
   Stichproben der historischen Daten prüfen.
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

## Noch zu automatisieren

Issue #2 ist erst abgeschlossen, wenn Werkzeuge für folgende Schritte
vorliegen und in einer isolierten Zielinstallation getestet wurden:

- datierte Backup-ID und Manifest erzeugen
- OpenSearch-Snapshot anlegen und auf `SUCCESS` prüfen
- konsistentes SQLite-Backup inklusive `integrity_check` erzeugen
- Schlüssel, Token und Konfiguration sicher bündeln
- Prüfsummen und Versionskompatibilität vor dem Restore prüfen
- Restore wahlweise in eine neue oder bestehende Installation durchführen
- Parser und Mailversand während des Restore sicher gesperrt halten
- typische Fehlerfälle mit klaren Abbruchmeldungen behandeln

