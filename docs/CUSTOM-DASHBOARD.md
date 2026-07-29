# DMARC Control

DMARC Control ist das eigene v2-Webdashboard des parseDMARC-Stacks. Es läuft
parallel zu Grafana und verwendet dieselben von parsedmarc geschriebenen
OpenSearch-Indizes.

## Architektur

```text
Browser ──HTTP──> DMARC Control (React + FastAPI) ──HTTP intern──> OpenSearch
Browser ──HTTP──> Grafana                         ──HTTP intern──> OpenSearch
Mailbox ────────> parsedmarc                      ───────────────> OpenSearch
```

React wird beim Image-Build statisch erzeugt. FastAPI liefert danach sowohl die
Oberfläche als auch die kontrollierten `/api`-Endpunkte aus. Es gibt keinen
direkten OpenSearch-Zugriff aus dem Browser.

## Datenzugriff

Die API liest:

- `dmarc_aggregate-*` für Übersicht, Trends, Domains, Policies und Sending Hosts
- `dmarc_failure-*` für minimierte Forensik-Aggregationen

Die Abfragen verwenden ausschließlich `_search`. Es werden keine Indizes,
Mappings oder DMARC-Dokumente verändert.

Forensik-Abfragen verwenden `size: 0` und `_source: false`. Insbesondere werden
folgende Felder nicht geladen oder ausgeliefert:

- `sample.raw`
- `sample.headers`
- `sample.body`
- `sample.subject`
- `original_rcpt_to`
- `original_mail_from`

## Eigene Persistenz

Statusänderungen an Warnungen, manuell bestätigte Sending Hosts sowie der
globale UI-Farbstandard werden in `data/dashboard/dashboard.db` gespeichert.
Diese SQLite-Datei ist vollständig von den OpenSearch- und Grafana-Daten
getrennt.

Die aktuell im Browser bearbeitete Farbe und das gespeicherte Custom-Profil
sind lokale UI-Präferenzen. Ein globaler Standard gilt für Browser ohne lokale
Abweichung. Beim ersten Aufruf blockiert ein Setup-Screen das Dashboard, bis
ein Admin-Passwort mit mindestens zwölf Zeichen festgelegt wurde. Nur der
gesalzene Passwort-Hash wird in `dashboard.db` gespeichert.

Eine Admin-Anmeldung ist ausschließlich für globale Einstellungen erforderlich.
Die Sitzung wird in einem `HttpOnly`-Cookie mit zwölf Stunden Gültigkeit
gehalten. Das Passwort kann unter **Einstellungen → Administration** geändert
werden; dabei werden andere bestehende Admin-Sitzungen beendet. Das lesende
Dashboard bleibt ohne Admin-Anmeldung verfügbar.

Die Warnungs-IDs werden deterministisch aus Auslöser, Domain, Host und Reporttag
gebildet. Damit werden wiederholte Anzeigen desselben Ereignisses dedupliziert,
ohne ein neues Ereignis an einem späteren Reporttag zu unterdrücken.

## Dienst-Erkennung

Die automatische Erkennung bewertet mehrere Signale:

- parsedmarc-Quelltyp und Dienstname
- PTR und Basisdomain
- ASN-Name und ASN-Domain
- SPF-Domains
- DKIM-Signing-Domains und Selector

PTR wird nie allein als vertrauenswürdige Dienstidentität behandelt. Das
Ergebnis enthält eine Konfidenz und kann administrativ bestätigt oder
überschrieben werden.

## API

| Endpunkt | Zweck |
|---|---|
| `GET /api/health` | Container- und OpenSearch-Status |
| `GET /api/auth/status` | Ersteinrichtung und Admin-Sitzung prüfen |
| `POST /api/auth/setup` | initiales Admin-Passwort einmalig festlegen |
| `POST /api/auth/login` | Admin-Sitzung starten |
| `POST /api/auth/logout` | Admin-Sitzung beenden |
| `POST /api/auth/change-password` | Admin-Passwort ändern |
| `GET /api/settings/appearance` | globalen UI-Farbstandard lesen |
| `PUT /api/settings/appearance` | globalen UI-Farbstandard als Admin ändern |
| `GET /api/domains` | verfügbare Header-From-Domains |
| `GET /api/overview` | Kennzahlen, Trend, Fehlerquellen, Reports und Policies |
| `GET /api/hosts` | vollständiges Sending-Host-Inventar |
| `GET /api/hosts/{ip}` | einzelne Host-Detailansicht |
| `PUT /api/hosts/{ip}/classification` | manuelle Dienst- und Vertrauenszuordnung |
| `GET /api/alerts` | abgeleitete und deduplizierte Warnungen |
| `PATCH /api/alerts/{id}` | Warnungsstatus ändern |
| `GET /api/forensics` | minimierte Forensik-Aggregationen |

Alle Filter werden serverseitig als strukturierte OpenSearch-Abfragen erzeugt.
Die API akzeptiert keine frei eingebbare Query-DSL.

## Dockge auf docker01

Der produktive Dockge-Stack liegt unter:

```text
/opt/stacks/parsedmarc
```

Dockge verwendet dort `compose.yaml`. Das Dashboard-Verzeichnis liegt relativ
dazu unter `./dashboard`, die eigene Persistenz unter `./data/dashboard`.

Beim Update werden nur der Dashboard-Quellcode und der zusätzliche
`dashboard`-Service verändert. Die bestehenden Services `opensearch`,
`parsedmarc` und `grafana` müssen dafür nicht neu erstellt werden.

Das neue Dashboard ist nach dem Start unter `http://HOSTNAME:3030` erreichbar;
Grafana bleibt parallel unter Port `3020` verfügbar.

## Lokale Prüfungen

Frontend:

```bash
cd dashboard/frontend
pnpm install
pnpm build
```

Backend:

```bash
PYTHONPATH=dashboard/backend python -m unittest discover \
  -s dashboard/backend/tests -v
```

Gesamtes Image:

```bash
docker build -t parsedmarc-dashboard:local dashboard
```
