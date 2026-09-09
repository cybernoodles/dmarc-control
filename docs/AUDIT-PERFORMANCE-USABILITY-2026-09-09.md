# Punkt 8: Bedienung und Auswertungsleistung

Prüfung vom 9. September 2026, Ausgangscode `e4aeb06` (produktiver Anwendungscode
`286012b`). Die manuelle Versandwiederholung aus Punkt 7 ist auf Wunsch
ausgelassen und gehört nicht zu dieser Änderung.

## Ergebnis und Umfang

Der bestehende Produktionsbestand zeigt keinen akuten Leistungsengpass.
Die Prüfung größerer künstlicher Bestände hat einen unnötig mit dem Quadrat
der Domainzahl wachsenden Zugriff vor Frischebenachrichtigungen und eine
langsame Domainverwaltung mit sehr vielen Formularen nachgewiesen. Beide
Pfade wurden gezielt verbessert. Außerdem werden beschädigte Folgeseiten der
Hostsuche zuverlässig als Fehler angezeigt; beim bewussten Blättern in der
Hostliste werden Listenanfang und Tastaturfokus wiederhergestellt.

Die Ereignislogik, vollständige Abfrage aller Seiten, historischen Links,
Bearbeitungszustände und Versandregeln bleiben die Abnahmekriterien.

## Messung des laufenden Betriebs

Gemessen um 06:28 UTC auf docker01, ausschließlich lesend:

- Die letzten 20 gespeicherten automatischen Prüfungen von 04:51 bis 06:26 UTC
  waren erfolgreich. Laufzeit: mindestens 173 ms, Median 186 ms, höchstens
  213 ms. Geprüfter Umfang im letzten Lauf: 3 Domains, 331 historische Hosts,
  32 aktuelle Ereignisse.
- 3 aktive Domains, 75 gespeicherte Ereignisse, 51 Bearbeitungszustände und
  4 Hostzuordnungen. SQLite-Dateigröße: 256 KiB.
- Dashboard-Ressourcen im einmaligen Container-Snapshot: rund 57 MiB RAM und
  0,14 % CPU. OpenSearch: rund 1,46 GiB RAM, keine wartenden oder abgewiesenen
  Suchanfragen, Clusterzustand grün. Einzelne CPU-/Speicher-Snapshots sind
  keine dauerhafte Lastmessung.

Die folgenden Ansichten wurden im bisherigen Dashboard-Image gegen eine
Wegwerfkopie der Datenbank und die reale, ausschließlich lesende Reportsuche
gemessen. Ein Durchlauf je Ansicht; die Werte sind Stichproben, keine
garantierten Antwortzeiten und keine Ende-zu-Ende-Browsermessung.

| Ansicht | Zeitraum | Ergebnis | Gesamtdauer | Suchabfragen |
| --- | ---: | ---: | ---: | ---: |
| Domainauswahl | gesamte Historie | 3 Domains | 103 ms | 2 |
| Hosts | 7 Tage | 1 Quelle | 128 ms | 2 |
| Hosts | 30 Tage | 9 Quellen | 116 ms | 2 |
| Hosts | 90 Tage | 19 Quellen | 146 ms | 2 |
| Hosts | 365 Tage | 100 von 255 Quellen | 191 ms | 2 |
| Warnungen | 7 Tage | 8 Ereignisse | 236 ms | 7 |
| Warnungen | 30 Tage | 32 Ereignisse | 176 ms | 7 |
| Warnungen | 90 Tage | 74 Ereignisse | 231 ms | 7 |
| Warnungen | 365 Tage | 382 Ereignisse | 638 ms | 9 |

Die 40 Suchabfragen dieser Messung waren erfolgreich. Die Quelldatenbank
blieb unverändert; kein echter E-Mail-Versand fand statt. Die Hostabfrage
liest auch für kurze Anzeigezeiträume die Historie aller Quellen, damit
Erstbeobachtung und Klassifikation richtig bleiben. Die letzte leere
Composite-Seite beendet die vollständige Abfrage; ein bloß kurzes Ergebnis
wird nicht als Beweis für Vollständigkeit verwendet.

## Gezielter Zugriff vor Frischebenachrichtigungen

Vor jedem möglichen Versand wird geprüft, ob die Warnung zum aktuellen
Domainzustand und zur aktuellen Frist passt. Zuvor verwendete diese Prüfung
die öffentliche Domainliste: Für jede einzelne Warnung wurde die
gesamte Domainhistorie zur Aliasaufbereitung erneut gelesen und normalisiert.
Bei D fälligen Domainwarnungen führte das zu D² Domainaufbereitungen.

