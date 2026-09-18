# Audit: Sending Hosts und Alerting

Stand: 7. September 2026 · DMARC Control

## Ergebnis und Einordnung

Der Audit bestätigt zehn fachliche beziehungsweise funktionale Inkonsistenzen. Die wichtigsten betreffen die Identität von Alerts, die Vollständigkeit der ausgewerteten Hosts, die Zuordnung zu Domains und die Überwachung ausbleibender Reports. Diese Fehler können zusätzliche Warnungen erzeugen oder relevante Warnungen ausblenden, ohne dass die Anwendung abstürzt. Das ist mit einem ansonsten stabilen Produktionsbetrieb vereinbar.

Die Befunde wurden am **aktuellen lokalen Arbeitsstand** untersucht: Basis-Commit `9f3456d16127c4f159cad8057c9e57e68b6a07b3`, einschließlich der bereits vorhandenen, nicht eingecheckten Änderungen. Eine Übereinstimmung dieses Arbeitsstands mit dem produktiven Image wurde nicht geprüft. Es gab keinen Zugriff auf `docker01`, keinen echten Mailversand und keine Änderung an Anwendungscode oder Produktionsdaten. Neu angelegt wurde dieser Bericht.

„Hoch“ bezeichnet die empfohlene Korrekturpriorität wegen möglicher falscher oder fehlender Warnungen. Es bedeutet nicht, dass ein entsprechender Vorfall in der Produktion nachgewiesen wurde.

| ID | Priorität | Befund | Relevant insbesondere bei |
|---|---|---|---|
| F01 | Hoch | Erfolgreiche Folgereports erzeugen neue Alerts für alte Fehler | Gemischten Pass-/Fail-Zeiträumen und bearbeiteten Alerts |
| F02 | Hoch | Mengenlimits lassen Hosts und Alerts unbemerkt weg | Mehr als 100/250/300 Hosts, abhängig vom Zugriff |
| F03 | Hoch | Fehler gemeinsam genutzter IPs werden einer falschen Domain zugeschrieben | Mehreren Domains auf derselben Source-IP |
| F04 | Hoch | Ausbleibende Reports werden unvollständig erkannt | Mehreren Domains oder längeren Ausfällen |
| F05 | Mittel | Teilweise SMTP-Ablehnung wird als vollständiger Erfolg gespeichert | Mehreren Empfängern und teilweiser Ablehnung |
| F06 | Mittel | Kompensiertes Alignment meldet zu viele betroffene Nachrichten | Gemischten Alignment-Ergebnissen eines Hosts |
| F07 | Mittel | Einzelne Zeichenketten erzeugen überhöhte Erkennungskonfidenz | Automatischer Dienst-Erkennung |
| F08 | Mittel | Eine Notiz friert unbemerkt den automatisch erkannten Dienst ein | Notizpflege bei automatischer Zuordnung |
| F09 | Mittel | Alte Ergebnisse können unter neuen Filtern erscheinen | Filterwechseln, langsamen Antworten, fehlendem Hostdetail |
| F10 | Mittel | Links und Neuladen verlieren Domain und Zeitraum | Gefilterten Untersuchungen und älteren Hosts |

## Bestätigte Befunde

### F01 — Erfolgreiche Folgereports erzeugen neue Alerts für alte Fehler

**Ursache:** Die Host-Auswertung summiert Fehler über den gesamten gewählten Zeitraum. Die Alert-ID verwendet dagegen den Tag von `last_seen`, also den neuesten beliebigen Report dieser IP. Sie verwendet damit nicht zwingend den Tag eines tatsächlichen Fehlers.

**Reproduktion:** Ein Host hat einen DMARC-Fail und erfolgreiche Nachrichten im 30-Tage-Fenster. Der Alert wird als behoben markiert. Ein neuer Tagesreport enthält ausschließlich weitere bestandene Nachrichten. Die Fail-Anzahl bleibt exakt **1**, aber der neuere Reporttag erzeugt eine andere Alert-ID mit Status **offen**. Der Versandprozess kann dafür erneut eine Nachricht senden. Die alte ID wird in der dynamisch erzeugten Liste nicht mehr angeboten; auch der frühere E-Mail-Link kann dadurch sein Ziel verlieren.

