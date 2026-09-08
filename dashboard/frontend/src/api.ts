import type { AlertEvaluationState } from "./AlertEvaluationStatus";
import type { RecipientDeliveryItem, RecipientDeliverySummary } from "./RecipientDeliveryStatus";

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
    profile: "dynamic_ip" | "mail_service" | "unknown";
  };
  override: {
    service_name: string | null;
    trust_status: TrustStatus;
    notes: string | null;
    updated_at: string;
  } | null;
}

export interface HostPage {
  items: Host[];
  total: number;
  limit: number;
  offset: number;
  scope: { domain: string; days: number; risk: string; search?: string };
}

export interface AlertDeliverySummary {
  alert_id: string;
  mode: "none" | "accepted" | "partial" | "failed" | "pending" | "legacy_hold";
  accepted: number;
  temporary_failure: number;
  permanent_failure: number;
  exhausted: number;
  pending: number;
  total: number;
  attempts_total: number;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  legacy: { total: number; sent: number; failed: number; pending: number;
    attempts_total: number; last_attempt_at: string | null; };
}

export interface AlertDeliveryDetails extends AlertDeliverySummary {
  items: RecipientDeliveryItem[];
  limit: number;
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
  total_messages?: number;
  kind: string;
  status: AlertStatus;
  status_updated_at: string | null;
  historical?: boolean;
  delivery?: AlertDeliverySummary;
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
  admin_configured: boolean;
  read_authenticated: boolean;
  read_username: string | null;
  authenticated: boolean;
}

export type MailboxProvider = "msgraph" | "imap";

export interface MailboxConnectionVersion {
  revision: number;
  provider: MailboxProvider;
  settings: {
    auth_method?: "ClientSecret";
    tenant_id?: string;
    client_id?: string;
    mailbox?: string;
    host?: string;
    port?: number;
    ssl?: boolean;
    skip_certificate_verification?: boolean;
    user?: string;
    reports_folder: string;
    archive_folder: string;
  };
  secret_configured: boolean;
  created_at: string;
}

export interface ParserRuntimeStatus {
  mode: "legacy" | "managed";
  state: "starting" | "running" | "restarting" | "error" | "stopped";
  revision: number | null;
  version: string | null;
  message: string | null;
  pid: number | null;
  updated_at: string;
}

export interface MailboxConnectionState {
  configured: boolean;
  draft: MailboxConnectionVersion | null;
  active: MailboxConnectionVersion | null;
  draft_revision: number | null;
  tested_revision: number | null;
  active_revision: number | null;
  test_status: "untested" | "success" | "failure";
  test_message: string | null;
  tested_at: string | null;
  updated_at: string | null;
  parser: ParserRuntimeStatus | null;
}

export interface MailboxConnectionUpdate {
  provider: MailboxProvider;
  tenant_id?: string;
  client_id?: string;
  client_secret?: string;
  mailbox?: string;
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  reports_folder: string;
  archive_folder: string;
}

export type NotificationTransport = "smtp" | "msgraph";
export type NotificationCase =
  | "new-host-fail"
  | "host-degradation"
  | "host-fail"
  | "dynamic-ip-fail"
  | "new-source-ip"
  | "compensated-alignment"
  | "stale-reports";

export interface NotificationSettings {
  configured: boolean;
  enabled: boolean;
  transport: NotificationTransport;
  recipients: string[];
  sender: string;
  language: "de" | "en";
  dashboard_url: string;
  cases: NotificationCase[];
  smtp: {
    host: string;
    port: number;
    security: "starttls" | "tls" | "plain";
    username: string;
    password_configured: boolean;
  };
  graph: {
    reuse_mailbox_connection: boolean;
    tenant_id: string;
    client_id: string;
    client_secret_configured: boolean;
  };
  test_status: "untested" | "success" | "failure";
  test_message: string | null;
  tested_at: string | null;
  updated_at: string | null;
  delivery: {
    recipient_delivery?: RecipientDeliverySummary;
    sent: number;
    failed: number;
    pending: number;
    latest: {
      status: string;
      last_attempt_at: string;
      sent_at: string | null;
      last_error: string | null;
    } | null;
  };
}

export interface NotificationStatus {
  configured: boolean;
  enabled: boolean;
}