Jetzt wird nur der passende Registry-Eintrag über seinen Primärschlüssel
gelesen. Jede Prüfung liest weiterhin den aktuellen Datenbankzustand und
vergleicht Ereignis-ID und Frist; es gibt keinen zusätzlichen Ergebniscache.
Ungültige historische Domainnamen behalten ihren exakten bisherigen Schlüssel.

Lokale Messung mit Python 3.12 und ausschließlich künstlichen SQLite-Dateien:

| Fällige Domains | Gesamte Frischeprüfung vorher | Nachher |
| ---: | ---: | ---: |
| 3 | 0,50 ms | 0,32 ms |
| 100 | 80,32 ms | 10,62 ms |
| 1.000 | 6.689,91 ms | 118,15 ms |
| 5.000 | nicht ausgeführt | 562,21 ms |

Die gesamte Frischeprüfung ist bei 1.000 Domains damit rund 57-mal schneller.
Das ist keine Aussage über eine entsprechende Beschleunigung des heutigen
Produktivlaufs mit drei Domains. Bis 100 Domains sind die Werte Mediane aus
drei Läufen; die großen Frischeläufe wurden einmal gemessen. Eine separate
Zählung bei 100 Domains bestätigt 100 statt 10.100 Normalisierungen sowie
keinen vollständigen History-Read mehr. Es bleiben 100 frische Einzelabfragen.

Andere SQLite-Operationen waren im gleichen Test unauffällig: Das erneute
Speichern von 1.000 Ereignissen benötigte rund 11 ms, die Synchronisierung
von 1.000 Reportständen ebenfalls rund 11 ms. Dafür wurden keine zusätzlichen
Caches oder Datenmigrationen eingeführt.

Die Ereignisauswertung wurde zusätzlich mit künstlichen Antworten für
1.000 Hosts über 30 Tage geprüft: 30.000 Tagesgruppen, 159 Suchaufrufe und
genau 1.000 erwartete eindeutige Ereignisse wurden vollständig verarbeitet.
Die lokale Laufzeit von rund 857 ms enthält keine Netzwerk- oder
OpenSearch-Latenz; das gesamte erneut serialisierte Tagesergebnis umfasst
rund 26 MB. Bei 10.000 Hosts blieben die Hostseiten disjunkt und ein seltener
Fehler am Ende des Bestands über den Risikofilter auffindbar. Diese
Wachstumskosten begründen bei Bedarf spätere Messungen, aber keinen
zusätzlichen Cache für den heute kleinen Bestand.

## Große Bestände bedienen

Browserprüfung mit künstlichen Daten und konstant 50 ms Antwortverzögerung.
Die künstliche CPU-Drosselung auf das Vierfache dient dem Vergleich auf
langsameren Geräten, nicht einer Simulation von docker01.

Die Hostliste begrenzt die Darstellung bereits auf 100 Quellen. Die Suche
fand die letzte Quelle unter 1.000 Einträgen mit einer abgesetzten Suchanfrage;
Filter, Detailansicht, historische Warnungslinks und Rückwege blieben korrekt.
Ein zusätzlicher Bedienfehler wurde beim Blättern nachgewiesen: Der Fokus
landete auf dem Dokument und die Ansicht blieb am unteren Seitenende.
Die Korrektur richtet die nächste erfolgreich geladene Seite am Listenanfang
aus. Suche, normale Aktualisierung und verspätete alte Antworten lösen diesen
Fokuswechsel nicht aus.

Die Domainverwaltung zeichnete bisher alle Formulare gleichzeitig:
Bei 1.000 Domains entstanden rund 22.270 DOM-Elemente und eine etwa 224.000 px
hohe Desktop-Seite. Das Öffnen dauerte rund 622 ms ohne Drosselung bzw.
2.374 ms bei vierfacher CPU-Drosselung. Eingaben benötigten dort im Median
100 ms bis zur Darstellung. 50 Domains öffneten unter derselben Drosselung
in rund 170 ms.

Ab mehr als 50 Domains erscheinen deshalb eine lokale Namenssuche und Seiten
mit jeweils 25 Einträgen. Die Suche umfasst alle geladenen Domains,
einschließlich bekannter Schreibweisen; die Gesamtzahl und die Trefferzahl
werden getrennt ausgewiesen. Fristentwürfe bleiben beim Suchen und Blättern
erhalten. Bei bis zu 50 Domains bleibt die bisherige einfache Liste bestehen.
Der aktuelle Produktivbestand mit drei Domains erhält keine zusätzlichen
Such- oder Seitenbedienelemente.