**Empfehlung:** Ereigniszeit und Ereignisidentität an der auslösenden Evidenz festmachen. Aktuelle Host-Zusammenfassungen getrennt vom gespeicherten Ereignis behandeln. Festlegen, wann zusätzliche Fehler einen bestehenden Vorfall aktualisieren beziehungsweise ein neues Ereignis erzeugen. Ein ausschließlich erfolgreicher Report darf diese Entscheidung nicht auslösen. Auch die Einordnung „neu“ beziehungsweise „verschlechtert“ sollte für ein gespeichertes Ereignis nicht bei jeder Ansicht neu bestimmt werden.

**Abnahme:** Behoben/ignoriert bleibt bei ausschließlich neuen Pass-Reports erhalten; neue tatsächliche Fehler werden nach einer expliziten Wiedereröffnungs- oder Folgeereignisregel behandelt. Alte Ereignisse bleiben über ihre ID erreichbar.

Code: [Datum und Domain der Alert-ID](../dashboard/backend/app/service.py:743), [Erzeugung des Fail-Alerts](../dashboard/backend/app/service.py:788), [Versand nur offener Ereignisse](../dashboard/backend/app/main.py:840).

### F02 — Begrenzte Hostlisten führen zu fehlenden Warnungen und Suchtreffern

**Ursache:** OpenSearch liefert nach Nachrichtenvolumen sortierte Host-Kandidaten. Die Standardabfrage holt höchstens 300 Kandidaten; erst anschließend wird nach Risiko gefiltert und auf 100 Ergebnisse begrenzt. Die Alert-Erzeugung übernimmt wiederum lediglich 250 Hosts. Der Umfang der Alert-Auswertung hängt somit an einer Listenbegrenzung.

**Reproduktionen:**

- **250 gesunde Hosts mit höherem Volumen + 1 kleiner Fehlerhost:** keine Alerts, obwohl die kritische Hostansicht den Fehlerhost noch findet.
- **300 gesunde Hosts mit höherem Volumen + 1 kleiner Fehlerhost:** zusätzlich leere kritische Hostansicht. Der direkte Abruf der betroffenen IP liefert weiterhin `dmarc_fail=1`.
- Die UI durchsucht ausschließlich die bereits geladenen maximal 100 Hosts. Eine existierende IP außerhalb dieser Auswahl kann deshalb „Keine Sending Hosts gefunden“ ergeben.

