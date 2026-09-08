import type { Host } from "./api";
import { classificationMode } from "./HostClassificationForm";
import { useI18n } from "./i18n";

const origins: Record<string, string> = {
  source_reverse_dns: "Reverse DNS (PTR)",
  source_base_domain: "PTR-Basisdomain",
  source_as_name: "ASN-Name",
  source_as_domain: "ASN-Domain",
  source_name: "Quellenname",
  spf_domains: "SPF-Domain (ohne Einzelergebnis)",
  dkim_domains: "DKIM-Domain (ohne Einzelergebnis)",
  "spf_results.domain": "SPF-Prüfung",
  "dkim_results.domain": "DKIM-Prüfung",
  source_auth_conflict: "Mehrdeutige Anbieter-Herkunft",
};
const groups: Record<string, string> = {
  network_identity: "Netzwerkidentität",
  asn: "Autonomes System (ASN)",
  spf: "SPF",
  dkim: "DKIM",
  auth_conflict: "Widersprüchliche Anbieterhinweise",
};
const authLabels: Record<string, string> = {
  pass: "Bestanden", fail: "Nicht bestanden", softfail: "Softfail",
  neutral: "Neutral", none: "Keine Prüfung", temperror: "Vorübergehender Prüffehler",
  permerror: "Dauerhafter Prüffehler", unknown: "Ergebnis unbekannt",
};

export function HostServiceDetection({ host }: { host: Host }) {
  const { t, translateBackendLabel } = useI18n();
  const mode = classificationMode(host);
  const automatic = host.service_detection.automatic_detection
    ?? (mode === "automatic" ? host.service_detection : null);
  const details = automatic && "evidence_details" in automatic ? automatic.evidence_details ?? [] : [];
  const modeLabel = mode === "automatic" ? "Automatisch ermittelt" : mode === "manual" ? "Manuell" : "Übernommen";
  return (
    <div className="host-detection">
      <div className="host-effective-service">
        <div>
          <h3>{t("Verwendete Dienstzuordnung")}</h3>
          <strong>{mode === "automatic" ? translateBackendLabel(host.service_detection.service) : host.service_detection.service}</strong>
        </div>
        <span className={`status-pill status-${mode === "automatic" ? "info" : "neutral"}`}>{t(modeLabel)}</span>
      </div>
      <section className="host-automatic-detection" aria-label={t(mode === "automatic" ? "Automatische Erkennung" : "Automatische Alternative")}>
        <h4>{t(mode === "automatic" ? "Automatische Erkennung" : "Automatische Alternative")}</h4>
        {automatic ? <>
          <div className="host-automatic-summary">
            <strong>{translateBackendLabel(automatic.service)}</strong>
            <span>{t("Konfidenz")} {translateBackendLabel(automatic.confidence_label)}
              {automatic.confidence != null && ` · ${Math.round(automatic.confidence * 100)} %`}</span>
          </div>
          <p>{t("Die Konfidenz gehört ausschließlich zur automatischen Erkennung. Sie ist eine regelbasierte Einschätzung, keine statistisch gemessene Wahrscheinlichkeit. Mehrere Angaben aus derselben Quelle gelten nicht als unabhängige Bestätigung.")}</p>
          <div className="evidence-list">
            {(automatic.evidence ?? []).map((item) => <span className="evidence-chip" key={item}>{translateBackendLabel(item)}</span>)}
            {!automatic.evidence?.length && <span className="muted">{t("Keine belastbare Evidenz.")}</span>}
          </div>
          {details.length > 0 && <details className="host-evidence-details">
            <summary>{t("Herkunft der Erkennungssignale")}</summary>
            <p>{t("Ein SPF- oder DKIM-Domainname allein bestätigt keine erfolgreiche Authentifizierung. Ein Prüfergebnis wird nur angezeigt, wenn es im Report vorliegt.")}</p>
            <ul>
              {details.map((item, index) => <li key={`${item.origin}:${item.value}:${item.rule_id}:${index}`}>
                <strong>{t(origins[item.origin] ?? item.origin)}: {item.value}</strong>
                {item.origin === "source_auth_conflict" && <span>{t("Bestandene Prüfungen weisen auf verschiedene Anbieter hin. Das ist keine zusätzliche Bestätigung.")}</span>}
                {item.auth_result && <span>{t("Prüfergebnis")}: {t(authLabels[item.auth_result] ?? item.auth_result)}</span>}
                <span>{t("Signalgruppe")}: {t(groups[item.independence_group] ?? item.independence_group)}</span>
                <span>{t("Erkennungsregel")}: <code>{item.rule_id}</code></span>
              </li>)}
            </ul>
          </details>}
        </> : <p>{t("Für diesen Eintrag liegt keine getrennte automatische Erkennung vor.")}</p>}
      </section>
    </div>
  );
}
