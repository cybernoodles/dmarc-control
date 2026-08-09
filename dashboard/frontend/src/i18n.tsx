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
  "Darstellung, Benachrichtigungen, Backups, Postfachanbindung und geschützte Administration":
    "Appearance, notifications, backups, mailbox connection and protected administration",
  Einstellungsbereiche: "Settings sections",
  "Darstellung & Sprache": "Appearance & language",
  "Branding und Benutzeroberfläche": "Branding and user interface",
  Benachrichtigungen: "Notifications",
  "E-Mail-Alerting und Versandwege": "Email alerting and delivery methods",
  "Backup & Restore": "Backup & restore",
  "Sicherungen und Wiederherstellung": "Backups and recovery",
  "Backup & Wiederherstellung": "Backup & recovery",
  "OpenSearch-Snapshot und konsistentes Dashboard-Steuerungsbackup mit gemeinsamer Backup-ID erstellen.":
    "Create an OpenSearch snapshot and a consistent dashboard control backup with a shared backup ID.",
  "Backup-Zeitplan, Historie und manuelle Ausführung sind ausschließlich für Administratoren sichtbar.":
    "Backup schedule, history and manual runs are visible only to administrators.",
  "Backup-Einstellungen werden geladen": "Loading backup settings",
  "Automatische Online-Backups aktivieren": "Enable automatic online backups",
  "Der Parser läuft weiter. OpenSearch und SQLite werden mit ihren nativen konsistenten Backup-Verfahren gesichert.":
    "The parser continues running. OpenSearch and SQLite are protected using their native consistent backup mechanisms.",
  Intervall: "Interval",
  "Alle 6 Stunden": "Every 6 hours",
  "Alle 12 Stunden": "Every 12 hours",
  Täglich: "Daily",
  Wöchentlich: "Weekly",
  "Aufbewahrte Sicherungen": "Retained backups",
  "Backup-Ziel": "Backup target",
  "Docker-Mount ist beschreibbar": "Docker mount is writable",
  "Docker-Mount ist nicht beschreibbar": "Docker mount is not writable",
  "Vor dem ersten Backup muss DMARC_BACKUP_ROOT auf ein beschreibbares, vorzugsweise externes und verschlüsseltes Ziel zeigen.":
    "Before the first backup, DMARC_BACKUP_ROOT must point to a writable, preferably external and encrypted target.",
  "Backup läuft …": "Backup running …",
  "Jetzt sichern": "Back up now",
  "Letzte Online-Backups": "Latest online backups",
  "OpenSearch und Dashboard-Steuerungsdaten":
    "OpenSearch and dashboard control data",
  Manuell: "Manual",
  Zeitplan: "Scheduled",
  Erfolgreich: "Successful",
  Läuft: "Running",
  "Noch keine Sicherung vorhanden.": "No backup is available yet.",
  "Ein vollständiges Cold-Backup oder ein Restore wird bewusst mit dem hostseitigen Wartungswerkzeug ausgeführt. Das Dashboard erhält dafür keinen Zugriff auf Docker.":
    "A complete cold backup or restore is deliberately performed with the host-side maintenance tool. The dashboard does not receive Docker access.",
  "Letzter Backup-Fehler: {error}": "Latest backup error: {error}",
  "Letztes Backup fehlgeschlagen": "Latest backup failed",
  "Letztes Backup erfolgreich": "Latest backup successful",
  "Backup läuft": "Backup running",
  "Noch kein Backup": "No backup yet",
  "Backup-Einstellungen wurden gespeichert.": "Backup settings were saved.",
  "Backup-Einstellungen konnten nicht gespeichert werden.":
    "Backup settings could not be saved.",
  "Backup-Einstellungen konnten nicht geladen werden.":
    "Backup settings could not be loaded.",
  "Speichere Änderungen vor dem manuellen Backup.":
    "Save changes before running a manual backup.",
  "Online-Backup wurde gestartet.": "Online backup started.",
  "Online-Backup konnte nicht gestartet werden.":
    "Online backup could not be started.",
  "Das Backup-Ziel ist nicht beschreibbar. Prüfe den Docker-Mount und die Berechtigungen.":
    "The backup target is not writable. Check the Docker mount and permissions.",
  "Ein Online-Backup wird bereits ausgeführt.":
    "An online backup is already running.",
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
  "Erfolgreich zugestellt": "Successfully delivered",
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
  "Der bestehende einzelne Parser-Prozess wird kurz gestoppt und mit dem geprüften Entwurf neu gestartet. Grafana und OpenSearch laufen weiter.":
    "The existing single parser process is briefly stopped and restarted with the tested draft. Grafana and OpenSearch continue running.",
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
  Warnungszentrale: "Alert center",
  "Deduplizierte Ereignisse mit nachvollziehbarem Auslöser":
    "Deduplicated events with a traceable trigger",
  "{count} offen": "{count} open",
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
