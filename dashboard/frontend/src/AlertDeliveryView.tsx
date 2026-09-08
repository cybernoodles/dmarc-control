import { useEffect, useId, useRef, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { api, ApiError } from "./api";
import type { AlertDeliveryDetails, AlertDeliverySummary } from "./api";
import { useI18n } from "./i18n";
import { RecipientDeliveryStatus } from "./RecipientDeliveryStatus";
import "./AlertDeliveryView.css";

const labelsByLanguage = {
  de: {
    modes: {
      none: "Kein Versandversuch erfasst",
      accepted: "Vom Versandserver akzeptiert",
      partial: "Teilweise akzeptiert",
      failed: "Versand fehlgeschlagen",
      pending: "Versand in Bearbeitung",
      legacy_hold: "Alter Versand zurückgehalten",
    },
    acceptedCount: (accepted: string, total: string) => `${accepted} von ${total} akzeptiert`,
    exhaustedCount: (count: string) => `${count} × Versuche ausgeschöpft`,
    lastAttempt: "Letzter Versuch",
    nextAttempt: "Erneut frühestens",
    retryCondition: "Ein weiterer Versuch erfolgt nur bei aktivem Alerting, offener Warnung, ausgewähltem Ereignistyp und weiterhin konfiguriertem Empfänger. Der Zeitpunkt ist eine Untergrenze, kein zugesagter Termin.",
    title: "Versanddetails",
    close: "Schließen",
    loading: "Versanddetails werden geladen …",
    retry: "Erneut laden",
    loadError: "Die Versanddetails konnten nicht geladen werden.",
    adminRequired: "Für Versanddetails bitte als Administrator anmelden.",
    notFound: "Für diese Warnung sind keine Versanddetails verfügbar.",
    legacyTitle: "Frühere Gruppenzustellungen",
    legacyDescription: "Frühere Versandstände wurden für die gesamte Empfängerliste gespeichert. Daraus lässt sich nicht zuverlässig ableiten, welche einzelnen Empfänger die Nachricht angenommen haben. Alte Versuche für diese Warnung werden deshalb nicht automatisch wiederholt.",
    legacyCount: (records: string, attempts: string) => `${records} frühere Gruppenstände · ${attempts} erfasste Versuche`,
  },
  en: {
    modes: {
      none: "No delivery attempt recorded",
      accepted: "Accepted by the sending server",
      partial: "Partially accepted",
      failed: "Delivery failed",
      pending: "Delivery in progress",
      legacy_hold: "Previous delivery on hold",
    },
    acceptedCount: (accepted: string, total: string) => `${accepted} of ${total} accepted`,
    exhaustedCount: (count: string) => `${count} with attempts exhausted`,
    lastAttempt: "Last attempt",
    nextAttempt: "Retry no earlier than",
    retryCondition: "Another attempt requires alerting to be enabled, the alert to remain open, its event type to be selected and the recipient to remain configured. This is the earliest possible time, not a scheduled delivery.",
    title: "Delivery details",
    close: "Close",
    loading: "Loading delivery details …",
    retry: "Try again",
    loadError: "Delivery details could not be loaded.",
    adminRequired: "Sign in as an administrator to view delivery details.",
    notFound: "Delivery details are not available for this alert.",
    legacyTitle: "Previous group deliveries",
    legacyDescription: "Previous delivery records cover the entire recipient list. They cannot reliably establish which individual recipients accepted the message. Previous attempts for this alert are therefore not retried automatically.",
    legacyCount: (records: string, attempts: string) => `${records} previous group records · ${attempts} recorded attempts`,
  },
};

const tones = {
  none: "info",
  accepted: "success",
  partial: "warning",
  failed: "critical",
  pending: "info",
  legacy_hold: "warning",
} as const;

export function AlertDeliveryBadge({ summary }: { summary: AlertDeliverySummary }) {
  const { language, formatDate, formatNumber } = useI18n();
  const labels = labelsByLanguage[language];
  const lastAttempt = summary.last_attempt_at ?? summary.legacy.last_attempt_at;
  return (
    <div className="alert-delivery-badge">
      <div className="alert-delivery-badge-line">
        <span className={`status-pill status-${tones[summary.mode]}`}>
          {labels.modes[summary.mode]}
        </span>
        {summary.total > 0 && (
          <span className="alert-delivery-volume">
            {labels.acceptedCount(formatNumber(summary.accepted), formatNumber(summary.total))}
          </span>
        )}
      </div>
      {lastAttempt && (
        <span className="alert-delivery-time">
          {labels.lastAttempt}: {formatDate(lastAttempt, true)}
        </span>
      )}
      {summary.next_attempt_at && (
        <span className="alert-delivery-time" title={labels.retryCondition}>
          {labels.nextAttempt}: {formatDate(summary.next_attempt_at, true)}
        </span>
      )}
      {summary.exhausted > 0 && (
        <span className="alert-delivery-exhausted">
          {labels.exhaustedCount(formatNumber(summary.exhausted))}
        </span>
      )}
    </div>
  );
}

type PanelState = {
  alertId: string;
  refreshKey: number;
  retry: number;
} & (
  | { phase: "loading" }
  | { phase: "ready"; details: AlertDeliveryDetails }
  | { phase: "error"; reason: "loadError" | "adminRequired" | "notFound" }
);

export function AlertDeliveryPanel({
  alertId,
  title,
  onClose,
  refreshKey = 0,
}: {
  alertId: string;
  title: string;
  onClose: () => void;
  refreshKey?: number;
}) {
  const { language, formatNumber } = useI18n();
  const labels = labelsByLanguage[language];
  const headingId = useId();
  const panel = useRef<HTMLElement>(null);
  const generation = useRef(0);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<PanelState | null>(null);

  useEffect(() => {
    panel.current?.focus();
  }, [alertId]);

  useEffect(() => {
    const controller = new AbortController();
    const requestGeneration = ++generation.current;
    const context = { alertId, refreshKey, retry };
    let active = true;
    setState({ ...context, phase: "loading" });
    api.alertDelivery(alertId, controller.signal).then(
      (details) => {
        if (active && !controller.signal.aborted && generation.current === requestGeneration) {
          setState({ ...context, phase: "ready", details });
        }
      },
      (error: unknown) => {
        if (!active || controller.signal.aborted || generation.current !== requestGeneration) return;
        const reason = error instanceof ApiError && [401, 403].includes(error.status)
          ? "adminRequired"
          : error instanceof ApiError && error.status === 404 ? "notFound" : "loadError";
        setState({ ...context, phase: "error", reason });
      },
    );
    return () => {
      active = false;
      controller.abort();
    };
  }, [alertId, refreshKey, retry]);

  // Hide the previous alert or refresh immediately, before the new effect runs.
  const current = state?.alertId === alertId && state.refreshKey === refreshKey && state.retry === retry
    ? state : null;
  const loading = !current || current.phase === "loading";
  const details = current?.phase === "ready" ? current.details : null;

  return (
    <section
      className="alert-delivery-panel"
      ref={panel}
      tabIndex={-1}
      aria-labelledby={headingId}
      aria-busy={loading}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="alert-delivery-panel-heading">
        <div>
          <h3 id={headingId}>{labels.title}</h3>
          <p>{title}</p>
        </div>
        <button className="button button-ghost" type="button" onClick={onClose}>
          <X aria-hidden="true" />
          {labels.close}
        </button>
      </div>
      {loading && <p className="alert-delivery-loading" role="status">{labels.loading}</p>}
      {current?.phase === "error" && (
        <div className="alert-delivery-load-error">
          <p role="alert">{labels[current.reason]}</p>
          <button className="button button-secondary" type="button" onClick={() => setRetry((value) => value + 1)}>
            <RefreshCw aria-hidden="true" />
            {labels.retry}
          </button>
        </div>
      )}
      {details && (
        <>
          <AlertDeliveryBadge summary={details} />
          {(details.mode === "legacy_hold" || details.legacy.total > 0) && (
            <div className="alert-delivery-legacy" role="note">
              <strong>{labels.legacyTitle}</strong>
              <p>{labels.legacyDescription}</p>
              <p>{labels.legacyCount(formatNumber(details.legacy.total), formatNumber(details.legacy.attempts_total))}</p>
            </div>
          )}
          <p className="alert-delivery-retry-note">{labels.retryCondition}</p>
          <RecipientDeliveryStatus summary={details} />
        </>
      )}
    </section>
  );
}
