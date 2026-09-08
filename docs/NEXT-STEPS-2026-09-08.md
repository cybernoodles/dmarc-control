# Folgeplan: Sending Hosts und Alerting

Arbeitsvorschlag für die verbleibenden Auditpunkte F05–F10 und die Bedienung.
Grundlage ist das in [CUSTOM-DASHBOARD.md](CUSTOM-DASHBOARD.md) beschriebene
Ereignismodell F01–F04. Dieses Dokument beschreibt Reihenfolge und Abnahme.
Verbindliche Umsetzungstickets gehören weiterhin in den
[Issue-Tracker](BACKLOG.md).

Aufwand relativ: **klein** = begrenzte Änderung ohne Datenmigration,
**mittel** = abgestimmte API-/UI-Änderung mit mehreren Grenzfällen,
**größer** = zusätzliche persistente Zustände und Migration.

## 1. SMTP-Teilzustellungen korrekt verfolgen — F05

**Stand:** Implementiert. Empfängerzustände, begrenzte Wiederholungen und
Admin-Ansicht sind vorhanden. Alte Gruppenversände bleiben unverändert
erhalten und werden wegen fehlender Empfängerevidenz automatisch
zurückgehalten, einschließlich alter fehlgeschlagener oder ungeklärter Versuche.

**Umsetzung:** Den SMTP-Rückgabewert auswerten und Annahme, temporäre sowie
dauerhafte Ablehnung pro Empfänger speichern. Nur vorübergehend abgewiesene
Empfänger erneut versuchen. Im UI „vom Versandserver akzeptiert“ anzeigen;
daraus lässt sich keine bestätigte Zustellung ins Postfach ableiten.

**Abnahme:** Bei einem akzeptierten Empfänger und einem `450`-Fehler wird nur
der zweite erneut angeschrieben. Ein `550`-Fehler bleibt sichtbar und führt
zu keiner automatischen Endlosschleife. Neustart und wiederholte Auswertung
erzeugen kein Duplikat beim bereits akzeptierten Empfänger. Vorhandene
Versandzustände werden bei der Migration erhalten; unklare alte Teilzustellungen
werden nicht automatisch vollständig erneut versendet.

**Abhängigkeit / Aufwand:** Stabile Ereignis-IDs aus F01; eigenes Zustellmodell
pro Empfänger samt Migration. **Größer.** Die späteren Versanddetails am Alert
bauen darauf auf.

## 2. Auswertung und Betrieb sichtbar machen

**Stand:** Persistenter Prüflaufstatus und Versanddetails direkt an der
Warnung sind implementiert. Auswertungserfolg, pausierter Versand und
Empfängerablehnung werden getrennt angezeigt. Manuelle Wiederholungen bleiben
als separate Erweiterung offen; sie dürfen weder bereits akzeptierte
Empfänger erneut anschreiben noch unklare Altzustellungen pauschal freigeben.

**Umsetzung:** Letzten begonnenen und letzten vollständig erfolgreichen
Alert-Prüflauf, Dauer, geprüften Umfang und aktuellen Fehler getrennt vom
Schalter „Alerting aktiviert“ darstellen. Nach einem Fehler den Zeitpunkt des
letzten Erfolgs erhalten. Am Alert Versandstatus, letzten/nächsten Versuch und
ausgeschöpfte Wiederholungen sichtbar machen; Empfängerdetails erhalten den
bestehenden Admin-Schutz.

**Abnahme:** Ein OpenSearch-Fehler vor dem ersten Versand oder eine
unvollständige Folgeseite erscheint als Auswertungsfehler und aktualisiert
keinen Erfolgszeitpunkt. Eine leere, erfolgreich bewertete Liste ist davon
unterscheidbar. Status bleibt nach Neustart nachvollziehbar. Pausiertes
Alerting, fehlgeschlagene Auswertung und SMTP-Ablehnung sind eindeutig
verschiedene Zustände.

