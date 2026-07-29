# DMARC Control Backlog

## Alert-Bearbeitung und Sending-Host-Untersuchung

**Status:** geplant

Alert-Status und Host-Klassifizierung bleiben fachlich getrennt:

- Der Alert-Status beschreibt den Bearbeitungsstand eines konkreten
  Ereignisses: `open`, `acknowledged`, `resolved` oder `ignored`.
- Die Host-Klassifizierung speichert dauerhaftes Wissen über die technische
  Quelle, den erkannten Dienst und den administrativen Kontext.
- Eine bestätigte Host-Klassifizierung ist keine Freigabeliste und
  unterdrückt keine zukünftigen echten DMARC-Fails.

Vorgesehener Arbeitsablauf:

1. Ein Alert wird im Dashboard oder künftig per E-Mail gemeldet.
2. Der Bearbeiter bestätigt ihn mit **Acknowledge**.
3. Eine direkte Aktion öffnet den betroffenen Sending Host in der
   Detailansicht.
4. Dienstklassifizierung und Evidenz werden geprüft, bei Bedarf korrigiert und
   mit einer Notiz ergänzt.
5. Der Bearbeiter kehrt zum Alert zurück und schließt ihn mit **Resolved** oder
   **Ignore** ab.

Für das künftige E-Mail-Alerting sollen Benachrichtigungen direkt auf den
betroffenen Alert beziehungsweise dessen Sending-Host-Untersuchung verlinken.

## Eindeutige Bezeichnung für verworfene Host-Klassifizierungen

**Status:** geplant

Die aktuelle Bezeichnung **„Klassifizierung ignoriert“** kann mit dem
Alert-Status **„Ignoriert“** verwechselt werden. Vor der finalen
Produktversion soll der Host-Status deshalb eindeutig umbenannt werden, zum
Beispiel in:

- **„Automatische Zuordnung verworfen“**, oder
- **„Nicht zuordnen“**.

Die deutsche und englische Bezeichnung müssen dieselbe Bedeutung vermitteln.
Die Umbenennung betrifft nur die Benutzeroberfläche; der interne Statuswert
und bestehende gespeicherte Zuordnungen sollen kompatibel bleiben.
