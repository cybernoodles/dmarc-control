import { useEffect, useState } from "react";
import { api } from "./api";
import { AlertEvaluationState, AlertEvaluationStatus } from "./AlertEvaluationStatus";
import { useI18n } from "./i18n";

export function AlertEvaluationMonitor({ refreshKey }: { refreshKey?: string | number }) {
  const { language } = useI18n();
  const [state, setState] = useState<AlertEvaluationState | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let controller: AbortController | undefined;
    const load = () => {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      api.evaluationStatus(request.signal)
        .then((next) => {
          if (!request.signal.aborted) { setState(next); setFailed(false); }
        })
        .catch(() => { if (!request.signal.aborted) setFailed(true); });
    };
    const refreshVisible = () => { if (!document.hidden) load(); };
    load();
    const timer = window.setInterval(refreshVisible, 30_000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [refreshKey, retry]);
  return (
    <div className="evaluation-monitor">
      {failed && (
        <div className="inline-warning" role="status">
          <span>{language === "de"
            ? "Der Status der automatischen Auswertung konnte nicht aktualisiert werden. Angezeigte Daten können veraltet sein."
            : "Automatic evaluation status could not be refreshed. Displayed data may be outdated."}</span>
          <button className="button button-secondary" type="button" onClick={() => setRetry((value) => value + 1)}>
            {language === "de" ? "Erneut versuchen" : "Try again"}
          </button>
        </div>
      )}
      {state ? <AlertEvaluationStatus state={state} /> : !failed && (
        <p role="status">{language === "de" ? "Status der automatischen Auswertung wird geladen …" : "Loading automatic evaluation status …"}</p>
      )}
    </div>
  );
}
