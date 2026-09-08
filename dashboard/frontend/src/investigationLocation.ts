export type View = "overview" | "hosts" | "alerts" | "forensics" | "settings";
export interface InvestigationLocation {
  view: View;
  domain: string;
  days: number;
  alert?: string;
  host?: string;
  fromAlert?: string;
  fromDomain?: string;
  fromDays?: number;
}

export function validDomain(value: string | null | undefined): string {
  const original = value?.trim() ?? "";
  if (original === "*") return original;
  if (!original || original.length > 253 || /[\s/\\:@?#%\[\]]/.test(original)) return "*";
  try {
    const ascii = new URL(`http://${original}`).hostname;
    const name = ascii.endsWith(".") ? ascii.slice(0, -1) : ascii;
    if (name.length > 253 || !name.split(".").every((part) =>
      /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(part))) return "*";
    return original;
  } catch { return "*"; }
}

export function validDays(value: string | number | null | undefined): number {
  const text = String(value ?? "").trim();
  if (!/^[0-9]{1,3}$/.test(text)) return 30;
  const days = Number(text);
  return Number.isSafeInteger(days) && days >= 1 && days <= 730 ? days : 30;
}

function validId(value: string | null): string | undefined {
  return value && value.length <= 255 && /^[A-Za-z0-9._:-]+$/.test(value) ? value : undefined;
}

export function validHost(value: string | null): string | undefined {
  if (!value || value.length > 45) return undefined;
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value)) {
    return value.split(".").every((part) => Number(part) <= 255) ? value : undefined;
  }
  if (!/^[0-9a-f:.]+$/i.test(value) || !value.includes(":")) return undefined;
  try { new URL(`http://[${value}]/`); return value; } catch { return undefined; }
}

export function readInvestigationLocation(href: string): InvestigationLocation {
  const parameters = new URL(href).searchParams;
  const requested = parameters.get("view") as View;
  const view = ["overview", "hosts", "alerts", "forensics", "settings"].includes(requested) ? requested : "overview";
  return {
    view, domain: validDomain(parameters.get("domain")), days: validDays(parameters.get("days")),
    alert: view === "alerts" ? validId(parameters.get("alert")) : undefined,
    host: view === "hosts" ? validHost(parameters.get("host")) : undefined,
    fromAlert: view === "hosts" ? validId(parameters.get("from_alert")) : undefined,
    fromDomain: view === "hosts" && parameters.has("from_domain") ? validDomain(parameters.get("from_domain")) : undefined,
    fromDays: view === "hosts" && parameters.has("from_days") ? validDays(parameters.get("from_days")) : undefined,
  };
}

export function investigationUrl(location: InvestigationLocation, href = window.location.href): string {
  const url = new URL(href);
  const values = {
    view: location.view === "overview" ? undefined : location.view,
    domain: validDomain(location.domain), days: validDays(location.days),
    alert: location.view === "alerts" ? location.alert : undefined,
    host: location.view === "hosts" ? location.host : undefined,
    from_alert: location.view === "hosts" ? location.fromAlert : undefined,
    from_domain: location.view === "hosts" ? location.fromDomain : undefined,
    from_days: location.view === "hosts" ? location.fromDays : undefined,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined) url.searchParams.delete(key);
    else url.searchParams.set(key, String(value));
  }
  return url.href;
}
