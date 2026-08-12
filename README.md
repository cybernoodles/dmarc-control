# DMARC Control

DMARC Control ist eine selbst gehostete Plattform zur Auswertung und
Überwachung von DMARC-Berichten. Sie baut auf
[parsedmarc](https://github.com/domainaware/parsedmarc) auf und kombiniert den
Parser mit OpenSearch sowie einem eigenen Webdashboard – vollständig
containerisiert mit Docker Compose. Grafana bleibt vorläufig als optionales
Compose-Profil für bestehende Installationen verfügbar, gehört aber nicht mehr
zur Standardinstallation.

## Stack

| Component | Image | Zweck |
|---|---|---|
| DMARC Control | lokaler Multi-Stage-Build | Eigenes risikoorientiertes Webdashboard und API |
| parsedmarc 10.4.0 | `ghcr.io/domainaware/parsedmarc:10.4.0` + lokaler Supervisor | Ein verwalteter Mailbox-Consumer für Microsoft Graph oder IMAP |
| OpenSearch 2.x | `opensearchproject/opensearch:2` | Datenspeicher |
| Grafana (optional) | `grafana/grafana:latest` | Übergangsvisualisierung im Compose-Profil `grafana` |

## Voraussetzungen

- Docker + Docker Compose
- `vm.max_map_count` auf mindestens 262144 gesetzt (OpenSearch-Pflicht)

```bash
# Einmalig setzen
sudo sysctl -w vm.max_map_count=262144

# Dauerhaft machen
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-opensearch.conf
```

## Verzeichnisstruktur

```
dmarc-control/
├── docker-compose.yml
├── .env                                    ← Passwörter (nicht ins Git!)
├── .env.example                            ← Vorlage ohne echte Werte
├── .gitignore
├── README.md
├── docs/
│   ├── BACKLOG.md                           ← geplante Weiterentwicklung von DMARC Control
│   ├── BACKUP-RESTORE.md                    ← Dateninventar und Wiederherstellungsabhängigkeiten
│   ├── M365.md                              ← M365-Setup und RBAC-Prüfung
│   ├── MIGRATION-TO-PORTABLE-DATA.md        ← Einmalmigration bestehender Docker-Volumes
│   └── CUSTOM-DASHBOARD.md                  ← Architektur und Betrieb von DMARC Control
├── dashboard/
│   ├── Dockerfile                           ← React-Build und FastAPI-Laufzeit
│   ├── frontend/                            ← React, TypeScript und ECharts
│   └── backend/                             ← Kontrollierte OpenSearch-API und lokale Zustände
├── parser/
│   ├── Dockerfile                           ← gepinntes parsedmarc 10.4.0
│   └── supervisor.py                        ← übernimmt nur aktivierte GUI-Konfigurationen
├── data/                                    ← Persistente Laufzeitdaten (nicht im Git)
│   ├── opensearch/                          ← Indizes und OpenSearch-Zustand
│   ├── grafana/                             ← optional: Grafana SQLite, Benutzer und Plugins
│   ├── dashboard/                           ← UI-Zustände, Zugangs-Hashes und verschlüsselte Verbindungen
│   └── parser-control/                      ← automatisch erzeugtes internes Control-Token
├── config/
│   ├── parsedmarc.ini                       ← optionaler Legacy-/Migrations-Fallback
│   ├── parsedmarc.ini.example               ← Referenz für bestehende Installationen
│   └── grafana/                             ← optionales Provisioning
│       └── provisioning/
│           ├── datasources/
│           │   └── opensearch.yml          ← Grafana Datasources (auto-provisioniert)
│           └── dashboards/
│               ├── dashboards.yml          ← Grafana Dashboard Provider
│               ├── DMARC-Overview.json     ← Haupt-Dashboard (auto-provisioniert)
│               ├── DMARC-Analysis.json     ← Detailanalyse (auto-provisioniert)
│               └── Forensic/
│                   └── DMARC-Forensic.json ← RUF-Analyse (separater Ordner)
└── dmarc-reports/                           ← optional: Reports als Dateien ablegen
```

## Installation

**1. Repo klonen**

```bash
git clone https://github.com/cybernoodles/dmarc-control.git
cd dmarc-control
```

**2. Konfiguration anlegen**

```bash
# Konfiguration und Passwörter setzen
cp .env.example .env
nano .env
```

Die Mailbox wird nach dem ersten Start im Webdashboard konfiguriert. Eine
`config/parsedmarc.ini` ist für neue Installationen nicht erforderlich.

### Deployment-Varianten

| Variante | `COMPOSE_PROFILES` | Laufende Dienste |
|---|---|---|
| Standard/Kunde | leer | OpenSearch, DMARC Control, parsedmarc |
| Übergang/Bestand mit Grafana | `grafana` | Kern-Stack plus Grafana |

In der Standardinstallation bleiben diese beiden Werte leer:

```dotenv
COMPOSE_PROFILES=
GRAFANA_ADMIN_PASSWORD=
```

Damit besteht der Stack ausschließlich aus OpenSearch, DMARC Control und
parsedmarc. Für eine bestehende Installation, die Grafana vorläufig weiter
betreiben soll, muss die lokale `.env` stattdessen beide Werte enthalten:

```dotenv
COMPOSE_PROFILES=grafana
GRAFANA_ADMIN_PASSWORD=EIN_EIGENES_STARKES_PASSWORT
```

`COMPOSE_PROFILES` ist damit die verbindliche, installationsspezifische
Auswahl. Der Kommandozeilenparameter `--profile grafana` ist zwar ebenfalls
möglich, sollte für dauerhafte Installationen aber nicht der einzige Nachweis
der gewählten Variante sein.

**3. Datenverzeichnisse vorbereiten**

Die persistenten Daten liegen unter `./data`, damit das Projektverzeichnis
vollständig auf einen anderen Host übertragen werden kann. Die Inhalte sind
absichtlich nicht versioniert.

```bash
mkdir -p data/opensearch data/dashboard data/parser-control dmarc-reports
sudo chown 1000:1000 data/opensearch
sudo chown 10001:10001 data/dashboard data/parser-control
```

Nur bei aktiviertem Grafana-Profil wird zusätzlich dessen Datenverzeichnis
benötigt:

```bash
mkdir -p data/grafana
sudo chown 472:472 data/grafana
```

OpenSearch läuft im Container als UID 1000, DMARC Control als UID 10001 und
das optionale Grafana als UID 472. Ohne diese Eigentümer kann der jeweilige
Dienst beim ersten Start nicht in sein Datenverzeichnis schreiben. Beim ersten
Aufruf von DMARC Control führt ein Setup-Screen durch das einmalige Festlegen
eines Read-Benutzers mit Passwort und des separaten Admin-Passworts. Das
Dashboard ist anschließend nur mit einer gültigen Read-Sitzung erreichbar.

Bei bestehenden Installationen ohne Read-Benutzer erscheint nach dem Update
ebenfalls der Setup-Screen. Das vorhandene Admin-Passwort muss dort bestätigt
werden; es wird nicht ersetzt. Danach wird lediglich der neue Read-Zugang
ergänzt.

> **Dockge:** Relative Pfade wie `./data` beziehen sich auf den Ordner der
> Compose-Datei. Daher entweder das gesamte Repository als Stack-Ordner
> verwenden oder beim Übertragen nach Dockge die relativen Pfade (`./config`,
> `./data` und `./dmarc-reports`) konsistent auf den Projektordner umstellen.

**4. Stack starten**

```bash
docker compose up -d --build --remove-orphans
```

Beim ersten Start werden das Dashboard und der kleine Parser-Supervisor lokal
gebaut. Die darunterliegende parsedmarc-Version ist reproduzierbar auf 10.4.0
gepinnt. Ohne `COMPOSE_PROFILES=grafana` wird weder ein Grafana-Container
erzeugt noch Port `3020` veröffentlicht.

**5. Logs verfolgen**

```bash
docker compose logs -f parsedmarc
```

### Bestehende Installation migrieren

Bestehende Installationen, die Grafana behalten sollen, müssen vor dem ersten
Start mit dieser Compose-Version `COMPOSE_PROFILES=grafana` sowie ein
`GRAFANA_ADMIN_PASSWORD` in ihrer `.env` setzen. Damit bleiben Container, Port
und Datenpfad bei den gewohnten Compose-Befehlen Bestandteil des Stacks.

Ältere Versionen dieses Repositories verwendeten Docker-Volumes für
OpenSearch und Grafana. Die einmalige, datenerhaltende Übernahme in das neue
`data/`-Layout ist in [docs/MIGRATION-TO-PORTABLE-DATA.md](docs/MIGRATION-TO-PORTABLE-DATA.md)
beschrieben. Nicht vorab einen leeren Stack mit dem neuen Compose starten.

## Mailbox-Konfiguration

Die Einrichtung erfolgt unter **Einstellungen → Postfachanbindung**:

1. Als Admin anmelden und Microsoft 365 oder IMAP auswählen.
2. Verbindungsdaten eingeben und als neuen Entwurf speichern.
3. **Verbindung testen**. Dieser Test authentifiziert sich und prüft nur den
   lesenden Zugriff auf die angegebenen Ordner. Er liest, verarbeitet,
   verschiebt und löscht keine Nachrichten.
4. Den erfolgreich getesteten Entwurf ausdrücklich aktivieren. Der Supervisor
   beendet bei einem Wechsel seinen bisherigen Kindprozess kontrolliert und
   startet genau einen parsedmarc-Prozess mit der neuen Revision.

Das Client Secret beziehungsweise IMAP-Passwort wird verschlüsselt in
`data/dashboard/dashboard.db` abgelegt. Der AES-Schlüssel entsteht automatisch
als `data/dashboard/connection.key`; für ein vollständiges Backup werden beide
Dateien benötigt. Weder Secret noch Schlüssel werden über die API an den
Browser zurückgegeben.

### Microsoft 365 via Microsoft Graph API (empfohlen)

Für den Betrieb ein separates Postfach wie `dmarc-reports@example.com` mit dem
Ordner `Inbox/DMARC` verwenden. Es enthält ausschließlich DMARC-Reports und wird
nicht interaktiv genutzt.

- **Berechtigung:** App-only `Mail.ReadWrite`; parsedmarc archiviert verarbeitete Nachrichten.
- **Scope:** Zugriff zwingend auf dieses eine Postfach beschränken. Für neue Unternehmens-Setups ist Exchange Online Application RBAC vorgesehen; das ausführliche Vorgehen steht in [docs/M365.md](docs/M365.md).
- **Anmeldung:** Die aktuelle GUI unterstützt App-only `ClientSecret`.
  Eigentümer, Ablaufdatum und Rotation müssen dokumentiert werden.

### Forensic-/RUF-Reports (nur nach Freigabe)

Forensic-Berichte können Header, Empfänger und Betreffzeilen enthalten. Die Speicherung ist deshalb standardmäßig deaktiviert. Ein `git pull` aktiviert sie **nicht** und ändert auch keine vorhandene `config/parsedmarc.ini`.

Erst nach Freigabe von Retention, Berechtigungskonzept und Incident-Prozess in
der lokalen `.env` aktivieren:

```dotenv
PARSEDMARC_SAVE_FAILURE=True
```

Der Compose-Wert wird als parsedmarc-Option `save_failure` übernommen.
Bestehende Legacy-Konfigurationen mit `save_forensic = True` funktionieren
weiterhin, da parsedmarc dies als Alias behandelt. Nicht beide Optionen
gleichzeitig setzen – `save_failure` hat Vorrang.

Danach parsedmarc neu starten und eingehende RUF-Berichte abwarten:

```bash
docker compose restart parsedmarc
```

Bei aktiviertem Grafana-Profil zeigt das zusätzliche Dashboard **DMARC
Forensic Analysis** ausschließlich minimierte Betriebsmetadaten – keine
Betreffzeilen, Empfänger, Header oder Rohinhalte. Es wird in den separaten
Grafana-Ordner **Forensic** provisioniert. Diesem Ordner in Grafana nur den
zuständigen Security-/Incident-Rollen Zugriff gewähren.

### IMAP

Host, Port, TLS, Benutzer, Passwort sowie Report- und Archivordner werden
ebenfalls unter **Einstellungen → Postfachanbindung** verwaltet. Der Verbindungstest
öffnet die Ordner mit `read-only`; Abruf und Verarbeitung beginnen erst nach
der expliziten Aktivierung.

## E-Mail-Benachrichtigungen

Das Alerting wird unter **Einstellungen → Benachrichtigungen** eingerichtet und
ist nach Installation oder Update standardmäßig deaktiviert. Unterstützt werden:

- SMTP mit STARTTLS, implizitem TLS oder einem explizit gewählten internen Relay,
  jeweils mit optionaler Benutzeranmeldung
- Microsoft Graph mit einer eigenen App-Registrierung oder wiederverwendeten
  Zugangsdaten der gespeicherten Microsoft-365-Postfachanbindung

Für Graph-Versand benötigt die App-Registrierung die Application-Berechtigung
`Mail.Send`. Der Zugriff sollte in Exchange Online auf das konfigurierte
Absenderpostfach begrenzt werden.

Empfänger, E-Mail-Sprache, öffentliche Dashboard-URL und auslösende Fälle sind
im GUI wählbar. Ein expliziter Testversand ist möglich, ohne das automatische
Alerting einzuschalten. Jede Nachricht enthält eine HTML- und Klartext-Version,
stabile `X-DMARC-Control-*`-Header und den versionierten JSON-Anhang
`dmarc-alert.json`. Erfolgreich versendete Ereignisse werden in
`dashboard.db` dedupliziert; vorübergehende Fehler werden höchstens dreimal mit
ansteigendem Abstand versucht.

## Optionales Grafana-Profil

Grafana ist nicht Bestandteil der Standardinstallation. Es bleibt als
Übergangsvariante in derselben Compose-Datei versioniert und wird nur mit
`COMPOSE_PROFILES=grafana` in der lokalen `.env` oder explizit mit
`docker compose --profile grafana ...` aktiviert.

| URL | Credentials |
|---|---|
| `http://HOSTNAME:3020` | `admin` / Passwort aus `.env` |

Grafana provisioniert drei versionierte Dashboards und öffnet nach Anmeldung direkt **DMARC Overview**:

- **DMARC Overview:** Betriebsstatus, Datenfrische, DMARC-Trend und Policies; Zeitraum 30 Tage, Aktualisierung alle 5 Minuten.
- **DMARC Analysis:** Sender-, IP-, SPF- und DKIM-Detailanalyse; Zeitraum 90 Tage. Forensic-Daten sind bewusst ausgeschlossen.
- **DMARC Forensic Analysis:** RUF-/Forensic-Untersuchung mit 30 Tagen Standardzeitraum und begrenzten Aggregationen. Aktuelle parsedmarc-Versionen speichern diese Berichte in `dmarc_failure-*`; das Dashboard bleibt leer, solange `save_failure = False` gesetzt ist oder keine RUF-Berichte eingehen.

Datasources und Dashboards sind schreibgeschützt provisioniert. Änderungen
erfolgen im Repository und werden danach mit `docker compose restart grafana`
übernommen. Damit bleibt die laufende Instanz nachvollziehbar und frei von
UI-Drift.

Die Grafana-Version bleibt vorläufig bewusst unverändert auf `latest`, wie in
`docker-compose.yml` definiert.

Um Grafana in einer bestehenden Installation kontrolliert stillzulegen, zuerst
den Dienst stoppen und entfernen:

```bash
docker compose --profile grafana stop grafana
docker compose --profile grafana rm -f grafana
```

Danach `COMPOSE_PROFILES=` und `GRAFANA_ADMIN_PASSWORD=` in `.env` leeren. Das
Verzeichnis `data/grafana/` wird dabei nicht gelöscht und kann bis zum Ende der
vereinbarten Rückrollfrist gesichert aufbewahrt werden.

## DMARC Control

Das eigene Webdashboard ist die Standardoberfläche. Das optionale Grafana kann
in Übergangsinstallationen parallel laufen. Für die Normalisierung und Ablage
der DMARC-Berichte verwendet DMARC Control
[parsedmarc](https://github.com/domainaware/parsedmarc) als technische Basis:

- Übersicht mit Volumen, Passrate, echten DMARC-Fails, Datenfrische und Trend
- klare Trennung zwischen finalem DMARC-Fail und kompensiertem SPF-/DKIM-Alignment
- vollständiges Sending-Host-Inventar mit IP, PTR, ASN/Land, Identitäten und Last Seen
- mehrstufige Dienst-Erkennung mit Konfidenz und manueller Bestätigung
- deduplizierte Warnungen mit Status `offen`, `bestätigt`, `behoben` und `ignoriert`
- durchgängige Alert-Triage mit direkter Sending-Host-Untersuchung, Rückweg zum
  Ausgangs-Alert und kompatiblen Deep Links aus E-Mail-Benachrichtigungen
- konfigurierbares E-Mail-Alerting über SMTP oder Microsoft Graph
- datenschutzreduzierte Forensik ohne Laden von Rohinhalt, Empfängern, Betreff oder Headern

Der Browser spricht ausschließlich mit FastAPI. OpenSearch ist nicht direkt aus
dem Browser erreichbar und wird von der API ausschließlich lesend abgefragt.
Warnungsstatus, Benachrichtigungszustellungen, manuelle Zuordnungen, der globale
UI-Farbstandard sowie verschlüsselte Mailbox- und Benachrichtigungszugänge
liegen getrennt in
`data/dashboard/dashboard.db`. Lokale Farbanpassungen bleiben als
Browser-Präferenz erhalten. Globale Farb- und Mailboxänderungen sind mit dem
separaten Admin-Passwort geschützt. Gleiches gilt für
Benachrichtigungseinstellungen und Testversand. Der Zugriff auf das gesamte
Dashboard erfordert zusätzlich eine gültige Read-Sitzung. Beide Passwörter
werden ausschließlich als gesalzene Hashes gespeichert und können unter
**Einstellungen → Administration** geändert werden.

Weitere Details und der Dockge-Betriebsablauf stehen in
[docs/CUSTOM-DASHBOARD.md](docs/CUSTOM-DASHBOARD.md).

Die vollständige Trennung zwischen historischen OpenSearch-Daten,
Dashboard-Steuerungsdaten, Verschlüsselungsschlüssel und optionalem
Grafana-Zustand ist in
[docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md) beschrieben. Dort ist auch
festgehalten, welche Teilwiederherstellungen möglich sind und in welcher
Reihenfolge ein vollständiger Restore erfolgen muss.

## Ports

| Service | Port | Beschreibung |
|---|---|---|
| Grafana (optional) | 3020 | Nur bei aktiviertem Profil `grafana` |
| DMARC Control | 3030 | Eigenes v2-Webdashboard |
| OpenSearch API | 9200 | Nur intern |

## Ressourcenbedarf

| Ressource | Minimum |
|---|---|
| RAM | 2 GB |
| CPU | 1 Core |
| Disk | ~1 GB/Jahr (je nach Report-Volumen) |

## Hinweise

- **Zeitfelder:** Aggregate verwenden `date_begin`, Failure-/Forensic-Indizes `arrival_date`.
- **Forensic/RUF:** Standardmäßig deaktiviert, weil diese Reports personenbezogene Header oder Betreffzeilen enthalten können. Bei Bedarf nur mit dokumentierter Retention und getrennten Berechtigungen aktivieren.
- **OpenSearch-Sicherheit:** Der Stack veröffentlicht keine OpenSearch-Ports;
  Dashboard, Parser und optional Grafana greifen nur im Compose-Netz darauf zu.
  Vor einem Firmenbetrieb müssen OpenSearch Security, TLS, Zugriffskontrolle
  und Back-up verbindlich ergänzt werden.
- **Portabilität:** Konfiguration, `.env` und alle persistenten Containerdaten liegen unter dem Projektverzeichnis. Für einen Hostwechsel den Stack sauber stoppen, das gesamte Verzeichnis inklusive `data/` übertragen und auf dem Zielhost mit kompatiblen Image-Versionen starten. Für OpenSearch ist ein Snapshot zusätzlich der empfohlene Backup- und Migrationsweg.

## Troubleshooting

```bash
# OpenSearch Gesundheit prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cluster/health | python3 -m json.tool

# Indizes prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cat/indices?v | grep dmarc

# parsedmarc Logs
docker compose logs parsedmarc --tail=50

# Optional: prüfen, ob die Grafana-Dashboards und Datasource provisioniert wurden
docker compose logs grafana | grep -i "provision\|opensearch"

# Aktive Standarddienste anzeigen; ohne Profil darf grafana nicht erscheinen
docker compose config --services

# Optionale Variante auflösen; hier muss grafana erscheinen
docker compose --profile grafana config --services

# Stack neu starten
docker compose restart

# parsedmarc Image neu bauen (nach Update)
docker compose build --no-cache parsedmarc
docker compose up -d
```

## Lizenz

DMARC Control steht unter [Apache 2.0](LICENSE). Das zugrunde liegende
[parsedmarc](https://github.com/domainaware/parsedmarc) steht ebenfalls unter
[Apache 2.0](https://github.com/domainaware/parsedmarc/blob/master/LICENSE).
