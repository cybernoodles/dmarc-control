import { useI18n } from "./i18n";
import "./AlertEvaluationStatus.css";

export interface AlertEvaluationRun {
  id: number;
  status: "running" | "success" | "failure" | "interrupted";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  scope: { domain: string; days: number };
  counts: { events: number | null; domains: number | null; hosts: number | null };
  error: string | null;
}

export interface AlertEvaluationState {
  configured: boolean;
  enabled: boolean;
  evaluation: {
    latest: AlertEvaluationRun | null;
    last_success: AlertEvaluationRun | null;
  };
}

const labelsByLanguage = {
  de: {
    title: "Automatische Alert-Auswertung",
    delivery: "Automatischer Versand",
    active: "Aktiv",
    paused: "Pausiert",
    unconfigured: "Nicht eingerichtet",
    evaluation: "Letzter Prüflauf",
    never: "Noch nie gestartet",
    running: "Läuft",
    success: "Erfolgreich",
    failure: "Fehlgeschlagen",
    interrupted: "Unterbrochen",
    started: "Letzter Start",
    succeeded: "Letzte vollständige Auswertung",
    noSuccess: "Noch kein erfolgreicher Lauf",
    duration: "Dauer des letzten Laufs",
    scope: "Prüfumfang",
    allDomains: "Alle Domains",
    days: "Tage",
    domains: "Geprüfte Domains",
    hosts: "Geprüfte Hosts",
    events: "Ermittelte Ereignisse",
    history: "Die Quellen- und Domainzahlen umfassen auch die berücksichtigte Report-Historie.",
    incomplete: "Für diesen Lauf liegt kein vollständig ermittelter Umfang vor.",
    separate: "Ein erfolgreicher Prüflauf bestätigt die vollständige Auswertung. SMTP- und Graph-Versand haben einen eigenen Status.",
  },
  en: {
    title: "Automatic alert evaluation",
    delivery: "Automatic email delivery",
    active: "Active",
    paused: "Paused",
    unconfigured: "Not configured",
    evaluation: "Latest evaluation",
    never: "Never started",
    running: "Running",
    success: "Successful",
    failure: "Failed",
    interrupted: "Interrupted",
    started: "Latest start",
    succeeded: "Last complete evaluation",
    noSuccess: "No successful evaluation yet",
    duration: "Duration of latest evaluation",
    scope: "Evaluation scope",
    allDomains: "All domains",
    days: "days",
    domains: "Domains checked",
    hosts: "Hosts checked",
    events: "Events found",
    history: "Source and domain counts also include the report history considered during evaluation.",
    incomplete: "The scope of this evaluation has not been fully determined.",
    separate: "A successful evaluation confirms the complete report analysis. SMTP and Graph delivery have a separate status.",
  },
};

const englishErrors: Record<string, string> = {
  "Die Reportdaten konnten nicht vollständig ausgewertet werden. Bitte OpenSearch-Verbindung und Daten prüfen.":
    "The report data could not be fully evaluated. Check the OpenSearch connection and data.",
  "Die Benachrichtigungseinstellungen konnten nicht geladen werden.":
    "The notification settings could not be loaded.",
  "Die automatische Alert-Auswertung ist fehlgeschlagen. Details stehen im Serverprotokoll.":
    "Automatic alert evaluation failed. Details are available in the server log.",
  "Die Auswertung wurde vor dem Abschluss unterbrochen.":
    "The evaluation was interrupted before completion.",
  "Der vorherige Prüflauf wurde durch einen Neustart unterbrochen.":
    "The previous evaluation was interrupted by a restart.",
};

const tones = {
  running: "info",
  success: "success",
  failure: "critical",
  interrupted: "warning",
} as const;

export function AlertEvaluationStatus({ state }: { state: AlertEvaluationState }) {
  const { language, formatDate, formatNumber } = useI18n();
  const labels = labelsByLanguage[language];
  const { latest, last_success: lastSuccess } = state.evaluation;
  const error = latest?.error
    ? language === "en" ? englishErrors[latest.error] ?? latest.error : latest.error
    : null;
  const duration = latest?.duration_ms == null
    ? latest?.status === "running" ? labels.running : "–"
    : latest.duration_ms < 1000 ? "< 1 s" : `${formatNumber(latest.duration_ms / 1000)} s`;
  const counts = ["domains", "hosts", "events"] as const;
  const incomplete = latest && counts.some((name) => latest.counts[name] == null);
  return (
    <section className="surface alert-evaluation-status" aria-label={labels.title}>
      <div className="alert-evaluation-heading">
        <h3>{labels.title}</h3>
        <div className="alert-evaluation-badges" aria-live="polite">
          <span className={`status-pill status-${state.configured && state.enabled ? "info" : "neutral"}`}>
            {labels.delivery}: {!state.configured ? labels.unconfigured : state.enabled ? labels.active : labels.paused}
          </span>
          <span className={`status-pill status-${latest ? tones[latest.status] : "neutral"}`}>
            {labels.evaluation}: {latest ? labels[latest.status] : labels.never}
          </span>
        </div>
      </div>
      <dl className="alert-evaluation-details">
        <div>
          <dt>{labels.started}</dt>
          <dd>{formatDate(latest?.started_at, true)}</dd>
        </div>
        <div>
          <dt>{labels.succeeded}</dt>
          <dd>{lastSuccess ? formatDate(lastSuccess.finished_at, true) : labels.noSuccess}</dd>
        </div>
        <div>
          <dt>{labels.duration}</dt>
          <dd>{duration}</dd>
        </div>
        <div>
          <dt>{labels.scope}</dt>
          <dd>{latest
            ? `${latest.scope.domain === "*" ? labels.allDomains : latest.scope.domain} · ${formatNumber(latest.scope.days)} ${labels.days}`
            : "–"}</dd>
        </div>
      </dl>
      {latest && (
        <dl className="alert-evaluation-counts">
          {counts.map((name) => (
            <div key={name}>
              <dt>{labels[name]}</dt>
              <dd>{latest.counts[name] == null ? "–" : formatNumber(latest.counts[name])}</dd>
            </div>
          ))}
        </dl>
      )}
      {incomplete && <p className="alert-evaluation-note">{labels.incomplete}</p>}
      {latest && <p className="alert-evaluation-note">{labels.history}</p>}
      {error && <p className="alert-evaluation-error" role="status">{error}</p>}
      <p className="alert-evaluation-note">{labels.separate}</p>
    </section>
  );
}
