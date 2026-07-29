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
  "Geschützte globale Einstellung": "Protected global setting",
  "Der Token wird nur für diese Browser-Sitzung gespeichert.":
    "The token is stored for this browser session only.",
  "Settings-Token": "Settings token",
  "Token für globale Änderungen": "Token for global changes",
  "Settings-Token ist erforderlich.": "A settings token is required.",
  "Settings-Token ist ungültig.": "The settings token is invalid.",
  "Speichere zuerst eine Custom-Farbe.": "Save a Custom color first.",
  "Globaler Standard wurde aktualisiert.": "The global default was updated.",
  "Aktualisierung fehlgeschlagen.": "Update failed.",
  "Auf dem Server ist noch kein Settings-Token eingerichtet.":
    "No settings token has been configured on the server yet.",
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
  Konfidenz: "Confidence",
  Details: "Details",
  "Keine Sending Hosts gefunden": "No sending hosts found",
  "Passe Suche, Zeitraum oder Risikofilter an.":
    "Adjust the search, time range or risk filter.",
  "Pass · Hinweis": "Pass · Advisory",
  "Nicht bestätigt": "Unconfirmed",
  "Automatisch erkannt": "Automatically detected",
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
  Ignorieren: "Ignore",
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
  "Kompensiertes Alignment-Problem": "Compensated alignment issue",
  "DMARC-Reports bleiben aus": "DMARC reports are missing",
  "Erstmals gesehen am {date}": "First seen on {date}",
  "Letzter Report vor {days} Tagen; übliche Zustellverzögerung berücksichtigt":
    "Latest report was {days} days ago; usual delivery delay accounted for",
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
      "Keine Zuordnung": t("Keine Zuordnung"),
      Hoch: t("Hoch"),
      Mittel: t("Mittel"),
      Niedrig: t("Niedrig"),
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
