import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Globe2, LockKeyhole, RefreshCw } from "lucide-react";
import {
  api, ApiError, type AuthStatus, type DomainMonitoringItem,
  type DomainMonitoringPatch,
} from "./api";
import { useI18n } from "./i18n";
import { DOMAIN_LIST_THRESHOLD, domainSearchIndex, domainSearchTerms,
  domainPage, initialDomainDraft, reconcileDomainDraft, storedDomainDraft, type DomainRowDraft } from "./domainMonitoringView";
type RowAction = "grace" | "retire" | "reactivate";

const errorSources: Record<string, string> = {
  "Invalid domain name": "Ungültiger Domainname.",
  "Domain is already monitored": "Diese Domain wird bereits überwacht.",
  "Grace period must be between 1 and 365 days": "Die Wartefrist muss zwischen 1 und 365 Tagen liegen.",
  "Observed domains cannot be set to expected": "Für diese Domain wurden bereits Reports beobachtet.",
  "Domains without reports must be set to expected": "Domains ohne Reports müssen als erwartet geführt werden.",
  "Invalid monitoring state": "Ungültiger Überwachungsstatus.",
  "Admin login required": "Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.",
};

function graceValue(value: string): number | null {
  if (!/^\d{1,3}$/.test(value.trim())) return null;
  const number = Number(value);
  return number >= 1 && number <= 365 ? number : null;
}

export function DomainMonitoringSettings({ active, auth, setAuth, onChanged, onAdminLogin }: {
  active: boolean;
  auth: AuthStatus;
  setAuth: (auth: AuthStatus) => void;
  onChanged: () => void;
  onAdminLogin: () => void;
}) {
  const { t } = useI18n();
  return <section className="surface domain-monitoring-settings" aria-labelledby="domain-monitoring-heading">
    <div className="settings-title">
      <span className="settings-icon"><Globe2 aria-hidden="true" /></span>
      <div><h2 id="domain-monitoring-heading">{t("Domain-Überwachung")}</h2>
        <p>{t("Erwartete Domains und Warnungen bei ausbleibenden Reports verwalten.")}</p></div>
    </div>
    {auth.authenticated ? <DomainRegistry active={active} onChanged={onChanged}
      onAdminExpired={() => setAuth({ ...auth, authenticated: false })} /> :
      <div className="connection-locked"><LockKeyhole aria-hidden="true" /><div>
        <strong>{t("Admin-Anmeldung erforderlich")}</strong>
        <p>{t("Melde dich als Admin an, um die Domain-Überwachung zu verwalten.")}</p>
        <button className="button button-secondary" type="button" onClick={onAdminLogin}>{t("Zur Administration")}</button>
      </div></div>}
  </section>;
}

