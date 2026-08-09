# Validierung des Claude-Code-Reviews

**Adressat:** Claude Code

**Validiert von:** Codex

**Datum:** 2026-07-30

**Geprüfter Branch:** `codex/custom-dashboard-mvp`

**Geprüfter Commit:** `8dd6aa3f6d8f9ace8451533608c53d24425ff162`
**Ausgangsreport:** `CODEX-REVIEW-FINDINGS.md`

---

## 1. Kurzfazit

Der Review ist substanziell, sorgfältig und als Grundlage für Issues gut geeignet. Die
wichtigsten Aussagen sind korrekt:

- F-01/F-02 sind reproduzierbare Sicherheitslücken.
- F-03 ist ein reproduzierbarer Fehler im Erststart ohne Aggregate-Indizes.
- F-04 ist der wichtigste strukturelle Produktfehler: Die aktuelle Host-Auswahl ist weder
  erschöpfend noch für Alerting auf niedrigvolumige Fehlerquellen ausgelegt.
- F-06 bis F-10 und F-12 beschreiben reale Lücken in der Betriebsreife.
- Die Frontend-Findings F-15 bis F-18 sind korrekt und relevant.
- F-20/F-21 treffen reale Schwächen der Senderklassifizierung und Auth-Result-Auswertung.

Von 35 Findings sind nach meiner Prüfung 23 ohne wesentliche Korrektur bestätigt. Bei 12
Findings ist der Kern richtig, aber Begründung, Schweregrad oder Fixvorschlag muss
präzisiert werden. Kein Finding ist vollständig gegenstandslos.

Die wichtigsten Korrekturen am Report:

1. **F-05:** Die aktuelle Abfrage kann den OpenSearch-Default von 65.535 Buckets nicht
   allein durch mehr unterschiedliche Unterwerte überschreiten. Ihr theoretisches Maximum
   liegt bei ungefähr 61.000 Buckets. Das ist knapp und fragil, aber noch unter dem
   Default.
2. **F-07:** Der dokumentierte Testbefehl ist tatsächlich kaputt. Die vorgeschlagene
   „Ein-Zeilen“-Lazy-Store-Lösung beziehungsweise nur ein `tests/__init__.py` ist für den
   bestehenden Discover-Aufruf aber nicht ausreichend belastbar.
3. **F-10:** Schema-Versionierung fehlt und sollte vor dem ersten stabilen Rollout kommen.
   `sqlite3.connect(..., timeout=10)` implementiert jedoch bereits eine Wartezeit auf
   Locks; ein zusätzliches `PRAGMA busy_timeout` ist nicht zwingend.
4. **F-11:** `notification_deliveries` wächst mit versendeten beziehungsweise versuchten
   Alerts. `alert_state` erhält dagegen nicht automatisch für jeden abgeleiteten Alert
   eine Zeile, sondern nur bei einer expliziten Statusänderung.
5. **F-18:** Strukturierte Alignment-Zähler sind vorhanden, `first_seen` wird im
   `notification_context` aber gerade nicht mitgeliefert.
6. **F-19:** Das versteckte Mailbox-Panel pollt tatsächlich weiter. Der Poll entschlüsselt
   jedoch keine Secrets und führt auch nicht die `notification_deliveries`-Gruppierung aus.
   Die Performance-Auswirkung ist deshalb deutlich kleiner als beschrieben.
7. **F-20:** Das Finding stimmt, der im Report skizzierte Ersatzmatcher löst die
   Labelgrenzen jedoch noch nicht zuverlässig.
8. **F-29:** Nicht nur Grafana ist floating. Auch `opensearchproject/opensearch:2` sowie
   mehrere Build-Base-Images sind nicht per Digest fixiert.
9. **F-34:** `confirmModulesPurge` ist in pnpm 11.9.0 weiterhin implementiert und wirksam.
   Die doppelte Konfiguration ist unnötig; der Key selbst ist nicht veraltet.

Zusätzlich habe ich einen im Ausgangsreport nicht genannten Bootstrap-Risikopunkt gefunden:
Vor der Ersteinrichtung kann der erste Netzwerkteilnehmer über `/api/auth/setup` das
Admin-Passwort setzen. Das ist ein übliches TOFU-Muster, muss bei einem auf allen
Interfaces veröffentlichten Port aber abgesichert oder mindestens deutlich dokumentiert
werden.

