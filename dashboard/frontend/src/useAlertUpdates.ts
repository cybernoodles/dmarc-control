import { useCallback, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { api, type AlertStatus } from "./api";


// A sent mutation can still finish after its view disappears. Keep its lock
// outside the component so a remount cannot submit a second change meanwhile.
let pendingSnapshot = new Set<string>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function getSnapshot() {
  return pendingSnapshot;
}

function setPending(alertId: string, pending: boolean) {
  const next = new Set(pendingSnapshot);
  if (pending) next.add(alertId);
  else next.delete(alertId);
  pendingSnapshot = next;
  listeners.forEach((listener) => listener());
}

export function useAlertUpdates(scope: string, onSuccess: () => void) {
  const pending = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const [error, setError] = useState("");
  const lifecycle = useRef({ scope, generation: 0, mounted: false });
  const success = useRef(onSuccess);

  useLayoutEffect(() => {
    success.current = onSuccess;
  }, [onSuccess]);

  useLayoutEffect(() => {
    lifecycle.current = {
      scope, generation: lifecycle.current.generation + 1, mounted: true,
    };
    setError("");
    return () => { lifecycle.current.mounted = false; };
  }, [scope]);

  const clearError = useCallback(() => {
    if (lifecycle.current.mounted) setError("");
  }, []);

  const update = useCallback(async (alertId: string, status: AlertStatus): Promise<void> => {
    if (!lifecycle.current.mounted || lifecycle.current.scope !== scope || pendingSnapshot.has(alertId)) return;
    const generation = lifecycle.current.generation;
    const isCurrent = () => lifecycle.current.mounted
      && lifecycle.current.scope === scope
      && lifecycle.current.generation === generation;

    // This synchronous check-and-lock also catches clicks before React renders
    // the disabled button, without blocking actions on any other alert.
    setPending(alertId, true);
    setError("");
    try {
      await api.updateAlert(alertId, status);
    } catch (reason) {
      if (isCurrent()) {
        setError(reason instanceof Error ? reason.message : "Statusänderung fehlgeschlagen");
      }
      return;
    } finally {
      setPending(alertId, false);
    }
    if (isCurrent()) success.current();
  }, [scope]);

  return { update, pending, error, clearError };
}
