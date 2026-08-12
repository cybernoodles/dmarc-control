# Migration bestehender Docker-Volumes in `./data`

Diese Anleitung verschiebt eine bestehende parsedmarc-Installation von den
historischen Docker-Volumes in die projektlokalen Bind-Mounts `./data/opensearch`
und – nur bei weiterhin aktiviertem Grafana-Profil – `./data/grafana`. Sie ist
für einen kontrollierten Wartungszeitraum gedacht und wird nicht automatisch
durch ein `git pull` ausgeführt.

## Vorbedingungen

- Die aktuelle Installation funktioniert noch mit den bestehenden Docker-Volumes.
- Das Repository ist auf den Stand mit dem `data/`-Layout aktualisiert.
- Für den gesamten Kopiervorgang bleibt der Stack gestoppt.
- Vor dem Eingriff existiert ein getestetes OpenSearch-Snapshot oder ein
  zusätzlicher Volume-Export.
- Soll Grafana weiterlaufen, enthält `.env` vor dem Start
  `COMPOSE_PROFILES=grafana` und ein gesetztes `GRAFANA_ADMIN_PASSWORD`.

Die nachfolgenden Volume-Namen gelten für einen bisherigen Compose-Projektnamen
`parsedmarc`:

```text
parsedmarc_opensearch-data
parsedmarc_grafana-data
```

Vor dem Kopieren die tatsächlichen Namen prüfen:

```bash
docker volume ls | grep -E 'parsedmarc.*(opensearch|grafana)'
```

## Migration

Im Projektverzeichnis ausführen:

```bash
docker compose --profile grafana stop
mkdir -p data/opensearch
```

Das bisherige OpenSearch-Volume in das neue Verzeichnis kopieren. Ersetze den
Volume-Namen, falls die vorherige Prüfung einen anderen Namen ergeben hat:

```bash
docker run --rm \
  -v parsedmarc_opensearch-data:/source:ro \
  -v "$PWD/data/opensearch":/destination \
  alpine:3.20 sh -c 'cp -a /source/. /destination/'

sudo chown -R 1000:1000 data/opensearch
```

Nur wenn Grafana weiter betrieben werden soll, auch dessen Volume übernehmen:

```bash
mkdir -p data/grafana
docker run --rm \
  -v parsedmarc_grafana-data:/source:ro \
  -v "$PWD/data/grafana":/destination \
  alpine:3.20 sh -c 'cp -a /source/. /destination/'
sudo chown -R 472:472 data/grafana
```

Jetzt den Stack mit dem neuen Compose starten:

```bash
docker compose up -d
```

## Prüfung

```bash
docker exec dmarc-opensearch curl -sf http://localhost:9200/_cluster/health
docker exec dmarc-opensearch curl -s 'http://localhost:9200/_cat/indices/dmarc_*?v'
```

Nur bei aktiviertem Grafana-Profil zusätzlich:

```bash
docker logs --tail=100 dmarc-grafana
```

Prüfe anschließend DMARC Control und, falls aktiviert, die Grafana-Anmeldung,
die vorhandenen Dashboards und die historischen Aggregate.

## Erst nach erfolgreicher Prüfung

Die ursprünglichen Docker-Volumes mindestens bis zum nächsten geprüften Backup
behalten. Sie dürfen nicht mit `docker compose down -v` oder `docker volume rm`
entfernt werden, solange ein Rollback noch benötigt wird.

Für reguläre Backups und einen Host- oder Versionswechsel ist ein
OpenSearch-Snapshot der bevorzugte Weg. Das Kopieren des Datenverzeichnisses
ist nur für diese kontrollierte Migration bei gestopptem Stack vorgesehen.
