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
Hosts, der globale UI-Farbstandard sowie versionierte Mailbox-Verbindungen
werden in `data/dashboard/dashboard.db` gespeichert. Diese SQLite-Datei ist vollständig
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
Ein eindeutig zugeordneter alter Link verwendet die kanonische Ereignis-ID. Domain
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
einzelner Empfängeradresse persistent dedupliziert. Insgesamt sind höchstens
drei Versuche pro Empfänger vorgesehen, bei vorübergehenden Fehlern nach
frühestens fünf beziehungsweise zehn Minuten. Die tatsächliche Wiederholung
findet im nächsten Prüflauf statt und setzt weiterhin eine offene, ausgewählte
Warnung sowie den Empfänger in der aktuellen Konfiguration voraus.

Beim ersten Einsatz des Ereignismodells erfolgt einmalig eine vollständige
Auswertung aller Domains für die letzten 30 Tage. Dieser initiale Bestand ist
in der Oberfläche sichtbar, löst aber keine neuen automatischen Zustellungen
aus. Initiale Ereignisse und Initialisierungsmarkierung werden gemeinsam
gespeichert; eine fehlgeschlagene oder unvollständige Auswertung schließt die
Initialisierung nicht ab. Danach erstmals beobachtete Ereignisse können nach
den konfigurierten Regeln versendet werden. Später ergänzte Reports mit
demselben initial erfassten Ereignisschlüssel heben dessen
Versandunterdrückung nicht auf.

Alte Warnungs-IDs werden nur dann einem aktuellen Ereignis zugeordnet, wenn
die rekonstruierte Zuordnung eindeutig ist. Dabei bleiben Bearbeitungsstatus,
bisherige Gruppenversände samt Versuchszahlen erhalten. Seit F05 werden
Ereignisse mit solchen alten Versandzeilen automatisch zurückgehalten, auch
wenn Empfängerliste oder Versandweg geändert werden. Das betrifft ebenfalls
alte fehlgeschlagene und ungeklärte Versuche: Frühere SMTP-Teilannahmen lassen
sich aus dem Gruppen-Hash nicht rekonstruieren. Die Oberfläche zeigt diesen
Altbestand getrennt von neuen Empfängerannahmen. Mehrdeutige Zusammenfassungen
mehrerer Domains oder Tage werden nicht willkürlich einem einzelnen neuen
Ereignis zugeordnet.

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

Bei kompensiertem Alignment zählt `messages` nur Nachrichten mit nicht
ausgerichtetem SPF **oder** DKIM; beide Merkmale zählen dieselbe Nachricht
höchstens einmal. `total_messages` enthält separat das Tagesgesamtvolumen der
Domain/IP. Oberfläche, Klartext, HTML und JSON-Anhang verwenden diese Werte;
im weiterhin kompatiblen JSON-Schema heißt die betroffene Menge
`alert.affected_messages`, ergänzt um `alert.total_messages`. Die Korrektur
ändert weder Ereignis-ID noch Bearbeitungs- und Versandzustand.

Neue Versandzustände liegen in `notification_recipient_deliveries`. SMTP-
Annahme, vorübergehende Ablehnung (4xx), dauerhafte Ablehnung (5xx), laufender
Versuch und ausgeschöpftes Budget werden getrennt gespeichert. Nur noch fällige
Empfänger stehen in einem Wiederholungsversand. Hinzufügen einer Adresse setzt
die bereits gespeicherten Ergebnisse anderer Adressen nicht zurück. Microsoft
Graph bestätigt die Annahme des Versandauftrags; die Oberfläche bezeichnet
beides ausdrücklich als Annahme durch den Versandserver, nicht als bestätigte
Zustellung ins Postfach. Empfängerdetails sind ausschließlich in den
administrativ geschützten Benachrichtigungseinstellungen verfügbar; die Liste
zeigt die letzten 100 Einträge und die Gesamtzahl.

Beanspruchte Versuche werden atomar gespeichert und nach 15 Minuten ohne
Ergebnis wieder freigegeben, ohne das Budget zurückzusetzen. Ein verspätetes
Ergebnis kann keinen neueren Versuch überschreiben. Ein Verbindungsabbruch
nach serverseitiger Annahme, aber vor deren Bestätigung, bleibt grundsätzlich
mehrdeutig; ein begrenzter Retry kann in diesem Fall eine Annahme wiederholen.
Eine allgemeine Exactly-once-Garantie besteht daher nicht.