**Empfehlung:** Alert-Auswertung unabhängig von Darstellungslimits vollständig durchführen. Hostinventar und Suche serverseitig paginieren; Risikoauswahl vor einer begrenzten Ergebnisauswahl berücksichtigen. Gesamtzahl und eventuell unvollständige Ergebnisse sichtbar ausweisen. Nur die Grenzwerte zu erhöhen verschiebt das Problem. Die Begrenzung der zurückgegebenen Buckets durch `size` ist auch in der [OpenSearch-Dokumentation](https://docs.opensearch.org/latest/aggregations/bucket/terms/#the-size-and-shard_size-parameters) beschrieben.

**Abnahme:** Fehlerhosts bleiben bei mehr als 1.000 aktiven IPs in Alerting, Risikofilter und Suche auffindbar; die UI zeigt eine vollständige oder ausdrücklich paginierte Ergebnismenge.

Code: [Kandidatenbegrenzung](../dashboard/backend/app/service.py:527), [nachgelagerter Risikofilter](../dashboard/backend/app/service.py:660), [250 Hosts für Alerts](../dashboard/backend/app/service.py:737), [lokale Suche](../dashboard/frontend/src/App.tsx:4318).

### F03 — Gemeinsame Source-IPs vermischen Domain und Fehler

**Ursache:** Unter „Alle Domains“ werden Nachrichten einer IP über sämtliche Domains zusammengefasst. Als einzelne Alert-Domain wird danach die erste Domain aus `header_froms` verwendet. Diese Liste ist nach Reportzeilenhäufigkeit sortiert; sie stellt keinen Bezug zu den fehlerhaften Nachrichten her.

**Reproduktion:** Dieselbe IP liefert 2.000 bestandene Nachrichten für `healthy.example` und einen Fail für `failing.example`. Die globale Ansicht meldet einen kritischen Alert für **healthy.example**. Gefiltert auf diese Domain gibt es korrekterweise keinen solchen Alert. Gefiltert auf `failing.example` erscheint der Fehler unter einer **anderen ID**. Wird dieser als behoben markiert, bleibt der globale Alert offen. Der automatische Versand verwendet die globale Ansicht.

**Empfehlung:** Warnungen mindestens pro Domain und Source-IP anhand der zugehörigen Fehlerdaten erzeugen. Die globale Ansicht soll dieselben Ereignisse zusammenführen, die auch im Domainfilter erscheinen. Eine übergreifende Hostansicht kann weiter sinnvoll sein, benötigt aber Domain-Aufschlüsselungen.

**Abnahme:** Globale und domainspezifische Ansicht verwenden für dasselbe Ereignis dieselbe ID und denselben Bearbeitungsstatus. Fehlerzahlen und Domain beziehen sich auf dieselbe Datengruppe.

Code: [Gruppierung nur nach IP](../dashboard/backend/app/service.py:528), [Domainauswahl](../dashboard/backend/app/service.py:744), [globaler Versandlauf](../dashboard/backend/app/main.py:834).

### F04 — Die Report-Frische hat zwei blinde Flecken

**Ursache A:** Der automatische Versand bewertet `alerts("*", 30)`. Die Frischeprüfung verwendet dabei nur den jüngsten Report über alle Domains. Eine aktive Domain verdeckt den Ausfall einer anderen.

**Reproduktion A:** Domain A seit vier Tagen ohne Report, Domain B aktuell: global **0** Frischewarnungen, nach Auswahl von A **1** Warnung.

**Ursache B:** Der jüngste Report wird aus der zeitlich gefilterten Übersicht genommen. Liegt kein Report mehr in diesem Fenster, ist `last_report=None`. Dieser Fall wird nicht als Ausfall bewertet.

**Reproduktion B:** Derselbe vier Tage alte Report führt bei 30 Tagen zu einer Warnung, bei drei Tagen zu keiner. Bei 31 Tagen Ausfall ist die Warnung im standardmäßigen 30-Tage-Fenster vollständig verschwunden; bei 90 Tagen erscheint sie wieder.

**Empfehlung:** Den letzten bekannten Berichtszeitraum unabhängig vom Anzeigezeitraum pro überwachter Domain ermitteln. Erwartete aktive Domains verwalten; „noch nie Daten erhalten“, „bewusst stillgelegt“ und „Reports bleiben aus“ getrennt behandeln. Das bereits verwendete `date_end` ist als Ende des Berichtszeitraums sinnvoll und sollte erhalten bleiben.

**Abnahme:** Neue Reports für B lösen den Ausfall von A nicht auf. Ein bestehender Ausfall bleibt auch nach Ablauf des Anzeigezeitraums erkennbar; eine leere Erstinstallation erzeugt nicht automatisch unbegründete Ausfälle.

Code: [zeitlich gefilterte Übersicht](../dashboard/backend/app/service.py:298), [Frischeprüfung nur bei vorhandenem Zeitwert](../dashboard/backend/app/service.py:868), [Versandumfang](../dashboard/backend/app/main.py:834).

### F05 — Teilweise SMTP-Ablehnung wird als Erfolg gespeichert

**Ursache:** `SMTP.send_message()` kann bei mindestens einem akzeptierten Empfänger regulär zurückkehren und dabei ein Dictionary der abgelehnten Empfänger zurückgeben. Das entspricht der [Python-Dokumentation](https://docs.python.org/3/library/smtplib.html#smtplib.SMTP.sendmail). Der Rückgabewert wird ignoriert; der Versandlauf markiert das Ereignis für die gesamte Empfängerliste als erfolgreich.

**Reproduktion:** Ein Empfänger wird akzeptiert, ein zweiter vorübergehend mit `450` abgewiesen. Ergebnis im Zustellstatus: **1 erfolgreich, 0 fehlgeschlagen**. Zwei Versandzyklen verursachen insgesamt nur einen SMTP-Aufruf; der abgewiesene Empfänger wird nicht erneut versucht.

**Empfehlung:** Ergebnisse pro Empfänger erfassen und vorübergehend abgewiesene Empfänger gezielt erneut versuchen. Eine pauschale Wiederholung an alle Empfänger würde zusätzliche Duplikate erzeugen. Dauerhafte Ablehnungen separat anzeigen. In der UI „vom Versandserver akzeptiert“ von nachgewiesener Zustellung unterscheiden.

**Abnahme:** Teilfehler sind sichtbar, akzeptierte Empfänger erhalten kein unnötiges Duplikat, vorübergehend abgewiesene werden nach der Wiederholungsregel berücksichtigt.

Code: [ignorierter SMTP-Rückgabewert](../dashboard/backend/app/notifications.py:531), [Erfolgsmarkierung](../dashboard/backend/app/main.py:869).

### F06 — Kompensiertes Alignment überschätzt die betroffene Menge

**Ursache:** Bei `compensated-alignment` wird das gesamte Nachrichtenvolumen des Hosts als `messages` übernommen. E-Mail und JSON geben es anschließend als betroffene Nachrichten aus.

**Reproduktion:** 1.000 Nachrichten bestehen DMARC, nur eine hat ein SPF-Alignment-Problem bei bestandenem DKIM. Der Alert meldet **1.000 betroffen**, tatsächlich ist es **1**.

**Empfehlung:** Betroffene Nachrichten mit „SPF nicht aligned ODER DKIM nicht aligned“ aggregieren; Gesamtvolumen separat ausweisen.

**Abnahme:** Der Beispielsfall meldet eine betroffene Nachricht und 1.000 Nachrichten Gesamtvolumen.

Code: [Mengenübernahme](../dashboard/backend/app/service.py:861), [JSON-Feld affected_messages](../dashboard/backend/app/notifications.py:234).

### F07 — Hohe Konfidenz beruht teilweise auf nur einer Zeichenkette

**Ursache:** PTR, Domain, ASN und Identitätsinformationen werden zu einem gemeinsamen Text zusammengefügt. Die Erkennung prüft beliebige Teilzeichenketten und addiert überlappende Treffer. Die Herkunft der einzelnen Evidenz geht dabei verloren.

**Reproduktion:** Jeder dieser Fälle ergibt für sich **Microsoft 365, Konfidenz 0,99, „Hoch“**:

- ausschließlich PTR `x.outbound.protection.outlook.com`;
- ausschließlich PTR `x.outbound.protection.outlook.com.attacker.example`;
- ausschließlich ein Identitäts-Evidenzeintrag mit der Outlook-Zeichenkette, ohne PTR oder ASN.

Im letzten Fall enthält die Ergebnis-Evidenz trotzdem „PTR: Microsoft EOP“. Die Oberfläche verspricht dagegen, PTR sei niemals die alleinige Entscheidungsgrundlage. Der Wert 0,99 ist hier ein aufsummierter Heuristikwert und keine validierte Trefferwahrscheinlichkeit.

**Empfehlung:** Herkunft und Typ der Signale erhalten, Domain-Grenzen prüfen, korrelierte Treffer begrenzen und hohe Konfidenz an unabhängige Evidenz knüpfen. Die tatsächliche Herkunft muss in der UI stimmen. Das betrifft die Qualität der Triage; die Dienst-Erkennung hebt DMARC-Fails derzeit nicht auf.

**Abnahme:** Fremde Domains mit eingebettetem Providernamen gelten nicht als Providerdomain. Ein alleiniger PTR kann nicht durch drei überlappende Regeln wie drei unabhängige Belege gewertet werden.

Code: [Zusammenführung der Signale](../dashboard/backend/app/service.py:128), [überlappende Microsoft-Regeln](../dashboard/backend/app/service.py:145), [Teilzeichenkettenvergleich](../dashboard/backend/app/service.py:168), [UI-Aussage zur Evidenz](../dashboard/frontend/src/App.tsx:4752).

### F08 — Eine Notiz speichert unbemerkt eine feste Dienstzuordnung

**Ursache:** Das Formular startet mit dem automatisch erkannten Dienstnamen. Auch wenn ausschließlich eine Notiz geändert wird, übermittelt es diesen Namen als expliziten Override. Der Status kann gleichzeitig „Automatisch“ bleiben. Später wird der gespeicherte Name weiter angezeigt, während Konfidenz und Evidenz aus der neuen automatischen Bewertung stammen.

**Reproduktion:** SMTP2GO automatisch erkannt → nur Notiz gespeichert → spätere Erkennung Microsoft 365. Ergebnis: **Dienst SMTP2GO, Status Automatisch, Konfidenz 0,99, Microsoft-Evidenz**.

**Empfehlung:** Notiz, manuellen Dienst und Zuordnungsmodus unabhängig speichern. Ein unveränderter automatisch erkannter Name darf durch eine Notiz nicht eingefroren werden. Manuelle Zuordnung und automatische Alternative mit jeweils eigener Herkunft darstellen.

**Abnahme:** Eine reine Notizänderung lässt die automatische Erkennung weiterarbeiten. Eine bewusst manuelle Zuordnung bleibt erhalten und wird eindeutig als manuell gekennzeichnet.

Code: [Formularinitialisierung](../dashboard/frontend/src/App.tsx:4571), [Speicherpayload](../dashboard/frontend/src/App.tsx:4590), [Übernahme des Overrides](../dashboard/backend/app/service.py:679).

### F09 — Filter und angezeigte Ergebnisse können auseinanderlaufen

**Fall A:** Hostliste und ausgewähltes Hostdetail werden gemeinsam mit `Promise.all` geladen. Fehlt der ausgewählte Host im neuen Domain-/Zeitfenster, verwirft dessen 404 auch die erfolgreich geladene neue Liste. Die alte Liste und das alte Detail bleiben stehen. Es erscheint zwar ein Fehler, aber die weiterhin angezeigten Daten gehören nicht zum neuen Filter.

**Fall B:** Die Loader für Hosts und Alerts prüfen nicht, ob eine Antwort noch zur aktuellsten Anfrage gehört. Anfrage A startet vor B, Antwort B kommt vor A: Die spätere Antwort A überschreibt B. Die Oberfläche zeigt anschließend den Filter B mit Daten aus A, ohne Fehlerhinweis.

**Nachweis:** Die tatsächlichen Loader aus dem Quelltext wurden mit kontrollierten Promise-Antworten ausgeführt. Beide Abläufe führten zu den beschriebenen veralteten Ergebnissen. Dies war ein isolierter Logiktest, kein vollständiger Browsertest.

**Empfehlung:** Listen- und Detailfehler getrennt behandeln. Laufende Anfragen abbrechen oder versionieren; nur die aktuellste Anfrage darf Daten, Fehler und Ladezustand setzen. Nicht mehr vorhandene Details gezielt schließen beziehungsweise ihren fehlenden Bezug zum Filter kennzeichnen. Der Alerts-Loader sollte außerdem sein Promise zurückgeben, damit `await load()` nach Statusänderungen tatsächlich auf das Neuladen wartet.

**Abnahme:** Kontrolliert vertauschte Antwortreihenfolgen führen immer zu Daten des aktuellen Filters. Ein Detail-404 verhindert keine neue gültige Hostliste.

Code: [Hostloader](../dashboard/frontend/src/App.tsx:4298), [Alertloader](../dashboard/frontend/src/App.tsx:4861), [vermeintliches Warten auf Neuladen](../dashboard/frontend/src/App.tsx:4886).

### F10 — Untersuchungslinks bewahren den gewählten Kontext nicht

**Ursache:** URLs speichern View, Host-IP, Alert-ID und Ausgangsalert, aber weder Domain noch Zeitraum. Beim Neuladen startet die Anwendung immer mit allen Domains und 30 Tagen.

**Beispiel:** Ein nur vor 60 Tagen aktiver Host lässt sich im 90-Tage-Fenster untersuchen. Nach Neuladen derselben URL wird er im 30-Tage-Fenster gesucht und kann nicht mehr gefunden werden. Bei domainspezifischen Alerts kommt die unterschiedliche Ereignisidentität aus F03 hinzu.

**Empfehlung:** Domain und Zeitraum validiert in der URL speichern und wiederherstellen. Historische Alerts direkt per stabiler ID laden können, unabhängig davon, ob sie noch in der aktuellen Liste enthalten sind. Bestehende Links ohne neue Parameter weiterhin unterstützen.

**Abnahme:** Neuladen und Teilen eines 90-Tage-/Domain-Links erhält den Untersuchungsumfang. Alte Mail-Links bleiben auflösbar oder zeigen das gespeicherte Ereignis mit verständlichem historischen Kontext.

Code: [feste Startfilter](../dashboard/frontend/src/App.tsx:997), [URL-Verwaltung](../dashboard/frontend/src/App.tsx:1120), [E-Mail-Links](../dashboard/backend/app/notifications.py:58).

## Zusätzliche Vorschläge für UI und Bedienung

Die folgenden Vorschläge ergänzen die Fehlerkorrekturen. Die Einschätzung beruht auf Komponenten, Datenfluss und Styles; es wurde kein visueller Usability-Test mit der produktiven Oberfläche durchgeführt.

| Reihenfolge | Vorschlag | Nutzen und konkreter Ansatz | Aufwand relativ |
|---|---|---|---|
| 1 | Hostdetail sofort sichtbar öffnen | Seitenpanel oder gezielter Scroll samt Fokus. Das Detail steht aktuell unter der kompletten Tabelle; bei vielen Hosts wirkt der Klick zunächst wirkungslos. | Klein–mittel |
| 2 | IP-Klick in der Übersicht öffnet genau diese IP | Die IP-Links verwenden derzeit denselben parameterlosen Wechsel zur Hostliste. Die bereits ausgewählte Quelle direkt übergeben. | Klein |
| 3 | „Wieder öffnen“ und Rückgängig anbieten | Versehentlich behobene oder ignorierte Alerts lassen sich gezielt korrigieren. Die API unterstützt `open` bereits. | Klein |
| 4 | Offene Alerts konsistent zählen | Der aktuelle Zähler zählt bereits nach Status gefilterte Zeilen. Bei „Behoben“ ergibt das grün „0 offen“, auch wenn andere offene Alerts existieren. Gesamtzahl separat abfragen oder ausdrücklich als Auswahlzählung beschriften. | Klein–mittel |
| 5 | Versandstatus am einzelnen Alert anzeigen | Ausgewählter Ereignistyp, Empfängerstatus, letzter Versuch und nächster Versuch helfen direkt bei der Triage. Ausgeschöpfte Versuche gezielt erneut anstoßen können. | Mittel |
| 6 | Aktivierung und Funktionsstatus unterscheiden | „Alerting aktiviert“ um letzten erfolgreichen Prüflauf und aktuellen Fehler ergänzen. Fehler vor dem Versand werden heute im Wesentlichen nur protokolliert. | Mittel |
| 7 | Ungespeicherte Änderungen erhalten | Neue Hostobjekte setzen das Formular zurück. Änderungen als ungespeichert markieren und beim Aktualisieren oder Filterwechsel nicht still verwerfen. | Mittel |
| 8 | Alert-Suche, Typ-/Prioritätsfilter und Sortierung | Triage nach Domain, IP, Ereignistyp und Priorität erleichtern. Die aktuelle Reihenfolge zeigt innerhalb einer Priorität ältere Reportzeiten zuerst. | Mittel |
| 9 | Erklärtexte an die tatsächliche Logik angleichen | Kritisch bedeutet echter DMARC-Fail, unabhängig von bestätigter Dienstzuordnung. „Neuer unbekannter Sender“ nur verwenden, wenn er tatsächlich unbekannt ist; sonst „Neue Source-IP mit DMARC-Fail“. | Klein |

Relevante UI-Stellen: [IP-Link in der Übersicht](../dashboard/frontend/src/App.tsx:4113), [Hostdetail unter der Tabelle](../dashboard/frontend/src/App.tsx:4487), [Formularreset](../dashboard/frontend/src/App.tsx:4578), [Zählung offener Alerts](../dashboard/frontend/src/App.tsx:4903), [Statusaktionen](../dashboard/frontend/src/App.tsx:5020).

## Technische Verbesserungen und Umsetzung

**Zuerst die fachlichen Grundlagen:** F01–F04 gemeinsam auf ein konsistentes Ereignismodell ausrichten. Anzeigezeiträume und Listenlimits dürfen die Identität oder Vollständigkeit von Alerts nicht bestimmen. Bei einer späteren Änderung der IDs bestehende Bearbeitungszustände, E-Mail-Links und Versanddeduplizierung ausdrücklich übernehmen; sonst droht beim Update eine erneute Benachrichtigung alter Fälle.

**Danach gezielte Korrekturen:** SMTP-Teilzustellungen und Mengenangaben (F05/F06), Erkennung und Overrides (F07/F08), anschließend oder parallel Filterkonsistenz und Links (F09/F10). Diese Änderungen lassen sich mit kleinen, auf die jeweiligen Grenzfälle ausgerichteten Tests absichern.

**Beobachtbarkeit ergänzen:** Der [OpenSearch-Client](../dashboard/backend/app/opensearch.py:43) prüft bei HTTP-Erfolg weder `timed_out` noch fehlgeschlagene Shards. Eine unvollständige Auswertung sollte als solche erkennbar sein. Das ist eine zusätzliche Absicherung; ein konkreter produktiver Fall mit solchen Antworten wurde nicht untersucht.

**Leistung anschließend messen:** Hostabfragen beziehen historische Daten für „erstmals gesehen“ und frühere Ergebnisse ein. Vor zusätzlichen Caches oder einer Umgestaltung zunächst Laufzeiten mit realistischen Datenmengen messen. Unveränderliche Hosthistorie, Anzeigeabfragen und periodische Alert-Auswertung bieten mögliche Ansatzpunkte. Der Frontend-Build meldet außerdem ein großes JavaScript-Paket von rund 821 kB beziehungsweise 262 kB komprimiert; bedarfsgesteuertes Laden etwa der Diagramme ist eine nachrangige Optimierung, keine hier nachgewiesene Bedienungsstörung.

## Validierung und Grenzen

| Prüfung | Ergebnis |
|---|---|
| Vollständige bestehende Backend-Tests | **28 bestanden** |
| Bestehende Parser-Tests | **3 bestanden** |
| TypeScript-Prüfung und produktiver Frontend-Build | **Erfolgreich**, Hinweis auf Paketgröße |
| Gezielt konstruierte Host-/Domain-/Frischefälle | Beschriebene Inkonsistenzen mit echten Service-/Store-Funktionen reproduziert |
| Teilweise SMTP-Ablehnung | Mit echtem Versandzyklus und temporärer SQLite-Datenbank, simuliertem SMTP-Transport reproduziert |
| UI-Antwortreihenfolge und Detail-404 | Mit tatsächlichen Loadern und kontrollierten Antworten reproduziert |
| Produktive OpenSearch-Daten, SMTP/Graph-Zustellung, Browserdarstellung | Nicht getestet |

Die zusätzlichen Prüfungen verwendeten synthetische Aggregationen beziehungsweise kontrollierte Antworten. Sie belegen das Verhalten des Anwendungscodes für diese Eingaben, nicht die Häufigkeit der Fälle im laufenden System. Die temporären Prüfskripte wurden außerhalb des Projekts ausgeführt; Anwendungstests und Anwendungscode wurden nicht verändert.

Die bestehenden Tests prüfen bereits sinnvolle Grundlagen, darunter Statuspersistenz, Trennung von Hostklassifizierung und Alertstatus, Ende des Berichtszeitraums, Versandformat und persistente Deduplizierung. Es fehlen aber insbesondere Tests der Alert-Erzeugung über mehrere Tage, mehrere Domains und größere Hostmengen sowie vollständige automatische Versandzyklen mit Teilfehlern und ausgeschöpften Wiederholungsversuchen. Deshalb widersprechen die grünen Tests den gefundenen Inkonsistenzen nicht.

Für die spätere Korrektur sollten die Abnahmeszenarien F01–F10 als gezielte Regressionstests übernommen werden. Vor einem produktiven Update ist besonders die Übernahme bestehender Ereignis- und Versandzustände zu prüfen.