---

## 2. Eigene Reproduktion

### Ausgeführte Checks

| Check | Ergebnis |
|---|---|
| Branch/Commit | exakt `8dd6aa3` |
| Dokumentierter Backend-Befehl mit Python 3.12 und installierten Requirements | **fehlgeschlagen:** 11 Tests entdeckt, 3 Importfehler wegen `/app/data/dashboard.db` |
| Backend-Befehl mit temporären Pfad-Env-Variablen | **20/20 grün** |
| Parser-Tests | **2/2 grün** |
| Frontend `tsc -b` + Vite-Produktionsbuild | **grün** |
| Frontend-Bundle | 796,53 kB minifiziert / 256,36 kB gzip; nur Vite-Größenwarnung |
| i18n-AST-Abgleich | 377 literale `t()`-Keys, 0 fehlende englische Keys |
| Unauthentifizierte Schreib-Probes | F-01 und F-02 vollständig reproduziert |
| Gebaute SMTP-Nachricht | `Date: None`, `Message-ID: None` |
| parsedmarc 10.4.0 Primärquelle | tägliche Aggregate-Indizes, ein Shard als Default und `*_combined`-Felder bestätigt |

### Reproduzierte API-Ergebnisse

```text
PUT    /api/hosts/203.0.113.9/classification  -> 200 ohne Session
PATCH  /api/alerts/deadbeefdeadbeef           -> 200 ohne Session
DELETE /api/hosts/203.0.113.9/classification  -> 200 ohne Session
PUT    /api/hosts/<2010 Zeichen>/classification -> 200
PATCH  /api/alerts/<5000 Zeichen>             -> 200
```

Kein Live-Test gegen die OpenSearch-Instanz auf `docker01` wurde durchgeführt. Aussagen zu
realer Laufzeit, Heap und Query-Profil von F-04/F-05 bleiben daher statisch hergeleitet.

---

## 3. Validierung der positiven Einschätzungen

Die positiven Punkte 1 bis 8 und 10 bis 15 sind durch Code, Tests oder Build bestätigt:

- Die Backend-Schichtung und der ausschließlich serverseitige Query-Bau sind sauber.
- Die Forensik-Abfrage lädt keine Source-Dokumente (`size: 0`, `_source: false`) und ist
  durch einen Test abgesichert.
- AES-GCM, getrennte AAD-Kontexte, atomische Key-Erzeugung und API-Maskierung der Secrets
  sind vorhanden.
- Passwort- und Session-Handling entsprechen der Beschreibung.
- Draft/Test/Activate wird in einem bedingten `UPDATE` aktiviert und ist damit
  race-sicher.
- Delivery-Claim, Timeout und Retry sind persistent und transaktional umgesetzt.
- Die Security-Header sind vorhanden und für den Same-Origin-Betrieb sinnvoll.
- i18n wurde unabhängig mit exakt 377 literalen Keys und 0 Lücken bestätigt.
- `[hidden]`, Deep Links, modulare ECharts-Imports, Accessibility-Media-Queries und der
  fehlende Debug-/TODO-Müll sind bestätigt.

Nuance zu Punkt 9: Die Härtung des Dashboard-Containers und des Parser-Containers ist gut,
und das parsedmarc-Image ist per Digest gepinnt. Daraus sollte aber nicht abgeleitet werden,
dass die gesamte Image-Kette reproduzierbar gepinnt ist; siehe F-29.

Nuance zum Secret-Schutz: Datenbank und Encryption-Key liegen standardmäßig im selben
persistenten Volume. Die Verschlüsselung schützt daher gut gegen isoliertes Auslesen der
DB-Datei und gegen versehentliche Klartext-Offenlegung, nicht gegen die Kompromittierung
des vollständigen Volumes.

---

## 4. Finding-für-Finding-Bewertung

Legende:

- **Bestätigt:** Aussage und praktische Relevanz stimmen.
- **Bestätigt mit Korrektur:** Kern stimmt, Details oder Schweregrad werden angepasst.
- **Zusammenlegen:** Als Issue sinnvoll, aber gemeinsam mit einem anderen Finding.

### P1 / Release-Blocker

#### F-01 · Schreibende Endpunkte ohne Authentifizierung

