import { FormEvent, useEffect, useRef, useState } from "react";
import { RefreshCw, Save } from "lucide-react";
import { api } from "./api";
import type { ClassificationMode, Host, HostClassification, HostClassificationPatch, TrustStatus } from "./api";
import { useI18n } from "./i18n";
import { useUnsavedChangesRegistration } from "./UnsavedChanges";

type Draft = {
  mode: ClassificationMode;
  serviceName: string;
  trustStatus: TrustStatus;
  notes: string;
};

const fields = ["mode", "serviceName", "trustStatus", "notes"] as const;

export function classificationMode(host: Host): ClassificationMode {
  return host.service_detection.classification_mode ?? host.override?.classification_mode
    ?? (host.service_detection.manual_override ? "legacy_preserved" : "automatic");
}

function hostDraft(host: Host): Draft {
  return {
    mode: classificationMode(host),
    serviceName: host.override?.manual_service_name ?? host.service_detection.manual_service_name
      ?? host.override?.service_name ?? "",
    trustStatus: host.override?.trust_status ?? "automatic",
    notes: host.override?.notes ?? "",
  };
}

function storedDraft(stored: HostClassification): Draft {
  return {
    mode: stored.classification_mode,
    serviceName: stored.manual_service_name ?? stored.service_name ?? "",
    trustStatus: stored.trust_status,
    notes: stored.notes ?? "",
  };
}

function changes(draft: Draft, baseline: Draft): HostClassificationPatch {
  const update: HostClassificationPatch = {};
  if (draft.mode !== baseline.mode && draft.mode !== "legacy_preserved") update.classification_mode = draft.mode;
  if (draft.mode === "manual" && (baseline.mode !== "manual" || draft.serviceName.trim() !== baseline.serviceName)) {
    update.manual_service_name = draft.serviceName.trim() || null;
  }
  if (draft.trustStatus !== baseline.trustStatus) update.trust_status = draft.trustStatus;
  // A mode-only automatic patch resets trust server-side. Preserve the selected
  // status for the dropdown; the dedicated restore action intentionally resets it.
  if (update.classification_mode === "automatic") update.trust_status = draft.trustStatus;
  if (draft.notes.trim() !== baseline.notes) update.notes = draft.notes.trim() || null;
  return update;
}

