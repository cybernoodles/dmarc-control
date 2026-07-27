# Migration bestehender Docker-Volumes in `./data`

Diese Anleitung verschiebt eine bestehende parsedmarc-Installation von den
historischen Docker-Volumes in die projektlokalen Bind-Mounts `./data/opensearch`
und `./data/grafana`. Sie ist für einen kontrollierten Wartungszeitraum gedacht
und wird nicht automatisch durch ein `git pull` ausgeführt.

## Vorbedingungen

- Die aktuelle Installation funktioniert noch mit den bestehenden Docker-Volumes.
- Das Repository ist auf den Stand mit dem `data/`-Layout aktualisiert.
- Für den gesamten Kopiervorgang bleibt der Stack gestoppt.
- Vor dem Eingriff existiert ein getestetes OpenSearch-Snapshot oder ein
  zusätzlicher Volume-Export.

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
docker compose stop
mkdir -p data/opensearch data/grafana
```

Die beiden bisherigen Volumes in die neuen Verzeichnisse kopieren. Ersetze die
Volume-Namen, falls die vorherige Prüfung andere Namen ergeben hat:

```bash
docker run --rm \
  -v parsedmarc_opensearch-data:/source:ro \
  -v "$PWD/data/opensearch":/destination \
  alpine:3.20 sh -c 'cp -a /source/. /destination/'

docker run --rm \
  -v parsedmarc_grafana-data:/source:ro \
  -v "$PWD/data/grafana":/destination \
  alpine:3.20 sh -c 'cp -a /source/. /destination/'

sudo chown -R 1000:1000 data/opensearch
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
docker logs --tail=100 dmarc-grafana
```

Prüfe anschließend Anmeldung, vorhandene Dashboards und die historischen
Aggregate in Grafana.

## Erst nach erfolgreicher Prüfung

Die ursprünglichen Docker-Volumes mindestens bis zum nächsten geprüften Backup
behalten. Sie dürfen nicht mit `docker compose down -v` oder `docker volume rm`
entfernt werden, solange ein Rollback noch benötigt wird.

Für reguläre Backups und einen Host- oder Versionswechsel ist ein
OpenSearch-Snapshot der bevorzugte Weg. Das Kopieren des Datenverzeichnisses
ist nur für diese kontrollierte Migration bei gestopptem Stack vorgesehen.