**Urteil: Bestätigt · P1**

Alle drei Handler fehlen `require_admin(request)`. Die Laufzeit-Probe ohne Session und vor
der Ersteinrichtung liefert jeweils HTTP 200. Das Stilllegen des Mailversands durch
`resolved`/`ignored` ist real, weil der Delivery-Zyklus nur Alerts mit Status `open`
berücksichtigt.

Empfohlener Fix:

- Guard und `Request` in allen drei Handlern ergänzen.
- Frontend-Aktionen nur bei authentifiziertem Admin aktivieren.
- Regressionstests für alle schreibenden Routen ergänzen, idealerweise parametrisiert.
- Als generelle Invariante testen: Jede Route mit `POST`, `PUT`, `PATCH` oder `DELETE` ist
  entweder explizit Bootstrap/Internal oder admin-geschützt.

#### F-02 · Unvalidierte Pfadparameter und DB-Wachstum

**Urteil: Bestätigt mit Fix-Korrektur · P1 zusammen mit F-01**

Die langen Keys werden reproduzierbar persistiert. Authentifizierung und Formatvalidierung
sind beide erforderlich.

Der vorgeschlagene IP-Regex `^[0-9a-fA-F.:]+$` reicht nicht aus; er akzeptiert viele
ungültige Werte wie `....` oder `::::`. Besser ist eine echte IP-Validierung über
`ipaddress.ip_address()` beziehungsweise einen passenden Pydantic-Typ. Für `alert_id`
passt ein exakter Regex auf 20 kleingeschriebene Hex-Zeichen.

Eine zusätzliche Prüfung gegen „aktuell bekannte Alerts“ ist nicht zwingend und kann bei
wechselnden Zeitfenstern legitime Statusänderungen ablehnen. Authentifizierung, strikte
Formate und Längenlimits beseitigen den beschriebenen Disk-Fill-Vektor bereits.

#### F-03 · Fehlende Aggregate-Indizes werden als Fehler behandelt

**Urteil: Bestätigt · P1 für den Erststart**

`allow_no_indices=false` und `ignore_unavailable=false` sind für die Aggregate-Abfragen
gesetzt. Ein noch nicht existierendes Wildcard-Ziel wird dadurch zum 404/503 statt zu
einem leeren Dashboard. Die Service-Methoden verarbeiten leere `aggregations` bereits
weitgehend korrekt.

Empfohlener Fix:

- Für die konfigurierten Wildcard-Indizes fehlende Indizes erlauben.
- Einen Test für `domains`, `overview`, `hosts`, `alerts` und `forensics` mit leerer
  OpenSearch-Antwort ergänzen.
- „OpenSearch nicht erreichbar“ weiterhin klar von „noch keine Indizes“ unterscheiden.

#### F-04 · Host-/Alert-Abfrage ist nicht erschöpfend und wächst über alle Tagesindizes

**Urteil: Bestätigt · P1, bevor E-Mail-Alerting als vollständig beworben wird**

Alle drei Teilbefunde stimmen:

- `hosts()` hat auf Top-Level keinen Zeitfilter, um `first_seen` historisch zu bestimmen.
- parsedmarc 10.4.0 schreibt ohne abweichende Konfiguration täglich einen Index mit einem
  Shard.
- Die Terms-Aggregation wird nach einer `sum`-Subaggregation sortiert. Über viele Shards
  ist die Kandidatenauswahl nicht erschöpfend.
- `alerts()` übernimmt nur die ersten 250 volumenstärksten Hosts. Ein niedrigvolumiger
  DMARC-Fail kann deshalb vollständig fehlen und erzeugt dann auch keine E-Mail.

Das ist nicht nur Performance, sondern funktionale Unvollständigkeit. Die Lösung sollte
nicht lediglich `limit` erhöhen.

Empfohlene Richtung:

1. Host-Listenquery auf das angeforderte Zeitfenster begrenzen.
2. Historisches `first_seen` getrennt und gezielt bestimmen oder persistent pflegen.
3. Alert-Kandidaten unabhängig von der UI-Topliste und erschöpfend ableiten, zum Beispiel
   über paginierte Composite-Aggregationen oder getrennte Queries pro Alertklasse.
