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
                         └── Online-Backup ────────> Snapshot-Repository
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

Die fachlichen Dashboard-Abfragen verwenden ausschließlich `_search`. Es werden
keine Mappings oder DMARC-Dokumente verändert. Der getrennte, admin-geschützte
Backupdienst verwendet zusätzlich nur die OpenSearch-Endpunkte
`_snapshot` zum Registrieren des fest konfigurierten Repositorys sowie zum
Anlegen und Löschen von Snapshots.

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
-zustellungen, Backup-Zeitplan und -Historie, manuell bestätigte Sending Hosts
sowie der globale UI-Farbstandard
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

OpenSearch-Historie, SQLite-Steuerungszustand, Schlüssel und Parser-Token sind
getrennte Backup-Objekte. Die verbindliche Dateninventar- und
Abhängigkeitsmatrix steht in
[BACKUP-RESTORE.md](BACKUP-RESTORE.md).

Die aktuell im Browser bearbeitete Farbe und das gespeicherte Custom-Profil
sind lokale UI-Präferenzen. Ein globaler Standard gilt für Browser ohne lokale
Abweichung. Beim ersten Aufruf blockiert ein Setup-Screen das Dashboard, bis
ein Read-Benutzer mit Passwort und ein separates Admin-Passwort festgelegt
wurden. Beide Passwörter müssen mindestens zwölf Zeichen enthalten; nur ihre
gesalzenen Hashes werden in `dashboard.db` gespeichert.

Eine gültige Read-Sitzung ist für das gesamte Dashboard und alle normalen
API-Endpunkte erforderlich. Ausgenommen sind Healthcheck, die öffentlich
erreichbaren Read-Auth-Endpunkte und die separat per Control-Token abgesicherte
Parser-API. Die Read-Sitzung wird in einem `HttpOnly`-Cookie mit zwölf Stunden
Gültigkeit gehalten. Ein Read-Logout beendet zusätzlich eine im selben Browser
aktive Admin-Sitzung.

Eine Admin-Anmeldung ist für globale Einstellungen sowie die Mailbox-,
Benachrichtigungs- und Backup-Verwaltung erforderlich. Sie verwendet eine
unabhängige, ebenfalls zwölf Stunden gültige Sitzung. Das Admin-Passwort und
der Read-Zugang können unter **Einstellungen → Administration** geändert
werden. Eine Änderung beendet jeweils die anderen Sitzungen des betroffenen
Zugangstyps; der ändernde Browser erhält direkt eine neue Sitzung.

Beim Upgrade einer bestehenden Installation ohne Read-Zugang wird das Setup
erneut als unvollständig markiert. Das vorhandene Admin-Passwort muss bestätigt
werden, bevor der Read-Benutzer ergänzt wird. Das Admin-Passwort selbst bleibt
dabei unverändert.

Die Warnungs-IDs werden deterministisch aus Auslöser, Domain, Host und Reporttag
gebildet. Damit werden wiederholte Anzeigen desselben Ereignisses dedupliziert,
ohne ein neues Ereignis an einem späteren Reporttag zu unterdrücken.

Die Datenfrische und die Warnung für ausbleibende Reports verwenden das Ende
des jüngsten DMARC-Berichtszeitraums (`date_end`). Der Beginn (`date_begin`)
würde bei üblichen Tagesreports rund 24 Stunden zu früh warnen. Dieser Wert
beschreibt den Berichtszeitraum und nicht den technischen Eingangszeitpunkt der
E-Mail.

## Alert-Triage und Host-Untersuchung

Warnungsstatus und Host-Klassifizierung sind bewusst unabhängige Zustände. Der
Status `open`, `acknowledged`, `resolved` oder `ignored` gehört zum konkreten
Alert in `alert_state`. Dienst, Zuordnungsstatus und Notiz gehören dauerhaft
zur Source-IP in `host_overrides`. Eine bestätigte Host-Zuordnung unterdrückt
deshalb keine späteren echten DMARC-Fails und ist keine Freigabeliste.

Die Warnungszentrale führt über **Host untersuchen** direkt zur Detailansicht
der betroffenen Source-IP. Dort bleiben Ausgangs-Alert und Rückweg sichtbar;
**Zurück zur Warnung** öffnet wieder exakt das ursprüngliche Ereignis. Die
Deep Links verwenden folgende stabile Query-Parameter:

- `?view=alerts&alert={alert_id}` für einen konkreten Alert
- `?view=hosts&host={source_ip}&from_alert={alert_id}` für dessen
  Sending-Host-Untersuchung

In der Oberfläche heißt der weiterhin kompatible interne Host-Status
`ignored` auf Deutsch **Automatische Zuordnung verworfen** und auf Englisch
**Automatic classification rejected**. Er ist damit eindeutig vom
Alert-Status **Ignoriert** beziehungsweise **Ignored** getrennt.

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

HTML, Klartext und JSON enthalten einen Link zum konkreten Alert. Bei
Host-bezogenen Ereignissen kommt ein direkter Link zur Sending-Host-Untersuchung
hinzu; der Rückweg führt wieder zum Ausgangs-Alert.

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
| `GET /api/auth/status` | Ersteinrichtung, Read- und Admin-Sitzung prüfen |
| `POST /api/auth/setup` | Read-Zugang und Admin-Passwort initial festlegen beziehungsweise Read-Zugang sicher nachrüsten |
| `POST /api/auth/read-login` | Read-Sitzung starten |
| `POST /api/auth/read-logout` | Read- und zugehörige Admin-Sitzung beenden |
| `POST /api/auth/login` | Admin-Sitzung starten |
| `POST /api/auth/logout` | Admin-Sitzung beenden |
| `POST /api/auth/change-password` | Admin-Passwort ändern |
| `PUT /api/auth/read-credentials` | Read-Benutzername und -Passwort als Admin ändern |
| `GET /api/settings/appearance` | globalen UI-Farbstandard lesen |
| `PUT /api/settings/appearance` | globalen UI-Farbstandard als Admin ändern |
| `GET /api/settings/notifications/status` | Read-sicheren Konfigurations- und Aktivstatus des E-Mail-Alertings lesen |
| `GET /api/settings/mailbox` | Entwurf, aktive Revision und Parserstatus lesen |
| `PUT /api/settings/mailbox` | neuen Verbindungsentwurf als Admin speichern |
| `POST /api/settings/mailbox/test` | gespeicherten Entwurf streng lesend prüfen |
| `POST /api/settings/mailbox/activate` | erfolgreich getestete Revision aktivieren |
| `GET /api/settings/notifications` | geschützte Alerting-Konfiguration und Zustellstatus lesen |
| `PUT /api/settings/notifications` | SMTP-/Graph-Versand und Ereignisauswahl speichern |
| `POST /api/settings/notifications/test` | explizite strukturierte Test-E-Mail versenden |
| `GET /api/settings/backups` | Online-Backup-Zeitplan, Ziel und Laufhistorie lesen |
| `PUT /api/settings/backups` | Intervall und Retention als Admin speichern |
| `POST /api/settings/backups/run` | Online-Backup als Admin manuell starten |
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

Bei der erstmaligen Aktivierung des Backup-Mounts wird OpenSearch einmal
kontrolliert neu erstellt, weil `path.repo` eine statische Einstellung ist.
`data/opensearch/` bleibt dabei unverändert erhalten. Das Dashboard wird mit
seinem Control-Backup-Mount ebenfalls neu erstellt; Grafana und die fachlichen
DMARC-Indizes werden nicht geändert. Der verwaltete Parser startet weiterhin
genau einen Kindprozess mit der aktiven GUI- oder Legacy-Konfiguration.

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