export interface NotificationSettingsUpdate {
  enabled: boolean;
  transport: NotificationTransport;
  recipients: string[];
  sender: string;
  language: "de" | "en";
  dashboard_url: string;
  cases: NotificationCase[];
  smtp: {
    host: string;
    port: number;
    security: "starttls" | "tls" | "plain";
    username: string;
    password?: string;
  };
  graph: {
    reuse_mailbox_connection: boolean;
    tenant_id: string;
    client_id: string;
    client_secret?: string;
  };
}

const query = (values: Record<string, string | number>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) =>
    params.set(key, String(value)),
  );
  return params.toString();
};

function responseErrorMessage(payload: unknown, status: number): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return `HTTP ${status}`;
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (!item || typeof item !== "object" || !("msg" in item)) {
        return [];
      }
      const message = (item as { msg?: unknown }).msg;
      return typeof message === "string" ? [message] : [];
    });
    if (messages.length) {
      return messages.join(" ");
    }
  }

  return `HTTP ${status}`;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

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
    const message = responseErrorMessage(payload, response.status);
    if (response.status === 401 && message === "Read login required") {
      window.dispatchEvent(new Event("dmarc-read-session-expired"));
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setupAccess: (
    adminPassword: string,
    readUsername: string,
    readPassword: string,
  ) =>
    request<AuthStatus>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({
        admin_password: adminPassword,
        read_username: readUsername,
        read_password: readPassword,
      }),
    }),
  loginRead: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/read-login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logoutRead: () =>
    request<AuthStatus>("/api/auth/read-logout", {
      method: "POST",
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
  updateReadCredentials: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/read-credentials", {
      method: "PUT",
      body: JSON.stringify({ username, password }),
    }),
  mailboxSettings: () =>
    request<MailboxConnectionState>("/api/settings/mailbox"),
  saveMailboxSettings: (update: MailboxConnectionUpdate) =>
    request<MailboxConnectionState>("/api/settings/mailbox", {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  testMailboxSettings: () =>
    request<MailboxConnectionState>("/api/settings/mailbox/test", {
      method: "POST",
    }),
  activateMailboxSettings: () =>
    request<MailboxConnectionState>("/api/settings/mailbox/activate", {
      method: "POST",
    }),
  evaluationStatus: (signal?: AbortSignal) =>
    request<AlertEvaluationState>("/api/alerts/evaluation/status", { signal }),
  alertDelivery: (alertId: string, signal?: AbortSignal) =>
    request<AlertDeliveryDetails>(`/api/alerts/${encodeURIComponent(alertId)}/delivery`, { signal }),
  notificationSettings: () =>
    request<NotificationSettings>("/api/settings/notifications"),
  notificationStatus: () =>
    request<NotificationStatus>("/api/settings/notifications/status"),
  saveNotificationSettings: (update: NotificationSettingsUpdate) =>
    request<NotificationSettings>("/api/settings/notifications", {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  testNotificationSettings: () =>
    request<NotificationSettings>("/api/settings/notifications/test", {
      method: "POST",
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
  hosts: (
    domain: string,
    days: number,
    risk = "all",
    options: { limit?: number; offset?: number; search?: string; signal?: AbortSignal } = {},
  ) =>
    request<HostPage>(
      `/api/hosts?${query({
        domain,
        days,
        risk,
        limit: options.limit ?? 100,
        offset: options.offset ?? 0,
        search: options.search ?? "",
      })}`,
      { signal: options.signal },
    ),
  host: (sourceIp: string, domain: string, days: number, signal?: AbortSignal) =>
    request<Host>(
      `/api/hosts/${encodeURIComponent(sourceIp)}?${query({ domain, days })}`,
      { signal },
    ),
  alerts: (domain: string, days: number, status = "all", signal?: AbortSignal) =>
    request<{ items: Alert[] }>(
      `/api/alerts?${query({ domain, days, status })}`,
      { signal },
    ).then((response) => response.items),
  alert: (alertId: string, signal?: AbortSignal) =>
    request<Alert>(`/api/alerts/${encodeURIComponent(alertId)}`, { signal }),
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
  clearHostClassification: (sourceIp: string) =>
    request(`/api/hosts/${encodeURIComponent(sourceIp)}/classification`, {
      method: "DELETE",
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