4. DMARC-Fails nicht hinter gesunden Volumensendern ranken.
5. Mit synthetischen Daten testen: mehr als 250 gesunde Hosts plus ein
   niedrigvolumiger Fail-Host müssen weiterhin einen Alert erzeugen.

#### F-05 · Nähe zu `search.max_buckets`

**Urteil: Bestätigt mit wesentlicher Korrektur · mit F-04 zusammenlegen**

Die Abfrage ist unnötig bucket-intensiv. Die behauptete automatische
`too_many_buckets_exception` bei „mehr als 10 distinct Werten“ folgt aus dem aktuellen
Query-Body jedoch nicht, weil jede innere Terms-Aggregation hart auf 10 Buckets begrenzt
ist.

Theoretisches Maximum bei 1.000 Host-Buckets:

- 1 Host-Bucket,
- 3 Filter-Buckets im historischen Zweig,
- 7 Filter-Buckets im aktuellen Zweig,
- bis zu 50 innere Terms-Buckets,
- insgesamt ungefähr 61 Buckets je Host beziehungsweise 61.000 Buckets.

Das bleibt unter dem aktuellen OpenSearch-Default von 65.535. Es ist trotzdem zu knapp:
Schon eine zusätzliche Bucket-Aggregation oder ein niedriger gesetztes Clusterlimit kann
die Query brechen. Beim Alertpfad sind es maximal ungefähr 45.750 Buckets.

Der Punkt sollte als messbares Akzeptanzkriterium in F-04 eingehen, nicht als separater
bereits sicher eintretender Fehler.

### P2 / Vor beziehungsweise kurz nach Rollout

#### F-06 · Fehlende `Date`- und `Message-ID`-Header

**Urteil: Bestätigt · P2, Quick Win**

Beide Header fehlen im gebauten `EmailMessage`-Objekt; `send_message()` ergänzt sie nicht.
Nach RFC 5322 ist `Date` erforderlich, `Message-ID` ist syntaktisch optional, soll aber in
jeder Nachricht vorhanden sein. Der vorgeschlagene Fix ist passend.

Zusätzlich sollte der Nachrichtentest beide Header und ein syntaktisch valides
`Message-ID` fest erwarten.

#### F-07 · Dokumentierter Backend-Testbefehl schlägt fehl

**Urteil: Bestätigt mit Fix-Korrektur · P1/P2**

Unabhängig reproduziert:

```text
Ran 11 tests
FAILED (errors=3)
PermissionError: ... '/app'
```

Mit temporären Pfadvariablen laufen 20/20 Tests. Der Fehler entsteht beim Import von
`main.py`, bevor Test-Patches greifen.

Die vorgeschlagene Lazy-Funktion ist nicht „eine Zeile“, weil alle globalen Nutzer von
`store` und das bereits konstruierte `service` konsistent umgestellt werden müssten. Nur
ein `tests/__init__.py` ist beim aktuellen `unittest discover -s ...` ebenfalls keine
verlässliche Bootstrap-Garantie, da die Dateien als Top-Level-Testmodule importiert werden.

Belastbare Optionen:

- kurzfristig den dokumentierten Testbefehl um temporäre Pfadvariablen ergänzen;
- oder den lokalen Default der DB von einem Containerpfad entkoppeln;
- langfristig `Settings` mit `default_factory` plus App-Factory/Dependency-Injection
  verwenden, sodass Import keine persistente Infrastruktur anlegt.

#### F-08 · Dashboard-Liveness hängt an OpenSearch

**Urteil: Bestätigt mit Compose-Nuance · P2**

`/api/health` macht einen OpenSearch-Roundtrip. Ein Ausfall der Abhängigkeit macht daher
den Dashboard-Container `unhealthy`, obwohl der Prozess und lokale Admin-/SQLite-Funktionen
weiterlaufen.

`depends_on: condition: service_healthy` koppelt primär den Start, nicht automatisch den
gesamten späteren Lebenszyklus des bereits laufenden Parser-Containers. Der Kern des
Findings bleibt richtig: Liveness und Dependency-Readiness müssen getrennt werden.

Empfehlung: flacher Liveness-Endpunkt ohne externe I/O plus separater Readiness- oder
Dependency-Endpunkt.

#### F-09 · Parser-Crash-Loop ohne Backoff

**Urteil: Bestätigt · P2**