Der Vergleich nach der Änderung nutzt denselben Produktionsbuild-Aufbau,
dieselben künstlichen Antworten und dieselbe Verzögerung:

| Browsermessung bei 1.000 Domains | Vorher | Nachher |
| --- | ---: | ---: |
| Gleichzeitig dargestellte Domainkarten | 1.000 | 25 |
| DOM-Elemente der Seite | 22.270 | 1.155 |
| Öffnen ohne CPU-Drosselung | 622 ms | 117 ms |
| Öffnen bei vierfacher CPU-Drosselung | 2.374 ms | 148 ms |
| Aktualisieren bei vierfacher CPU-Drosselung | 1.960 ms | 137 ms |
| Eingabe bis Darstellung, Median bei vierfacher CPU-Drosselung | 100 ms | 19 ms |
| Eingabe bis Darstellung, Maximum bei vierfacher CPU-Drosselung | 136 ms | 30 ms |

Die Eingabewerte stammen aus 19 Zeichen. Bei drei Domains bleiben
668 DOM-Elemente und die Seitenhöhen auf Desktop und Mobilgerät identisch;
die gemessene Öffnungszeit beträgt 120 ms vorher und 116 ms nachher.
Diese Stichproben zeigen die Wirkung der begrenzten Darstellung bei großen
Beständen und keine wesentliche Änderung für den heutigen kleinen Bestand.

Die Browserregression prüft Unicode-/IDNA-Schreibweisen und Aliase,
vollständige Suchtreffer über Seitengrenzen, erhaltene Entwürfe sowie
erfolgreiches und fehlgeschlagenes Speichern beim zwischenzeitlichen
Blättern. Späte Hostantworten dürfen weder eine neuere Suche überschreiben
noch den Fokus aus einer begonnenen Bearbeitung zurückholen.

## OpenSearch: keine Änderung am Indexbestand

Die 706 Aggregate-Dokumente verteilen sich auf 263 Indizes: 261 Namen folgen
dem Tagesmuster und zwei dem Monatsmuster. 258 Indizes enthalten höchstens
zehn Dokumente; Median zwei Dokumente und rund 28 KiB je Index. Der gesamte
Cluster meldet 278 aktive primäre Shards.

Das ist ein sehr kleinteiliger historischer Bestand. Die vorhandene
Beispielkonfiguration sieht bereits Monatsindizes vor. Die gemessenen
Antwortzeiten, leeren Suchwarteschlangen und fehlerfreien Prüfläufe begründen
derzeit keine Datenumschichtung oder pauschale Änderung von Clusterparametern.
Eine mögliche Konsolidierung historischer Tagesindizes bleibt ein separates
Betriebsthema im bestehenden Issue #6; sie würde eine eigene Prüfung von
Vollständigkeit, Rückkehrweg und historischen Suchen benötigen.

## Wiederholbare Messungen und Absicherung

- `dashboard/backend/benchmarks/freshness_lookups.py` erzeugt ausschließlich
  künstliche SQLite-Daten und misst die Einzeloperationen für wählbare Größen.
- `dashboard/backend/benchmarks/profile_views.py` verlangt über
  `AUDIT_BASELINE_DB` eine vorhandene Datenbankkopie und erzeugt eine weitere
  temporäre Arbeitskopie. Es nutzt `OPENSEARCH_URL` für ausschließlich lesende
  Suchanfragen, blockiert Versandwege und begrenzt Zahl und Dauer der Aufrufe.
  Die Ausgabe enthält Mengen, Zeiten und Größen statt Reportinhalten.
- Größen des Profilers sind erneut serialisierte JSON-Größen, keine
  komprimierten Netzwerkgrößen. Die Messung der Ereignisschleife enthält auch
  den Aufwand der Messinstrumentierung.
- Regressionen prüfen begrenzte Einzelabfragen statt fragiler Zeitlimits,
  zwischenzeitliche Stilllegung/Reaktivierung und Friständerungen sowie
  fehlerhafte erste oder folgende Host-Aggregationsseiten.
- Die vollständige Backend-Suite mit 223 Tests und die 16 Frontendtests
  sind erfolgreich. Die Browserprüfung ergänzt diese Tests um tatsächliche
  Navigation, Fokus und Formularzustände unter verzögerten Antworten.

Beispiel für den vollständig lokalen synthetischen Vergleich:

```sh
PYTHONPATH=dashboard/backend python dashboard/backend/benchmarks/freshness_lookups.py \
  --sizes 3 100 1000 5000 --output /tmp/dmarc-freshness-benchmark.json
```