**Abhängigkeit / Aufwand:** Laufstatus kann parallel zu Phase 1 entstehen;
Empfängeransicht folgt auf deren Zustellmodell. **Mittel.**

## 3. Betroffene Nachrichten korrekt zählen — F06

**Stand:** Implementiert. Gemeinsame betroffene Menge und Gesamtvolumen
werden in Oberfläche, E-Mail und JSON getrennt dargestellt.

**Umsetzung:** Bei kompensiertem Alignment die Nachrichten mit „SPF nicht
aligned ODER DKIM nicht aligned“ als gemeinsame Menge zählen. Das
Gesamtvolumen separat ausweisen und dieselben Werte in UI, E-Mail und
JSON-Anhang verwenden.

**Abnahme:** 1.000 DMARC-Pass-Nachrichten mit genau einem kompensierten
Alignment-Problem ergeben **1 betroffen, 1.000 insgesamt**. Überlappende
Merkmale zählen eine Nachricht höchstens einmal. Ereignis-ID,
Bearbeitungsstatus und Versanddeduplizierung bleiben bei der Korrektur
erhalten.

**Abhängigkeit / Aufwand:** Aggregation pro Domain/IP/Evidenztag aus F01/F03;
eine klare Bedeutung bestehender und ergänzter JSON-Felder. **Klein–mittel.**
Kann parallel zu Phase 1 umgesetzt werden.

## 4. Dienst-Erkennung und manuelle Zuordnung trennen — F07/F08

**Stand:** Implementiert. Herkunft und unabhängige Gruppen der Belege werden
explizit ausgewiesen. Domain-Grenzen und tatsächliche Authentifizierungsergebnisse
werden geprüft. Automatik, manuelle Festlegung und übernommene Altzuordnung
sind getrennt; Notizen ändern den Modus nicht. Änderungen während eines
laufenden Speicherns bleiben im Formular erhalten.

**Umsetzung:** Evidenz mit ihrer tatsächlichen Herkunft aufbewahren, Domain-
Grenzen prüfen und mehrfach passende Regeln derselben Quelle begrenzen.
Hohe Konfidenz braucht unabhängige Belege. Notiz, manuell gesetzten Dienst
und Zuordnungsmodus unabhängig speichern; automatische Alternative und
manuelle Auswahl eindeutig kennzeichnen.

**Abnahme:** `outbound.protection.outlook.com.attacker.example` gilt nicht
als Microsoft-Providerdomain. Ein einzelner PTR erzeugt durch überlappende
Regeln keine drei unabhängigen Belege. Eine reine Notizänderung lässt spätere
automatische Erkennung wirksam werden. Ein bewusst gesetzter manueller Dienst
bleibt erhalten, auch wenn die automatische Alternative wechselt. Bestehende
Overrides werden ohne sichere Kenntnis ihrer Absicht nicht pauschal entfernt.

**Abhängigkeit / Aufwand:** Zuerst Herkunft und Zuordnungsmodus im Datenmodell
festlegen, danach Formular und Evidenzanzeige anpassen. **Mittel.**

## 5. Untersuchungswege vervollständigen — F09/F10 und UI

**Stand:** Implementiert. Browser- und E-Mail-Links erhalten Domain, Zeitraum
und konkrete Quelle. Die Rückkehr zur Warnung bewahrt den Ausgangskontext.
Details erhalten gezielten Tastaturfokus; Aktualisierungen verschieben ihn
nicht erneut. Statusänderungen werden pro Warnung abgesichert; Offenzahlen
beziehen sich unabhängig vom Statusfilter auf Domain und Zeitraum.
„Wieder öffnen“ erhält Ereignis- und Versandzustände. Beim Verlassen eines
geänderten Host-Formulars stehen Speichern, Verwerfen und Weiterbearbeiten
zur Wahl. Alte GET-Antworten und fehlgeschlagenes Speichern können den
aktuellen Kontext beziehungsweise Entwurf nicht still überschreiben.