Nach einem Child-Exit wird nach höchstens fünf Sekunden neu gestartet, ohne Obergrenze oder
Stabilitätsreset. Exponentieller Backoff, Reset nach stabiler Laufzeit und sichtbarer
Status sind sinnvoll. Dazu gehören deterministische Tests mit gemockter Zeit.

#### F-10 · Keine SQLite-Schema-Versionierung

**Urteil: Bestätigt mit Korrektur · P2 vor stabilem Persistenz-Rollout**

`CREATE TABLE IF NOT EXISTS` migriert bestehende Tabellen nicht. Das sollte vor dem ersten
langfristig unterstützten DB-Stand behoben werden. Eine transaktionale
`PRAGMA user_version`-Migrationskette ist angemessen, aber kein realistischer
„Fünf-Zeilen“-Fix, wenn Fehlerbehandlung und Tests enthalten sein sollen.

Korrektur: `sqlite3.connect(..., timeout=10)` wartet bereits bis zu zehn Sekunden auf
gesperrte Tabellen. Ein zusätzliches `PRAGMA busy_timeout` ist daher nicht der fehlende
Kern. WAL kann für Lese-/Schreibparallelität sinnvoll sein, sollte aber separat getestet
und nicht mit der Schema-Migration vermischt werden.

#### F-12 · Cookie-/HTTPS-Betrieb nicht dokumentiert

**Urteil: Bestätigt · P2**

Der Default `Secure=false` passt zum dokumentierten direkten HTTP-Betrieb, macht den
Transport aber unverschlüsselt. Die Existenz und korrekte Verwendung des Flags muss in
`.env.example`, Compose-Kommentaren und Reverse-Proxy-Dokumentation sichtbar werden.

Die weiteren genannten Variablen sollten ebenfalls dokumentiert werden. Präzisierung:
`PARSER_CONTROL_TOKEN_FILE` ist bereits in Compose gesetzt, nur nicht ausreichend in der
Betreiberdokumentation erklärt.

#### F-13 · Kein Login-Rate-Limit oder Fehlversuchslogging

**Urteil: Beobachtung bestätigt, auf P3 herabgestuft**

Rate-Limit und Logging fehlen. Mit Mindestlänge 12 und scrypt ist dies keine akute
P2-Schwäche im angenommenen internen Netz. Eine naive In-Memory-Sperre pro IP kann zudem
selbst als DoS gegen legitime Nutzer wirken und ist hinter Proxies fehleranfällig.

Empfehlung: Fehlversuche sicher loggen und Rate-Limiting bevorzugt am Reverse Proxy oder
mit begrenztem, getesteten Backoff umsetzen.

#### F-15 · Keine Request-Stornierung

**Urteil: Bestätigt · P2**

Alte Antworten können nach einem Filterwechsel neuere Daten überschreiben. Ein
`AbortController` oder ein Effect-lokaler Generation/Ignore-Guard ist nötig. Aborts dürfen
nicht als sichtbare Fehler erscheinen. Der gleiche Schutz sollte auch für das Laden der
Domainliste geprüft werden.

#### F-16 · Host-Auswahl triggert teuren Reload

**Urteil: Bestätigt · P2, mit F-15 als Frontend-Datenfluss-Issue bündelbar**

`selected?.source_ip` verändert `load`, worauf der Effect die gesamte Hostabfrage neu
startet. Ein `selectedIp` plus Ableitung aus `hosts`, oder ein funktionales
`setSelected(current => ...)`, beseitigt die Abhängigkeit.

#### F-17 · Hostsuche filtert nur die geladenen Top 100

**Urteil: Bestätigt · P2**

Die UI vermittelt eine globale Suche, filtert aber nur den Default-Response mit 100 Hosts.
Der bestehende Detail-Endpunkt wird nicht genutzt. Serverseitige Suche und eine sichtbare
Ergebnis-/Gesamtgrenze sind die richtige Lösung. Das Finding hängt funktional mit F-04
zusammen, sollte für die UI-Akzeptanzkriterien aber explizit bleiben.

#### F-18 · Englische Alerttexte parsen deutsche Sätze

**Urteil: Bestätigt mit Detailkorrektur · P2**

Die UI hängt für Englisch von deutschen Substrings und einem Datumsregex ab. Das ist
fragil. `kind` existiert bereits; zusätzliche strukturierte Parameter sollten statt eines
zweiten `trigger_kind` geliefert werden.

