# parsedmarc-stack

Self-hosted DMARC report parsing and visualization using [parsedmarc](https://github.com/domainaware/parsedmarc), OpenSearch and Grafana – containerized with Docker Compose.

## Stack

| Component | Image | Zweck |
|---|---|---|
| parsedmarc | gebaut aus GitHub | Parser, liest DMARC-Reports via Microsoft Graph oder IMAP |
| OpenSearch 2.x | `opensearchproject/opensearch:2` | Datenspeicher |
| Grafana | `grafana/grafana:latest` | Visualisierung |
| DMARC Control | lokaler Multi-Stage-Build | Eigenes risikoorientiertes Webdashboard und API |

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
parsedmarc-stack/
├── docker-compose.yml
├── .env                                    ← Passwörter (nicht ins Git!)
├── .env.example                            ← Vorlage ohne echte Werte
├── .gitignore
├── README.md
├── docs/
│   ├── M365.md                              ← M365-Setup und RBAC-Prüfung
│   ├── MIGRATION-TO-PORTABLE-DATA.md        ← Einmalmigration bestehender Docker-Volumes
│   └── CUSTOM-DASHBOARD.md                  ← Architektur und Betrieb von DMARC Control
├── dashboard/
│   ├── Dockerfile                           ← React-Build und FastAPI-Laufzeit
│   ├── frontend/                            ← React, TypeScript und ECharts
│   └── backend/                             ← Kontrollierte OpenSearch-API und lokale Zustände
├── data/                                    ← Persistente Laufzeitdaten (nicht im Git)
│   ├── opensearch/                          ← Indizes und OpenSearch-Zustand
│   ├── grafana/                             ← Grafana SQLite, Benutzer und Plugins
│   └── dashboard/                           ← Warnungsstatus und bestätigte Hostzuordnungen
├── config/
│   ├── parsedmarc.ini                      ← Mailbox & OpenSearch Konfig (nicht ins Git!)
│   ├── parsedmarc.ini.example              ← Vorlage ohne echte Credentials
│   └── grafana/
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
git clone https://github.com/DEIN-USERNAME/parsedmarc-stack.git
cd parsedmarc-stack
```

**2. Konfiguration anlegen**

```bash
# Passwörter setzen
cp .env.example .env
nano .env

# parsedmarc konfigurieren
cp config/parsedmarc.ini.example config/parsedmarc.ini
nano config/parsedmarc.ini
```

**3. Datenverzeichnisse vorbereiten**

Die persistenten OpenSearch- und Grafana-Daten liegen unter `./data`, damit
das Projektverzeichnis vollständig auf einen anderen Host übertragen werden
kann. Die Inhalte sind absichtlich nicht versioniert.

```bash
mkdir -p data/opensearch data/grafana data/dashboard dmarc-reports
sudo chown 1000:1000 data/opensearch
sudo chown 472:472 data/grafana
sudo chown 10001:10001 data/dashboard

# Schreibzugriff auf globale Dashboard-Einstellungen absichern
openssl rand -hex 32 | sudo tee data/dashboard/settings.token >/dev/null
sudo chown 10001:10001 data/dashboard/settings.token
sudo chmod 400 data/dashboard/settings.token
```

OpenSearch läuft im Container als UID 1000, Grafana als UID 472 und DMARC
Control als UID 10001. Ohne diese Eigentümer kann der jeweilige Dienst beim
ersten Start nicht in sein Datenverzeichnis schreiben. Den generierten
Settings-Token beim ersten globalen Farbwechsel in der Oberfläche eingeben.

> **Dockge:** Relative Pfade wie `./data` beziehen sich auf den Ordner der
> Compose-Datei. Daher entweder das gesamte Repository als Stack-Ordner
> verwenden oder beim Übertragen nach Dockge alle drei Pfade (`./config`,
> `./data`, `./dmarc-reports`) konsistent auf den Projektordner umstellen.

**4. Stack starten**

```bash
docker compose up -d --build --remove-orphans
```

Der erste Start dauert länger da parsedmarc direkt aus dem GitHub-Repo gebaut wird.

**5. Logs verfolgen**

```bash
docker compose logs -f parsedmarc
```

### Bestehende Installation migrieren

Ältere Versionen dieses Repositories verwendeten Docker-Volumes für
OpenSearch und Grafana. Die einmalige, datenerhaltende Übernahme in das neue
`data/`-Layout ist in [docs/MIGRATION-TO-PORTABLE-DATA.md](docs/MIGRATION-TO-PORTABLE-DATA.md)
beschrieben. Nicht vorab einen leeren Stack mit dem neuen Compose starten.

## Mailbox-Konfiguration

### Microsoft 365 via Microsoft Graph API (empfohlen)

Für den Betrieb ein separates Postfach wie `dmarc-reports@example.com` mit dem Ordner `Inbox/DMARC` verwenden. Es enthält ausschließlich DMARC-Reports und wird nicht interaktiv genutzt.

- **Berechtigung:** App-only `Mail.ReadWrite`; parsedmarc archiviert verarbeitete Nachrichten.
- **Scope:** Zugriff zwingend auf dieses eine Postfach beschränken. Für neue Unternehmens-Setups ist Exchange Online Application RBAC vorgesehen; das ausführliche Vorgehen steht in [docs/M365.md](docs/M365.md).
- **Anmeldung:** Für produktiven Betrieb Zertifikat bevorzugen; Client Secret nur für den ersten Funktionstest und mit dokumentiertem Ablauf zur Rotation.

Beim ersten Lauf bleibt `test = True` gesetzt. Erst wenn Logs und Dashboard korrekt aussehen, `test = False` setzen; dann werden verarbeitete Mails in `Inbox/DMARC/Processed` verschoben.

Konfiguration in `parsedmarc.ini`:

```ini
[msgraph]
auth_method = ClientSecret
tenant_id = TENANT_ID
client_id = CLIENT_ID
client_secret = CLIENT_SECRET
mailbox = dmarc@example.com

[mailbox]
test = True
delete = False
watch = True
reports_folder = Inbox/DMARC
archive_folder = Inbox/DMARC/Processed
```

### Forensic-/RUF-Reports (nur nach Freigabe)

Forensic-Berichte können Header, Empfänger und Betreffzeilen enthalten. Die Speicherung ist deshalb standardmäßig deaktiviert. Ein `git pull` aktiviert sie **nicht** und ändert auch keine vorhandene `config/parsedmarc.ini`.

Erst nach Freigabe von Retention, Berechtigungskonzept und Incident-Prozess in der lokalen, nicht versionierten Konfiguration aktivieren:

```ini
[general]
save_failure = True
```

`save_failure` ist die aktuelle Bezeichnung. Bestehende Installationen mit `save_forensic = True` funktionieren weiterhin, da parsedmarc dies als Legacy-Alias behandelt. Nicht beide Optionen gleichzeitig setzen – `save_failure` hat Vorrang.

Danach parsedmarc neu starten und eingehende RUF-Berichte abwarten:

```bash
docker compose restart parsedmarc
```

Das Dashboard **DMARC Forensic Analysis** zeigt ausschließlich minimierte Betriebsmetadaten – keine Betreffzeilen, Empfänger, Header oder Rohinhalte. Es wird in den separaten Grafana-Ordner **Forensic** provisioniert. Diesem Ordner in Grafana nur den zuständigen Security-/Incident-Rollen Zugriff gewähren.

### IMAP (nur Fallback)

```ini
[imap]
host = mail.example.com
user = dmarc@example.com
password = PASSWORT

[mailbox]
watch = True
reports_folder = Inbox
```

## Grafana

| URL | Credentials |
|---|---|
| `http://HOSTNAME:3020` | `admin` / Passwort aus `.env` |

Grafana provisioniert drei versionierte Dashboards und öffnet nach Anmeldung direkt **DMARC Overview**:

- **DMARC Overview:** Betriebsstatus, Datenfrische, DMARC-Trend und Policies; Zeitraum 30 Tage, Aktualisierung alle 5 Minuten.
- **DMARC Analysis:** Sender-, IP-, SPF- und DKIM-Detailanalyse; Zeitraum 90 Tage. Forensic-Daten sind bewusst ausgeschlossen.
- **DMARC Forensic Analysis:** RUF-/Forensic-Untersuchung mit 30 Tagen Standardzeitraum und begrenzten Aggregationen. Aktuelle parsedmarc-Versionen speichern diese Berichte in `dmarc_failure-*`; das Dashboard bleibt leer, solange `save_failure = False` gesetzt ist oder keine RUF-Berichte eingehen.

Datasources und Dashboards sind schreibgeschützt provisioniert. Änderungen erfolgen im Repository, dann mit `docker compose restart grafana` übernehmen. Damit bleibt die laufende Instanz nachvollziehbar und frei von UI-Drift.

Die Grafana-Version bleibt vorläufig bewusst unverändert auf `latest`, wie in `docker-compose.yml` definiert.

## DMARC Control

Das eigene Webdashboard läuft parallel zu Grafana und übernimmt dessen
Informationsumfang in einer risikoorientierten Oberfläche:

- Übersicht mit Volumen, Passrate, echten DMARC-Fails, Datenfrische und Trend
- klare Trennung zwischen finalem DMARC-Fail und kompensiertem SPF-/DKIM-Alignment
- vollständiges Sending-Host-Inventar mit IP, PTR, ASN/Land, Identitäten und Last Seen
- mehrstufige Dienst-Erkennung mit Konfidenz und manueller Bestätigung
- deduplizierte Warnungen mit Status `offen`, `bestätigt`, `behoben` und `ignoriert`
- datenschutzreduzierte Forensik ohne Laden von Rohinhalt, Empfängern, Betreff oder Headern

Der Browser spricht ausschließlich mit FastAPI. OpenSearch ist nicht direkt aus
dem Browser erreichbar und wird von der API ausschließlich lesend abgefragt.
Warnungsstatus, manuelle Zuordnungen und der globale UI-Farbstandard liegen
getrennt in `data/dashboard/dashboard.db`. Lokale Farbanpassungen bleiben als
Browser-Präferenz erhalten. Globale Farbänderungen sind mit dem separaten
Dashboard-Settings-Token geschützt.

Weitere Details und der Dockge-Betriebsablauf stehen in
[docs/CUSTOM-DASHBOARD.md](docs/CUSTOM-DASHBOARD.md).

## Ports

| Service | Port | Beschreibung |
|---|---|---|
| Grafana | 3020 | Haupt-Dashboard und Analyse |
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
- **OpenSearch-Sicherheit:** Der aktuelle Ad-hoc-Stack veröffentlicht keine OpenSearch-Ports und nutzt nur Grafana als Oberfläche. Vor einem Firmenbetrieb müssen OpenSearch Security, TLS, Zugriffskontrolle und Back-up verbindlich ergänzt werden.
- **Portabilität:** Konfiguration, `.env` und alle persistenten Containerdaten liegen unter dem Projektverzeichnis. Für einen Hostwechsel den Stack sauber stoppen, das gesamte Verzeichnis inklusive `data/` übertragen und auf dem Zielhost mit kompatiblen Image-Versionen starten. Für OpenSearch ist ein Snapshot zusätzlich der empfohlene Backup- und Migrationsweg.

## Troubleshooting

```bash
# OpenSearch Gesundheit prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cluster/health | python3 -m json.tool

# Indizes prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cat/indices?v | grep dmarc

# parsedmarc Logs
docker compose logs parsedmarc --tail=50

# Prüfen, ob beide Dashboards und die Datasource provisioniert wurden
docker compose logs grafana | grep -i "provision\|opensearch"

# Stack neu starten
docker compose restart

# parsedmarc Image neu bauen (nach Update)
docker compose build --no-cache parsedmarc
docker compose up -d
```

## Lizenz

Dieses Setup-Repo steht unter [Apache 2.0](LICENSE). parsedmarc selbst steht ebenfalls unter [Apache 2.0](https://github.com/domainaware/parsedmarc/blob/master/LICENSE).
