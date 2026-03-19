# parsedmarc Stack – Setup auf docker01

## Verzeichnisstruktur

```
dmarc/
├── docker-compose.yml
├── .env                          ← Passwörter (nicht ins Git!)
├── config/
│   ├── parsedmarc.ini            ← IMAP & OpenSearch Konfiguration
│   └── grafana/
│       └── provisioning/
│           └── datasources/
│               └── opensearch.yml
└── dmarc-reports/                ← optional: Reports als Dateien
```

## 1. Voraussetzungen

```bash
# vm.max_map_count erhöhen (OpenSearch Pflicht)
sudo sysctl -w vm.max_map_count=262144

# Dauerhaft machen:
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-opensearch.conf
```

## 2. Verzeichnisse anlegen

```bash
mkdir -p ./config/grafana/provisioning/datasources
```

## 3. Dateien platzieren

```bash
# parsedmarc.ini anpassen (IMAP-Host, User, Passwort)
nano ./config/parsedmarc.ini

# Grafana Datasource
cp grafana-datasource.yml ./config/grafana/provisioning/datasources/opensearch.yml

# Passwörter in .env setzen
nano .env
```

## 4. Stack starten

```bash
docker compose up -d

# Logs verfolgen
docker compose logs -f parsedmarc
```

## 5. Grafana Dashboard einrichten

1. Browser: http://docker01:3000 (admin / Passwort aus .env)
2. **Connections → Data Sources** prüfen (sollte auto-provisioniert sein)
3. **Dashboards → Import**
4. Dashboard-JSON aus dem parsedmarc-Repo importieren:
   https://github.com/domainaware/parsedmarc/blob/master/grafana/Grafana-DMARC_Reports.json
   → "Download raw file" → in Grafana importieren → Datasource `parsedmarc-aggregate` wählen

## 6. Optional: OpenSearch Dashboards (natives Kibana-ähnliches UI)

Browser: http://docker01:5601

Dashboard-JSON importieren:
- Menü → Management → Saved Objects → Import
- Datei: https://github.com/domainaware/parsedmarc/blob/master/kibana/ (eine der .ndjson Dateien)

## Ports

| Service              | Port  | Beschreibung              |
|----------------------|-------|---------------------------|
| Grafana              | 3000  | Haupt-Dashboard           |
| OpenSearch Dashboards| 5601  | Natives UI (optional)     |
| OpenSearch API       | 9200  | Nur intern (kein Expose)  |

## Ressourcenbedarf (Minimum)

- RAM: 2 GB (OpenSearch 512m Heap + Overhead + Grafana)
- Disk: je nach Report-Volumen, ~1 GB/Jahr realistisch
- CPU: 1 Core reicht für kleine Umgebungen

## Troubleshooting

```bash
# OpenSearch Gesundheit prüfen
docker exec dmarc-opensearch curl -s http://localhost:9200/_cluster/health | python3 -m json.tool

# parsedmarc Logs
docker compose logs parsedmarc

# Grafana Plugin-Installation prüfen
docker compose logs grafana | grep -i plugin
```
