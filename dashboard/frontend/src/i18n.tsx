import {
  ReactNode,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type Language = "de" | "en";
export type Translate = (
  source: string,
  values?: Record<string, string | number>,
) => string;

const LANGUAGE_STORAGE_KEY = "dmarc-control-language";

const english: Record<string, string> = {
  "Letzter Report": "Latest report",
  "Registrierte Domains durchsuchen": "Search registered domains",
  "Domainname oder alternative Schreibweise": "Domain name or alternative spelling",
  "{matches} Treffer von {total} registrierten Domains": "{matches} matches out of {total} registered domains",
  "Domain-Seiten": "Domain pages",
  "{start}–{end} von {total} Treffern": "{start}–{end} of {total} matches",
  "Keine passenden Domains": "No matching domains",
  "Registrierte Domains": "Registered domains",
  "Alle registrierten Domains, unabhängig von der Domain-Auswahl.": "All registered domains, regardless of the selected domain.",
  "Keine Frist aktiv": "No active deadline",
  "Domain-Überwachung": "Domain monitoring",
  "Erwartete Domains und Warnungen bei ausbleibenden Reports verwalten.": "Manage expected domains and alerts for missing reports.",
  "Melde dich als Admin an, um die Domain-Überwachung zu verwalten.": "Sign in as admin to manage domain monitoring.",
  "Zur Administration": "Go to administration",
  "Beobachtete Domains werden automatisch aufgenommen. Erwartete Domains kannst du schon vor dem ersten Report hinzufügen.": "Observed domains are added automatically. You can add expected domains before their first report arrives.",
  "Erwartete Domain hinzufügen": "Add expected domain",
  "Wartefrist (Tage)": "Grace period (days)",
  "Wird hinzugefügt …": "Adding …",
  "Domain hinzufügen": "Add domain",
  "1–365 Tage. Standard: {days} Tage. Ohne ersten Report entsteht nach Ablauf eine Warnung.": "1–365 days. Default: {days} days. An alert is raised if no first report arrives within this period.",
  "Überwachte Domains": "Monitored domains",
  "Liste aktualisieren": "Refresh list",
  "Domain-Überwachung wird geladen …": "Loading domain monitoring …",
  "Noch keine Domains registriert. Füge eine erwartete Domain hinzu oder warte auf den ersten Report.": "No domains registered yet. Add an expected domain or wait for the first report.",
  "Stilllegen beendet Warnungen wegen ausbleibender Reports. Echte DMARC-Fehler werden weiterhin ausgewertet. Vorhandene Reports und Warnungen bleiben erhalten.": "Retiring a domain stops alerts for missing reports. Actual DMARC failures are still evaluated. Existing reports and alerts are preserved.",
  "{domain} wird überwacht. Die erste Wartefrist beginnt jetzt.": "Monitoring started for {domain}. The first grace period begins now.",
  "Wartefrist gespeichert. Der Beginn bleibt unverändert.": "Grace period saved. The start remains unchanged.",
  "Domain stillgelegt. Reports und Warnungen bleiben erhalten.": "Domain retired. Reports and alerts are preserved.",
  "Domain reaktiviert. Eine neue Wartefrist hat begonnen.": "Domain reactivated. A new grace period has started.",
  "Stillgelegt": "Retired",
  "Erwartet · noch kein Report": "Expected · no report yet",
  "Aktiv · Reports beobachtet": "Active · reports observed",
  "Noch kein Report": "No report yet",
  "Überwachungsbeginn": "Monitoring started",
  "Fristende": "Deadline",
  "Überwachung pausiert": "Monitoring paused",
  "Wartefrist für {domain}": "Grace period for {domain}",
  "Mit neuer Frist reaktivieren": "Reactivate with a new grace period",
  "Frist speichern": "Save grace period",
  "Stilllegen": "Retire",
  "Reaktivieren startet ab jetzt eine neue Wartefrist mit der eingetragenen Tageszahl.": "Reactivating starts a new grace period from now, using the number of days entered.",
  "Eine Friständerung verschiebt nur das Fristende. Der Beginn bleibt erhalten; eine kürzere Frist kann sofort eine Warnung auslösen.": "Changing the grace period only changes the deadline. Its start is preserved; a shorter period may trigger an alert immediately.",
  "Änderung wird gespeichert …": "Saving change …",
  "Erwartete Versanddienste": "Expected sending services",
  "Erwartete Versanddienste für {domain}": "Expected sending services for {domain}",
  "DNS-Konfiguration und DMARC-Historie liefern Hinweise auf erwartete Versandplattformen.":
    "DNS configuration and DMARC history provide indicators of expected sending platforms.",
  "MX ist nur ein Hinweis auf den Empfangsdienst. Automatische Erwartungen benötigen SPF- oder DKIM-Belege und eine stabile DMARC-Historie.":
    "MX only indicates the inbound service. Automatic expectations require SPF or DKIM evidence and stable DMARC history.",
  "Keine Freigabeliste; DMARC-Fails bleiben kritisch.":
    "This is not an allowlist; DMARC failures remain critical.",
  "Erwarteter Versanddienst · DMARC bestanden":
    "Expected sending service · DMARC passed",
  "{service} · erwarteter Versanddienst · DMARC bestanden":
    "{service} · expected sending service · DMARC passed",
  "Die Zuordnung gilt für diesen DMARC-bestandenen Host. DMARC-Fehler bleiben kritisch.":
    "This classification applies to this DMARC-passing host. DMARC failures remain critical.",
  "Diese Installation liefert noch keine Versanddienstbewertungen.":
    "This installation does not provide sending service assessments yet.",
  "Noch keine erwarteten Versanddienste ermittelt.":
    "No expected sending services have been identified yet.",
  "Status unbekannt": "Status unknown",
  "Automatisch vorgeschlagen": "Suggested automatically",
  "Als Versanddienst erwartet": "Expected sending service",
  "Nicht erwartet": "Not expected",
  "DNS aktuell": "DNS current",
  "Keine DNS-Hinweise": "No DNS indicators",
  "DNS-Antwort ungültig": "Invalid DNS response",
  "DNS nicht verfügbar": "DNS unavailable",
  "DNS-Bewertung veraltet": "DNS assessment stale",
  "DNS-Bewertung ausstehend": "DNS assessment pending",
  "Automatisch": "Automatic",
  "Manuell bestätigt": "Manually confirmed",
  "Entscheidung: {decision}": "Decision: {decision}",
  "MX-Konfiguration": "MX configuration",
  "SPF-Konfiguration": "SPF configuration",
  "DKIM-Konfiguration": "DKIM configuration",
  "DMARC-Historie": "DMARC history",
  "Report-Beobachtung": "Report observation",
  "Provider-Zuordnung": "Provider classification",
  "Belege": "Evidence",
  "Keine belastbaren Belege vorhanden.": "No reliable evidence is available.",
  "Widersprüche": "Contradictions",
  "Beobachtungstage": "Observation days",
  "Zuletzt beobachtet": "Last observed",
  "Noch keine Beobachtung": "No observation yet",
  "Zuletzt bewertet: {date}": "Last assessed: {date}",
  "Entscheidung für {service} bei {domain}": "Decision for {service} on {domain}",
  "{decision} für {service} bei {domain}": "{decision} for {service} on {domain}",
  "Bewertung für {service} bei {domain} aktualisieren": "Refresh assessment for {service} on {domain}",
  "Aktualisieren": "Refresh",
  "Versanddienstbewertung wird aktualisiert …": "Refreshing sending service assessment …",
  "Entscheidung wird gespeichert …": "Saving decision …",
  "Bewertung für {service} aktualisiert.": "Assessment for {service} refreshed.",
  "Entscheidung für {service} gespeichert.": "Decision for {service} saved.",
  "Ungültiger Domainname.": "Invalid domain name.",
  "Diese Domain wird bereits überwacht.": "This domain is already monitored.",
  "Die Wartefrist muss zwischen 1 und 365 Tagen liegen.": "The grace period must be between 1 and 365 days.",
  "Für diese Domain wurden bereits Reports beobachtet.": "Reports have already been observed for this domain.",
  "Domains ohne Reports müssen als erwartet geführt werden.": "Domains without reports must be marked as expected.",
  "Ungültiger Überwachungsstatus.": "Invalid monitoring state.",
  "Domain ist nicht registriert": "Domain is not registered",
  "Darstellung, Domains, Benachrichtigungen, Postfachanbindung und geschützte Administration": "Appearance, domains, notifications, mailbox connection and protected administration",
  "Report-Eingang und Wartefristen": "Report arrivals and grace periods",
  "Erster DMARC-Report fehlt": "First DMARC report missing",
  "Kein neuer DMARC-Report nach Reaktivierung": "No new DMARC report after reactivation",
  "Seit dem Überwachungsbeginn am {date} ist kein erster Report eingegangen; die Wartefrist von {days} Tagen ist abgelaufen.": "No first report has arrived since monitoring started on {date}; the {days}-day grace period has expired.",
  "Seit der Reaktivierung am {date} liegt kein aktueller Report vor; die neue Wartefrist von {days} Tagen ist abgelaufen.": "No current report is available since reactivation on {date}; the new {days}-day grace period has expired.",
  "Es fehlen aktuelle DMARC-Reports; die Wartefrist ist abgelaufen.": "Recent DMARC reports are missing; the grace period has expired.",
  "Deine Sitzung ist abgelaufen. Ungespeicherte Host-Änderungen bleiben für die erneute Anmeldung in diesem Tab erhalten.":
    "Your session has expired. Unsaved host changes are kept in this tab so you can sign in again.",
  "Quelle {ip} untersuchen": "Investigate source {ip}",
  "Details für Quelle {ip}": "Details for source {ip}",
  "Wieder öffnen": "Reopen",
  "Offene Warnungen für die gewählte Domain und den Zeitraum, unabhängig vom Statusfilter.":
    "Open alerts for the selected domain and time range, regardless of the status filter.",
  "Offenzahl wird geladen": "Loading open alert count",
  "Offenzahl nicht verfügbar": "Open alert count unavailable",
  "Eine Quelle mit echtem DMARC-Fail. Die Dienstzuordnung ist keine Sendefreigabe.":
    "A source with an actual DMARC failure. Service classification does not authorize sending.",
  "Ungespeicherte Host-Zuordnung": "Unsaved host classification",
  "Für diesen Sending Host gibt es ungespeicherte Änderungen. Wie möchtest du fortfahren?":
    "This sending host has unsaved changes. How would you like to continue?",
  "Ein Speichervorgang läuft bereits. Speichern und weiter wartet auf dessen Ergebnis.":
    "A save is already in progress. Save and continue will wait for its result.",
  "Es bestehen weiterhin ungespeicherte Änderungen. Prüfe den Entwurf oder versuche das Speichern erneut.":
    "There are still unsaved changes. Review the draft or try saving again.",
  "Speichern fehlgeschlagen. Der Entwurf bleibt erhalten.": "Saving failed. Your draft is preserved.",
  "Speichern und weiter": "Save and continue",
  "Verwerfen und weiter": "Discard and continue",
  "Weiterbearbeiten": "Keep editing",
  "Speichern läuft …": "Saving …",
  "Bitte gib einen manuellen Dienstnamen ein.": "Enter a manual service name.",
  "Host-Zuordnung bearbeiten": "Edit host classification",
  "Änderungen gespeichert.": "Changes saved.",
  "Diensterkennung": "Service detection",
  "Automatisch ermitteln": "Detect automatically",
  "Manuellen Dienst verwenden": "Use a manual service",
  "Bisherige Zuordnung übernommen": "Previous classification preserved",
  "Manueller Dienstname": "Manual service name",
  "Automatisch aus Erkennung ableiten": "Derive automatically from detection",
  "Die bisherige Zuordnung bleibt erhalten. Ob der Dienstname früher bewusst festgelegt wurde, ist nicht sicher bekannt. Notizen können unabhängig geändert werden; für eine neue Entscheidung wähle automatische oder manuelle Erkennung.":
    "The previous classification is preserved. It is uncertain whether the service name was intentionally chosen before. Notes can be changed independently; choose automatic or manual detection to make a new decision.",
  "Notizen und Zuordnungsstatus legen keinen Dienstnamen fest. Die automatische Erkennung kann sich mit neuen Reports ändern.":
    "Notes and classification status do not set a service name. Automatic detection may change as new reports arrive.",
  "Automatik wiederherstellen behält gespeicherte Notizen und leitet den Zuordnungsstatus wieder automatisch ab.":
    "Restoring automatic detection keeps saved notes and derives the classification status automatically again.",
  "Ungespeicherte Änderungen vorhanden.": "There are unsaved changes.",
  "Verwendete Dienstzuordnung": "Current service classification",
  "Automatisch ermittelt": "Detected automatically",
  "Manuell": "Manual",
  "Übernommen": "Preserved",
  "Automatische Erkennung": "Automatic detection",
  "Automatische Alternative": "Automatic alternative",
  "Die Konfidenz gehört ausschließlich zur automatischen Erkennung. Sie ist eine regelbasierte Einschätzung, keine statistisch gemessene Wahrscheinlichkeit. Mehrere Angaben aus derselben Quelle gelten nicht als unabhängige Bestätigung.":
    "Confidence applies only to automatic detection. It is a rule-based assessment, not a statistically measured probability. Multiple observations from the same source do not count as independent confirmation.",
  "Herkunft der Erkennungssignale": "Detection signal sources",
  "Ein SPF- oder DKIM-Domainname allein bestätigt keine erfolgreiche Authentifizierung. Ein Prüfergebnis wird nur angezeigt, wenn es im Report vorliegt.":
    "An SPF or DKIM domain name alone does not confirm successful authentication. A result is shown only when the report provides one.",
  "Für diesen Eintrag liegt keine getrennte automatische Erkennung vor.":
    "Separate automatic detection is unavailable for this record.",
  "Reverse DNS (PTR)": "Reverse DNS (PTR)",
  "PTR-Basisdomain": "PTR base domain",
  "ASN-Name": "ASN name",
  "ASN-Domain": "ASN domain",
  "Quellenname": "Source name",
  "SPF-Domain (ohne Einzelergebnis)": "SPF domain (no individual result)",
  "DKIM-Domain (ohne Einzelergebnis)": "DKIM domain (no individual result)",
  "SPF-Prüfung": "SPF check",
  "DKIM-Prüfung": "DKIM check",
  "Netzwerkidentität": "Network identity",
  "Autonomes System (ASN)": "Autonomous system (ASN)",
  "Bestanden": "Passed",
  "Nicht bestanden": "Failed",
  "Keine Prüfung": "No check",
  "Vorübergehender Prüffehler": "Temporary check error",
  "Dauerhafter Prüffehler": "Permanent check error",
  "Ergebnis unbekannt": "Unknown result",
  "Prüfergebnis": "Check result",
  "Signalgruppe": "Signal group",
  "Erkennungsregel": "Detection rule",
  "Mehrdeutige Anbieter-Herkunft": "Ambiguous provider attribution",
  "Widersprüchliche Anbieterhinweise": "Conflicting provider signals",
  "Bestandene Prüfungen weisen auf verschiedene Anbieter hin. Das ist keine zusätzliche Bestätigung.":
    "Passed checks point to different providers. This is not additional confirmation.",
  "Herkunftsland {country}": "Country of origin {country}",
  "Herkunftsland unbekannt": "Country of origin unknown",
  "Daten werden geladen": "Loading data",
  "Daten konnten nicht geladen werden": "Unable to load data",
  "Erneut versuchen": "Try again",
  "Keine Reports": "No reports",
  Heute: "Today",
  "Vor einem Tag": "One day ago",
  "Vor {days} Tagen": "{days} days ago",
  Übersicht: "Overview",
  Warnungen: "Alerts",
  Versand: "Delivery",
  Versanddetails: "Delivery details",
  Forensik: "Forensics",
  Einstellungen: "Settings",
  "Mail-Authentifizierungsbetrieb": "Mail authentication operations",
  "Live aus OpenSearch": "Live from OpenSearch",
  "Dashboard-Bereiche": "Dashboard sections",
  Domain: "Domain",
  "Alle Domains": "All domains",
  Zeitraum: "Time range",
  "Letzte 7 Tage": "Last 7 days",
  "Letzte 30 Tage": "Last 30 days",
  "Letzte 90 Tage": "Last 90 days",
  "Letzte 12 Monate": "Last 12 months",
  "{days} Tage": "{days} days",
  "Daten aktualisieren": "Refresh data",
  "Domain-Liste nicht verfügbar: {error}": "Domain list unavailable: {error}",
  "OpenSearch ist ausschließlich über die kontrollierte API erreichbar.":
    "OpenSearch is accessible exclusively through the controlled API.",
  "Basiert auf": "Built on",
  "Branding und Darstellung dieses Browsers":
    "Branding and display preferences for this browser",
  "Eigenes Branding aktiv": "Custom branding active",
  "Sprache und visuelle Darstellung": "Language and visual appearance",
  "Sprache, UI-Farbgebung und Administration":
    "Language, UI color scheme and administration",
  "Anbindung, Sprache, UI-Farbgebung und Administration":
    "Connection, language, UI color scheme and administration",
  "Darstellung, Postfachanbindung und geschützte Administration":
    "Appearance, mailbox connection and protected administration",
  "Darstellung, Benachrichtigungen, Postfachanbindung und geschützte Administration":
    "Appearance, notifications, mailbox connection and protected administration",
  "Darstellung, Domains, Benachrichtigungen, Postfachanbindung, Backup und geschützte Administration":
    "Appearance, domains, notifications, mailbox connection, backup and protected administration",
  "Backup & Wiederherstellung": "Backup & restore",
  "Dumps oder externe Sicherung": "Dumps or external backup",
  "Backup-Strategie": "Backup strategy",
  "Integrierte Dumps": "Integrated dumps",
  "DMARC Control erstellt automatisch geprüfte OpenSearch-Snapshots und verschlüsselte Steuerungsbackups.":
    "DMARC Control automatically creates verified OpenSearch snapshots and encrypted control-state backups.",
  "Externe Sicherung": "External backup",
  "VM oder Host werden bereits anwendungskonsistent einschließlich aller persistenten Daten gesichert.":
    "The VM or host is already backed up application-consistently, including all persistent data.",
  "Kein Backup": "No backup",
  "Nur für Testsysteme. Bei einem Ausfall gehen Historie und Steuerungszustand verloren.":
    "For test systems only. History and control state will be lost after a failure.",
  "Wähle eine Backup-Strategie.": "Select a backup strategy.",
  "Diese Entscheidung ist erforderlich und kann später in den Einstellungen geändert werden.":
    "This decision is required and can be changed later in Settings.",
  "Backup-Strategie festlegen": "Choose a backup strategy",
  "Bestehende Installationen müssen einmalig festlegen, ob DMARC Control selbst sichert oder eine externe Sicherung verantwortlich ist.":
    "Existing installations must choose once whether DMARC Control creates backups or an external backup is responsible.",
  "Eine Containersicherung allein genügt nicht. Externe Sicherungen müssen die persistenten data-Verzeichnisse und die Konfiguration anwendungskonsistent erfassen.":
    "A container backup alone is insufficient. External backups must capture the persistent data directories and configuration application-consistently.",
  "Admin-Passwort zur Bestätigung": "Admin password for confirmation",
  "Strategie übernehmen": "Apply strategy",
  "Backup-Strategie konnte nicht gespeichert werden.":
    "The backup strategy could not be saved.",
  "Lege fest, ob DMARC Control integrierte Dumps erstellt oder eine externe Sicherung verantwortlich ist.":
    "Choose whether DMARC Control creates integrated dumps or an external backup is responsible.",
  "Letztes Backup erfolgreich": "Latest backup successful",
  Backupfehler: "Backup error",
  "Backup läuft": "Backup running",
  "Wiederherstellung läuft": "Restore in progress",
  "Integrierte Sicherung aktiv": "Integrated backup active",
  "Integrierte Sicherung inaktiv": "Integrated backup inactive",
  "Backup-Status wird geladen": "Loading backup status",
  "Backup-Status konnte nicht geladen werden.":
    "The backup status could not be loaded.",
  "Integrierte Sicherungen wirklich deaktivieren? Vorhandene Backups bleiben erhalten.":
    "Disable integrated backups? Existing backups will be retained.",
  "Backup-Strategie wurde gespeichert.": "The backup strategy was saved.",
  "Der Recovery-Key fehlt. Er wird nicht automatisch ersetzt, damit vorhandene Backups nicht unbemerkt unlesbar werden.":
    "The recovery key is missing. It will not be replaced automatically, so existing backups do not silently become unreadable.",
  "Letzter Erfolg": "Latest success",
  "Noch kein erfolgreiches Backup": "No successful backup yet",
  "Nächster Lauf": "Next run",
  "Wird geplant": "Being scheduled",
  "Recovery-Key-Fingerprint": "Recovery key fingerprint",
  "Melde dich im Bereich Administration an, um die Backup-Strategie zu ändern.":
    "Sign in under Administration to change the backup strategy.",
  "Backup-Strategie speichern": "Save backup strategy",
  Einstellungsbereiche: "Settings sections",
  "Darstellung & Sprache": "Appearance & language",
  "Branding und Benutzeroberfläche": "Branding and user interface",
  Benachrichtigungen: "Notifications",
  "E-Mail-Alerting und Versandwege": "Email alerting and delivery methods",
  "E-Mail-Benachrichtigungen": "Email notifications",
  "Kritische Fälle und Hinweise als strukturierte HTML-E-Mail über SMTP oder Microsoft Graph versenden.":
    "Send critical cases and advisories as structured HTML email through SMTP or Microsoft Graph.",
  "E-Mail-Alerting aktiv": "Email alerting active",
  "E-Mail-Alerting pausiert": "Email alerting paused",
  "Versandwege, Empfänger und auslösende Fälle sind ausschließlich für Administratoren sichtbar.":
    "Delivery methods, recipients and triggering cases are visible only to administrators.",
  "Benachrichtigungen werden geladen": "Loading notifications",
  "Status nicht verfügbar": "Status unavailable",
  "Automatischen E-Mail-Versand aktivieren": "Enable automatic email delivery",
  "Neue offene Ereignisse werden einmalig versendet und über Container-Neustarts hinweg dedupliziert.":
    "New open events are sent once and deduplicated across container restarts.",
  Versandweg: "Delivery method",
  "STARTTLS, TLS oder internes Relay":
    "STARTTLS, TLS or an internal relay",
  "Microsoft 365 · App-only Mail.Send": "Microsoft 365 · app-only Mail.Send",
  Empfänger: "Recipients",
  "Eine Adresse pro Zeile; maximal 20 Empfänger.":
    "One address per line; no more than 20 recipients.",
  Absender: "Sender",
  "Sprache der E-Mail": "Email language",
  "Öffentliche Dashboard-URL": "Public dashboard URL",
  "Optional. Wird für den direkten Link zur Warnungszentrale verwendet.":
    "Optional. Used for the direct link to the alert center.",
  "SMTP-Server": "SMTP server",
  Transportverschlüsselung: "Transport encryption",
  "Implizites TLS": "Implicit TLS",
  "Unverschlüsselt · internes Relay": "Unencrypted · internal relay",
  Passwort: "Password",
  "Optional bei Relay ohne Anmeldung": "Optional for relay without sign-in",
  "Unverschlüsseltes SMTP nur in einem vertrauenswürdigen internen Netz verwenden.":
    "Use unencrypted SMTP only on a trusted internal network.",
  "Vorhandene Microsoft-365-Anbindung wiederverwenden":
    "Reuse existing Microsoft 365 connection",
  "Tenant, Client-ID und Client Secret werden aus der gespeicherten Graph-Postfachanbindung übernommen.":
    "Tenant, client ID and client secret are taken from the stored Graph mailbox connection.",
  "Die App-Registrierung benötigt Application Mail.Send. Der Zugriff sollte in Exchange Online auf das Absenderpostfach begrenzt werden.":
    "The app registration requires Application Mail.Send. Access should be restricted to the sender mailbox in Exchange Online.",
  "Welche Fälle lösen eine E-Mail aus?": "Which cases trigger an email?",
  "Neuer Host mit DMARC-Fail": "New host with a DMARC failure",
  "Erstmals beobachtete Quelle mit echtem DMARC-Fail.":
    "First observed source with an actual DMARC failure.",
  "Verschlechterung eines Hosts": "Host degradation",
  "Zuvor unauffälliger Host liefert neu DMARC-Fails.":
    "A previously healthy host now produces DMARC failures.",
  "DMARC-Fehlerquelle": "DMARC failure source",
  "Bekannte Quelle mit mindestens einem echten DMARC-Fail.":
    "Known source with at least one actual DMARC failure.",
  "DMARC-Fail aus einem erkannten Endkunden- oder Zugangsnetz.":
    "DMARC failure from a detected consumer or access network.",
  "Neue Source-IP": "New source IP",
  "Neue Quelle, auch wenn DMARC noch bestanden wurde.":
    "New source, even when DMARC still passed.",
  "Kompensiertes Alignment": "Compensated alignment",
  "SPF oder DKIM nicht aligned, finales DMARC aber bestanden.":
    "SPF or DKIM not aligned while final DMARC still passed.",
  "Ausbleibende Reports": "Missing reports",
  "Keine neuen DMARC-Reports nach berücksichtigter Verzögerung.":
    "No new DMARC reports after accounting for the usual delay.",
  "Einstellungen speichern": "Save settings",
  "Speichere Änderungen vor dem Testversand.":
    "Save changes before sending a test.",
  "Test-E-Mail wird versendet …": "Sending test email …",
  "Test-E-Mail senden": "Send test email",
  "Frühere Gruppenversände: als erfolgreich gespeichert": "Earlier group sends: recorded as successful",
  "Frühere Gruppenversände: fehlgeschlagen oder ungeklärt": "Earlier group sends: failed or uncertain",
  "Frühere Gruppenversände bleiben erhalten. Da Ergebnisse je Empfänger fehlen, werden diese Warnungen nicht automatisch erneut versendet; auch frühere fehlgeschlagene oder ungeklärte Versuche bleiben angehalten.": "Earlier group sends are retained. As recipient outcomes are unavailable, these alerts will not be sent again automatically; earlier failed or uncertain attempts also remain on hold.",
  Fehlgeschlagen: "Failed",
  "Letzter Test": "Latest test",
  "Jede E-Mail enthält HTML, Klartext, stabile X-DMARC-Control-Header und einen versionierten JSON-Anhang für Mailregeln oder SIEM-Workflows.":
    "Each email contains HTML, plain text, stable X-DMARC-Control headers and a versioned JSON attachment for mail rules or SIEM workflows.",
  "Benachrichtigungseinstellungen konnten nicht geladen werden.":
    "Notification settings could not be loaded.",
  "Der SMTP-Server ist ungültig.": "The SMTP server is invalid.",
  "Bei gesetztem SMTP-Benutzernamen ist ein Passwort erforderlich.":
    "A password is required when an SMTP username is set.",
  "Die Graph Tenant-ID muss eine gültige UUID sein.":
    "The Graph tenant ID must be a valid UUID.",
  "Die Graph Client-ID muss eine gültige UUID sein.":
    "The Graph client ID must be a valid UUID.",
  "Ein Graph Client Secret muss hinterlegt werden.":
    "A Graph client secret must be stored.",
  "Es ist keine Microsoft-Graph-Postfachanbindung zur Wiederverwendung vorhanden.":
    "No Microsoft Graph mailbox connection is available for reuse.",
  "Die Dashboard-URL muss mit http:// oder https:// beginnen.":
    "The dashboard URL must begin with http:// or https://.",
  "Mindestens ein Empfänger ist erforderlich.":
    "At least one recipient is required.",
  "Wähle mindestens einen Benachrichtigungsfall.":
    "Select at least one notification case.",
  "Benachrichtigungseinstellungen wurden gespeichert.":
    "Notification settings were saved.",
  "Test-E-Mail wurde erfolgreich versendet.":
    "The test email was sent successfully.",
  "Test-E-Mail konnte nicht versendet werden.":
    "The test email could not be sent.",
  "Letzter Versandfehler: {error}": "Latest delivery error: {error}",
  Postfachanbindung: "Mailbox connection",
  "Microsoft 365 oder IMAP": "Microsoft 365 or IMAP",
  "Einrichtung ausstehend": "Setup pending",
  "Read-Zugang und Admin-Passwort": "Read access and admin password",
  "Postfachanbindung wartet auf Aktivierung":
    "Mailbox connection is awaiting activation",
  "Postfachanbindung im GUI einrichten":
    "Set up the mailbox connection in the UI",
  "Der gespeicherte Entwurf ist noch nicht als aktive Verbindung übernommen.":
    "The saved draft has not yet been applied as the active connection.",
  "Die bestehende Parser-Konfiguration läuft weiter, bis eine geprüfte GUI-Verbindung aktiviert wird.":
    "The existing parser configuration continues running until a tested UI connection is activated.",
  "Anbindung prüfen": "Review connection",
  "Jetzt einrichten": "Set up now",
  Anbindung: "Connection",
  "Microsoft 365 oder IMAP verbinden, ohne eine Docker-Konfigurationsdatei manuell zu bearbeiten.":
    "Connect Microsoft 365 or IMAP without manually editing a Docker configuration file.",
  Parserfehler: "Parser error",
  "Verwaltete Anbindung aktiv": "Managed connection active",
  "Parser übernimmt Konfiguration": "Parser is applying the configuration",
  "Bereit zur Aktivierung": "Ready to activate",
  "Entwurf gespeichert": "Draft saved",
  "Bestehende Konfiguration aktiv": "Existing configuration active",
  "Nicht eingerichtet": "Not configured",
  "Verbindungsdaten und Tests sind ausschließlich für angemeldete Administratoren verfügbar.":
    "Connection details and tests are available only to signed-in administrators.",
  "Anbindung wird geladen": "Loading connection",
  "Aktiver Modus": "Active mode",
  "GUI-verwaltet": "GUI-managed",
  "Bestehende Konfiguration": "Existing configuration",
  "Letzter Verbindungstest": "Latest connection test",
  "Noch nicht durchgeführt": "Not run yet",
  Verbindungsart: "Connection type",
  "Graph API · App-Registrierung": "Graph API · App registration",
  "TLS · Benutzer oder App-Passwort": "TLS · User or app password",
  "Tenant-ID": "Tenant ID",
  "Client-ID": "Client ID",
  "Client Secret": "Client secret",
  "Secret hinterlegt · leer lassen zum Beibehalten":
    "Secret stored · leave empty to keep it",
  "Secret-Wert, nicht die Secret-ID": "Secret value, not the secret ID",
  "DMARC-Postfach": "DMARC mailbox",
  "IMAP-Server": "IMAP server",
  Port: "Port",
  Benutzername: "Username",
  "Passwort / App-Passwort": "Password / app password",
  "Passwort hinterlegt · leer lassen zum Beibehalten":
    "Password stored · leave empty to keep it",
  "IMAP- oder App-Passwort": "IMAP or app password",
  Eingangsordner: "Reports folder",
  Archivordner: "Archive folder",
  "Erforderlich: Application Mail.ReadWrite, begrenzt auf dieses Postfach. Die Anwendung erstellt keine Entra-App.":
    "Required: Application Mail.ReadWrite, scoped to this mailbox. The application does not create an Entra app.",
  "TLS und Zertifikatsprüfung sind immer aktiv. OAuth-only-Anbieter benötigen einen eigenen API-Adapter.":
    "TLS and certificate verification are always enabled. OAuth-only providers require a dedicated API adapter.",
  "Entwurf speichern": "Save draft",
  "Speichere Änderungen vor dem Verbindungstest.":
    "Save your changes before testing the connection.",
  "Verbindung wird geprüft …": "Testing connection …",
  "Verbindung testen": "Test connection",
  Aktivieren: "Activate",
  "Der Test meldet sich an und prüft die Ordner ausschließlich lesend. Er lädt, verarbeitet, verschiebt und löscht keine Nachrichten.":
    "The test signs in and checks the folders read-only. It does not download, process, move or delete any messages.",
  "Neue Anbindung jetzt aktivieren?": "Activate the new connection now?",
  "Der bestehende einzelne Parser-Prozess wird kurz gestoppt und mit dem geprüften Entwurf neu gestartet. OpenSearch läuft weiter.":
    "The existing single parser process is briefly stopped and restarted with the tested draft. OpenSearch continues running.",
  "Wird aktiviert …": "Activating …",
  "Geprüfte Anbindung aktivieren": "Activate tested connection",
  Abbrechen: "Cancel",
  "Anbindung konnte nicht geladen werden.":
    "The connection could not be loaded.",
  "Die Tenant-ID muss eine gültige UUID sein.":
    "The tenant ID must be a valid UUID.",
  "Die Client-ID muss eine gültige UUID sein.":
    "The client ID must be a valid UUID.",
  "Das Postfach muss eine gültige E-Mail-Adresse sein.":
    "The mailbox must be a valid email address.",
  "Ein Client Secret muss hinterlegt werden.":
    "A client secret must be stored.",
  "Ein IMAP-Passwort muss hinterlegt werden.":
    "An IMAP password must be stored.",
  "Eingangs- und Archivordner müssen unterschiedlich sein.":
    "Reports and archive folders must be different.",
  "Verbindungsentwurf gespeichert. Führe jetzt den read-only Test aus.":
    "Connection draft saved. Run the read-only test now.",
  "Speichern fehlgeschlagen.": "Saving failed.",
  "Microsoft-365-Postfach und Ordner sind erreichbar.":
    "Microsoft 365 mailbox and folders are accessible.",
  "IMAP-Postfach und Ordner sind erreichbar.":
    "IMAP mailbox and folders are accessible.",
  "Verbindungstest erfolgreich.": "Connection test successful.",
  "Verbindungstest fehlgeschlagen.": "Connection test failed.",
  "Anbindung aktiviert. Der einzelne Parser-Prozess übernimmt die neue Konfiguration.":
    "Connection activated. The single parser process is applying the new configuration.",
  "Aktivierung fehlgeschlagen.": "Activation failed.",
  "Die Anwendung konnte nicht gestartet werden.":
    "The application could not be started.",
  "Sichere Anwendung wird vorbereitet …": "Preparing the secure application …",
  Ersteinrichtung: "Initial setup",
  "Admin-Passwort": "Admin password",
  "Das Admin-Passwort muss mindestens 12 Zeichen lang sein.":
    "The admin password must contain at least 12 characters.",
  "Die Passwörter stimmen nicht überein.": "The passwords do not match.",
  "Wird gespeichert …": "Saving …",
  "Zugänge einrichten": "Set up access",
  "Bestätige das bestehende Admin-Passwort und ergänze den neuen Read-Zugang.":
    "Confirm the existing admin password and add the new read access.",
  "Lege den Read-Zugang für das Dashboard und das separate Admin-Passwort für geschützte Einstellungen fest.":
    "Set the read access for the dashboard and a separate admin password for protected settings.",
  "Bestehendes Admin-Passwort": "Existing admin password",
  "Admin-Passwort wiederholen": "Repeat admin password",
  "Read-Benutzername": "Read username",
  "Read-Passwort": "Read password",
  "Read-Passwort wiederholen": "Repeat read password",
  "Beide Passwörter benötigen mindestens 12 Zeichen.":
    "Both passwords must contain at least 12 characters.",
  "Der Read-Benutzername darf keine Leerzeichen enthalten.":
    "The read username must not contain whitespace.",
  "Das Read-Passwort muss mindestens 12 Zeichen lang sein.":
    "The read password must contain at least 12 characters.",
  "Die Read-Passwörter stimmen nicht überein.":
    "The read passwords do not match.",
  "Zugänge konnten nicht gespeichert werden.":
    "The access credentials could not be saved.",
  "Zugänge speichern": "Save access credentials",
  "Der Read-Zugang schützt den Dashboard-Zugriff. Das separate Admin-Passwort schützt Änderungen an globalen Einstellungen.":
    "Read access protects dashboard access. The separate admin password protects changes to global settings.",
  "Geschützter Zugriff": "Protected access",
  "Bei DMARC Control anmelden": "Sign in to DMARC Control",
  "Melde dich mit dem beim Setup definierten Read-Zugang an.":
    "Sign in with the read credentials defined during setup.",
  "Benutzername oder Passwort ist falsch.":
    "The username or password is incorrect.",
  "Anmeldung läuft …": "Signing in …",
  Anmelden: "Sign in",
  "Angemeldet als {username}": "Signed in as {username}",
  "Lokale Farbgebung aktiv": "Local color scheme active",
  "Globaler Standard: Custom": "Global default: Custom",
  "Globaler Standard: Standardgrün": "Global default: Default green",
  Standardgrün: "Default green",
  Sprache: "Language",
  "Sprache der Benutzeroberfläche":
    "Language used throughout the user interface",
  Deutsch: "German",
  Englisch: "English",
  Markenfarbe: "Brand color",
  "UI-Farbgebung": "UI color scheme",
  "Die Grundfarbe steuert Navigation, Akzente, Fokus sowie die feine Tönung von Karten, Flächen und Trennlinien. Statusfarben für Fehler und Warnungen bleiben semantisch eindeutig.":
    "The base color controls navigation, accents, focus and the subtle tint of cards, surfaces and dividers. Status colors for errors and warnings remain semantically distinct.",
  "Farbe wählen": "Choose color",
  "Aktuelle Farbe": "Current color",
  "RGB-Farbwerte": "RGB color values",
  Custom: "Custom",
  "Als Custom speichern": "Save as Custom",
  "Aktuelle Farbe wurde als Custom gespeichert.":
    "The current color was saved as Custom.",
  "Farbprofil ist lokal aktiv.": "The color profile is active locally.",
  "Lokale Abweichung entfernen": "Remove local override",
  "Änderungen wirken sofort und bleiben automatisch in diesem Browser gespeichert.":
    "Changes apply immediately and are saved automatically in this browser.",
  "Ursprüngliche Gestaltung": "Original design",
  "Live-Vorschau": "Live preview",
  "Änderungen werden unmittelbar auf die gesamte Oberfläche angewendet.":
    "Changes are applied to the entire interface immediately.",
  "Gebrandete Oberfläche": "Branded interface",
  "Aktiver Bereich": "Active section",
  "Inaktiver Bereich": "Inactive section",
  "Akzent und Fading": "Accent and fading",
  "Akzente und Flächentöne aus {color} abgeleitet":
    "Accents and surface tints derived from {color}",
  Beispielaktion: "Example action",
  "Die Auswahl wird lokal in diesem Browser gespeichert und verändert keine DMARC- oder Serverdaten.":
    "These preferences are stored locally in this browser and do not alter DMARC or server data.",
  "Die Vorschau verändert keine DMARC- oder OpenSearch-Daten.":
    "The preview does not alter DMARC or OpenSearch data.",
  Farbprofile: "Color profiles",
  "Profile können lokal angewendet oder als Standard für alle Browser dieser Installation gesetzt werden.":
    "Profiles can be applied locally or set as the default for every browser using this installation.",
  "Noch nicht gespeichert": "Not saved yet",
  Global: "Global",
  Anwenden: "Apply",
  "Global setzen": "Set globally",
  Administration: "Administration",
  "Der Read-Zugang schützt das Dashboard. Die separate Admin-Anmeldung schützt globale Einstellungen.":
    "Read access protects the dashboard. The separate admin sign-in protects global settings.",
  "Admin angemeldet": "Admin signed in",
  "Nicht angemeldet": "Not signed in",
  "Als Admin anmelden": "Sign in as admin",
  "Als Admin angemeldet.": "Signed in as admin.",
  "Admin-Passwort ist falsch.": "The admin password is incorrect.",
  "Anmeldung fehlgeschlagen.": "Sign-in failed.",
  "Aktuelles Passwort": "Current password",
  "Neues Passwort": "New password",
  "Neues Passwort wiederholen": "Repeat new password",
  "Passwort ändern": "Change password",
  Abmelden: "Sign out",
  "Admin-Passwort wurde geändert.": "The admin password was changed.",
  "Das aktuelle Admin-Passwort ist falsch.":
    "The current admin password is incorrect.",
  "Das neue Passwort muss sich vom aktuellen unterscheiden.":
    "The new password must be different from the current password.",
  "Passwortänderung fehlgeschlagen.": "Password change failed.",
  "Admin-Sitzung wurde beendet.": "The admin session was ended.",
  "Abmeldung fehlgeschlagen.": "Sign-out failed.",
  "Nach einer Passwortänderung werden andere Admin-Sitzungen automatisch beendet.":
    "Changing the password automatically ends other admin sessions.",
  "Read-Zugang": "Read access",
  "Eine Änderung beendet alle anderen Read-Sitzungen. Diese Sitzung bleibt angemeldet.":
    "A change ends all other read sessions. This session remains signed in.",
  "Neues Read-Passwort": "New read password",
  "Read-Zugang aktualisieren": "Update read access",
  "Read-Zugang wurde aktualisiert.": "Read access was updated.",
  "Melde dich zuerst als Admin an.": "Sign in as admin first.",
  "Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.":
    "The admin session has expired. Please sign in again.",
  "Admin-Anmeldung erforderlich": "Admin sign-in required",
  "Melde dich im Bereich Administration an, um ein Profil global zu setzen.":
    "Sign in under Administration to set a profile globally.",
  "Speichere zuerst eine Custom-Farbe.": "Save a Custom color first.",
  "Globaler Standard wurde aktualisiert.": "The global default was updated.",
  "Aktualisierung fehlgeschlagen.": "Update failed.",
  "Globale Farbgebung ist nicht verfügbar: {error}":
    "Global color settings are unavailable: {error}",
  "DMARC-Kennzahlen": "DMARC metrics",
  "DMARC-Passrate": "DMARC pass rate",
  Nachrichten: "Messages",
  "{passed} von {total} Nachrichten": "{passed} of {total} messages",
  "Letzter Report: {date}": "Latest report: {date}",
  "Kritische Quellen": "Critical sources",
  "{count} echte DMARC-Fails": "{count} actual DMARC failures",
  "Was braucht Aufmerksamkeit?": "What needs attention?",
  "Nach finalem DMARC-Ergebnis und Aktualität priorisiert":
    "Prioritized by final DMARC result and recency",
  "Alle Warnungen": "All alerts",
  Status: "Status",
  "Sending Host": "Sending host",
  Authentifizierung: "Authentication",
  Kritisch: "Critical",
  "Kein PTR": "No PTR",
  Unbekannt: "Unknown",
  "nicht aligned": "not aligned",
  aligned: "aligned",
  "Keine echten DMARC-Fehler": "No actual DMARC failures",
  "Im gewählten Zeitraum sind keine Quellen mit passed_dmarc:false vorhanden.":
    "There are no sources with passed_dmarc:false in the selected period.",
  "Alignment gegenüber finalem DMARC-Ergebnis":
    "Alignment compared with the final DMARC result",
  "DMARC bestanden": "DMARC passed",
  "DMARC fehlgeschlagen": "DMARC failed",
  "{count} Alignment-Beobachtungen wurden durch den jeweils anderen Mechanismus kompensiert und sind deshalb keine kritischen DMARC-Fails.":
    "{count} alignment observations were compensated by the other mechanism and are therefore not critical DMARC failures.",
  "Alignment und finales DMARC-Ergebnis sind im gewählten Zeitraum konsistent.":
    "Alignment and the final DMARC result are consistent in the selected period.",
  "DMARC Pass/Fail im Zeitverlauf": "DMARC pass/fail over time",
  "Zeitverlauf der bestandenen und fehlgeschlagenen DMARC-Nachrichten":
    "Timeline of passed and failed DMARC messages",
  "Tageswerte für {scope}": "Daily values for {scope}",
  "alle Domains": "all domains",
  "Domains & Reports": "Domains & reports",
  "Volumen, Berichtsersteller und veröffentlichte Richtlinien":
    "Volume, reporting organizations and published policies",
  "Nachrichten nach Domain": "Messages by domain",
  "Keine Domains im Zeitraum": "No domains in this period",
  "Reporting Organizations": "Reporting organizations",
  "Keine Berichtsersteller im Zeitraum":
    "No reporting organizations in this period",
  "Veröffentlichte DMARC-Policies": "Published DMARC policies",
  "Keine Policies im Zeitraum": "No policies in this period",
  "Sending Hosts werden geladen": "Loading sending hosts",
  "Technische Quellen, erkannte Dienste und Authentifizierungsergebnis":
    "Technical sources, detected services and authentication results",
  "{count} Quellen": "{count} sources",
  "Sending Hosts durchsuchen": "Search sending hosts",
  "Sending-Hosts-Seiten": "Sending host pages",
  "{start}–{end} von {total} Quellen": "{start}–{end} of {total} sources",
  "Vorherige Seite": "Previous page",
  "Nächste Seite": "Next page",
  "Host-Detail wird geladen": "Loading host details",
  "Die Quelle {ip} ist für die gewählte Domain und den Zeitraum nicht vorhanden. Passe die Filter an.":
    "Source {ip} is not available for the selected domain and time range. Adjust the filters.",
  "IP, PTR, Domain oder Dienst suchen": "Search by IP, PTR, domain or service",
  Risiko: "Risk",
  "Alle Ergebnisse": "All results",
  Hinweise: "Advisories",
  Unauffällig: "Healthy",
  "SPF nicht aligned": "SPF not aligned",
  "DKIM nicht aligned": "DKIM not aligned",
  Source: "Source",
  "Erkannter Dienst": "Detected service",
  Vertrauen: "Trust",
  Zuordnung: "Classification",
  Konfidenz: "Confidence",
  "Die Zahlen zeigen betroffene Nachrichten im gewählten Zeitraum.":
    "The numbers show affected messages in the selected time range.",
  "{count} von {total} nicht aligned":
    "{count} of {total} not aligned",
  "{count} von {total} aligned": "{count} of {total} aligned",
  Details: "Details",
  "Keine Sending Hosts gefunden": "No sending hosts found",
  "Passe Suche, Zeitraum oder Risikofilter an.":
    "Adjust the search, time range or risk filter.",
  "Pass · Hinweis": "Pass · Advisory",
  "Nicht bestätigt": "Unconfirmed",
  "Automatisch erkannt": "Automatically detected",
  "Prüfung ausstehend": "Review pending",
  "Automatisch zugeordnet": "Automatically classified",
  "Zuordnung bestätigt": "Classification confirmed",
  "Automatische Zuordnung verworfen": "Automatic classification rejected",
  "Dynamischer IP-Bereich": "Dynamic IP range",
  "Netzprofil · Dynamische IP": "Network profile · Dynamic IP",
  "Dynamischer öffentlicher IP-Bereich": "Dynamic public IP range",
  "Das Muster entspricht einem Endkunden- oder Zugangsnetz. Zusammen mit dem DMARC-Fail ist dies ein starkes Indiz für Spoofing oder Spam; eine Fehlkonfiguration bleibt möglich.":
    "The pattern matches a consumer or access network. Combined with the DMARC failure, this is a strong indicator of spoofing or spam; a misconfiguration remains possible.",
  "Das Muster entspricht einem Endkunden- oder Zugangsnetz. Solche Adressen sind für direkte Mailzustellung ungewöhnlich und sollten geprüft werden.":
    "The pattern matches a consumer or access network. Such addresses are unusual for direct mail delivery and should be reviewed.",
  Bestätigt: "Acknowledged",
  Ignoriert: "Ignored",
  "Zuordnung gespeichert.": "Classification saved.",
  "Speichern fehlgeschlagen": "Unable to save",
  "PTR: nicht vorhanden": "PTR: unavailable",
  "Host-Detail": "Host details",
  "Kein Reverse-DNS-Name vorhanden": "No reverse DNS name available",
  "Detailansicht schließen": "Close details",
  "SPF-Identitäten": "SPF identities",
  "DKIM-Domains": "DKIM domains",
  "DKIM-Selector": "DKIM selectors",
  Netzwerk: "Network",
  "Erstmals gesehen": "First seen",
  "Zuletzt gesehen": "Last seen",
  "DMARC-Ergebnis": "DMARC result",
  "Dienst-Erkennung": "Service detection",
  "Mehrere Signale werden kombiniert. PTR ist nur ein Indiz und niemals die alleinige Entscheidungsgrundlage.":
    "Multiple signals are combined. PTR is only one indicator and never the sole basis for a decision.",
  "Keine belastbare Evidenz.": "No reliable evidence.",
  Dienst: "Service",
  Vertrauensstatus: "Trust status",
  Zuordnungsstatus: "Classification status",
  "Automatisch zugeordnet · Systemstatus":
    "Automatically classified · system status",
  "Automatische Zuordnung wiederherstellen":
    "Restore automatic classification",
  "Automatische Zuordnung wiederhergestellt.":
    "Automatic classification restored.",
  "Der Zuordnungsstatus beschreibt nur die Dienstklassifizierung. Er ändert weder das DMARC-Ergebnis noch Warnungen und ist keine Freigabeliste.":
    "The classification status describes only the service classification. It does not change the DMARC result or alerts and is not an allowlist.",
  "Untersuchung aus der Warnungszentrale. Alert-Status und Host-Zuordnung werden getrennt gespeichert.":
    "Investigation from the alert center. Alert status and host classification are stored separately.",
  "Zurück zur Warnung": "Back to alert",
  Notiz: "Note",
  "Optionaler administrativer Kontext": "Optional administrative context",
  Speichern: "Save",
  "Statusänderung fehlgeschlagen": "Unable to update status",
  "Warnungen werden bewertet": "Evaluating alerts",
  "Verlinkte Warnung wird geladen": "Loading linked alert",
  "Verlinkte Warnung": "Linked alert",
  "Gespeichertes Ereignis aus der Historie.":
    "Stored historical event.",
  "Dieses Ereignis liegt außerhalb der aktuellen Filter.":
    "This event is outside the current filters.",
  "Die verlinkte Warnung wurde nicht gefunden. Für ältere Links ist möglicherweise kein gespeichertes Ereignis vorhanden.":
    "The linked alert was not found. Older links may not have a stored event.",
  Warnungszentrale: "Alert center",
  "Deduplizierte Ereignisse mit nachvollziehbarem Auslöser":
    "Deduplicated events with a traceable trigger",
  "{count} offen": "{count} open",
  "{affected} von {total} Nachrichten betroffen":
    "{affected} of {total} messages affected",
  "Alle Status": "All statuses",
  Offen: "Open",
  Behoben: "Resolved",
  Priorität: "Priority",
  Warnung: "Alert",
  Auslöser: "Trigger",
  Reportzeit: "Report time",
  Bestätigen: "Acknowledge",
  "Sending Host untersuchen": "Investigate sending host",
  Ignorieren: "Ignore",
  "Die verlinkte Warnung ist im gewählten Zeitraum nicht mehr vorhanden. Passe Zeitraum oder Domainfilter an.":
    "The linked alert is no longer available in the selected period. Adjust the time range or domain filter.",
  "Keine Warnungen in dieser Ansicht": "No alerts in this view",
  "Für Domain, Zeitraum und Status existieren keine passenden Ereignisse.":
    "No matching events exist for this domain, time range and status.",
  "Sofort kritisch": "Immediately critical",
  "Neuer oder nicht autorisierter Host mit echtem DMARC-Fail.":
    "New or unauthorized host with an actual DMARC failure.",
  Konfigurationshinweis: "Configuration advisory",
  "Ein Mechanismus ist nicht aligned, DMARC besteht aber weiterhin.":
    "One mechanism is not aligned, but DMARC still passes.",
  "Ein Mechanismus ist nicht aligned, DMARC besteht aber weiterhin. Jede betroffene Nachricht zählt einmal; die Gesamtzahl umfasst diese Domain, Source-IP und diesen Reporttag.":
    "One mechanism is not aligned, but DMARC still passes. Each affected message is counted once; the total covers this domain, source IP and report day.",
  "Report-Verzögerung": "Report delay",
  "Ausbleibende Reports werden erst nach der üblichen Verzögerung gewarnt.":
    "Missing reports trigger an alert only after the usual delay.",
  Hinweis: "Advisory",
  "Forensik-Metadaten werden geladen": "Loading forensic metadata",
  "DMARC Forensik": "DMARC forensics",
  "Minimierte Betriebsmetadaten aus RUF-/Failure-Reports":
    "Minimized operational metadata from RUF/failure reports",
  Fehlertyp: "Failure type",
  "Alle Fehlertypen": "All failure types",
  "Rohinhalt, Empfänger, Absender, Betreff und Header werden von dieser API nicht geladen.":
    "Raw content, recipients, senders, subjects and headers are not loaded by this API.",
  "Forensic Samples": "Forensic samples",
  "Aggregierte Failure-Metadaten": "Aggregated failure metadata",
  Datenaktualität: "Data freshness",
  "Source-IPs": "Source IPs",
  "{count} Länder/Zuordnungen": "{count} countries/mappings",
  "Keine Forensik-Daten im Zeitraum": "No forensic data in this period",
  "RUF-Daten sind möglicherweise deaktiviert oder es sind keine passenden Failure-Reports eingegangen.":
    "RUF data may be disabled or no matching failure reports were received.",
  "Authentication Failure Types": "Authentication failure types",
  "Keine Fehlertypen": "No failure types",
  "Betroffene Domains": "Affected domains",
  "Keine Domains": "No domains",
  "Quellen nach Land": "Sources by country",
  "Keine Länderinformationen": "No country information",
  "Top Forensic Source IPs": "Top forensic source IPs",
  "IP, PTR, Basisdomain, Land und letzte Beobachtung":
    "IP, PTR, base domain, country and latest observation",
  "PTR / Basisdomain": "PTR / base domain",
  Land: "Country",
  Samples: "Samples",
  "Bereinigte Failure-Evidenz": "Sanitized failure evidence",
  "Nur Authentifizierungs- und Delivery-Ergebnis; keine Nachrichteninhalte":
    "Authentication and delivery results only; no message content",
  "Neue Source-IP erkannt": "New source IP detected",
  "Neuer unbekannter Sender mit DMARC-Fail":
    "New unknown sender with a DMARC failure",
  "Bekannter Sending Host hat sich verschlechtert":
    "Known sending host has degraded",
  "DMARC-Fehlerquelle erkannt": "DMARC failure source detected",
  "DMARC-Fail aus dynamischem IP-Bereich":
    "DMARC failure from a dynamic IP range",
  "Kompensiertes Alignment-Problem": "Compensated alignment issue",
  "DMARC-Reports bleiben aus": "DMARC reports are missing",
  "Erstmals gesehen am {date}": "First seen on {date}",
  "Letzter Berichtszeitraum endete vor {days} Tagen; übliche Zustellverzögerung berücksichtigt":
    "Latest reporting period ended {days} days ago; usual delivery delay accounted for",
  "Keine Zuordnung": "No classification",
  Hoch: "High",
  Mittel: "Medium",
  Niedrig: "Low",
};

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
  formatNumber: (value: number | null | undefined) => string;
  formatPercent: (value: number | null | undefined) => string;
  formatDate: (
    value: string | null | undefined,
    withTime?: boolean,
  ) => string;
  reportAge: (value: string | null | undefined) => string;
  translateBackendLabel: (value: string | null | undefined) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function interpolate(
  template: string,
  values?: Record<string, string | number>,
) {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, key) =>
    values[key] === undefined ? match : String(values[key]),
  );
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => {
    try {
      return localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "de";
    } catch {
      return "de";
    }
  });

  const setLanguage = (nextLanguage: Language) => {
    setLanguageState(nextLanguage);
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage);
    } catch {
      // The preference still applies to the current page.
    }
  };

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<I18nValue>(() => {
    const locale = language === "de" ? "de-CH" : "en-GB";
    const numberFormatter = new Intl.NumberFormat(locale);
    const percentFormatter = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    const dateFormatter = new Intl.DateTimeFormat(locale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
    const dateTimeFormatter = new Intl.DateTimeFormat(locale, {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    const t: Translate = (source, values) =>
      interpolate(language === "en" ? english[source] ?? source : source, values);
    const formatDate = (
      rawValue: string | null | undefined,
      withTime = false,
    ) => {
      if (!rawValue) return "–";
      const parsed = new Date(rawValue);
      if (Number.isNaN(parsed.getTime())) return rawValue;
      return (withTime ? dateTimeFormatter : dateFormatter).format(parsed);
    };
    const reportAge = (rawValue: string | null | undefined) => {
      if (!rawValue) return t("Keine Reports");
      const days = Math.max(
        0,
        Math.floor((Date.now() - new Date(rawValue).getTime()) / 86_400_000),
      );
      if (days === 0) return t("Heute");
      if (days === 1) return t("Vor einem Tag");
      return t("Vor {days} Tagen", { days });
    };
    const backendLabels: Record<string, string> = {
      Unbekannt: t("Unbekannt"),
      "Dynamischer IP-Bereich": t("Dynamischer IP-Bereich"),
      "Keine Zuordnung": t("Keine Zuordnung"),
      Hoch: t("Hoch"),
      Mittel: t("Mittel"),
      Niedrig: t("Niedrig"),
      "PTR: umgekehrte Quell-IP eingebettet":
        language === "en"
          ? "PTR: reversed source IP embedded"
          : "PTR: umgekehrte Quell-IP eingebettet",
      "PTR: dynamisches Anschlussmuster":
        language === "en"
          ? "PTR: dynamic access-network pattern"
          : "PTR: dynamisches Anschlussmuster",
    };
    const translateBackendLabel = (rawValue: string | null | undefined) => {
      if (!rawValue) return "";
      if (backendLabels[rawValue]) return backendLabels[rawValue];
      if (language === "de") return rawValue;
      return rawValue
        .replace("Mail-Domain:", "Mail domain:")
        .replace("Identität:", "Identity:")
        .replace("PTR/Domain:", "PTR/domain:")
        .replace("Mehrdeutige Provider-Herkunft: bestandene Authentifizierungen für", "Ambiguous provider attribution: passed authentication for")
        .replace("Domain/ASN:", "Domain/ASN:");
    };

    return {
      language,
      setLanguage,
      t,
      formatNumber: (rawValue) => numberFormatter.format(rawValue ?? 0),
      formatPercent: (rawValue) => percentFormatter.format(rawValue ?? 0),
      formatDate,
      reportAge,
      translateBackendLabel,
    };
  }, [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used within LanguageProvider");
  }
  return value;
}