export function HostClassificationForm({ host, saved }: { host: Host; saved: () => void }) {
  const { t, translateBackendLabel } = useI18n();
  const initial = hostDraft(host);
  const [draft, setDraft] = useState(initial);
  const [baseline, setBaseline] = useState(initial);
  const baselineRef = useRef(initial);
  const draftRef = useRef(initial);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const editDraft = (update: (current: Draft) => Draft) => {
    const next = update(draftRef.current);
    draftRef.current = next;
    setDraft(next);
  };
  const hasDraftChanges = () => Object.keys(changes(draftRef.current, baselineRef.current)).length > 0;
  const mounted = useRef(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const dirty = Object.keys(changes(draft, baseline)).length > 0;
  const automaticName = host.service_detection.automatic_detection?.service
    ?? host.service_detection.automatic_service ?? host.service_detection.service;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const next = hostDraft(host);
    const previous = baselineRef.current;
    baselineRef.current = next;
    setBaseline(next);
    editDraft((current) => {
      const merged = { ...current };
      for (const field of fields) {
        if (current[field] === previous[field]) Object.assign(merged, { [field]: next[field] });
      }
      return merged;
    });
  }, [host]);

  const save = (update: HostClassificationPatch): Promise<boolean> => {
    if (inFlight.current) return inFlight.current;
    if (Object.keys(update).length === 0) return Promise.resolve(!hasDraftChanges());
    const submitted = { ...draftRef.current };
    const previous = baselineRef.current;
    setSaving(true);
    setMessage("");
    setFailed(false);
    const operation = (async () => {
      try {
        const stored = await api.updateHost(host.source_ip, update);
        if (!mounted.current) return false;
        const next = storedDraft(stored);
        const requested: Record<keyof Draft, boolean> = {
          mode: "classification_mode" in update,
          serviceName: "manual_service_name" in update,
          trustStatus: "trust_status" in update,
          notes: "notes" in update,
        };
        baselineRef.current = next;
        setBaseline(next);
        editDraft((current) => {
          const merged = { ...current };
          for (const field of fields) {
            if (requested[field] ? current[field] === submitted[field] : current[field] === previous[field]) {
              Object.assign(merged, { [field]: next[field] });
            }
          }
          return merged;
        });
        setMessage(t("Änderungen gespeichert."));
        saved();
        return !hasDraftChanges();
      } catch (reason) {
        if (mounted.current) {
          setFailed(true);
          setMessage(reason instanceof Error ? reason.message : t("Speichern fehlgeschlagen"));
        }
        return false;
      }
    })().finally(() => {
      if (inFlight.current === operation) inFlight.current = null;
      if (mounted.current) setSaving(false);
    });
    inFlight.current = operation;
    return operation;
  };

  const saveDraft = (): Promise<boolean> => {
    if (inFlight.current) return inFlight.current;
    const current = draftRef.current;
    if (current.mode === "manual" && !current.serviceName.trim()) {
      setFailed(true);
      setMessage(t("Bitte gib einen manuellen Dienstnamen ein."));
      return Promise.resolve(false);
    }
    return save(changes(current, baselineRef.current));
  };

  useUnsavedChangesRegistration({
    isDirty: () => hasDraftChanges() || inFlight.current !== null,
    isSaving: () => inFlight.current !== null,
    save: saveDraft,
    discard: () => {
      if (inFlight.current) return;
      editDraft(() => ({ ...baselineRef.current }));
      setMessage("");
      setFailed(false);
    },
  }, dirty, saving);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void saveDraft();
  };

  return (
    <form className="classification-form" onSubmit={submit} aria-label={t("Host-Zuordnung bearbeiten")}>
      <label>
        <span>{t("Diensterkennung")}</span>
        <select value={draft.mode} onChange={(event) => {
          const mode = event.target.value as ClassificationMode;
          editDraft((current) => ({ ...current, mode,
            serviceName: mode === "manual" && !current.serviceName ? automaticName : current.serviceName }));
        }}>
          <option value="automatic">{t("Automatisch ermitteln")}</option>
          <option value="manual">{t("Manuellen Dienst verwenden")}</option>
          {baseline.mode === "legacy_preserved" && <option value="legacy_preserved" disabled>{t("Bisherige Zuordnung übernommen")}</option>}
        </select>
      </label>
      <label>
        <span>{t(draft.mode === "manual" ? "Manueller Dienstname" : "Dienst")}</span>
        <input value={draft.mode === "automatic" ? translateBackendLabel(automaticName) : draft.serviceName}
          readOnly={draft.mode !== "manual"} required={draft.mode === "manual"} maxLength={120}
          onChange={(event) => editDraft((current) => ({ ...current, serviceName: event.target.value }))} />
      </label>
      <label>
        <span>{t("Zuordnungsstatus")}</span>
        <select value={draft.trustStatus} onChange={(event) => editDraft((current) => ({ ...current, trustStatus: event.target.value as TrustStatus }))}>
          <option value="automatic">{t("Automatisch aus Erkennung ableiten")}</option>
          <option value="unconfirmed">{t("Prüfung ausstehend")}</option>
          <option value="confirmed">{t("Zuordnung bestätigt")}</option>
          <option value="ignored">{t("Automatische Zuordnung verworfen")}</option>
        </select>
      </label>
      <label className="notes-field">
        <span>{t("Notiz")}</span>
        <input value={draft.notes} maxLength={500} placeholder={t("Optionaler administrativer Kontext")}
          onChange={(event) => editDraft((current) => ({ ...current, notes: event.target.value }))} />
      </label>
      {draft.mode === "legacy_preserved" && <p className="classification-explanation">
        {t("Die bisherige Zuordnung bleibt erhalten. Ob der Dienstname früher bewusst festgelegt wurde, ist nicht sicher bekannt. Notizen können unabhängig geändert werden; für eine neue Entscheidung wähle automatische oder manuelle Erkennung.")}
      </p>}
      <p className="classification-explanation">
        {t("Notizen und Zuordnungsstatus legen keinen Dienstnamen fest. Die automatische Erkennung kann sich mit neuen Reports ändern.")}
      </p>
      <div className="classification-actions">
        <button className="button button-primary" type="submit" disabled={saving || !dirty || (draft.mode === "manual" && !draft.serviceName.trim())}>
          {saving ? <RefreshCw className="spin" aria-hidden="true" /> : <Save aria-hidden="true" />}{t("Speichern")}
        </button>
        {baseline.mode !== "automatic" && <button className="button button-secondary" type="button" disabled={saving}
          onClick={() => void save({ classification_mode: "automatic" })}>
          <RefreshCw aria-hidden="true" />{t("Automatische Zuordnung wiederherstellen")}
        </button>}
        {baseline.mode !== "automatic" && <span className="classification-explanation">
          {t("Automatik wiederherstellen behält gespeicherte Notizen und leitet den Zuordnungsstatus wieder automatisch ab.")}
        </span>}
      </div>
      {message && <span className="form-message" role={failed ? "alert" : "status"}>{message}</span>}
      {dirty && <span className="form-message classification-draft-note" role="status">{t("Ungespeicherte Änderungen vorhanden.")}</span>}
    </form>
  );
}
