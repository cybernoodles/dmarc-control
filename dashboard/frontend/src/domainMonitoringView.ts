import type { DomainMonitoringItem } from "./api";

export const DOMAIN_LIST_THRESHOLD = 50;
export const DOMAIN_PAGE_SIZE = 25;

// URL parsing only normalizes an international domain locally; it makes no request.
export function domainSearchTerms(value: string): string[] {
  const text = value.trim().normalize("NFC").toLowerCase().replace(/\.$/, "");
  if (!text) return [];
  const terms = [text];
  if (!/[\s/\\:@?#%\[\]]/.test(text)) {
    try {
      const ascii = new URL(`http://${text}`).hostname.replace(/\.$/, "");
      if (ascii !== text) terms.push(ascii);
    } catch { /* Partial names still match their literal text. */ }
  }
  return terms;
}

export function domainSearchIndex(items: DomainMonitoringItem[]) {
  return items.map((item) => ({ item, text: [item.domain, item.query_domain, ...item.aliases]
    .flatMap(domainSearchTerms).join("\n") }));
}

export interface DomainRowDraft {
  grace: string;
  baselineGrace: number;
  revision: number;
  busy: boolean;
  error: string;
  message: string;
}

export function storedDomainDraft(drafts: Record<string, DomainRowDraft>, domain: string): DomainRowDraft | undefined {
  return Object.hasOwn(drafts, domain) ? drafts[domain] : undefined;
}

export function initialDomainDraft(grace: number): DomainRowDraft {
  return { grace: String(grace), baselineGrace: grace, revision: 0, busy: false, error: "", message: "" };
}

export function reconcileDomainDraft(draft: DomainRowDraft, grace: number, requestRevision: number | undefined, saved = false): DomainRowDraft {
  const unchanged = draft.revision === requestRevision;
  return { ...draft, baselineGrace: grace,
    grace: unchanged && (saved || draft.grace === String(draft.baselineGrace)) ? String(grace) : draft.grace };
}

export function domainPage(total: number, requestedPage: number) {
  const page = Math.min(Math.max(0, requestedPage), Math.max(0, Math.ceil(total / DOMAIN_PAGE_SIZE) - 1));
  return { page, start: page * DOMAIN_PAGE_SIZE, end: Math.min((page + 1) * DOMAIN_PAGE_SIZE, total) };
}