function DomainRegistry({ active, onChanged, onAdminExpired }: {
  active: boolean;
  onChanged: () => void;
  onAdminExpired: () => void;
}) {
  const { t, formatNumber } = useI18n();
  const [items, setItems] = useState<DomainMonitoringItem[] | null>(null);
  const [defaultGrace, setDefaultGrace] = useState(3);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [pendingCount, setPendingCount] = useState(0);
  const [addDomain, setAddDomain] = useState("");
  const [addGrace, setAddGrace] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [addMessage, setAddMessage] = useState("");
  const [search, setSearch] = useState("");
  const [requestedPage, setRequestedPage] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, DomainRowDraft>>({});
  const draftRef = useRef(drafts);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const pageFocusVersion = useRef(0);
  const indexed = useMemo(() => domainSearchIndex(items ?? []), [items]);
  const paginated = (items?.length ?? 0) > DOMAIN_LIST_THRESHOLD;
  const terms = domainSearchTerms(search);
  const matching = paginated && terms.length
    ? indexed.filter(({ text }) => terms.some((term) => text.includes(term))).map(({ item }) => item)
    : items ?? [];
  const paging = domainPage(matching.length, requestedPage);
  const visible = paginated ? matching.slice(paging.start, paging.end) : matching;
  const setRowDraft = (item: DomainMonitoringItem, change: (draft: DomainRowDraft) => DomainRowDraft) => {
    if (!mounted.current) return;
    const next = { ...draftRef.current, [item.domain]: change(storedDomainDraft(draftRef.current, item.domain) ?? initialDomainDraft(item.grace_days)) };
    draftRef.current = next;
    setDrafts(next);
  };
  const changePage = (page: number) => {
    const version = ++pageFocusVersion.current;
    const initiator = document.activeElement;
    setRequestedPage(page);
    window.requestAnimationFrame(() => {
      if (version !== pageFocusVersion.current ||
        (document.activeElement !== document.body && document.activeElement !== initiator)) return;
      resultsHeading.current?.focus({ preventScroll: true });
      resultsHeading.current?.scrollIntoView({ block: "start" });
    });
  };
  const mounted = useRef(true);
  const requested = useRef(false);
  const requestVersion = useRef(0);
  const loadController = useRef<AbortController | null>(null);
  const pending = useRef(new Set<string>());
  const callbacks = useRef({ onChanged, onAdminExpired });
  callbacks.current = { onChanged, onAdminExpired };

  const publicError = (error: unknown) => error instanceof Error
    ? t(errorSources[error.message] ?? error.message) : t("Aktualisierung fehlgeschlagen.");
  const handleAdminExpiry = (error: unknown) => {
    if (mounted.current && error instanceof ApiError && error.message === "Admin login required") {
      callbacks.current.onAdminExpired();
    }
  };

  const load = async () => {
    if (pending.current.size) return;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    const version = ++requestVersion.current;
    const revisions = Object.fromEntries(Object.entries(draftRef.current).map(([domain, draft]) => [domain, draft.revision]));
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.domainMonitoring(controller.signal);
      if (!mounted.current || controller.signal.aborted || version !== requestVersion.current) return;
      const nextDrafts = { ...draftRef.current };
      for (const item of data.domains) {
        const draft = storedDomainDraft(nextDrafts, item.domain);
        if (draft) nextDrafts[item.domain] = reconcileDomainDraft(draft, item.grace_days,
          Object.hasOwn(revisions, item.domain) ? revisions[item.domain] : undefined);
      }
      draftRef.current = nextDrafts;
      setDrafts(nextDrafts);
      setItems(data.domains);
      setDefaultGrace(data.default_grace_days);
      setAddGrace((current) => current ?? String(data.default_grace_days));
    } catch (error) {
      if (!mounted.current || controller.signal.aborted || version !== requestVersion.current) return;
      handleAdminExpiry(error);
      setLoadError(publicError(error));
    } finally {
      if (mounted.current && !controller.signal.aborted && version === requestVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requested.current = false;
      loadController.current?.abort();
      requestVersion.current += 1;
    };
  }, []);
  useEffect(() => {
    if (active && !requested.current) {
      requested.current = true;
      void load();
    }
  }, [active]);

  const mutate = async (key: string, operation: () => Promise<DomainMonitoringItem>) => {
    if (pending.current.has(key)) return null;
    pending.current.add(key);
    setPendingCount(pending.current.size);
    loadController.current?.abort();
    requestVersion.current += 1;
    setLoading(false);
    try {
      const saved = await operation();
      if (!mounted.current) return null;
      setItems((current) => [...(current ?? []).filter((item) => item.domain !== saved.domain), saved]
        .sort((left, right) => left.domain.localeCompare(right.domain)));
      callbacks.current.onChanged();
      return saved;
    } catch (error) {
      handleAdminExpiry(error);
      throw error;
    } finally {
      pending.current.delete(key);
      if (mounted.current) setPendingCount(pending.current.size);
    }
  };

  const add = async (event: FormEvent) => {
    event.preventDefault();
    const submittedDomain = addDomain;
    const days = graceValue(addGrace ?? String(defaultGrace));
    if (!submittedDomain.trim() || days === null || adding) return;
    setAdding(true); setAddError(""); setAddMessage("");
    try {
      const saved = await mutate("__add__", () => api.addMonitoredDomain(submittedDomain.trim(), days));
      if (saved && mounted.current) {
        setAddDomain((current) => current === submittedDomain ? "" : current);
        setAddMessage(t("{domain} wird überwacht. Die erste Wartefrist beginnt jetzt.", { domain: saved.domain }));
      }
    } catch (error) {
      if (mounted.current) setAddError(publicError(error));
    } finally { if (mounted.current) setAdding(false); }
  };

  const runRow = async (item: DomainMonitoringItem, action: RowAction) => {
    const current = storedDomainDraft(draftRef.current, item.domain) ?? initialDomainDraft(item.grace_days);
    const parsedGrace = graceValue(current.grace);
    const submittedRevision = current.revision;
    const busy = current.busy;
    if (busy || loading || (action !== "retire" && parsedGrace === null)) return;
    if (action === "grace" && parsedGrace === item.grace_days) return;
    const patch: DomainMonitoringPatch = { domain: item.domain };
    if (action === "grace") patch.grace_days = parsedGrace!;
    if (action === "retire") patch.state = "retired";
    if (action === "reactivate") {
      patch.state = item.observed ? "active" : "expected";
      patch.grace_days = parsedGrace!;
    }
    setRowDraft(item, (draft) => ({ ...draft, busy: true, error: "", message: "" }));
    try {
      const saved = await mutate(item.domain, () => api.updateMonitoredDomain(patch));
      if (saved) setRowDraft(item, (draft) => ({ ...reconcileDomainDraft(draft, saved.grace_days, submittedRevision, action !== "retire"), message: action === "grace"
        ? t("Wartefrist gespeichert. Der Beginn bleibt unverändert.")
        : action === "retire" ? t("Domain stillgelegt. Reports und Warnungen bleiben erhalten.")
          : t("Domain reaktiviert. Eine neue Wartefrist hat begonnen.") }));
    } catch (reason) {
      setRowDraft(item, (draft) => ({ ...draft, error: publicError(reason) }));
    } finally { setRowDraft(item, (draft) => ({ ...draft, busy: false })); }
  };

  return <div className="domain-registry">
    <p className="domain-monitoring-note">{t("Beobachtete Domains werden automatisch aufgenommen. Erwartete Domains kannst du schon vor dem ersten Report hinzufügen.")}</p>
    <form className="domain-add-form" onSubmit={add} aria-busy={adding}>
      <h3>{t("Erwartete Domain hinzufügen")}</h3>
      <div className="domain-add-fields">
        <label><span>{t("Domain")}</span><input type="text" required maxLength={253}
          autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="example.org"
          value={addDomain} onChange={(event) => setAddDomain(event.target.value)} disabled={items === null} /></label>
        <label><span>{t("Wartefrist (Tage)")}</span><input type="number" min={1} max={365} step={1} required
          value={addGrace ?? defaultGrace} onChange={(event) => setAddGrace(event.target.value)} disabled={items === null}
          aria-describedby="domain-add-grace-help" /></label>
        <button className="button button-primary" type="submit"
          disabled={items === null || adding || !addDomain.trim() || graceValue(addGrace ?? String(defaultGrace)) === null}>
          {adding ? t("Wird hinzugefügt …") : t("Domain hinzufügen")}</button>
      </div>
      <p id="domain-add-grace-help" className="domain-monitoring-note">{t("1–365 Tage. Standard: {days} Tage. Ohne ersten Report entsteht nach Ablauf eine Warnung.", { days: defaultGrace })}</p>
      {addError && <p role="alert" className="inline-message critical">{addError}</p>}
      {addMessage && <p role="status" className="inline-message success">{addMessage}</p>}
    </form>
    <div className="domain-registry-heading"><h3 ref={resultsHeading} tabIndex={-1}>{t("Registrierte Domains")}{items !== null && ` (${formatNumber(items.length)})`}</h3>
      <button type="button" className="button button-secondary" onClick={() => void load()} disabled={loading || pendingCount > 0}>
        <RefreshCw aria-hidden="true" />{t("Liste aktualisieren")}</button></div>
    <p className="domain-monitoring-note">{t("Alle registrierten Domains, unabhängig von der Domain-Auswahl.")}</p>
    {loading && <p role="status" className="domain-monitoring-note">{t("Domain-Überwachung wird geladen …")}</p>}
    {loadError && <p role="alert" className="inline-message critical">{loadError}</p>}
    {items?.length === 0 && <p className="domain-monitoring-note">{t("Noch keine Domains registriert. Füge eine erwartete Domain hinzu oder warte auf den ersten Report.")}</p>}
    {paginated && <div className="domain-inventory-controls">
      <label className="domain-inventory-search"><span>{t("Registrierte Domains durchsuchen")}</span>
        <input type="search" value={search} onChange={(event) => { pageFocusVersion.current += 1; setSearch(event.target.value); setRequestedPage(0); }}
          placeholder={t("Domainname oder alternative Schreibweise")} aria-describedby="domain-search-count" />
      </label>
      <p id="domain-search-count" className="domain-monitoring-note" role="status">
        {t("{matches} Treffer von {total} registrierten Domains", { matches: formatNumber(matching.length), total: formatNumber(items?.length ?? 0) })}
      </p>
      <nav className="list-pagination domain-inventory-pagination" aria-label={t("Domain-Seiten")}>
        <span aria-live="polite">{matching.length > 0 ? t("{start}–{end} von {total} Treffern", {
          start: formatNumber(paging.start + 1), end: formatNumber(paging.end), total: formatNumber(matching.length),
        }) : t("Keine passenden Domains")}</span>
        <div className="row-actions">
          <button className="button button-secondary" type="button" disabled={paging.page === 0} onClick={() => changePage(paging.page - 1)}>{t("Vorherige Seite")}</button>
          <button className="button button-secondary" type="button" disabled={paging.end >= matching.length} onClick={() => changePage(paging.page + 1)}>{t("Nächste Seite")}</button>
        </div>
      </nav>
    </div>}
    <div className="domain-monitoring-list">
      {visible.map((item) => <DomainRow key={item.domain} item={item} loading={loading} draft={storedDomainDraft(drafts, item.domain)}
        onEdit={(grace) => setRowDraft(item, (draft) => ({ ...draft, grace, revision: draft.revision + 1 }))}
        onAction={(action) => void runRow(item, action)} />)}
    </div>
    <p className="domain-monitoring-note">{t("Stilllegen beendet Warnungen wegen ausbleibender Reports. Echte DMARC-Fehler werden weiterhin ausgewertet. Vorhandene Reports und Warnungen bleiben erhalten.")}</p>
  </div>;
}

