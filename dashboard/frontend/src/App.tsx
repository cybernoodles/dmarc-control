import {
  Activity,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  EyeOff,
  FileSearch,
  Globe2,
  Info,
  LayoutDashboard,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  AlertStatus,
  DomainItem,
  Forensics,
  Host,
  Overview,
  TrustStatus,
  api,
} from "./api";
import { TrendChart } from "./TrendChart";

type View = "overview" | "hosts" | "alerts" | "forensics";

const numberFormat = new Intl.NumberFormat("de-CH");
const percentFormat = new Intl.NumberFormat("de-CH", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const dateFormat = new Intl.DateTimeFormat("de-CH", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});
const dateTimeFormat = new Intl.DateTimeFormat("de-CH", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatNumber(value: number | null | undefined) {
  return numberFormat.format(value ?? 0);
}

function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return "–";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return (withTime ? dateTimeFormat : dateFormat).format(parsed);
}

function reportAge(value: string | null | undefined) {
  if (!value) return "Keine Reports";
  const days = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000),
  );
  if (days === 0) return "Heute";
  if (days === 1) return "Vor einem Tag";
  return `Vor ${days} Tagen`;
}

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function StatusPill({
  tone,
  children,
}: {
  tone: "critical" | "warning" | "success" | "info" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status-pill status-${tone}`}>{children}</span>;
}

function LoadingState({ label = "Daten werden geladen" }: { label?: string }) {
  return (
    <div className="state-box" role="status">
      <RefreshCw className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="state-box state-empty">
      <CheckCircle2 aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}

function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="state-box state-error" role="alert">
      <CircleAlert aria-hidden="true" />
      <div>
        <strong>Daten konnten nicht geladen werden</strong>
        <p>{message}</p>
      </div>
      <button className="button button-secondary" type="button" onClick={retry}>
        Erneut versuchen
      </button>
    </div>
  );
}

function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

function AlignmentBar({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: "success" | "danger" | "info" | "warning";
}) {
  const percentage = total ? Math.min(100, (value / total) * 100) : 0;
  return (
    <div className="alignment-row">
      <div>
        <span>{label}</span>
        <strong>
          {formatNumber(value)} / {formatNumber(total)}
        </strong>
      </div>
      <div
        className="bar-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={value}
      >
        <span
          className={`bar-fill bar-${tone}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function TopList({
  items,
  empty,
}: {
  items: Array<{ name: string; value: number; meta?: string }>;
  empty: string;
}) {
  const maximum = Math.max(...items.map((item) => item.value), 1);
  if (!items.length) {
    return <p className="muted compact-empty">{empty}</p>;
  }
  return (
    <div className="top-list">
      {items.map((item) => (
        <div className="top-list-item" key={`${item.name}-${item.meta ?? ""}`}>
          <div>
            <span className="truncate">{item.name}</span>
            <strong>{formatNumber(item.value)}</strong>
          </div>
          <div className="mini-track" aria-hidden="true">
            <span style={{ width: `${(item.value / maximum) * 100}%` }} />
          </div>
          {item.meta && <small>{item.meta}</small>}
        </div>
      ))}
    </div>
  );
}

export function App() {
  const [view, setView] = useState<View>("overview");
  const [domains, setDomains] = useState<DomainItem[]>([]);
  const [domain, setDomain] = useState("*");
  const [days, setDays] = useState(30);
  const [domainError, setDomainError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadDomains = useCallback(() => {
    setDomainError("");
    api.domains().then(setDomains).catch((error: Error) => setDomainError(error.message));
  }, []);

  useEffect(() => {
    loadDomains();
  }, [loadDomains, refreshKey]);

  const scopeLabel = `${domain === "*" ? "Alle Domains" : domain} · ${days} Tage`;

  const navigation: Array<{
    id: View;
    label: string;
    icon: typeof LayoutDashboard;
  }> = [
    { id: "overview", label: "Übersicht", icon: LayoutDashboard },
    { id: "hosts", label: "Sending Hosts", icon: Server },
    { id: "alerts", label: "Warnungen", icon: Bell },
    { id: "forensics", label: "Forensik", icon: FileSearch },
  ];

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">
            <ShieldCheck aria-hidden="true" />
          </span>
          <div>
            <strong>DMARC Control</strong>
            <span>Mail authentication operations</span>
          </div>
        </div>
        <div className="health-label">
          <span className="health-dot" />
          Live aus OpenSearch
        </div>
      </header>

      <nav className="main-nav" aria-label="Dashboard-Bereiche">
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              className={classNames("nav-button", view === item.id && "active")}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <Icon aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="scope-bar">
        <div className="filters">
          <label>
            <span>Domain</span>
            <select value={domain} onChange={(event) => setDomain(event.target.value)}>
              <option value="*">Alle Domains</option>
              {domains.map((item) => (
                <option value={item.domain} key={item.domain}>
                  {item.domain}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Zeitraum</span>
            <select
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              <option value={7}>Letzte 7 Tage</option>
              <option value={30}>Letzte 30 Tage</option>
              <option value={90}>Letzte 90 Tage</option>
              <option value={365}>Letzte 12 Monate</option>
            </select>
          </label>
        </div>
        <div className="scope-meta">
          <span>{scopeLabel}</span>
          <button
            className="icon-button"
            type="button"
            aria-label="Daten aktualisieren"
            title="Daten aktualisieren"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            <RefreshCw aria-hidden="true" />
          </button>
        </div>
      </div>

      {domainError && (
        <div className="inline-warning">
          <TriangleAlert aria-hidden="true" />
          Domain-Liste nicht verfügbar: {domainError}
        </div>
      )}

      <main>
        {view === "overview" && (
          <OverviewView
            domain={domain}
            days={days}
            refreshKey={refreshKey}
            openAlerts={() => setView("alerts")}
            openHosts={() => setView("hosts")}
          />
        )}
        {view === "hosts" && (
          <HostsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
        {view === "alerts" && (
          <AlertsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
        {view === "forensics" && (
          <ForensicsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
      </main>

      <footer>
        <span>DMARC Control MVP</span>
        <span>OpenSearch ist ausschließlich über die kontrollierte API erreichbar.</span>
      </footer>
    </div>
  );
}

function OverviewView({
  domain,
  days,
  refreshKey,
  openAlerts,
  openHosts,
}: {
  domain: string;
  days: number;
  refreshKey: number;
  openAlerts: () => void;
  openHosts: () => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .overview(domain, days)
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return null;

  const total = data.totals.messages;
  const compensated =
    Math.max(0, data.alignment.spf_not_aligned - data.totals.dmarc_fail) +
    Math.max(0, data.alignment.dkim_not_aligned - data.totals.dmarc_fail);

  return (
    <div className="page-stack">
      {error && <ErrorState message={error} retry={load} />}
      <section className="kpi-grid" aria-label="DMARC-Kennzahlen">
        <article className="card kpi">
          <div className="kpi-label">
            <span>DMARC-Passrate</span>
            <ShieldCheck aria-hidden="true" />
          </div>
          <strong>{percentFormat.format(data.totals.pass_rate)} %</strong>
          <p>
            {formatNumber(data.totals.dmarc_pass)} von {formatNumber(total)} Nachrichten
          </p>
        </article>
        <article className="card kpi">
          <div className="kpi-label">
            <span>Nachrichten</span>
            <Activity aria-hidden="true" />
          </div>
          <strong>{formatNumber(total)}</strong>
          <p>
            Letzter Report: {formatDate(data.totals.last_report)} ·{" "}
            {reportAge(data.totals.last_report)}
          </p>
        </article>
        <article className="card kpi kpi-critical">
          <div className="kpi-label">
            <span>Kritische Quellen</span>
            <TriangleAlert aria-hidden="true" />
          </div>
          <strong>{formatNumber(data.totals.critical_sources)}</strong>
          <p>{formatNumber(data.totals.dmarc_fail)} echte DMARC-Fails</p>
        </article>
      </section>

      <div className="overview-grid">
        <section className="surface attention-panel">
          <SectionHeader
            title="Was braucht Aufmerksamkeit?"
            subtitle="Nach finalem DMARC-Ergebnis und Aktualität priorisiert"
            action={
              <button className="text-button" type="button" onClick={openAlerts}>
                Alle Warnungen <ChevronRight aria-hidden="true" />
              </button>
            }
          />
          {data.critical_sources.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Sending Host</th>
                    <th>Domain</th>
                    <th>Authentifizierung</th>
                    <th className="numeric">Nachrichten</th>
                  </tr>
                </thead>
                <tbody>
                  {data.critical_sources.slice(0, 8).map((source) => (
                    <tr key={`${source.source_ip}-${source.header_from}`}>
                      <td>
                        <StatusPill tone="critical">Kritisch</StatusPill>
                      </td>
                      <td>
                        <button className="cell-link" type="button" onClick={openHosts}>
                          <strong>{source.source_ip}</strong>
                          <small>{source.reverse_dns || "Kein PTR"}</small>
                        </button>
                      </td>
                      <td>
                        <span>{source.header_from || "–"}</span>
                        <small>{source.country || "Unbekannt"}</small>
                      </td>
                      <td>
                        <span className="auth-pair">
                          SPF {source.spf_aligned ? "aligned" : "nicht aligned"}
                        </span>
                        <small>
                          DKIM {source.dkim_aligned ? "aligned" : "nicht aligned"}
                        </small>
                      </td>
                      <td className="numeric">
                        <strong>{formatNumber(source.messages)}</strong>
                        <small>{formatDate(source.last_seen)}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="Keine echten DMARC-Fehler"
              description="Im gewählten Zeitraum sind keine Quellen mit passed_dmarc:false vorhanden."
            />
          )}
        </section>

        <section className="surface alignment-panel">
          <SectionHeader
            title="Authentifizierung"
            subtitle="Alignment gegenüber finalem DMARC-Ergebnis"
          />
          <div className="alignment-list">
            <AlignmentBar
              label="DMARC bestanden"
              value={data.alignment.dmarc_pass}
              total={total}
              tone="success"
            />
            <AlignmentBar
              label="DKIM aligned"
              value={data.alignment.dkim_aligned}
              total={total}
              tone="info"
            />
            <AlignmentBar
              label="SPF aligned"
              value={data.alignment.spf_aligned}
              total={total}
              tone="warning"
            />
            <AlignmentBar
              label="DMARC fehlgeschlagen"
              value={data.alignment.dmarc_fail}
              total={total}
              tone="danger"
            />
          </div>
          <div className="insight">
            <Info aria-hidden="true" />
            <p>
              {compensated
                ? `${formatNumber(compensated)} Alignment-Beobachtungen wurden durch den jeweils anderen Mechanismus kompensiert und sind deshalb keine kritischen DMARC-Fails.`
                : "Alignment und finales DMARC-Ergebnis sind im gewählten Zeitraum konsistent."}
            </p>
          </div>
        </section>
      </div>

      <section className="surface">
        <SectionHeader
          title="DMARC Pass/Fail im Zeitverlauf"
          subtitle={`Tageswerte für ${domain === "*" ? "alle Domains" : domain}`}
        />
        <TrendChart data={data.trend} />
      </section>

      <section>
        <SectionHeader
          title="Domains & Reports"
          subtitle="Volumen, Berichtsersteller und veröffentlichte Richtlinien"
        />
        <div className="three-column-grid">
          <article className="surface compact-surface">
            <h3>Nachrichten nach Domain</h3>
            <TopList
              items={data.domains.slice(0, 8).map((item) => ({
                name: item.name,
                value: item.messages,
              }))}
              empty="Keine Domains im Zeitraum"
            />
          </article>
          <article className="surface compact-surface">
            <h3>Reporting Organizations</h3>
            <TopList
              items={data.reporting_organisations.slice(0, 8).map((item) => ({
                name: item.name,
                value: item.messages,
              }))}
              empty="Keine Berichtsersteller im Zeitraum"
            />
          </article>
          <article className="surface compact-surface">
            <h3>Veröffentlichte DMARC-Policies</h3>
            {data.policies.length ? (
              <div className="policy-list">
                {data.policies.slice(0, 8).map((item) => (
                  <div key={item.domain}>
                    <span className="truncate">{item.domain}</span>
                    <StatusPill
                      tone={item.policy === "reject" ? "success" : "neutral"}
                    >
                      p={item.policy} · {item.percentage} %
                    </StatusPill>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted compact-empty">Keine Policies im Zeitraum</p>
            )}
          </article>
        </div>
      </section>
    </div>
  );
}

function HostsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [risk, setRisk] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Host | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .hosts(domain, days, risk)
      .then((items) => {
        setHosts(items);
        if (selected) {
          setSelected(
            items.find((item) => item.source_ip === selected.source_ip) ?? null,
          );
        }
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, risk, selected?.source_ip]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return hosts;
    return hosts.filter((host) =>
      [
        host.source_ip,
        host.reverse_dns,
        host.base_domain,
        host.service_detection.service,
        host.as_name,
        ...host.header_froms,
        ...host.envelope_froms,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [hosts, search]);

  if (loading && !hosts.length) return <LoadingState label="Sending Hosts werden geladen" />;
  if (error && !hosts.length) return <ErrorState message={error} retry={load} />;

  return (
    <div className="page-stack">
      <SectionHeader
        title="Sending Hosts"
        subtitle="Technische Quellen, erkannte Dienste und Authentifizierungsergebnis"
        action={<StatusPill tone="neutral">{filtered.length} Quellen</StatusPill>}
      />
      <div className="list-toolbar">
        <label className="search-field">
          <Search aria-hidden="true" />
          <span className="sr-only">Sending Hosts durchsuchen</span>
          <input
            type="search"
            placeholder="IP, PTR, Domain oder Dienst suchen"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="compact-select">
          <span>Risiko</span>
          <select value={risk} onChange={(event) => setRisk(event.target.value)}>
            <option value="all">Alle Ergebnisse</option>
            <option value="critical">Kritisch</option>
            <option value="warning">Hinweise</option>
            <option value="healthy">Unauffällig</option>
            <option value="spf-not-aligned">SPF nicht aligned</option>
            <option value="dkim-not-aligned">DKIM nicht aligned</option>
          </select>
        </label>
      </div>

      {error && <ErrorState message={error} retry={load} />}

      <section className="surface">
        {filtered.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Erkannter Dienst</th>
                  <th>Vertrauen</th>
                  <th>Alignment</th>
                  <th>DMARC</th>
                  <th className="numeric">Nachrichten</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((host) => (
                  <tr
                    className={selected?.source_ip === host.source_ip ? "selected-row" : ""}
                    key={host.source_ip}
                  >
                    <td>
                      <strong className="mono">{host.source_ip}</strong>
                      <small>{host.reverse_dns || "Kein PTR"}</small>
                      <small>
                        {[host.country, host.as_name].filter(Boolean).join(" · ") || "–"}
                      </small>
                    </td>
                    <td>
                      <strong>{host.service_detection.service}</strong>
                      <small>
                        Konfidenz {host.service_detection.confidence_label} ·{" "}
                        {Math.round(host.service_detection.confidence * 100)} %
                      </small>
                    </td>
                    <td>
                      <TrustPill status={host.trust_status} />
                    </td>
                    <td>
                      <span>
                        SPF{" "}
                        {host.spf_not_aligned
                          ? `${formatNumber(host.spf_not_aligned)} nicht aligned`
                          : "aligned"}
                      </span>
                      <small>
                        DKIM{" "}
                        {host.dkim_not_aligned
                          ? `${formatNumber(host.dkim_not_aligned)} nicht aligned`
                          : "aligned"}
                      </small>
                    </td>
                    <td>
                      <RiskPill host={host} />
                    </td>
                    <td className="numeric">
                      <strong>{formatNumber(host.messages)}</strong>
                      <small>{formatDate(host.last_seen)}</small>
                    </td>
                    <td className="numeric">
                      <button
                        className="button button-ghost"
                        type="button"
                        onClick={() => setSelected(host)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="Keine Sending Hosts gefunden"
            description="Passe Suche, Zeitraum oder Risikofilter an."
          />
        )}
      </section>

      {selected && (
        <HostDetail host={selected} close={() => setSelected(null)} saved={load} />
      )}
    </div>
  );
}

function RiskPill({ host }: { host: Host }) {
  if (host.risk === "critical") {
    return (
      <StatusPill tone="critical">
        Fail · {formatNumber(host.dmarc_fail)}
      </StatusPill>
    );
  }
  if (host.risk === "warning") {
    return <StatusPill tone="warning">Pass · Hinweis</StatusPill>;
  }
  return <StatusPill tone="success">Pass</StatusPill>;
}

function TrustPill({ status }: { status: TrustStatus }) {
  const values: Record<TrustStatus, { label: string; tone: "neutral" | "info" | "success" }> = {
    unconfirmed: { label: "Nicht bestätigt", tone: "neutral" },
    automatic: { label: "Automatisch erkannt", tone: "info" },
    confirmed: { label: "Bestätigt", tone: "success" },
    ignored: { label: "Ignoriert", tone: "neutral" },
  };
  const value = values[status];
  return <StatusPill tone={value.tone}>{value.label}</StatusPill>;
}

function HostDetail({
  host,
  close,
  saved,
}: {
  host: Host;
  close: () => void;
  saved: () => void;
}) {
  const [serviceName, setServiceName] = useState(host.service_detection.service);
  const [trustStatus, setTrustStatus] = useState<TrustStatus>(host.trust_status);
  const [notes, setNotes] = useState(host.override?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setServiceName(host.service_detection.service);
    setTrustStatus(host.trust_status);
    setNotes(host.override?.notes ?? "");
  }, [host]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api.updateHost(host.source_ip, {
        service_name: serviceName.trim() || null,
        trust_status: trustStatus,
        notes: notes.trim() || null,
      });
      setMessage("Zuordnung gespeichert.");
      saved();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Speichern fehlgeschlagen");
    } finally {
      setSaving(false);
    }
  };

  const evidence = [
    ...(host.service_detection.evidence ?? []),
    host.reverse_dns ? `PTR: ${host.reverse_dns}` : "PTR: nicht vorhanden",
    host.asn ? `ASN ${host.asn}: ${host.as_name ?? "Unbekannt"}` : "",
  ].filter(Boolean);

  return (
    <section className="surface host-detail" aria-live="polite">
      <div className="host-detail-head">
        <div>
          <div className="eyebrow">Host-Detail</div>
          <h2 className="mono">{host.source_ip}</h2>
          <p>{host.reverse_dns || "Kein Reverse-DNS-Name vorhanden"}</p>
        </div>
        <div className="host-detail-actions">
          <RiskPill host={host} />
          <button
            className="icon-button"
            type="button"
            onClick={close}
            aria-label="Detailansicht schließen"
          >
            <X aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="detail-grid">
        <Detail label="Header From" value={host.header_froms.join(", ") || "–"} />
        <Detail label="Envelope From" value={host.envelope_froms.join(", ") || "–"} />
        <Detail
          label="SPF-Identitäten"
          value={host.spf_domains.join(", ") || "–"}
        />
        <Detail
          label="DKIM-Domains"
          value={host.dkim_domains.join(", ") || "–"}
        />
        <Detail
          label="DKIM-Selector"
          value={host.dkim_selectors.join(", ") || "–"}
        />
        <Detail
          label="Netzwerk"
          value={[
            host.country,
            host.asn ? `AS${host.asn}` : null,
            host.as_name,
          ]
            .filter(Boolean)
            .join(" · ") || "–"}
        />
        <Detail label="Erstmals gesehen" value={formatDate(host.first_seen, true)} />
        <Detail label="Zuletzt gesehen" value={formatDate(host.last_seen, true)} />
        <Detail
          label="DMARC-Ergebnis"
          value={`${formatNumber(host.dmarc_pass)} Pass · ${formatNumber(host.dmarc_fail)} Fail`}
        />
      </div>

      <div className="evidence-block">
        <div>
          <h3>Dienst-Erkennung</h3>
          <p>
            Mehrere Signale werden kombiniert. PTR ist nur ein Indiz und niemals
            die alleinige Entscheidungsgrundlage.
          </p>
        </div>
        <div className="evidence-list">
          {evidence.map((item) => (
            <span className="evidence-chip" key={item}>
              <Check aria-hidden="true" />
              {item}
            </span>
          ))}
          {!evidence.length && <span className="muted">Keine belastbare Evidenz.</span>}
        </div>
      </div>

      <form className="classification-form" onSubmit={submit}>
        <label>
          <span>Dienst</span>
          <input
            value={serviceName}
            maxLength={120}
            onChange={(event) => setServiceName(event.target.value)}
          />
        </label>
        <label>
          <span>Vertrauensstatus</span>
          <select
            value={trustStatus}
            onChange={(event) => setTrustStatus(event.target.value as TrustStatus)}
          >
            <option value="unconfirmed">Nicht bestätigt</option>
            <option value="automatic">Automatisch erkannt</option>
            <option value="confirmed">Bestätigt</option>
            <option value="ignored">Ignoriert</option>
          </select>
        </label>
        <label className="notes-field">
          <span>Notiz</span>
          <input
            value={notes}
            maxLength={500}
            placeholder="Optionaler administrativer Kontext"
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <button className="button button-primary" type="submit" disabled={saving}>
          {saving ? <RefreshCw className="spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
          Speichern
        </button>
        {message && <span className="form-message">{message}</span>}
      </form>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AlertsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .alerts(domain, days, status)
      .then(setAlerts)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, status]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const update = async (alertId: string, nextStatus: AlertStatus) => {
    setUpdating(alertId);
    try {
      await api.updateAlert(alertId, nextStatus);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Statusänderung fehlgeschlagen");
    } finally {
      setUpdating("");
    }
  };

  if (loading && !alerts.length) return <LoadingState label="Warnungen werden bewertet" />;
  if (error && !alerts.length) return <ErrorState message={error} retry={load} />;

  const openCount = alerts.filter((item) => item.status === "open").length;
  return (
    <div className="page-stack">
      <SectionHeader
        title="Warnungszentrale"
        subtitle="Deduplizierte Ereignisse mit nachvollziehbarem Auslöser"
        action={
          <StatusPill tone={openCount ? "critical" : "success"}>
            {openCount} offen
          </StatusPill>
        }
      />
      <div className="list-toolbar align-end">
        <label className="compact-select">
          <span>Status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">Alle Status</option>
            <option value="open">Offen</option>
            <option value="acknowledged">Bestätigt</option>
            <option value="resolved">Behoben</option>
            <option value="ignored">Ignoriert</option>
          </select>
        </label>
      </div>
      {error && <ErrorState message={error} retry={load} />}
      <section className="surface">
        {alerts.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Priorität</th>
                  <th>Warnung</th>
                  <th>Auslöser</th>
                  <th>Reportzeit</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td><PriorityPill priority={alert.priority} /></td>
                    <td>
                      <strong>{alert.title}</strong>
                      <small>
                        {[alert.source_ip, alert.domain].filter(Boolean).join(" · ")}
                      </small>
                    </td>
                    <td>
                      <span>{alert.trigger}</span>
                      <small>{formatNumber(alert.messages)} Nachrichten</small>
                    </td>
                    <td>
                      <span>{formatDate(alert.report_time)}</span>
                      <small>{reportAge(alert.report_time)}</small>
                    </td>
                    <td><AlertStatusPill status={alert.status} /></td>
                    <td className="numeric">
                      <div className="row-actions">
                        {alert.status === "open" && (
                          <button
                            className="button button-secondary"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "acknowledged")}
                          >
                            Bestätigen
                          </button>
                        )}
                        {alert.status !== "resolved" && (
                          <button
                            className="button button-ghost"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "resolved")}
                          >
                            Behoben
                          </button>
                        )}
                        {alert.status !== "ignored" && (
                          <button
                            className="button button-ghost"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "ignored")}
                          >
                            Ignorieren
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="Keine Warnungen in dieser Ansicht"
            description="Für Domain, Zeitraum und Status existieren keine passenden Ereignisse."
          />
        )}
      </section>

      <section className="alert-logic-grid">
        <article className="logic-item">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>Sofort kritisch</strong>
            <span>Neuer oder nicht autorisierter Host mit echtem DMARC-Fail.</span>
          </div>
        </article>
        <article className="logic-item">
          <Info aria-hidden="true" />
          <div>
            <strong>Konfigurationshinweis</strong>
            <span>Ein Mechanismus ist nicht aligned, DMARC besteht aber weiterhin.</span>
          </div>
        </article>
        <article className="logic-item">
          <Clock3 aria-hidden="true" />
          <div>
            <strong>Report-Verzögerung</strong>
            <span>Ausbleibende Reports werden erst nach der üblichen Verzögerung gewarnt.</span>
          </div>
        </article>
      </section>
    </div>
  );
}

function PriorityPill({ priority }: { priority: Alert["priority"] }) {
  if (priority === "critical") return <StatusPill tone="critical">Kritisch</StatusPill>;
  if (priority === "warning") return <StatusPill tone="warning">Warnung</StatusPill>;
  return <StatusPill tone="info">Hinweis</StatusPill>;
}

function AlertStatusPill({ status }: { status: AlertStatus }) {
  const values: Record<AlertStatus, { label: string; tone: "critical" | "info" | "success" | "neutral" }> = {
    open: { label: "Offen", tone: "critical" },
    acknowledged: { label: "Bestätigt", tone: "info" },
    resolved: { label: "Behoben", tone: "success" },
    ignored: { label: "Ignoriert", tone: "neutral" },
  };
  const value = values[status];
  return <StatusPill tone={value.tone}>{value.label}</StatusPill>;
}

function ForensicsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const [data, setData] = useState<Forensics | null>(null);
  const [failureType, setFailureType] = useState("*");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .forensics(domain, days, failureType)
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, failureType]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading && !data) return <LoadingState label="Forensik-Metadaten werden geladen" />;
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return null;

  const failureOptions = data.failure_types.map((item) => item.name);
  return (
    <div className="page-stack">
      <SectionHeader
        title="DMARC Forensik"
        subtitle="Minimierte Betriebsmetadaten aus RUF-/Failure-Reports"
        action={
          <label className="compact-select">
            <span>Fehlertyp</span>
            <select
              value={failureType}
              onChange={(event) => setFailureType(event.target.value)}
            >
              <option value="*">Alle Fehlertypen</option>
              {failureOptions.map((item) => (
                <option value={item} key={item}>{item}</option>
              ))}
            </select>
          </label>
        }
      />
      <div className="privacy-banner">
        <EyeOff aria-hidden="true" />
        <div>
          <strong>Privacy by design</strong>
          <span>
            Rohinhalt, Empfänger, Absender, Betreff und Header werden von dieser API
            nicht geladen.
          </span>
        </div>
      </div>
      {error && <ErrorState message={error} retry={load} />}
      <section className="kpi-grid">
        <article className="card kpi">
          <div className="kpi-label"><span>Forensic Samples</span><Database aria-hidden="true" /></div>
          <strong>{formatNumber(data.samples)}</strong>
          <p>Aggregierte Failure-Metadaten</p>
        </article>
        <article className="card kpi">
          <div className="kpi-label"><span>Datenaktualität</span><Clock3 aria-hidden="true" /></div>
          <strong className="date-value">{formatDate(data.last_report)}</strong>
          <p>{reportAge(data.last_report)}</p>
        </article>
        <article className="card kpi">
          <div className="kpi-label"><span>Source-IPs</span><Globe2 aria-hidden="true" /></div>
          <strong>{formatNumber(data.sources.length)}</strong>
          <p>{formatNumber(data.countries.length)} Länder/Zuordnungen</p>
        </article>
      </section>

      {!data.samples ? (
        <EmptyState
          title="Keine Forensik-Daten im Zeitraum"
          description="RUF-Daten sind möglicherweise deaktiviert oder es sind keine passenden Failure-Reports eingegangen."
        />
      ) : (
        <>
          <div className="three-column-grid">
            <article className="surface compact-surface">
              <h3>Authentication Failure Types</h3>
              <TopList
                items={data.failure_types.map((item) => ({
                  name: item.name,
                  value: item.samples,
                }))}
                empty="Keine Fehlertypen"
              />
            </article>
            <article className="surface compact-surface">
              <h3>Betroffene Domains</h3>
              <TopList
                items={data.domains.map((item) => ({
                  name: item.name,
                  value: item.samples,
                }))}
                empty="Keine Domains"
              />
            </article>
            <article className="surface compact-surface">
              <h3>Quellen nach Land</h3>
              <TopList
                items={data.countries.map((item) => ({
                  name: item.name,
                  value: item.samples,
                }))}
                empty="Keine Länderinformationen"
              />
            </article>
          </div>

          <section className="surface">
            <SectionHeader
              title="Top Forensic Source IPs"
              subtitle="IP, PTR, Basisdomain, Land und letzte Beobachtung"
            />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Source-IP</th>
                    <th>PTR / Basisdomain</th>
                    <th>Land</th>
                    <th>Zuletzt gesehen</th>
                    <th className="numeric">Samples</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((source) => (
                    <tr key={source.source_ip}>
                      <td><strong className="mono">{source.source_ip}</strong></td>
                      <td>
                        <span>{source.reverse_dns || "–"}</span>
                        <small>{source.base_domain || "–"}</small>
                      </td>
                      <td>{source.country}</td>
                      <td>{formatDate(source.last_seen, true)}</td>
                      <td className="numeric"><strong>{formatNumber(source.samples)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="surface">
            <SectionHeader
              title="Bereinigte Failure-Evidenz"
              subtitle="Nur Authentifizierungs- und Delivery-Ergebnis; keine Nachrichteninhalte"
            />
            <div className="evidence-table">
              {data.evidence.map((item, index) => (
                <article key={`${item.authentication_result}-${index}`}>
                  <code>{item.authentication_result}</code>
                  <div>
                    {item.failure_types.map((failure) => (
                      <StatusPill tone="critical" key={failure}>{failure}</StatusPill>
                    ))}
                    {item.delivery_results.map((delivery) => (
                      <StatusPill tone="neutral" key={delivery}>{delivery}</StatusPill>
                    ))}
                    <span>{formatNumber(item.samples)} Samples</span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