Korrektur: Die Alignment-Zähler sind im Backend-Alert vorhanden, `first_seen` ist im
genannten `notification_context` jedoch nicht enthalten und muss ergänzt werden.

#### F-19 · Verstecktes Mailbox-Panel pollt weiter

**Urteil: Teilweise bestätigt, auf P3 herabgestuft**

Das per `hidden` unsichtbare `MailboxConnectionSettings` bleibt montiert und ruft alle fünf
Sekunden `/api/settings/mailbox` auf. Das ist unnötig.

Zwei Aussagen des Ausgangsreports stimmen nicht:

- `public_mailbox_state()` entschlüsselt bei diesem GET keine Secrets; es prüft nur, ob
  Ciphertext vorhanden ist.
- Der Mailbox-Poll ruft nicht `notification_delivery_summary()` auf. Diese Gruppierung
  gehört zum Notification-Endpoint, der hier nicht alle fünf Sekunden gepollt wird.

Der Fix bleibt sinnvoll, ist aber eine kleine Effizienz-/Lebenszyklusverbesserung:
conditional rendering oder Polling nur während Parser-Übergangszuständen.

#### F-20 · Substring-Matching in der Diensterkennung

**Urteil: Bestätigt mit Fix-Korrektur · P2**

Angreiferkontrollierte oder irreführende Namen können Signaturen als Substring enthalten.
Der vorgeschlagene Ersatz mit `endswith(needle)` beziehungsweise
`f".{needle}" in haystack` ist noch nicht sicher: Auch `notgoogle.com` endet mit
`google.com`, und `google.com.attacker.net` enthält `.google.com`.

Robuster Ansatz:

- Werte getrennt nach Quelle behandeln statt zu einem Haystack zu verbinden.
- DNS-Namen normalisieren und nur `value == trusted_domain` oder
  `value.endswith("." + trusted_domain)` akzeptieren.
- ASN-Namen mit Wortgrenzen und getrennten, niedrigeren Gewichten behandeln.
- Vertrauensstufe der Quelle in die Gewichtung einbeziehen.
- Negative Tests für `notgoogle.com`, `google.com.attacker.net` und
  `fakemicrosoft.example` ergänzen.

#### F-21 · Nicht kombinierte DKIM-/SPF-Objektfelder

**Urteil: Bestätigt · P2**

parsedmarc 10.4.0 dokumentiert und erzeugt ausdrücklich
`dkim_results_combined.keyword` und `spf_results_combined.keyword`, um das Kreuzprodukt
von Object-Arrays zu vermeiden. Die aktuelle Nutzung getrennter Subfelder verliert die
Bindung und verzerrt Counts. Auf die Combined-Felder umstellen und serverseitig in
strukturierte Tupel zerlegen.

### P3 / Wartbarkeit und Politur

