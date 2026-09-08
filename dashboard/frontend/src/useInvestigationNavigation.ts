import { useCallback, useEffect, useRef, useState } from "react";
import { useUnsavedChanges } from "./UnsavedChanges";
import { investigationUrl, readInvestigationLocation } from "./investigationLocation";
import type { InvestigationLocation } from "./investigationLocation";

const historyKey = "dmarcInvestigationIndex";

export function useInvestigationNavigation() {
  const [location, setLocation] = useState(() => readInvestigationLocation(window.location.href));
  const active = useRef({ location, index: Number.isInteger(window.history.state?.[historyKey])
    ? window.history.state[historyKey] as number : 0, href: investigationUrl(location) });
  const guard = useUnsavedChanges();
  const guardRef = useRef(guard);
  guardRef.current = guard;
  const approved = useRef<number | null>(null);
  const restoring = useRef<null | { destination: number }>(null);

  const apply = useCallback((next: InvestigationLocation, index: number, href: string) => {
    active.current = { location: next, index, href };
    setLocation(next);
  }, []);

  useEffect(() => {
    window.history.replaceState({ ...window.history.state, [historyKey]: active.current.index }, "", active.current.href);
    const pop = () => {
      const index = window.history.state?.[historyKey];
      if (restoring.current) {
        if (index !== active.current.index) {
          if (Number.isInteger(index)) window.history.go(active.current.index - index);
          return;
        }
        const destination = restoring.current.destination;
        restoring.current = null;
        guardRef.current.request(() => {
          approved.current = destination;
          window.history.go(destination - active.current.index);
        });
        return;
      }
      const next = readInvestigationLocation(window.location.href);
      const href = investigationUrl(next);
      if (approved.current === index && Number.isInteger(index)) {
        approved.current = null;
        apply(next, index, href);
        return;
      }
      if (!Number.isInteger(index)) {
        // A same-document entry created outside this router has no position.
        // Restore the active URL before asking, then commit that destination.
        window.history.replaceState({ [historyKey]: active.current.index }, "", active.current.href);
        guardRef.current.request(() => {
          const nextIndex = active.current.index + 1;
          window.history.pushState({ [historyKey]: nextIndex }, "", href);
          apply(next, nextIndex, href);
        });
      } else if (guardRef.current.hasUnsavedChanges() && index !== active.current.index) {
        restoring.current = { destination: index };
        window.history.go(active.current.index - index);
      } else {
        window.history.replaceState({ ...window.history.state, [historyKey]: index }, "", href);
        apply(next, index, href);
      }
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [apply]);

  const go = useCallback((next: InvestigationLocation) => {
    if (restoring.current) return;
    const href = investigationUrl(next);
    if (href === active.current.href) return;
    guardRef.current.request(() => {
      const index = active.current.index + 1;
      window.history.pushState({ [historyKey]: index }, "", href);
      apply(readInvestigationLocation(href), index, href);
    });
  }, [apply]);
  return { location, go };
}
