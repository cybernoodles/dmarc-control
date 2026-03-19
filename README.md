# parsedmarc-stack

Self-hosted DMARC report parsing and visualization using [parsedmarc](https://github.com/domainaware/parsedmarc), OpenSearch and Grafana – containerized with Docker Compose.

## Stack

| Component | Image | Zweck |
|---|---|---|
| parsedmarc | gebaut aus GitHub | Parser, liest DMARC-Reports via IMAP oder MS Graph |
| OpenSearch 2.x | `opensearchproject/opensearch:2` | Datenspeicher |
| OpenSearch Dashboards | `opensearchproject/opensearch-dashboards:2` | Natives UI (optional) |
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
├── config/
│   ├── parsedmarc.ini                      ← Mailbox & OpenSearch Konfig (nicht ins Git!)
│   ├── parsedmarc.ini.example              ← Vorlage ohne echte Credentials
│   └── grafana/
│       └── provisioning/
│           ├── datasources/
│           │   └── opensearch.yml          ← Grafana Datasource (auto-provisioniert)
│           └── dashboards/
│               ├── dashboards.yml          ← Grafana Dashboard Provider
│               └── Grafana-DMARC_Reports.json  ← Dashboard (auto-provisioniert)
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
docker compose up -d --build
```

Der erste Start dauert länger da parsedmarc direkt aus dem GitHub-Repo gebaut wird.

**4. Logs verfolgen**

```bash
docker compose logs -f parsedmarc
```

## Mailbox-Konfiguration

### Option A – Microsoft 365 via Microsoft Graph API (empfohlen)

Voraussetzung: App-Registrierung in Azure Entra ID mit folgenden Einstellungen:

- **API Permissions:** `Mail.ReadWrite` (Application, nicht Delegated) + Admin Consent
- **Auth:** Client Secret

Mailbox-Zugriff auf ein einzelnes Postfach einschränken (Exchange Online PowerShell):

```powershell
New-ApplicationAccessPolicy `
  -AccessRight RestrictAccess `
  -AppId "<CLIENT_ID>" `
  -PolicyScopeGroupId "<dmarc@example.com>" `
  -Description "Restrict parsedmarc to DMARC mailbox only"
```

Konfiguration in `parsedmarc.ini`:

```ini
[msgraph]
auth_method = ClientSecret
tenant_id = TENANT_ID
client_id = CLIENT_ID
client_secret = CLIENT_SECRET
mailbox = dmarc@example.com

[mailbox]
watch = True
reports_folder = Inbox
```

### Option B – klassisches IMAP

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
| `http://HOSTNAME:3000` | `admin` / Passwort aus `.env` |

Das Dashboard wird beim Start automatisch provisioniert. Zeitraum oben rechts auf **Last 1 year** stellen.

### Datasource manuell anlegen (falls Auto-Provisioning fehlschlägt)

Connections → Data Sources → Add → **OpenSearch**:

| Feld | Wert |
|---|---|
| URL | `http://opensearch:9200` |
| Index name | `dmarc_aggregate-*` |
| Pattern | `No pattern` |
| Time field | `date_begin` |
| Version | `2.x` |

## Ports

| Service | Port | Beschreibung |
|---|---|---|
| Grafana | 3000 | Haupt-Dashboard |
| OpenSearch Dashboards | 5601 | Natives UI (optional) |
| OpenSearch API | 9200 | Nur intern |

## Ressourcenbedarf

| Ressource | Minimum |
|---|---|
| RAM | 2 GB |
| CPU | 1 Core |
| Disk | ~1 GB/Jahr (je nach Report-Volumen) |

## Hinweise

- **Forensic Reports (ruf):** Die meisten Mail-Provider (Microsoft, Google, Yahoo) senden keine Forensic Reports. Der DMARC Forensic-Bereich im Dashboard bleibt daher in der Regel leer – das ist normal.
- **Zeitfeld:** parsedmarc speichert Daten mit `date_begin` als Zeitfeld, nicht `date_range` (Array).
- **Dashboard-JSON:** Das mitgelieferte Dashboard ist für modernes Grafana (11.x) angepasst – Legacy Panel-Typen (`grafana-piechart-panel`, `graph`, `grafana-worldmap-panel`) wurden auf aktuelle Äquivalente konvertiert.
- **`fromdomain` Variable:** Muss mit `Include All option` und `Custom all value = *` konfiguriert sein, sonst bleiben alle Panels leer.

## Troubleshooting

```bash
# OpenSearch Gesundheit prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cluster/health | python3 -m json.tool

# Indizes prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cat/indices?v | grep dmarc

# parsedmarc Logs
docker compose logs parsedmarc --tail=50

# Grafana Plugin prüfen
docker compose logs grafana | grep -i "plugin\|opensearch"

# Stack neu starten
docker compose restart

# parsedmarc Image neu bauen (nach Update)
docker compose build --no-cache parsedmarc
docker compose up -d
```

## Lizenz

Dieses Setup-Repo steht unter [Apache 2.0](LICENSE). parsedmarc selbst steht ebenfalls unter [Apache 2.0](https://github.com/domainaware/parsedmarc/blob/master/LICENSE).
