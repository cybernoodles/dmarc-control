# DMARC Control

DMARC Control ist eine selbst gehostete Plattform zur Überwachung und Analyse
von DMARC-Berichten. Sie baut auf
[parsedmarc](https://github.com/domainaware/parsedmarc) auf und verwendet die
vom Parser geschriebenen OpenSearch-Indizes. Grafana kann in bestehenden
Installationen über das optionale Compose-Profil `grafana` parallel laufen.

## Architektur

```text
Browser ──HTTP──> DMARC Control (React + FastAPI) ──HTTP intern──> OpenSearch
Browser ──HTTP──> Grafana (optionales Profil)      ──HTTP intern──> OpenSearch
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

Statusänderungen und gespeicherte Ereignisinhalte von Warnungen, Zuordnungen
älterer Warnungs-IDs, bekannte Domains mit ihrem letzten Reportende,
Benachrichtigungseinstellungen und -zustellungen, manuell bestätigte Sending
Hosts, der globale UI-Farbstandard sowie versionierte Mailbox-Verbindungen werden in
`data/dashboard/dashboard.db` gespeichert. Diese SQLite-Datei ist vollständig
von den OpenSearch- und optionalen Grafana-Daten getrennt.

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

Eine Admin-Anmeldung ist für globale Einstellungen und die
Mailbox- und Benachrichtigungsverwaltung erforderlich. Sie verwendet eine
unabhängige, ebenfalls zwölf Stunden gültige Sitzung. Das Admin-Passwort und
der Read-Zugang können unter **Einstellungen → Administration** geändert
werden. Eine Änderung beendet jeweils die anderen Sitzungen des betroffenen
Zugangstyps; der ändernde Browser erhält direkt eine neue Sitzung.

Beim Upgrade einer bestehenden Installation ohne Read-Zugang wird das Setup
erneut als unvollständig markiert. Das vorhandene Admin-Passwort muss bestätigt
werden, bevor der Read-Benutzer ergänzt wird. Das Admin-Passwort selbst bleibt
dabei unverändert.

## Ereignisse und Datenfrische

Host-bezogene Warnungen werden pro Header-From-Domain, Source-IP und UTC-Tag
des Berichtsanfangs (`date_begin`) aus den Ergebnissen dieses Tages gebildet.
Die ID entsteht deterministisch aus Modellversion, Ereignisfamilie, Domain,
Source-IP und diesem Evidenztag. Beispielsweise gehören `new-host-fail`,
`host-degradation` und `host-fail` zur gemeinsamen Familie `dmarc-fail`.
Anzeigezeitraum, Host-Listenposition und später eingehende erfolgreiche
Reports ändern die Identität eines früheren Fail-Ereignisses nicht. Dieselbe
IP kann für verschiedene Domains unterschiedliche Ereignisse besitzen.

Die Bewertung neuer und verschlechterter Quellen berücksichtigt ihre
Vorgeschichte bis zum jeweiligen Evidenztag. Beim ersten Speichern vergebene
Ereignisart und Titel bleiben erhalten, auch wenn nachträglich ältere Reports
die rekonstruierte Vorgeschichte verändern. Ergänzende Reports desselben Tages
können Mengen und Evidenz im gespeicherten Ereignis aktualisieren;
Bearbeitungsstatus und Versandzustand bleiben separat erhalten.

Die aktuelle Warnungsliste bewertet den gewählten Zeitraum. Bereits gespeicherte
Ereignisse lassen sich zusätzlich über `GET /api/alerts/{id}` abrufen, auch
wenn sie aus dieser Liste herausgefallen sind. Dafür werden Ereignisinhalte in
`alert_events`, Bearbeitungszustände in `alert_state` und kompatible alte IDs in
`alert_aliases` gespeichert. Dies ist ein Einzelabruf gespeicherter Ereignisse;
eine vollständige Historienansicht ist damit nicht verbunden.

Datenfrische wird unabhängig vom Anzeigezeitraum pro Domain über die gesamte
noch verfügbare Reporthistorie bestimmt. Grundlage ist das Ende des jüngsten
DMARC-Berichtszeitraums (`date_end`), nicht der technische E-Mail-Eingang. Der
Beginn (`date_begin`) würde bei üblichen Tagesreports rund 24 Stunden zu früh
warnen. Frische Reports einer Domain verdecken keinen Ausfall einer anderen.

`domain_report_history` hält für jede bereits beobachtete Domain das jüngste
bekannte Reportende dauerhaft fest. Dadurch bleibt ein Ausfall erkennbar,
wenn die Indexaufbewahrung inzwischen auch den letzten Report entfernt hat.
Eine Frischewarnung bezieht sich auf Domain und letztes bekanntes Reportende;
sie verschwindet nicht allein durch die Wahl eines kürzeren Anzeigezeitraums.
Unvollständige Abfragen, etwa mit fehlgeschlagenen Shards oder ungültigen
Seitencursorn, gelten als Auswertungsfehler.

Alle so bekannten Domains bleiben überwacht. Eine Oberfläche zum Stilllegen
einzelner Domains oder zum Erfassen erwarteter, bisher nie beobachteter Domains
ist noch nicht vorhanden. Historische Domains, deren Reports bereits vor der
ersten Erfassung vollständig gelöscht waren, lassen sich aus diesen Daten
nicht nachträglich entdecken.

## Sending-Host-Inventar

Die Host-Abfrage liest alle passenden IP-Gruppen über fortgesetzte
OpenSearch-Aggregationen. Risiko- und Textfilter werden vor der Ausgabe einer
Seite auf den vollständigen Bestand angewendet. Die Suche berücksichtigt IP,
PTR, Basisdomain, erkannten beziehungsweise manuell gesetzten Dienst,
ASN-Namen sowie Header-From- und Envelope-From-Domains.

`GET /api/hosts` akzeptiert `domain`, `days`, `risk`, `search`, `limit` und
`offset`. Die Antwort enthält `items`, die Anzahl aller passenden Quellen
`total`, `limit`, `offset` und `scope`. Standardmäßig werden 100 Quellen pro
Seite ausgegeben; die API erlaubt bis zu 500. Die Oberfläche zeigt den
sichtbaren Bereich und die Gesamtzahl und startet nach Filteränderungen auf
der ersten Seite. Die Suchanfrage wird nach einer kurzen Eingabepause
serverseitig ausgeführt. Die Alert-Auswertung verwendet ihre eigene
vollständige Ereignisabfrage und hängt von keiner Host-Seite ab.

Host-Liste und ausgewähltes Detail werden unabhängig geladen. Fehlt eine IP
im gewählten Domain-/Zeitfenster, zeigt das Detail einen entsprechenden
Hinweis; die neue Host-Liste bleibt nutzbar. Überholte Listen- und
Detailanfragen dürfen aktuelle Ergebnisse nicht überschreiben.

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

Fehlt eine verlinkte Warnung in der aktuellen Liste, lädt die Oberfläche ihren
gespeicherten Inhalt und zeigt ihn in einem gesonderten historischen Kontext.
Ein auflösbarer alter Link verwendet dabei die kanonische Ereignis-ID. Domain
und Zeitraum werden derzeit noch nicht in diesen URLs gespeichert; nach dem
Neuladen gelten die Standardfilter. Ein historischer Alert kann daher
abrufbar sein, während seine Host-Untersuchung zunächst eine Anpassung des
Zeitraums benötigt.

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

Beim ersten Einsatz des Ereignismodells erfolgt einmalig eine vollständige
Auswertung aller Domains für die letzten 30 Tage. Dieser initiale Bestand ist
in der Oberfläche sichtbar, löst aber keine neuen automatischen Zustellungen
aus. Initiale Ereignisse und Initialisierungsmarkierung werden gemeinsam
gespeichert; eine fehlgeschlagene oder unvollständige Auswertung schließt die
Initialisierung nicht ab. Danach erstmals beobachtete Ereignisse können nach
den konfigurierten Regeln versendet werden. Ein später eintreffender Report
desselben initialen Ereignistages hebt dessen Versandunterdrückung nicht auf.

Alte Warnungs-IDs werden nur dann einem aktuellen Ereignis zugeordnet, wenn
die rekonstruierte Zuordnung eindeutig ist. Dabei bleiben Bearbeitungsstatus,
bereits erfolgreiche Zustellungen und vorhandene Wiederholungszustände
erhalten. Bereits begonnene, eindeutig zugeordnete und noch nicht
abgeschlossene Legacy-Zustellungen können ihren bestehenden Retry-Verlauf
fortsetzen. Mehrdeutige Zusammenfassungen mehrerer Domains oder Tage werden
nicht willkürlich einem einzelnen neuen Ereignis zugeordnet.

Ohne sichere Einzelzuordnung bleibt ein alter Bearbeitungsstatus am alten
Link erhalten; das entsprechende neue Tagesereignis beginnt mit `open`.
Auch dann verhindert die Initialisierung eine erneute automatische Versendung
des initialen Bestands. Eine pauschale Übernahme aller alten Status auf neue
Ereignisse wäre fachlich unsicher: Alte IDs bezogen sich auf den jeweils
letzten Reporttag eines Hosts und einen variablen Anzeigezeitraum, ohne die
damalige Evidenz zu speichern. Spätere erfolgreiche Reports oder nachgelieferte
Fail-Reports lassen den ursprünglichen Ereignisbezug nicht zuverlässig
rekonstruieren.

Frühere Versionen speicherten für alte Warnungen lediglich Status und
Versanddaten, keinen vollständigen Ereignisinhalt. Ein nicht zuordenbarer alter
Link kann deshalb nur den noch vorhandenen Bearbeitungsstatus und einen
Hinweis auf fehlende Details anzeigen. Weitere Evidenz kann in der
ursprünglichen E-Mail stehen. Existieren weder gespeicherter Inhalt noch
Status oder Versanddaten, liefert der Einzelabruf einen 404.

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
| `GET /api/internal/parser/config` | aktive Konfiguration für den Supervisor |
| `POST /api/internal/parser/status` | Laufzeitstatus des einzelnen Parsers melden |
| `GET /api/domains` | verfügbare Header-From-Domains |
| `GET /api/overview` | Kennzahlen, Trend, Fehlerquellen, Reports und Policies |
| `GET /api/hosts` | vollständiges Sending-Host-Inventar mit serverseitiger Suche, `limit`/`offset` und `total` |
| `GET /api/hosts/{ip}` | einzelne Host-Detailansicht |
| `PUT /api/hosts/{ip}/classification` | manuelle Dienst- und Klassifizierungszuordnung |
| `DELETE /api/hosts/{ip}/classification` | manuelle Zuordnung entfernen und Automatik wiederherstellen |
| `GET /api/alerts` | Warnungsereignisse pro Domain und Evidenztag für den gewählten Zeitraum |
| `GET /api/alerts/{id}` | gespeichertes Ereignis beziehungsweise erhaltenen Legacy-Status unabhängig vom Listenfilter lesen |
| `PATCH /api/alerts/{id}` | Warnungsstatus ändern |
| `GET /api/forensics` | minimierte Forensik-Aggregationen |

Domain- und Zeitfilter werden serverseitig als strukturierte
OpenSearch-Abfragen erzeugt. Risikobewertung und Host-Textsuche erfolgen auf
dem vollständig gelesenen Ergebnis, bevor eine Seite ausgegeben wird. Die API
akzeptiert keine frei eingebbare Query-DSL.

## Deployment mit Dockge

Dockge legt jeden Stack in einem eigenen Verzeichnis unter seinem
konfigurierten Stacks-Verzeichnis ab, beispielsweise:

```text
DOCKGE_STACKS_DIRECTORY/dmarc-control
```

Die Compose-Datei, `.env`, `dashboard/`, `parser/`, `config/` und `data/` müssen
gemeinsam in diesem Projektverzeichnis liegen. Relative Pfade werden von
Compose gegen den Speicherort der Compose-Datei aufgelöst.

Soll Grafana aktiviert werden, muss die lokale `.env`
`COMPOSE_PROFILES=grafana` und ein gesetztes `GRAFANA_ADMIN_PASSWORD`
enthalten. Installationen ohne Grafana lassen beide Werte leer.

Bei der Migration einer bestehenden Installation kann eine vorhandene
`config/parsedmarc.ini` zunächst als Legacy-Fallback eingebunden bleiben. Der
Supervisor startet damit genau einen parsedmarc-Kindprozess. Erst eine später
in der GUI getestete und aktivierte Revision ersetzt diese Konfiguration.

Das Dashboard ist nach dem Start unter `http://HOSTNAME_OR_IP:3030`
erreichbar. Port `3020` wird nur bei aktiviertem Grafana-Profil veröffentlicht.

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
