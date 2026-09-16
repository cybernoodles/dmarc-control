import type { Alert } from "./api";

type ProviderContextAlert = Pick<
  Alert,
  "kind" | "provider_expectation" | "notification_suppressed_reason"
>;

export function isExpectedProviderPassAlert(alert: ProviderContextAlert) {
  return alert.kind === "new-source-ip"
    && alert.provider_expectation === "expected"
    && alert.notification_suppressed_reason === "expected-provider-dmarc-pass";
}