**Umsetzung:** Die ergänzten Abbruchprüfungen und getrennten Host-Loader als
Regression absichern. Domain und Zeitraum validiert in Browser- und
E-Mail-Links übernehmen und wiederherstellen. IP-Klicks in der Übersicht
öffnen die konkrete Quelle; Hostdetails erhalten sichtbaren Fokus.
„Wieder öffnen“, nachvollziehbare Offenzähler und Schutz ungespeicherter
Formularänderungen ergänzen. Erklärtexte müssen die Unabhängigkeit von
DMARC-Ergebnis und Dienstzuordnung korrekt beschreiben.

**Abnahme:** Ein geteilter Domain-/90-Tage-Link öffnet nach Neuladen dieselbe
Untersuchung; bestehende Links ohne Zusatzparameter funktionieren weiter.
Vertauschte Antwortreihenfolgen und Detail-404 lassen die aktuelle Liste
korrekt. Historische Links zeigen ihren gespeicherten Inhalt oder den
erhaltenen Legacy-Status. Statusfilter führen nicht zu einer irreführenden
globalen Anzeige „0 offen“. Tastaturbedienung erreicht das geöffnete Detail;
ungespeicherte Notizen gehen bei Aktualisierung nicht still verloren.

**Abhängigkeit / Aufwand:** Ereignisabruf und Pagination aus F01/F02;
Formularschutz mit Phase 4 abstimmen. **Mittel.** Die vorhandenen
Abbruchprüfungen und historischen Einzelabrufe sind Ausgangspunkt, keine
erneut zu entwickelnden Funktionen.

## 6. Erwartete und stillgelegte Domains verwalten

**Als Nächstes:** Zuerst Zustände und Übergänge für beobachtete, erwartete und
stillgelegte Domains festlegen. Danach die persistente Domainverwaltung und
die geschützte Bedienung ergänzen; zuletzt Wartefristen und Frischewarnungen
mit Migration des vorhandenen Bestands prüfen. Manuelle Versandwiederholungen
bleiben ein separates Paket nach den bereits dokumentierten Empfängerregeln.

**Umsetzung:** Überwachungsstatus pro Domain ausdrücklich verwalten:
beobachtet und aktiv, erwartet aber noch nie beobachtet, sowie stillgelegt.
Für erwartete Domains einen nachvollziehbaren Beginn und eine Wartefrist
festlegen. Stilllegung unterdrückt gezielt Frischewarnungen und löscht weder
Reports noch Ereignishistorie. Neue echte DMARC-Fails bleiben auswertbar.

**Abnahme:** Eine bekannte Domain bleibt nach Ablauf der Indexaufbewahrung
überwacht. Eine ausdrücklich erwartete Domain ohne ersten Report warnt erst
nach ihrer Wartefrist und unterscheidet sich von einem späteren Reportausfall.
Eine stillgelegte Domain erzeugt keine neue Frischewarnung; Reaktivierung
verwendet eine klar sichtbare Erwartung. Bestehende beobachtete Domains werden
bei der Migration weiterhin als aktiv behandelt. Änderungen am
Überwachungsstatus setzen keine historischen Alert- oder Versandzustände zurück.

**Abhängigkeit / Aufwand:** Persistente bekannte Domains aus F04; explizite
Admin-Einstellungen, Migration und verständliche Statusanzeige. **Mittel–größer.**
Bis dahin bleiben alle bereits beobachteten Domains überwacht.

## Gemeinsame Freigabekriterien

Jede Phase erhält die genannten fachlichen Regressionstests und eine Prüfung
der betroffenen UI-/Mail-Ausgabe. Änderungen an persistenten Zuständen werden
zusätzlich mit einer vorhandenen Datenbankkopie geprüft: erhaltene
Bearbeitungszustände, auflösbare alte Links und keine ungewollte erneute
Versendung des Bestands. Auswertungslaufzeiten mit vollständigem Inventar
beobachten; zusätzliche Caches erst anhand gemessener Engpässe einplanen.
