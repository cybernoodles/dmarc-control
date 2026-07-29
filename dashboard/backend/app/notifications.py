from __future__ import annotations

import base64
import hashlib
import html
import json
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any
from urllib.parse import quote, urlencode

import httpx

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_TOKEN_ROOT = "https://login.microsoftonline.com"
SCHEMA_VERSION = "dmarc-control.alert.v1"
NOTIFICATION_CASES = {
    "new-host-fail",
    "host-degradation",
    "host-fail",
    "dynamic-ip-fail",
    "new-source-ip",
    "compensated-alignment",
    "stale-reports",
}


class NotificationDeliveryError(RuntimeError):
    pass


def notification_case(alert: dict[str, Any]) -> str:
    if (
        alert.get("kind") in {"new-host-fail", "host-degradation", "host-fail"}
        and alert.get("source_profile") == "dynamic_ip"
    ):
        return "dynamic-ip-fail"
    return str(alert.get("kind") or "unknown")


def destination_hash(settings: dict[str, Any]) -> str:
    identity = json.dumps(
        {
            "transport": settings["transport"],
            "sender": settings["sender"],
            "recipients": sorted(settings["recipients"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _dashboard_link(settings: dict[str, Any], alert_id: str) -> str | None:
    base_url = str(settings.get("dashboard_url") or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/?{urlencode({'view': 'alerts', 'alert': alert_id})}"


def _labels(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "alert": "DMARC alert",
            "test": "DMARC Control test email",
            "priority": "Priority",
            "domain": "Domain",
            "source": "Source IP",
            "country": "Country",
            "service": "Detected service",
            "trigger": "Trigger",
            "report_time": "Report time",
            "messages": "Affected messages",
            "dmarc": "DMARC result",
            "spf": "SPF alignment",
            "dkim": "DKIM alignment",
            "evidence": "Classification evidence",
            "open": "Open alert in DMARC Control",
            "machine": (
                "A versioned JSON representation is attached as "
                "dmarc-alert.json. Stable X-DMARC-Control-* headers support "
                "mail rules and automated processing."
            ),
            "generated": "Generated",
            "not_available": "Not available",
            "test_intro": (
                "This test confirms that DMARC Control can deliver structured "
                "HTML alert emails through the configured transport."
            ),
        }
    return {
        "alert": "DMARC-Warnung",
        "test": "DMARC Control Test-E-Mail",
        "priority": "Priorität",
        "domain": "Domain",
        "source": "Source-IP",
        "country": "Land",
        "service": "Erkannter Dienst",
        "trigger": "Auslöser",
        "report_time": "Reportzeit",
        "messages": "Betroffene Nachrichten",
        "dmarc": "DMARC-Ergebnis",
        "spf": "SPF-Alignment",
        "dkim": "DKIM-Alignment",
        "evidence": "Klassifizierungsevidenz",
        "open": "Warnung in DMARC Control öffnen",
        "machine": (
            "Eine versionierte JSON-Darstellung ist als dmarc-alert.json "
            "angehängt. Stabile X-DMARC-Control-*-Header unterstützen "
            "Mailregeln und maschinelle Verarbeitung."
        ),
        "generated": "Erzeugt",
        "not_available": "Nicht verfügbar",
        "test_intro": (
            "Dieser Test bestätigt, dass DMARC Control strukturierte "
            "HTML-Warnungen über den konfigurierten Versandweg zustellen kann."
        ),
    }


def _priority_label(priority: str, language: str) -> str:
    values = {
        "de": {"critical": "Kritisch", "warning": "Warnung", "info": "Hinweis"},
        "en": {"critical": "Critical", "warning": "Warning", "info": "Advisory"},
    }
    return values.get(language, values["de"]).get(priority, priority.title())


def _header_value(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _case_title(event_type: str, language: str) -> str:
    titles = {
        "de": {
            "new-host-fail": "Neuer unbekannter Sender mit DMARC-Fail",
            "host-degradation": "Bekannter Sending Host hat sich verschlechtert",
            "host-fail": "DMARC-Fehlerquelle erkannt",
            "dynamic-ip-fail": "DMARC-Fail aus dynamischem IP-Bereich",
            "new-source-ip": "Neue Source-IP erkannt",
            "compensated-alignment": "Kompensiertes Alignment-Problem",
            "stale-reports": "DMARC-Reports bleiben aus",
            "test": "Test der E-Mail-Benachrichtigung",
        },
        "en": {
            "new-host-fail": "New unknown sender with a DMARC failure",
            "host-degradation": "Known sending host has degraded",
            "host-fail": "DMARC failure source detected",
            "dynamic-ip-fail": "DMARC failure from a dynamic IP range",
            "new-source-ip": "New source IP detected",
            "compensated-alignment": "Compensated alignment issue",
            "stale-reports": "DMARC reports are missing",
            "test": "Email notification test",
        },
    }
    return titles.get(language, titles["de"]).get(event_type, event_type)


def test_alert() -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": f"test-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "priority": "info",
        "title": "Test der E-Mail-Benachrichtigung",
        "source_ip": "192.0.2.1",
        "country": "CH",
        "domain": "example.invalid",
        "trigger": "Explicit administrator test",
        "report_time": now,
        "messages": 1,
        "kind": "test",
        "status": "open",
        "status_updated_at": None,
        "source_profile": "unknown",
        "reverse_dns": "test.example.invalid",
        "service": "DMARC Control",
        "service_confidence": 1.0,
        "service_evidence": ["Explicit administrator action"],
        "header_froms": ["example.invalid"],
        "envelope_froms": ["bounce.example.invalid"],
        "spf_domains": ["example.invalid"],
        "dkim_domains": ["example.invalid"],
        "dkim_selectors": ["test"],
        "dmarc_pass": 0,
        "dmarc_fail": 1,
        "spf_aligned": 0,
        "spf_not_aligned": 1,
        "dkim_aligned": 0,
        "dkim_not_aligned": 1,
    }


def _payload(
    alert: dict[str, Any],
    settings: dict[str, Any],
    *,
    test: bool,
) -> dict[str, Any]:
    event_type = "test" if test else notification_case(alert)
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "test": test,
        "alert": {
            "id": alert["id"],
            "event_type": event_type,
            "source_event_type": alert.get("kind"),
            "priority": alert.get("priority"),
            "status": alert.get("status"),
            "domain": alert.get("domain"),
            "trigger": alert.get("trigger"),
            "report_time": alert.get("report_time"),
            "affected_messages": alert.get("messages", 0),
        },
        "source": {
            "ip": alert.get("source_ip"),
            "country": alert.get("country"),
            "reverse_dns": alert.get("reverse_dns"),
            "asn": alert.get("asn"),
            "as_name": alert.get("as_name"),
            "profile": alert.get("source_profile"),
        },
        "classification": {
            "service": alert.get("service"),
            "confidence": alert.get("service_confidence"),
            "evidence": alert.get("service_evidence") or [],
        },
        "identities": {
            "header_from": alert.get("header_froms") or [],
            "envelope_from": alert.get("envelope_froms") or [],
            "spf_domains": alert.get("spf_domains") or [],
            "dkim_domains": alert.get("dkim_domains") or [],
            "dkim_selectors": alert.get("dkim_selectors") or [],
        },
        "authentication": {
            "dmarc": {
                "passed": alert.get("dmarc_pass", 0),
                "failed": alert.get("dmarc_fail", 0),
            },
            "spf_alignment": {
                "aligned": alert.get("spf_aligned", 0),
                "not_aligned": alert.get("spf_not_aligned", 0),
            },
            "dkim_alignment": {
                "aligned": alert.get("dkim_aligned", 0),
                "not_aligned": alert.get("dkim_not_aligned", 0),
            },
        },
        "links": {
            "dashboard": _dashboard_link(settings, str(alert["id"])),
        },
    }


def _plain_text(
    payload: dict[str, Any],
    labels: dict[str, str],
    *,
    test: bool,
) -> str:
    alert = payload["alert"]
    source = payload["source"]
    classification = payload["classification"]
    authentication = payload["authentication"]
    rows = [
        _case_title(alert["event_type"], "en" if labels["alert"] == "DMARC alert" else "de"),
        "",
    ]
    if test:
        rows.extend([labels["test_intro"], ""])
    rows.extend(
        [
            f"{labels['priority']}: {alert['priority']}",
            f"{labels['domain']}: {alert['domain']}",
            f"{labels['source']}: {source['ip'] or labels['not_available']}",
            f"{labels['country']}: {source['country'] or labels['not_available']}",
            f"{labels['service']}: {classification['service'] or labels['not_available']}",
            f"{labels['trigger']}: {alert['trigger']}",
            f"{labels['report_time']}: {alert['report_time']}",
            f"{labels['messages']}: {alert['affected_messages']}",
            (
                f"{labels['dmarc']}: "
                f"{authentication['dmarc']['passed']} pass / "
                f"{authentication['dmarc']['failed']} fail"
            ),
            (
                f"{labels['spf']}: "
                f"{authentication['spf_alignment']['aligned']} aligned / "
                f"{authentication['spf_alignment']['not_aligned']} not aligned"
            ),
            (
                f"{labels['dkim']}: "
                f"{authentication['dkim_alignment']['aligned']} aligned / "
                f"{authentication['dkim_alignment']['not_aligned']} not aligned"
            ),
            "",
        ]
    )
    if payload["links"]["dashboard"]:
        rows.extend([f"{labels['open']}: {payload['links']['dashboard']}", ""])
    rows.append(labels["machine"])
    return "\n".join(rows)


def _html_body(
    payload: dict[str, Any],
    labels: dict[str, str],
    language: str,
    *,
    test: bool,
) -> str:
    alert = payload["alert"]
    source = payload["source"]
    classification = payload["classification"]
    authentication = payload["authentication"]
    priority_colors = {
        "critical": ("#8f2f38", "#fff0f1"),
        "warning": ("#8a651d", "#fff7e6"),
        "info": ("#285f83", "#edf7ff"),
    }
    accent, soft = priority_colors.get(
        str(alert["priority"]),
        ("#173f43", "#edf5f4"),
    )

    def value(raw: Any) -> str:
        if raw is None or raw == "":
            return html.escape(labels["not_available"])
        return html.escape(str(raw))

    dmarc_value = (
        f"{authentication['dmarc']['passed']} Pass · "
        f"{authentication['dmarc']['failed']} Fail"
    )
    spf_value = (
        f"{authentication['spf_alignment']['aligned']} aligned · "
        f"{authentication['spf_alignment']['not_aligned']} not aligned"
    )
    dkim_value = (
        f"{authentication['dkim_alignment']['aligned']} aligned · "
        f"{authentication['dkim_alignment']['not_aligned']} not aligned"
    )
    evidence = classification["evidence"]
    evidence_html = (
        "".join(f"<li>{value(item)}</li>" for item in evidence)
        if evidence
        else f"<li>{value(labels['not_available'])}</li>"
    )
    link = payload["links"]["dashboard"]
    action = (
        f'<a href="{html.escape(link, quote=True)}" '
        f'style="display:inline-block;background:#173f43;color:#fff;'
        f'text-decoration:none;border-radius:8px;padding:11px 16px;'
        f'font-weight:700">{html.escape(labels["open"])}</a>'
        if link
        else ""
    )
    test_intro = (
        f'<p style="margin:0 0 20px;color:#405457">{html.escape(labels["test_intro"])}</p>'
        if test
        else ""
    )
    generated = value(payload["generated_at"])
    return f"""<!doctype html>
<html lang="{html.escape(language)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#f3f6f6;color:#15282b;font-family:Arial,sans-serif">
  <div style="max-width:720px;margin:0 auto;padding:28px 16px">
    <div style="background:#101b1d;color:#fff;border-radius:12px 12px 0 0;padding:20px 24px">
      <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.72">DMARC Control</div>
      <h1 style="font-size:22px;line-height:1.3;margin:8px 0 0">{value(_case_title(alert["event_type"], language))}</h1>
    </div>
    <div style="background:#fff;border:1px solid #d9e2e2;border-top:0;border-radius:0 0 12px 12px;padding:24px">
      {test_intro}
      <div style="display:inline-block;background:{soft};color:{accent};border-radius:999px;padding:6px 10px;font-size:12px;font-weight:700">
        {value(_priority_label(str(alert["priority"]), language))}
      </div>
      <table role="presentation" style="width:100%;border-collapse:collapse;margin:20px 0">
        <tr><td style="padding:9px 0;color:#687a7d;width:38%">{value(labels["domain"])}</td><td style="padding:9px 0;font-weight:700">{value(alert["domain"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["source"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(source["ip"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["country"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(source["country"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["service"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(classification["service"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["trigger"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["trigger"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["report_time"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["report_time"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["messages"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["affected_messages"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["dmarc"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(dmarc_value)}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["spf"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(spf_value)}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["dkim"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(dkim_value)}</td></tr>
      </table>
      <h2 style="font-size:14px;margin:0 0 8px">{value(labels["evidence"])}</h2>
      <ul style="color:#405457;margin:0 0 22px;padding-left:20px">{evidence_html}</ul>
      {action}
      <p style="color:#687a7d;font-size:12px;line-height:1.5;margin:24px 0 0">{value(labels["machine"])}</p>
      <p style="color:#879598;font-size:11px;margin:8px 0 0">{value(labels["generated"])}: {generated}</p>
    </div>
  </div>
</body>
</html>"""


def build_message(
    alert: dict[str, Any],
    settings: dict[str, Any],
    *,
    test: bool = False,
) -> EmailMessage:
    language = str(settings.get("language") or "de")
    labels = _labels(language)
    payload = _payload(alert, settings, test=test)
    event_type = payload["alert"]["event_type"]
    priority = str(payload["alert"]["priority"])
    subject_prefix = labels["test"] if test else labels["alert"]
    subject = _header_value(
        f"[{subject_prefix}][{_priority_label(priority, language)}] "
        f"{_case_title(event_type, language)} · {alert.get('domain') or '-'}",
        500,
    )

    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = ", ".join(settings["recipients"])
    message["Auto-Submitted"] = "auto-generated"
    message["X-DMARC-Control-Schema"] = SCHEMA_VERSION
    message["X-DMARC-Control-Alert-ID"] = _header_value(alert["id"])
    message["X-DMARC-Control-Event-Type"] = _header_value(event_type)
    message["X-DMARC-Control-Priority"] = _header_value(priority)
    message["X-DMARC-Control-Domain"] = _header_value(alert.get("domain"))
    if alert.get("source_ip"):
        message["X-DMARC-Control-Source-IP"] = _header_value(
            alert["source_ip"]
        )
    message.set_content(_plain_text(payload, labels, test=test))
    message.add_alternative(
        _html_body(payload, labels, language, test=test),
        subtype="html",
    )
    message.add_attachment(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename="dmarc-alert.json",
    )
    return message


def _safe_error(value: str, secrets: tuple[str, ...]) -> str:
    message = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:500]


def send_smtp(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> None:
    smtp = settings["smtp"]
    password = secret.get("smtp_password", "")
    username = str(smtp.get("username") or "")
    security = smtp["security"]
    connection: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    try:
        if security == "tls":
            connection = smtplib.SMTP_SSL(
                host=smtp["host"],
                port=int(smtp["port"]),
                timeout=20,
                context=ssl.create_default_context(),
            )
        else:
            connection = smtplib.SMTP(
                host=smtp["host"],
                port=int(smtp["port"]),
                timeout=20,
            )
            connection.ehlo()
            if security == "starttls":
                connection.starttls(context=ssl.create_default_context())
                connection.ehlo()
        if username:
            connection.login(username, password)
        connection.send_message(message)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
        raise NotificationDeliveryError(
            _safe_error(f"SMTP delivery failed: {exc}", (password,))
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.quit()
            except (OSError, smtplib.SMTPException):
                connection.close()


def send_msgraph(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> None:
    graph = settings["graph"]
    client_secret = secret["graph_client_secret"]
    tenant_id = quote(str(graph["tenant_id"]), safe="")
    sender = quote(str(settings["sender"]), safe="")
    secrets_to_redact = (client_secret,)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
        ) as client:
            token_response = client.post(
                f"{GRAPH_TOKEN_ROOT}/{tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": graph["client_id"],
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                    "scope": "https://graph.microsoft.com/.default",
                },
                headers={"Accept": "application/json"},
            )
            if token_response.status_code >= 400:
                raise NotificationDeliveryError(
                    _safe_error(
                        f"Microsoft Entra authentication failed: "
                        f"HTTP {token_response.status_code}",
                        secrets_to_redact,
                    )
                )
            token_payload = token_response.json()
            access_token = (
                str(token_payload.get("access_token") or "")
                if isinstance(token_payload, dict)
                else ""
            )
            if not access_token:
                raise NotificationDeliveryError(
                    "Microsoft Entra returned no access token"
                )
            response = client.post(
                f"{GRAPH_ROOT}/users/{sender}/sendMail",
                content=base64.b64encode(message.as_bytes(policy=SMTP)),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "text/plain",
                },
            )
            if response.status_code >= 400:
                detail = response.text
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error = payload.get("error")
                        if isinstance(error, dict):
                            detail = str(error.get("message") or detail)
                except (TypeError, ValueError):
                    pass
                raise NotificationDeliveryError(
                    _safe_error(
                        f"Microsoft Graph delivery failed: {detail}",
                        secrets_to_redact,
                    )
                )
    except httpx.HTTPError as exc:
        raise NotificationDeliveryError(
            _safe_error(
                f"Microsoft Graph delivery failed: {exc}",
                secrets_to_redact,
            )
        ) from exc


def send_message(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> None:
    if settings["transport"] == "smtp":
        send_smtp(message, settings, secret)
        return
    if settings["transport"] == "msgraph":
        send_msgraph(message, settings, secret)
        return
    raise NotificationDeliveryError("Unsupported notification transport")
