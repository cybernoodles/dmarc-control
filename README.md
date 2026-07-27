# parsedmarc-stack

Self-hosted DMARC report parsing and visualization using [parsedmarc](https://github.com/domainaware/parsedmarc), OpenSearch and Grafana – containerized with Docker Compose.

## Stack

| Component | Image | Zweck |
|---|---|---|
| parsedmarc | gebaut aus GitHub | Parser, liest DMARC-Reports via Microsoft Graph oder IMAP |
| OpenSearch 2.x | `opensearchproject/opensearch:2` | Datenspeicher |
| Grafana | `grafana/grafana:latest` | Visualisierung |

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
│   └── M365.md                              ← M365-Setup und RBAC-Prüfung
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
└── dmarc-reports/                          ← optional: Reports als Dateien ablegen
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

**3. Stack starten**

```bash
docker compose up -d --build --remove-orphans
```

Der erste Start dauert länger da parsedmarc direkt aus dem GitHub-Repo gebaut wird.

**4. Logs verfolgen**

```bash
docker compose logs -f parsedmarc
```

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
- **DMARC Forensic Analysis:** RUF-/Forensic-Untersuchung mit 30 Tagen Standardzeitraum und begrenzten Aggregationen. Es bleibt leer, solange `save_failure = False` gesetzt ist.

Datasources und Dashboards sind schreibgeschützt provisioniert. Änderungen erfolgen im Repository, dann mit `docker compose restart grafana` übernehmen. Damit bleibt die laufende Instanz nachvollziehbar und frei von UI-Drift.

Die Grafana-Version bleibt vorläufig bewusst unverändert auf `latest`, wie in `docker-compose.yml` definiert.

## Ports

| Service | Port | Beschreibung |
|---|---|---|
| Grafana | 3020 | Haupt-Dashboard und Analyse |
| OpenSearch API | 9200 | Nur intern |

## Ressourcenbedarf

| Ressource | Minimum |
|---|---|
| RAM | 2 GB |
| CPU | 1 Core |
| Disk | ~1 GB/Jahr (je nach Report-Volumen) |

## Hinweise

- **Zeitfelder:** Aggregate verwenden `date_begin`, Forensic-Indices `arrival_date`.
- **Forensic/RUF:** Standardmäßig deaktiviert, weil diese Reports personenbezogene Header oder Betreffzeilen enthalten können. Bei Bedarf nur mit dokumentierter Retention und getrennten Berechtigungen aktivieren.
- **OpenSearch-Sicherheit:** Der aktuelle Ad-hoc-Stack veröffentlicht keine OpenSearch-Ports und nutzt nur Grafana als Oberfläche. Vor einem Firmenbetrieb müssen OpenSearch Security, TLS, Zugriffskontrolle und Back-up verbindlich ergänzt werden.

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
