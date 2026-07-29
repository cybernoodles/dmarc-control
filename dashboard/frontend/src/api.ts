export type Risk = "critical" | "warning" | "healthy";
export type TrustStatus =
  | "unconfirmed"
  | "automatic"
  | "confirmed"
  | "ignored";
export type AlertStatus =
  | "open"
  | "acknowledged"
  | "resolved"
  | "ignored";

export interface DomainItem {
  domain: string;
  messages: number;
  last_seen: string | null;
}

export interface Overview {
  scope: { domain: string; days: number };
  totals: {
    messages: number;
    dmarc_pass: number;
    dmarc_fail: number;
    pass_rate: number;
    critical_sources: number;
    last_report: string | null;
  };
  alignment: {
    spf_aligned: number;
    spf_not_aligned: number;
    dkim_aligned: number;
    dkim_not_aligned: number;
    dmarc_pass: number;
    dmarc_fail: number;
  };
  trend: Array<{ date: string; pass: number; fail: number }>;
  critical_sources: Array<{
    source_ip: string;
    reverse_dns: string | null;
    base_domain: string | null;
    country: string | null;
    header_from: string | null;
    envelope_from: string | null;
    spf_aligned: boolean | null;
    dkim_aligned: boolean | null;
    messages: number;
    last_seen: string | null;
  }>;
  domains: Array<{ name: string; messages: number }>;
  reporting_organisations: Array<{ name: string; messages: number }>;
  policies: Array<{
    domain: string;
    policy: string;
    percentage: number;
    messages: number;
  }>;
}

export interface Host {
  source_ip: string;
  reverse_dns: string | null;
  base_domain: string | null;
  country: string | null;
  asn: number | null;
  as_name: string | null;
  as_domain: string | null;
  source_type: string | null;
  header_froms: string[];
  envelope_froms: string[];
  spf_domains: string[];
  dkim_domains: string[];
  dkim_selectors: string[];
  messages: number;
  dmarc_pass: number;
  dmarc_fail: number;
  previous_dmarc_pass: number;
  previous_dmarc_fail: number;
  pass_rate: number;
  spf_aligned: number;
  spf_not_aligned: number;
  dkim_aligned: number;
  dkim_not_aligned: number;
  first_seen: string | null;
  last_seen: string | null;
  is_new: boolean;
  risk: Risk;
  trust_status: TrustStatus;
  service_detection: {
    service: string;
    automatic_service?: string;
    confidence: number;
    confidence_label: string;
    evidence: string[];
    manual_override: boolean;
  };
  override: {
    service_name: string | null;
    trust_status: TrustStatus;
    notes: string | null;
    updated_at: string;
  } | null;
}

export interface Alert {
  id: string;
  priority: "critical" | "warning" | "info";
  title: string;
  source_ip: string | null;
  country: string | null;
  domain: string;
  trigger: string;
  report_time: string | null;
  messages: number;
  kind: string;
  status: AlertStatus;
  status_updated_at: string | null;
}

export interface Forensics {
  scope: { domain: string; days: number; failure_type: string };
  samples: number;
  last_report: string | null;
  failure_types: Array<{ name: string; samples: number }>;
  domains: Array<{ name: string; samples: number }>;
  countries: Array<{ name: string; samples: number }>;
  sources: Array<{
    source_ip: string;
    samples: number;
    reverse_dns: string | null;
    base_domain: string | null;
    country: string;
    last_seen: string | null;
  }>;
  evidence: Array<{
    authentication_result: string;
    delivery_results: string[];
    failure_types: string[];
    samples: number;
  }>;
  privacy: {
    raw_samples_loaded: boolean;
    excluded_fields: string[];
  };
}

export interface AppearanceSettings {
  global_profile: "standard" | "custom";
  global_color: string;
  updated_at: string | null;
  write_protected: boolean;
  admin_configured: boolean;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
}

const query = (values: Record<string, string | number>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) =>
    params.set(key, String(value)),
  );
  return params.toString();
};

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setupAdmin: (password: string) =>
    request<AuthStatus>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  loginAdmin: (password: string) =>
    request<AuthStatus>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logoutAdmin: () =>
    request<AuthStatus>("/api/auth/logout", {
      method: "POST",
    }),
  changeAdminPassword: (currentPassword: string, newPassword: string) =>
    request<AuthStatus>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
  appearance: () =>
    request<AppearanceSettings>("/api/settings/appearance"),
  updateAppearance: (
    profile: AppearanceSettings["global_profile"],
    color: string | null,
  ) =>
    request<AppearanceSettings>("/api/settings/appearance", {
      method: "PUT",
      body: JSON.stringify({ profile, color }),
    }),
  domains: () =>
    request<{ items: DomainItem[] }>("/api/domains").then(
      (response) => response.items,
    ),
  overview: (domain: string, days: number) =>
    request<Overview>(`/api/overview?${query({ domain, days })}`),
  hosts: (domain: string, days: number, risk = "all") =>
    request<{ items: Host[] }>(
      `/api/hosts?${query({ domain, days, risk })}`,
    ).then((response) => response.items),
  alerts: (domain: string, days: number, status = "all") =>
    request<{ items: Alert[] }>(
      `/api/alerts?${query({ domain, days, status })}`,
    ).then((response) => response.items),
  updateAlert: (alertId: string, status: AlertStatus) =>
    request(`/api/alerts/${encodeURIComponent(alertId)}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  updateHost: (
    sourceIp: string,
    update: {
      service_name: string | null;
      trust_status: TrustStatus;
      notes: string | null;
    },
  ) =>
    request(`/api/hosts/${encodeURIComponent(sourceIp)}/classification`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  forensics: (
    domain: string,
    days: number,
    failureType = "*",
  ) =>
    request<Forensics>(
      `/api/forensics?${query({
        domain,
        days,
        failure_type: failureType,
      })}`,
    ),
};
