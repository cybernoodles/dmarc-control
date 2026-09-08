import { useI18n } from "./i18n";
import "./RecipientDeliveryStatus.css";

export interface RecipientDeliveryItem {
  alert_id: string;
  recipient: string;
  status: "accepted" | "temporary_failure" | "permanent_failure" | "sending" | "exhausted";
  attempts: number;
  last_attempt_at: string;
  next_attempt_at: string | null;
  accepted_at: string | null;
  last_error: string | null;
  smtp_code: number | null;
}

export interface RecipientDeliverySummary {
  accepted: number;
  temporary_failure: number;
  permanent_failure: number;
  exhausted: number;
  pending: number;
  items: RecipientDeliveryItem[];
  limit: number;
  total: number;
}

const labelsByLanguage = {
  de: {
    title: "Versand pro Empfänger",
    description: "Die Annahme durch SMTP oder Microsoft Graph bestätigt noch keine Zustellung ins Postfach.",
    accepted: "Vom Versandserver akzeptiert",
    temporary_failure: "Vorübergehend fehlgeschlagen",
    permanent_failure: "Dauerhaft fehlgeschlagen",
    exhausted: "Versuche ausgeschöpft",
    pending: "In Bearbeitung",
    recipient: "Empfänger",
    status: "Status",
    attempts: "Versuche",
    times: "Zeitpunkte",
    lastAttempt: "Letzter Versuch",
    nextAttempt: "Erneut frühestens",
    acceptedAt: "Akzeptiert",
    response: "Rückmeldung",
    alert: "Warnung",
    openAlert: "Warnung öffnen",
    empty: "Noch keine Empfängerzustände für den neuen Versandablauf vorhanden.",
    showing: (shown: string, total: string) => `${shown} von ${total} Empfängerzuständen angezeigt; die Liste zeigt die zuletzt bearbeiteten Einträge.`,
  },
  en: {
    title: "Delivery by recipient",
    description: "Acceptance by SMTP or Microsoft Graph does not confirm delivery to the inbox.",
    accepted: "Accepted by the sending server",
    temporary_failure: "Temporarily failed",
    permanent_failure: "Permanently failed",
    exhausted: "Attempts exhausted",
    pending: "In progress",
    recipient: "Recipient",
    status: "Status",
    attempts: "Attempts",
    times: "Timestamps",
    lastAttempt: "Last attempt",
    nextAttempt: "Retry no earlier than",
    acceptedAt: "Accepted",
    response: "Response",
    alert: "Alert",
    openAlert: "Open alert",
    empty: "No recipient records for the new delivery workflow yet.",
    showing: (shown: string, total: string) => `Showing ${shown} of ${total} recipient records, with the most recently processed entries listed first.`,
  },
};

const tones = {
  accepted: "success",
  temporary_failure: "warning",
  permanent_failure: "critical",
  exhausted: "critical",
  pending: "info",
} as const;

export function RecipientDeliveryStatus({ summary }: { summary: RecipientDeliverySummary }) {
  const { language, formatDate, formatNumber } = useI18n();
  const labels = labelsByLanguage[language];
  const counts = ["accepted", "temporary_failure", "permanent_failure", "exhausted", "pending"] as const;
  return (
    <section className="recipient-delivery">
      <div className="recipient-delivery-heading">
        <h4>{labels.title}</h4>
        <p>{labels.description}</p>
      </div>
      <dl className="recipient-delivery-counts">
        {counts.map((status) => (
          <div key={status}>
            <dt>{labels[status]}</dt>
            <dd>{formatNumber(summary[status])}</dd>
          </div>
        ))}
      </dl>
      {summary.items.length === 0 ? (
        <p className="recipient-delivery-empty">{labels.empty}</p>
      ) : (
        <>
          {summary.total > summary.items.length && (
            <p className="recipient-delivery-range">
              {labels.showing(formatNumber(summary.items.length), formatNumber(summary.total))}
            </p>
          )}
          <div className="recipient-delivery-table" role="region" aria-label={labels.title} tabIndex={0}>
            <table>
              <caption className="sr-only">{labels.title}</caption>
              <thead>
                <tr>
                  <th scope="col">{labels.recipient}</th>
                  <th scope="col">{labels.status}</th>
                  <th scope="col">{labels.attempts}</th>
                  <th scope="col">{labels.times}</th>
                  <th scope="col">{labels.response}</th>
                  <th scope="col">{labels.alert}</th>
                </tr>
              </thead>
              <tbody>
                {summary.items.map((item, index) => {
                  const status = item.status === "sending" ? "pending" : item.status;
                  return (
                    <tr key={`${item.alert_id}:${item.recipient}:${index}`}>
                      <td className="recipient-delivery-address">{item.recipient}</td>
                      <td><span className={`status-pill status-${tones[status]}`}>{labels[status]}</span></td>
                      <td>{formatNumber(item.attempts)}</td>
                      <td className="recipient-delivery-times">
                        <span>{labels.lastAttempt}: {formatDate(item.last_attempt_at, true)}</span>
                        {item.next_attempt_at && (
                          <span>{labels.nextAttempt}: {formatDate(item.next_attempt_at, true)}</span>
                        )}
                        {item.accepted_at && (
                          <span>{labels.acceptedAt}: {formatDate(item.accepted_at, true)}</span>
                        )}
                      </td>
                      <td className="recipient-delivery-response">
                        {item.smtp_code !== null && <span>SMTP {item.smtp_code}</span>}
                        {item.last_error ? <span>{item.last_error}</span> : item.smtp_code === null ? "–" : null}
                      </td>
                      <td>
                        <a className="cell-link" href={`?view=alerts&alert=${encodeURIComponent(item.alert_id)}`}>
                          {labels.openAlert}
                          <span className="sr-only"> · {item.recipient}</span>
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