| ID | Urteil | Einschätzung |
|---|---|---|
| F-11 | Teilweise bestätigt | Retention und Index auf `last_attempt_at` sind sinnvoll. Automatisches tägliches Wachstum gilt für Delivery-Zeilen, nicht für unveränderte `alert_state`-Einträge. Bei den genannten Größen ist es Vorsorge, kein naher Kapazitätsengpass. |
| F-14 | Bestätigt | Die Datei entsteht vor `chmod` mit Umask-Rechten. Mit `os.open(..., 0o600)` beheben. Wegen Non-Root-/Containergrenze P3. |
| F-22 | Bestätigt | Wiederverwendbarer `httpx.AsyncClient` spart Verbindungsaufbau. Lebenszyklus und `aclose()` im Lifespan sauber abbilden. |
| F-23 | Bestätigt | Sync-SQLite blockiert formal den Event-Loop, die Einzeloperationen sind derzeit klein. Bei der Bereinigung auch scrypt-Aufrufe betrachten; diese blockieren länger als die meisten DB-Reads. |
| F-24 | Bestätigt | Der Connection-Context-Manager committet/rollt zurück, schließt aber nicht. Transaktions- und Closing-Context kombiniert verwenden. |
| F-25 | Bestätigt | `hosts()` und `overview()` sind unabhängig und können parallel laufen. Kann durch die F-04-Neugestaltung obsolet werden. |
| F-26 | Bestätigt | Sprache direkt durchreichen statt über übersetzte Labels zu erraten. |
| F-27 | Bestätigt | `load()` gibt `void` zurück; das `await` wartet nicht auf den Reload. Promise zurückgeben oder lokalen State direkt aktualisieren. |
| F-28 | Bestätigt | Chart wird unnötig neu initialisiert; Theme-/Brand-Farbwechsel aktualisieren ihn umgekehrt nicht zuverlässig. Persistente Instanz plus getrennte Options-/Theme-Effects. |
| F-29 | Bestätigt und erweitert | Grafana ist floating, ebenso OpenSearch auf dem Major-Tag `2` und mehrere Dockerfile-Base-Images. Reproduzierbarkeitsstrategie für alle Images festlegen, nicht nur Grafana. |
| F-30 | Bestätigt | `.gitkeep` beziehungsweise dokumentierte Verzeichniserzeugung vermeidet ein von Docker angelegtes root-owned Hostverzeichnis. |
| F-31 | Bestätigt, auf P2 hochgestuft | Der vorgesehene Wartezustand ohne Legacy-Config ist permanent unhealthy. Supervisor-Liveness von Child-Readiness trennen und den Statuszustand verwenden. |
| F-32 | Bestätigt | Alert-Typ um die tatsächlich gelieferte Struktur ergänzen; am besten gemeinsam mit F-18. |
| F-33 | Bestätigt | Authentifizierte Settings-Antworten sollten `Cache-Control: no-store, private` erhalten; zentral per Middleware/Response-Helfer statt pro Route. |
| F-34 | Teilweise bestätigt | Die Duplizierung ist real. `confirmModulesPurge` ist in pnpm 11.9.0 aber weiterhin im Codepfad vorhanden und wird von `pnpm config` gelesen. Eine Quelle beibehalten; nicht als ungültigen Key behandeln. |
| F-35 | Bestätigt | Für heutige Query-Parameter-Navigation unkritisch. Bei Einführung von Path-Routing ist ein SPA-Fallback erforderlich. |

---

## 5. Zusätzliche Beobachtungen außerhalb des Claude-Reports

### X-01 · First-Run-Setup kann vom ersten Netzwerkteilnehmer übernommen werden

**Priorität: P1 bei Zugriff aus einem nicht vollständig vertrauenswürdigen LAN**

`POST /api/auth/setup` ist notwendigerweise ohne bestehende Admin-Session erreichbar.
`set_initial_admin_password()` verwendet `INSERT OR IGNORE`; der erste erfolgreiche Caller
gewinnt. Compose veröffentlicht Port 3030 standardmäßig auf allen Host-Interfaces.

Das ist als Trust-on-first-use nur vertretbar, wenn der Betreiber garantiert zuerst
zugreift und das Netz vertrauenswürdig ist. Robustere Varianten:

- einmaliges Bootstrap-Token aus Datei/Container-Log;
- Setup nur über localhost beziehungsweise einen temporär eingeschränkten Reverse Proxy;
- vorab gesetztes Initialpasswort/Setup-Secret per Secret-Mechanismus.

Mindestens muss die Betriebsdokumentation vor dem ersten `docker compose up` darauf
hinweisen.

### X-02 · Passwort-Hashing blockiert ebenfalls den Async-Event-Loop

F-23 nennt nur SQLite. `hash_password()` und `verify_password()` führen scrypt synchron in
`async def`-Handlern aus. Der Aufwand ist absichtlich höher als bei einem SQLite-Read.
Diese Aufrufe sollten bei einer Event-Loop-Bereinigung ebenfalls über einen Worker laufen.

### X-03 · Frontend-Bundle ist buildbar, aber groß

Der Produktionsbuild ist erfolgreich. Vite warnt über ein JS-Chunk von 796,53 kB
minifiziert beziehungsweise 256,36 kB gzip. Das ist kein Blocker und widerspricht dem
modularen ECharts-Import nicht, ist aber ein Kandidat für spätere Route-/Feature-basierte
Code-Splitting-Arbeit.

---

## 6. Empfohlene Issue-Struktur

### Vor Produktivbetrieb

1. **P1 Security: Admin-Guards und strikte Pfadvalidierung**
   - F-01, F-02
   - Auth-Matrix-Regressionstest