function DomainRow({ item, loading, draft, onEdit, onAction }: {
  item: DomainMonitoringItem;
  loading: boolean;
  draft?: DomainRowDraft;
  onEdit: (value: string) => void;
  onAction: (action: RowAction) => void;
}) {
  const { t, formatDate } = useI18n();
  const { grace, busy, error, message } = draft ?? initialDomainDraft(item.grace_days);
  const parsedGrace = graceValue(grace);
  const retired = item.state === "retired";
  return <article className="domain-monitoring-card" aria-label={item.domain} aria-busy={busy}>
    <div className="domain-monitoring-card-heading"><h4>{item.query_domain || item.domain}</h4>
      <span className={`status-pill status-${retired ? "neutral" : item.state === "expected" ? "info" : "success"}`}>
        {retired ? t("Stillgelegt") : item.state === "expected" ? t("Erwartet · noch kein Report") : t("Aktiv · Reports beobachtet")}
      </span></div>
    {item.query_domain !== item.domain && <p className="domain-monitoring-note">{item.domain}</p>}
    <dl className="domain-monitoring-dates">
      <div><dt>{t("Letzter Report")}</dt><dd>{item.last_report ? formatDate(item.last_report, true) : t("Noch kein Report")}</dd></div>
      <div><dt>{t("Überwachungsbeginn")}</dt><dd>{formatDate(item.monitoring_started_at, true)}</dd></div>
      <div><dt>{t("Fristende")}</dt><dd>{retired ? t("Keine Frist aktiv") : formatDate(item.deadline, true)}</dd></div>
    </dl>
    <form className="domain-monitoring-row-form" onSubmit={(event) => { event.preventDefault(); onAction(retired ? "reactivate" : "grace"); }}>
      <label><span>{t("Wartefrist (Tage)")}</span><input type="number" required min={1} max={365} step={1}
        value={grace} onChange={(event) => onEdit(event.target.value)} aria-label={t("Wartefrist für {domain}", { domain: item.domain })} /></label>
      <div className="domain-monitoring-row-actions">
        <button className="button button-secondary" type="submit" disabled={busy || loading || parsedGrace === null || (!retired && parsedGrace === item.grace_days)}>
          {retired ? t("Mit neuer Frist reaktivieren") : t("Frist speichern")}</button>
        {!retired && <button className="button button-ghost" type="button" onClick={() => onAction("retire")} disabled={busy || loading}>{t("Stilllegen")}</button>}
      </div>
    </form>
    <p className="domain-monitoring-note">{retired
      ? t("Reaktivieren startet ab jetzt eine neue Wartefrist mit der eingetragenen Tageszahl.")
      : t("Eine Friständerung verschiebt nur das Fristende. Der Beginn bleibt erhalten; eine kürzere Frist kann sofort eine Warnung auslösen.")}</p>
    {busy && <p role="status" className="domain-monitoring-note">{t("Änderung wird gespeichert …")}</p>}
    {error && <p role="alert" className="inline-message critical">{error}</p>}
    {message && <p role="status" className="inline-message success">{message}</p>}
  </article>;
}