Bei einem Rollback auf eine Version vor F05 muss der automatische Versand
zunächst pausiert werden: Alte Versionen berücksichtigen die neue
Empfängertabelle nicht und könnten bereits akzeptierte Nachrichten erneut
versenden. Die aktuelle Datenbank samt Empfängerzuständen erhalten; einen
Datenbank-Snapshot nicht pauschal über spätere Bearbeitungsstände schreiben.

Der Testversand wird ausschließlich durch einen angemeldeten Administrator
ausgelöst. Er schaltet den automatischen Versand nicht ein. Schon eine
Teilablehnung führt zu einem sichtbaren fehlgeschlagenen Test mit Anzahl der
akzeptierten Empfänger und den jeweiligen Fehlermeldungen.

## Status der automatischen Auswertung

Die Warnungszentrale und die Benachrichtigungseinstellungen zeigen den
automatischen Versand und das Ergebnis des letzten Prüflaufs getrennt.
Gespeichert werden Start, Abschluss, Dauer, Domain-/Zeitumfang sowie die
Anzahl geprüfter Domains, Quellen und ermittelter Ereignisse. Die Zahlen
berücksichtigen auch die zur Einordnung benötigte Report-Historie und bekannte
Domains ohne aktuelle Reports; sie entsprechen deshalb nicht zwingend der
gefilterten Host-Seite. Der automatische Lauf gilt immer für alle Domains;
ein Domain- oder Zeitfilter in der Oberfläche verändert diesen Prüfumfang nicht.

Ein vollständig erfolgreicher Lauf mit null Ereignissen unterscheidet sich
von einer fehlgeschlagenen oder unterbrochenen Auswertung. Solange kein
vollständiges Ergebnis vorliegt, bleiben die Umfangszahlen unbekannt statt
fälschlich null. Fehler ersetzen den letzten begonnenen Lauf, erhalten aber
Zeitpunkt und Ergebnis der letzten erfolgreichen Auswertung. Ein Neustart
markiert noch laufende Prüfungen als unterbrochen; pausierter Versand erzeugt
keine künstlichen Erfolgseinträge. Beim Upgrade werden keine historischen
Prüfläufe erfunden. Der erste Status entsteht beim nächsten regulären Lauf.
Normale Listenaufrufe und die automatische Statusaktualisierung im Browser
lösen keinen solchen Lauf aus.

Der Auswertungserfolg wird vor dem Versand gespeichert. Eine spätere SMTP-
oder Graph-Ablehnung bleibt ein Versandfehler und überschreibt diesen Erfolg
nicht. Unvollständige OpenSearch-Antworten, auch fehlerhafte Folgeseiten, führen
vor dem ersten Versand zum fehlgeschlagenen Lauf. Öffentliche Fehlertexte sind
feste Kategorien ohne Endpunkte, Zugangsdaten oder rohe Serverantworten.

`evaluation_runs` speichert die letzten 20 Läufe, zusätzlich gegebenenfalls
einen älteren letzten Erfolg und noch laufende Prüfungen. Unterschiedliche
Lauf-IDs verhindern, dass verspätete Abschlüsse neuere Ergebnisse ersetzen.
`GET /api/alerts/evaluation/status` ist für angemeldete Leser verfügbar;
die gespeicherte Auswahl der auslösenden E-Mail-Fälle bleibt intern.
Die Oberfläche aktualisiert den Status alle 30 Sekunden, solange die Seite
sichtbar ist, und kennzeichnet fehlgeschlagene Aktualisierungen.

## Versanddetails an einer Warnung

Die Alert-Liste und der Einzelabruf enthalten eine zusammengefasste
Versandhistorie: noch kein Versuch, ausstehend, teilweise akzeptiert,
vollständig akzeptiert, abschließend fehlgeschlagen oder zurückgehaltener
Altbestand. Erkennbar sind letzter Versuch, früheste erneute Versuchsmöglichkeit
und ausgeschöpftes Budget. Diese Ansicht enthält weder Empfängeradressen noch
Serverantworten. Angaben beziehen sich auf gespeicherte Versuche, nicht auf
alle Adressen einer später geänderten Konfiguration.

