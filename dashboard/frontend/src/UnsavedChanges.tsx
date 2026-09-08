import { createContext, ReactNode, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { useI18n } from "./i18n";

export interface UnsavedChangesGuard {
  isDirty: () => boolean;
  isSaving: () => boolean;
  save: () => Promise<boolean>;
  discard: () => void;
}

interface UnsavedChangesContextValue {
  request: (action: () => void) => void;
  cancelPendingNavigation: () => void;
  hasUnsavedChanges: () => boolean;
  register: (guard: UnsavedChangesGuard) => () => void;
  refresh: () => void;
}

const UnsavedChangesContext = createContext<UnsavedChangesContextValue | null>(null);

export function useUnsavedChanges() {
  const context = useContext(UnsavedChangesContext);
  if (!context) throw new Error("UnsavedChangesProvider is required");
  return context;
}

export function useUnsavedChangesRegistration(guard: UnsavedChangesGuard, dirty: boolean, saving: boolean) {
  const { register, refresh } = useUnsavedChanges();
  const latest = useRef(guard);
  latest.current = guard;
  useEffect(() => register({
    isDirty: () => latest.current.isDirty(),
    isSaving: () => latest.current.isSaving(),
    save: () => latest.current.save(),
    discard: () => latest.current.discard(),
  }), [register]);
  useEffect(refresh, [dirty, saving, refresh]);
}

type PendingNavigation = { guard: UnsavedChangesGuard; action: () => void; returnFocus: HTMLElement | null };

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const guards = useRef(new Set<UnsavedChangesGuard>());
  const pendingRef = useRef<PendingNavigation | null>(null);
  const [pending, setPending] = useState<PendingNavigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [, setRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const continueEditing = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const hasUnsavedChanges = useCallback(() => [...guards.current].some((guard) => guard.isDirty()), []);
  const register = useCallback((guard: UnsavedChangesGuard) => {
    guards.current.add(guard);
    return () => { guards.current.delete(guard); };
  }, []);
  const request = useCallback((action: () => void) => {
    if (pendingRef.current) return;
    const guard = [...guards.current].find((item) => item.isDirty());
    if (!guard) { action(); return; }
    const next = { guard, action, returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null };
    pendingRef.current = next;
    setPending(next);
    setBusy(false);
    setMessage("");
  }, []);
  const close = useCallback((restoreFocus: boolean) => {
    const previous = pendingRef.current;
    pendingRef.current = null;
    setPending(null);
    setBusy(false);
    setMessage("");
    dialog.current?.close();
    if (restoreFocus && previous?.returnFocus?.isConnected) previous.returnFocus.focus();
  }, []);
  const cancelPendingNavigation = useCallback(() => close(false), [close]);

  useEffect(() => {
    if (pending && !dialog.current?.open) {
      dialog.current?.showModal();
      continueEditing.current?.focus();
    }
  }, [pending]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [hasUnsavedChanges]);

  const saveAndContinue = async () => {
    const current = pendingRef.current;
    if (!current || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const saved = await current.guard.save();
      if (pendingRef.current !== current) return;
      if (saved && !hasUnsavedChanges()) {
        close(false);
        current.action();
      } else {
        setMessage("Es bestehen weiterhin ungespeicherte Änderungen. Prüfe den Entwurf oder versuche das Speichern erneut.");
      }
    } catch {
      if (pendingRef.current === current) setMessage("Speichern fehlgeschlagen. Der Entwurf bleibt erhalten.");
    } finally {
      if (pendingRef.current === current) setBusy(false);
    }
  };

  const discardAndContinue = () => {
    const current = pendingRef.current;
    if (!current || busy || current.guard.isSaving()) return;
    current.guard.discard();
    close(false);
    current.action();
  };
  const value = useMemo(() => ({ request, cancelPendingNavigation, hasUnsavedChanges, register, refresh }), [request, cancelPendingNavigation, hasUnsavedChanges, register, refresh]);
  const existingSave = pending?.guard.isSaving() ?? false;

  return <UnsavedChangesContext.Provider value={value}>
    {children}
    <dialog ref={dialog} className="unsaved-changes-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={(event) => { event.preventDefault(); close(true); }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
        const first = buttons[0];
        const last = buttons.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}>
      <h2 id={titleId}>{t("Ungespeicherte Host-Zuordnung")}</h2>
      <p id={descriptionId}>{t("Für diesen Sending Host gibt es ungespeicherte Änderungen. Wie möchtest du fortfahren?")}</p>
      {existingSave && <p className="unsaved-changes-note" role="status">{t("Ein Speichervorgang läuft bereits. Speichern und weiter wartet auf dessen Ergebnis.")}</p>}
      {message && <p className="unsaved-changes-error" role="alert">{t(message)}</p>}
      <div className="unsaved-changes-actions">
        <button className="button button-primary" type="button" disabled={busy} onClick={() => void saveAndContinue()}>
          {t(busy ? "Speichern läuft …" : "Speichern und weiter")}
        </button>
        <button className="button button-secondary" type="button" disabled={busy || existingSave} onClick={discardAndContinue}>
          {t("Verwerfen und weiter")}
        </button>
        <button ref={continueEditing} className="button button-ghost" type="button" onClick={() => close(true)}>
          {t("Weiterbearbeiten")}
        </button>
      </div>
    </dialog>
  </UnsavedChangesContext.Provider>;
}
