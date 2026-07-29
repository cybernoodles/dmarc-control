# DMARC Control

DMARC Control ist das eigene v2-Webdashboard des parseDMARC-Stacks. Es läuft
parallel zu Grafana und verwendet dieselben von parsedmarc geschriebenen
OpenSearch-Indizes.

## Architektur

```text
Browser ──HTTP──> DMARC Control (React + FastAPI) ──HTTP intern──> OpenSearch
Browser ──HTTP──> Grafana                         ──HTTP intern──> OpenSearch
                         │
                         └── aktivierte Revision ──> Parser-Supervisor
                         └── offene Warnungen ─────> SMTP / Microsoft Graph
Mailbox ────────> genau ein parsedmarc-Kindprozess ──────────────> OpenSearch
```

React wird beim Image-Build statisch erzeugt. FastAPI liefert danach sowohl die
Oberfläche als auch die kontrollierten `/api`-Endpunkte aus. Es gibt keinen
direkten OpenSearch-Zugriff aus dem Browser.

Die Mailbox-Konfiguration wird als versionierter Entwurf gespeichert. Ein
expliziter Verbindungstest prüft nur Anmeldung und lesenden Ordnerzugriff.
Nach erfolgreichem Test kann exakt diese Revision aktiviert werden. Der
Supervisor startet zu jeder Zeit höchstens einen parsedmarc-Kindprozess und
wechselt Konfigurationen durch kontrolliertes Stoppen und anschließendes
Starten. Bis zur ersten GUI-Aktivierung kann eine bestehende
`config/parsedmarc.ini` unverändert als Legacy-Fallback weiterlaufen.

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

Statusänderungen an Warnungen, Benachrichtigungseinstellungen und
-zustellungen, manuell bestätigte Sending Hosts, der globale UI-Farbstandard
sowie versionierte Mailbox-Verbindungen werden in
`data/dashboard/dashboard.db` gespeichert. Diese SQLite-Datei ist vollständig
von den OpenSearch- und Grafana-Daten getrennt.

Mailbox- und Benachrichtigungs-Secrets werden mit getrennten
AES-GCM-Kontexten verschlüsselt. Der gemeinsame Schlüssel wird beim ersten
Bedarf als `data/dashboard/connection.key` mit restriktiven Rechten erzeugt.
Datenbank und Schlüssel müssen gemeinsam gesichert werden; über die API werden
weder Klartext-Secret noch Schlüssel ausgeliefert. Ein separat automatisch
erzeugtes Token in `data/parser-control/control.token` schützt die nur im
Compose-Netz erreichbare Verbindung zwischen Supervisor und API.

Die aktuell im Browser bearbeitete Farbe und das gespeicherte Custom-Profil
sind lokale UI-Präferenzen. Ein globaler Standard gilt für Browser ohne lokale
Abweichung. Beim ersten Aufruf blockiert ein Setup-Screen das Dashboard, bis
ein Admin-Passwort mit mindestens zwölf Zeichen festgelegt wurde. Nur der
gesalzene Passwort-Hash wird in `dashboard.db` gespeichert.

Eine Admin-Anmeldung ist für globale Einstellungen und die
Mailbox- und Benachrichtigungsverwaltung erforderlich.
Die Sitzung wird in einem `HttpOnly`-Cookie mit zwölf Stunden Gültigkeit
gehalten. Das Passwort kann unter **Einstellungen → Administration** geändert
werden; dabei werden andere bestehende Admin-Sitzungen beendet. Das lesende
Dashboard bleibt ohne Admin-Anmeldung verfügbar.

Die Warnungs-IDs werden deterministisch aus Auslöser, Domain, Host und Reporttag
gebildet. Damit werden wiederholte Anzeigen desselben Ereignisses dedupliziert,
ohne ein neues Ereignis an einem späteren Reporttag zu unterdrücken.

## E-Mail-Alerting