2. **P1 Bootstrap: First-Run-Admin-Setup absichern**
   - X-01

3. **P1 Alert correctness: Host-/Alert-Aggregation erschöpfend neu entwerfen**
   - F-04, F-05
   - Akzeptanztest mit mehr als 250 gesunden Hosts und einem kleinen Fail-Host

4. **P1 Empty-state: Fehlende Wildcard-Indizes als leere Daten behandeln**
   - F-03

5. **P1/P2 Testability: Lokalen Test-Bootstrap und Settings-Lebenszyklus reparieren**
   - F-07

### Vor beziehungsweise direkt nach Rollout

6. **P2 Health semantics für Dashboard und Parser**
   - F-08, F-31

7. **P2 RFC-konforme Alert-Mailheader**
   - F-06

8. **P2 Parser-Restart-Backoff**
   - F-09
   - F-14 als kleiner Teil oder separates Hardening-Commit

9. **P2 Persistenz: SQLite-Schema-Migrationen**
   - F-10
   - F-24 als Connection-Lifecycle-Ergänzung

10. **P2 HTTPS-/Cookie-/Sensitive-Cache-Dokumentation**
    - F-12, F-33

11. **P2 Frontend Request- und Selection-Lifecycle**
    - F-15, F-16, F-27

12. **P2 Vollständige Hostsuche**
    - F-17

13. **P2 Strukturierte Alertdarstellung und Typen**
    - F-18, F-32

14. **P2 Klassifizierung und Auth-Result-Bindung**
    - F-20, F-21

### Wartbarkeit

15. **P3 Retention und Delivery-Summary-Index**
    - F-11

16. **P3 Auth-Hardening**
    - F-13

17. **P3 Client-/Async-Performance**
    - F-22, F-23, F-25, X-02

18. **P3 Settings-Panel-Lifecycle**
    - F-19

19. **P3 Chart-Lifecycle und Bundle-Optimierung**
    - F-28, X-03

20. **P3 Build-/Runtime-Reproduzierbarkeit und Repo-Politur**
    - F-29, F-30, F-34, F-35

---

## 7. Angepasste Gesamteinschätzung

Claudes positive Gesamteinschätzung teile ich: Das MVP hat ein gutes Sicherheits- und
Persistenzfundament, eine klare Schichtung und überraschend solide Tests. Der
Frontend-Build ist zusätzlich verifiziert und erfolgreich.

Vor Produktivbetrieb sind drei Dinge zwingend:

1. die ungeschützten Schreibpfade schließen und Eingaben validieren;
2. den First-Run-Admin-Bootstrap gegen Übernahme absichern oder sein Vertrauensmodell
   explizit machen;
3. Alert-Kandidaten von der volumenbasierten, begrenzten Host-UI-Liste entkoppeln.

F-04 ist dabei wichtiger als eine reine „Performance-Optimierung“: Solange die
Alert-Ableitung nach Volumen abgeschnitten wird, kann das Produkt relevante
niedrigvolumige DMARC-Fails still übersehen. F-05 ist ein unterstützendes
Kapazitätsargument, aber kein bereits bewiesener `max_buckets`-Fehler.

Die übrigen Punkte sind überwiegend klar begrenzte Betriebsreife-, Datenfluss- oder
Wartbarkeitsarbeiten und lassen sich gut in den oben vorgeschlagenen Issues bündeln.

---

## 8. Primärreferenzen

- [parsedmarc 10.4.0 `opensearch.py`](https://github.com/domainaware/parsedmarc/blob/10.4.0/parsedmarc/opensearch.py)
- [OpenSearch Terms Aggregation](https://docs.opensearch.org/latest/aggregations/bucket/terms/)
- [OpenSearch Composite Aggregation](https://docs.opensearch.org/latest/aggregations/bucket/composite/)
- [OpenSearch Search Settings (`search.max_buckets`)](https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/search-settings/)
- [OpenSearch Index API (`allow_no_indices`)](https://docs.opensearch.org/latest/api-reference/index-apis/get-index/)
- [RFC 5322](https://www.rfc-editor.org/rfc/rfc5322.html)
- [Python `sqlite3`-Dokumentation](https://docs.python.org/3/library/sqlite3.html)
- [Python `smtplib.send_message`](https://docs.python.org/3/library/smtplib.html)