Administratoren können direkt an der Warnung die geschützten Empfängerdetails
öffnen. `GET /api/alerts/{alert_id}/delivery` liefert höchstens 100 der zuletzt
bearbeiteten Empfängerzustände samt Gesamtzahl. Aliaslinks und die kanonische
Warnung zeigen dieselbe Historie; übernommene Gruppenzeilen werden nicht doppelt
gezählt. Diese Abrufe sind rein lesend und verändern keine Versandzustände.

Ein angezeigter Wiederholungszeitpunkt ist eine Untergrenze. Ein weiterer
Versuch setzt weiterhin aktiven Versand, eine offene und ausgewählte Warnung
sowie den Empfänger in der aktuellen Konfiguration voraus. Zurückgehaltene
Altzustellungen und ausgeschöpfte Versuche werden dadurch nicht reaktiviert.
Eine manuelle Wiederholung ist in dieser Phase nicht implementiert.

## Dienst-Erkennung

Die automatische Erkennung bewahrt zu jedem Beleg Herkunft, beobachteten
Wert, Regel und Unabhängigkeitsgruppe. Providerdomains müssen exakt oder als
echte Subdomain passen. Ein angehängtes `.attacker.example` ist kein Treffer.
PTR, davon abgeleitete Basisdomain und bekannte parsedmarc-Dienstnamen zählen
zusammen höchstens einmal; ASN-Name und ASN-Domain bilden eine weitere Gruppe.
Allgemeine Cloud-/Netzbetreiberdomains stützen nur bereits erkannte Dienste.
DKIM-Selectoren allein weisen keinen Provider nach.

Aggregierte SPF-/DKIM-Domains sind Beobachtungen ohne Erfolgsnachweis. Ein
`pass` zählt stärker, wenn Domain und Ergebnis im selben ursprünglichen
Authentifizierungsergebnis stehen. Hohe Konfidenz benötigt mindestens zwei
unabhängige Gruppen und mindestens einen bestandenen Authentifizierungsbeleg
für den Maildienst. Ein einzelner PTR ergibt nur eine niedrige Konfidenz.
Der Prozentwert ist eine Regelbewertung, keine statistisch kalibrierte
Wahrscheinlichkeit. Dienstzuordnung und Konfidenz bestätigen weder
DMARC-Alignment noch eine Berechtigung des Senders für die überwachte Domain.

Zuordnung, Vertrauensstatus und Notiz sind getrennt:

- `automatic`: Neue Evidenz aktualisiert die Erkennung. Eine reine Notizänderung
  schreibt keinen Dienst fest.
- `manual`: Der bewusst gewählte Name bleibt erhalten. Er besitzt keine
  automatische Konfidenz; die automatische Alternative samt Belegen wird
  separat angezeigt.
- `legacy_preserved`: Bestehende Zuordnungen werden unverändert übernommen,
  weil ihre frühere Absicht nicht sicher rekonstruierbar ist. Nutzer können
  sie ausdrücklich bestätigen oder zur Automatik zurückkehren.

„Automatik wiederherstellen“ entfernt den festgelegten Dienst und setzt den
Vertrauensstatus auf automatische Bewertung; die Notiz bleibt erhalten.
Explizit gleichzeitig übermittelte Vertrauensentscheidungen bleiben wirksam.
Echte DMARC-Fehler, Ereignis-IDs, Bearbeitungs- und Versandzustände sind davon
unabhängig. Die Migration ergänzt nur den Zuordnungsmodus und bewahrt alle
bisherigen Werte und Änderungszeitpunkte. Ältere Dashboard-Versionen können die
zusätzliche Spalte ignorieren, stellen aber keine expliziten Modi dar; ihre
alten Formulare können weiterhin einen gerade erkannten Dienst festschreiben.
Falls eine Altversion einen Namen in einen bisher automatischen Datensatz
schreibt, wird dieser beim erneuten Upgrade konservativ als übernommene
Zuordnung erhalten.