Das Alerting ist standardmäßig deaktiviert. Wenn es ein Administrator
einschaltet, bewertet ein Hintergrundprozess alle fünf Minuten die offenen
Warnungen der letzten 30 Tage. Nur die im GUI ausgewählten Ereignistypen werden
versendet. Eine Zustellung wird anhand von Warnungs-ID, Versandweg, Absender und
Empfängerliste persistent dedupliziert. Vorübergehende Fehler werden höchstens
dreimal mit ansteigendem Abstand erneut versucht.

SMTP unterstützt STARTTLS, implizites TLS und ein bewusst gewähltes internes
Relay. Microsoft Graph verwendet den app-only-Endpunkt
`/users/{sender}/sendMail`; Zugangsdaten können separat gepflegt oder aus einer
gespeicherten Graph-Postfachanbindung übernommen werden. In beiden Fällen wird
derselbe MIME-Inhalt erzeugt:

- menschenlesbare HTML-Version
- Klartext-Fallback
- stabile `X-DMARC-Control-*`-Header
- JSON-Anhang `dmarc-alert.json` mit Schema
  `dmarc-control.alert.v1`

Der Testversand wird ausschließlich durch einen angemeldeten Administrator
ausgelöst. Er schaltet den automatischen Versand nicht ein.

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

Öffentliche IPv4-Adressen werden zusätzlich als dynamischer Anschlussbereich
markiert, wenn der PTR sowohl die Quell-IP (auch in umgekehrter
Oktettreihenfolge) als auch ein typisches Zugangsnetz-Muster enthält. Explizite
Static-Marker und bereits belastbar erkannte Maildienste verhindern diese
Zuordnung. Ein dynamischer Bereich zusammen mit einem echten DMARC-Fail wird
als starkes Indiz für Spoofing oder Spam hervorgehoben, bleibt aber wegen
möglicher Fehlkonfigurationen bewusst keine definitive Scam-Feststellung.

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
| `GET /api/settings/mailbox` | Entwurf, aktive Revision und Parserstatus lesen |
| `PUT /api/settings/mailbox` | neuen Verbindungsentwurf als Admin speichern |
| `POST /api/settings/mailbox/test` | gespeicherten Entwurf streng lesend prüfen |
| `POST /api/settings/mailbox/activate` | erfolgreich getestete Revision aktivieren |
| `GET /api/settings/notifications` | geschützte Alerting-Konfiguration und Zustellstatus lesen |
| `PUT /api/settings/notifications` | SMTP-/Graph-Versand und Ereignisauswahl speichern |
| `POST /api/settings/notifications/test` | explizite strukturierte Test-E-Mail versenden |
| `GET /api/internal/parser/config` | aktive Konfiguration für den Supervisor |
| `POST /api/internal/parser/status` | Laufzeitstatus des einzelnen Parsers melden |
| `GET /api/domains` | verfügbare Header-From-Domains |
| `GET /api/overview` | Kennzahlen, Trend, Fehlerquellen, Reports und Policies |
| `GET /api/hosts` | vollständiges Sending-Host-Inventar |
| `GET /api/hosts/{ip}` | einzelne Host-Detailansicht |
| `PUT /api/hosts/{ip}/classification` | manuelle Dienst- und Klassifizierungszuordnung |
| `DELETE /api/hosts/{ip}/classification` | manuelle Zuordnung entfernen und Automatik wiederherstellen |
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
`dashboard`- und `parsedmarc`-Service verändert. OpenSearch und Grafana bleiben
unangetastet. Beim ersten Rollout wird nur der bestehende Parser-Container
ersetzt; der neue Supervisor startet darin genau einen Kindprozess mit der
vorhandenen Legacy-Konfiguration. Erst eine später in der GUI getestete und
aktivierte Revision ersetzt diese Konfiguration.

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
docker build -t parsedmarc-managed:local parser
python -m unittest discover -s parser/tests -v
```