Öffentliche IPv4-Adressen werden zusätzlich als dynamischer Anschlussbereich
markiert, wenn der PTR sowohl die Quell-IP (auch in umgekehrter
Oktettreihenfolge) als auch ein typisches Zugangsnetz-Muster enthält. Explizite
Static-Marker und bereits erkannte Maildienste verhindern diese
Zuordnung. Zwei Muster im selben PTR bleiben eine Quelle und ergeben nur
niedrige Konfidenz. Ein dynamischer Bereich zusammen mit einem echten DMARC-Fail wird
als starkes Indiz für Spoofing oder Spam hervorgehoben, bleibt aber wegen
möglicher Fehlkonfigurationen bewusst keine definitive Scam-Feststellung.

## Untersuchungskontext und Bearbeitung

Browserlinks enthalten `domain` und `days` (1–730 Tage), zusammen mit `view`
und bei Bedarf `alert`, `host` und `from_alert`. Ohne Filter gelten wie bisher
alle Domains und 30 Tage. Domainnamen werden syntaktisch geprüft; eine
historische Domain muss nicht mehr in der aktuellen Domainliste vorkommen.
Ungültige Parameter fallen auf sichere Standardwerte zurück. Ein frei
übermittelter gültiger Zeitraum bleibt auch dann sichtbar, wenn er nicht zu
den vier üblichen Auswahlwerten gehört.

E-Mail-Links verwenden die konkrete Domain des Ereignisses und den bei der
Erstellung eingestellten Alerting-Zeitraum. Bestehende Links bleiben gültig.
Beim Wechsel Warnung → Sending Host wird die konkrete Domain übernommen;
`from_domain` und `from_days` erhalten den Ausgangskontext für die Rückkehr.
Browser-Zurück/Vorwärts und Neuladen stellen den gespeicherten Kontext wieder
her. IPs in der Übersicht öffnen direkt die Quelle. Gezieltes Öffnen setzt
Tastaturfokus auf das Detail; reine Datenaktualisierungen tun dies nicht.

`GET /api/alerts` ergänzt `status_counts` mit `all`, `open`, `acknowledged`,
`resolved` und `ignored`. Diese Zahlen entstehen vor dem Statusfilter aus
derselben vollständigen Auswertung für Domain und Zeitraum. Laden, ein
Auswertungsfehler oder fehlende Zähldaten werden nicht als „0 offen“ angezeigt.
Jede laufende Statusänderung sperrt nur die betreffende Warnung. Verspätete
Antworten aus einem verlassenen Kontext verändern weder dessen Nachfolger
noch die Sperren anderer Warnungen. „Wieder öffnen“ verwendet den bestehenden
Status `open` und erzeugt weder eine neue ID noch eine neue Versandberechtigung.

Ungespeicherte Host-Zuordnungen und Notizen werden beim Schließen, Quellen-,
Domain-, Zeitraum- oder Ansichtswechsel sowie beim Abmelden geschützt.
Speichern und Weitergehen ist erst nach erfolgreicher Speicherung ohne
neueren Entwurf möglich. Verwerfen ist während eines laufenden Speicherns
nicht möglich. Browser-Zurück stellt bei offenen Änderungen zunächst den
aktiven Eintrag wieder her; Abbrechen lässt URL und Ansicht unverändert.
Beim Neuladen oder Verlassen der Website greift die übliche Browserwarnung.
Such- und Risikofilter behalten das geöffnete Detail und dessen Entwurf bei.
Bei einem Sitzungsablauf bleibt ein offener Host-Entwurf im selben Tab im
Speicher erhalten, während die Anwendung verborgen und die Anmeldung
angezeigt wird. Eine erneute Anmeldung stellt den Entwurf wieder her. Eine
zuvor angefragte Navigation wird dabei verworfen. Verspätete Fehler einer alten
Sitzung können die neue Anmeldung nicht wieder beenden; beim bewussten
Neuladen oder Schließen des Tabs gilt weiterhin die Browserwarnung.

URL-Vertrag und Sitzungsfehler lassen sich im Frontend-Verzeichnis mit
`pnpm test` prüfen;
es werden der vorhandene TypeScript-Compiler und Nodes Testwerkzeuge benutzt.
Die Browserabnahme umfasst zusätzlich Fokus, verzögerte Antwortreihenfolgen,
parallele Statusänderungen, mobile Darstellung und alle drei Dialogaktionen.

## Domainverwaltung und ausbleibende Reports

Unter **Einstellungen → Domains** verwalten angemeldete Administratoren die
Reportüberwachung. Das Inventar enthält auch bekannte Domains außerhalb der
Indexaufbewahrung und ausdrücklich erwartete Domains ohne ersten Report.

- **Aktiv:** Reports wurden beobachtet. Die Wartefrist zählt ab dem Ende des
  jüngsten Berichtszeitraums; ältere bereits bekannte Domains übernehmen
  unverändert den bisherigen Standard `STALE_REPORT_DAYS`.
- **Erwartet:** Manuell hinzugefügt, noch kein Report beobachtet. Der Server
  speichert den Beginn und eine Wartefrist von 1 bis 365 Tagen. Erst nach
  Ablauf entsteht „Erster DMARC-Report fehlt“. Mit dem ersten beobachteten
  Report wechselt die Domain automatisch zu aktiv.
- **Stillgelegt:** Ausbleibende Reports erzeugen keine aktuelle Frischewarnung.
  Reports, Warnungshistorie, Bearbeitungsstatus und Versandnachweise bleiben
  erhalten. Echte DMARC-Fehler werden weiterhin ausgewertet.

**Reaktivieren** beginnt eine neue, in der Oberfläche sichtbare Wartefrist.
Ein alter Report löst daher nicht sofort wieder eine Ausfallwarnung aus. Die
neue Erwartung erhält einen eigenen Ereignisbezug; frühere erledigte Warnungen
und Versandnachweise werden nicht zurückgesetzt. Eine bloße Änderung der
Wartefrist erhält ihren Beginn; sie kann die Warnschwelle vorziehen oder
verschieben. Unverändertes Speichern startet keine Frist neu.

Domainnamen werden in der Verwaltung ohne Beachtung der Großschreibung und
eines abschließenden Punkts verglichen; internationale Namen verwenden IDNA.
Beobachtete Schreibweisen bleiben für exakte Reportsuche und historische
Links erhalten. Mehrere Schreibweisen derselben Domain teilen sich die
Überwachung und den jüngsten Report. Die neue Registry ist eine zusätzliche
SQLite-Tabelle; vorhandene Reports und Ereignisse werden nicht umbenannt.

Frischewarnungen verwenden weiterhin den Benachrichtigungsfall `stale-reports`.
Der ergänzte Grund unterscheidet einen fehlenden ersten Report, eine noch
nicht erfüllte Reaktivierung und einen späteren Reportausfall. Beginn,
Wartefrist und Warnschwelle sind in den E-Mail-Details und im JSON-Anhang
enthalten. Die üblichen Alerting-Schalter und Versandregeln gelten weiter.
Ein regelmäßiger Versandlauf berücksichtigt Änderungen spätestens beim
nächsten Intervall; das Öffnen der Warnungsliste wertet den aktuellen Stand
direkt aus. Die Verwaltung des gespeicherten Bestands bleibt auch bei einer
OpenSearch-Störung möglich.

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
| `GET /api/settings/domains` | gespeicherte Domainüberwachung einschließlich Fristen als Admin lesen |
| `POST /api/settings/domains` | erwartete Domain mit `domain` und `grace_days` als Admin hinzufügen |
| `PATCH /api/settings/domains` | Status und/oder Wartefrist einer Domain als Admin ändern; `grace_days: null` übernimmt den globalen Standard |
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
| `GET /api/domains` | vollständige beobachtete sowie erwartete und historische Domains mit Überwachungsstatus |
| `GET /api/overview` | Kennzahlen, Trend, Fehlerquellen, Reports und Policies |
| `GET /api/hosts` | vollständiges Sending-Host-Inventar mit serverseitiger Suche, `limit`/`offset` und `total` |
| `GET /api/hosts/{ip}` | einzelne Host-Detailansicht |
| `PATCH /api/hosts/{ip}/classification` | ausschließlich übergebene Felder ändern: Modus, manueller Dienst, Vertrauensstatus, Notiz |
| `PUT /api/hosts/{ip}/classification` | bisheriger vollständiger Aufruf; als übernommene Zuordnung gespeichert |
| `DELETE /api/hosts/{ip}/classification` | bisherigen Datensatz vollständig einschließlich Notiz entfernen; UI verwendet stattdessen PATCH |
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
