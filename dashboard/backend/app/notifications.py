from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any, Literal
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


@dataclass(frozen=True)
class RecipientDeliveryResult:
    recipient: str
    status: Literal["accepted", "temporary_failure", "permanent_failure"]
    error: str | None = None
    smtp_code: int | None = None


def require_all_accepted(results: list[RecipientDeliveryResult]) -> None:
    """Make partial transport acceptance visible to an explicit test sender."""
    failed = [result for result in results if result.status != "accepted"]
    if results and not failed:
        return
    if not results:
        raise NotificationDeliveryError("No recipient delivery results were returned")
    detail = "; ".join(
        f"{result.recipient}: {result.error or result.status}" for result in failed
    )
    raise NotificationDeliveryError(
        _safe_error(
            f"{len(results) - len(failed)} of {len(results)} recipients accepted; {detail}",
            (),
        )
    )


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


def _navigation_context(settings: dict[str, Any], domain: Any) -> dict[str, str | int]:
    selected_domain = "*"
    if isinstance(domain, str):
        candidate = domain.strip()
        try:
            ascii_domain = candidate.removesuffix(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            ascii_domain = ""
        if (
            1 <= len(candidate) <= 253
            and 1 <= len(ascii_domain) <= 253
            and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in ascii_domain.split("."))
        ):
            # Keep the observed spelling: OpenSearch domain filters are exact.
            selected_domain = candidate
    days = settings.get("lookback_days")
    if isinstance(days, str) and re.fullmatch(r"[0-9]{1,3}", days.strip()):
        days = int(days.strip())
    if type(days) is not int or not 1 <= days <= 730:
        days = 30
    return {"domain": selected_domain, "days": days}


def _dashboard_link(settings: dict[str, Any], alert_id: str, domain: Any = None) -> str | None:
    base_url = str(settings.get("dashboard_url") or "").strip().rstrip("/")
    if not base_url:
        return None
    parameters = {"view": "alerts", "alert": alert_id, **_navigation_context(settings, domain)}
    return f"{base_url}/?{urlencode(parameters)}"


def _host_link(
    settings: dict[str, Any],
    alert_id: str,
    source_ip: str | None,
    domain: Any = None,
) -> str | None:
    base_url = str(settings.get("dashboard_url") or "").strip().rstrip("/")
    if not base_url or not source_ip:
        return None
    parameters = {
        "view": "hosts",
        "host": source_ip,
        "from_alert": alert_id,
        **_navigation_context(settings, domain),
    }
    return f"{base_url}/?{urlencode(parameters)}"


def _labels(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "alert": "DMARC alert",
            "test": "DMARC Control test email",
            "priority": "Priority",
            "domain": "Domain",
            "source": "Source IP",
            "country": "Country",
            "service": "Assigned service",
            "mode": "Assignment",
            "automatic_service": "Automatic alternative",
            "automatic": "Automatic",
            "manual": "Manual",
            "legacy_preserved": "Existing assignment retained",
            "trigger": "Trigger",
            "report_time": "Report time",
            "messages": "Affected messages",
            "total_messages": "Total messages",
            "dmarc": "DMARC result",
            "spf": "SPF alignment",
            "dkim": "DKIM alignment",
            "evidence": "Classification evidence",
            "open": "Open alert in DMARC Control",
            "investigate": "Investigate sending host",
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
        "service": "Zugeordneter Dienst",
        "mode": "Zuordnung",
        "automatic_service": "Automatische Alternative",
        "automatic": "Automatisch",
        "manual": "Manuell",
        "legacy_preserved": "Bestehende Zuordnung übernommen",
        "trigger": "Auslöser",
        "report_time": "Reportzeit",
        "messages": "Betroffene Nachrichten",
        "total_messages": "Nachrichten insgesamt",
        "dmarc": "DMARC-Ergebnis",
        "spf": "SPF-Alignment",
        "dkim": "DKIM-Alignment",
        "evidence": "Klassifizierungsevidenz",
        "open": "Warnung in DMARC Control öffnen",
        "investigate": "Sending Host untersuchen",
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


def _alert_title(alert: dict[str, Any], language: str) -> str:
    if alert.get("event_type") == "stale-reports":
        if alert.get("freshness_reason") == "never_observed":
            return "First DMARC report is missing" if language == "en" else "Erster DMARC-Report fehlt"
        if alert.get("freshness_reason") == "reactivated":
            return ("No new DMARC report after reactivation" if language == "en"
                    else "Kein neuer DMARC-Report nach Reaktivierung")
    return _case_title(alert["event_type"], language)


def _alert_trigger(alert: dict[str, Any], language: str) -> str:
    if language == "en" and alert.get("event_type") == "stale-reports":
        if alert.get("freshness_reason") == "never_observed":
            return "No first report has been observed since monitoring began; the waiting period has expired."
        if alert.get("freshness_reason") == "reactivated":
            return "No report period has ended since reactivation; the new waiting period has expired."
    return str(alert.get("trigger") or "")


def _freshness_rows(alert: dict[str, Any], language: str) -> list[tuple[str, Any]]:
    if alert.get("event_type") != "stale-reports" or not alert.get("grace_days"):
        return []
    english = language == "en"
    rows = []
    if alert.get("monitoring_started_at"):
        rows.append(("Monitoring began" if english else "Beginn der Überwachung", alert["monitoring_started_at"]))
    rows.append(("Waiting period (days)" if english else "Wartefrist (Tage)", alert["grace_days"]))
    if alert.get("deadline"):
        rows.append(("Warning after" if english else "Warnung nach", alert["deadline"]))
    return rows


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
        "total_messages": 1,
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
    total_messages = alert.get("total_messages")
    if total_messages is None:
        # Older snapshots contain authentication totals but no explicit volume.
        total_messages = max(
            int(alert.get("messages") or 0),
            int(alert.get("dmarc_pass") or 0) + int(alert.get("dmarc_fail") or 0),
        )
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
            "freshness_reason": alert.get("freshness_reason"),
            "monitoring_started_at": alert.get("monitoring_started_at"),
            "monitoring_episode_id": alert.get("monitoring_episode_id"),
            "grace_days": alert.get("grace_days"),
            "deadline": alert.get("deadline"),
            "affected_messages": alert.get("messages", 0),
            "total_messages": total_messages,
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
            "mode": alert.get("classification_mode"),
            "automatic_detection": alert.get("automatic_detection"),
            "evidence_details": alert.get("service_evidence_details") or [],
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
            "dashboard": _dashboard_link(settings, str(alert["id"]), alert.get("domain")),
            "host": _host_link(
                settings,
                str(alert["id"]),
                alert.get("source_ip"),
                alert.get("domain"),
            ),
        },
    }


def _classification_rows(classification: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str]]:
    mode = classification.get("mode")
    if mode not in {"automatic", "manual", "legacy_preserved"}:
        return []
    rows = [(labels["mode"], labels[mode])]
    automatic = classification.get("automatic_detection")
    if mode != "automatic" and automatic:
        rows.append((labels["automatic_service"], str(automatic["service"])))
    return rows


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
    language = "en" if labels["alert"] == "DMARC alert" else "de"
    rows = [
        _alert_title(alert, language),
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
            *[f"{label}: {content}" for label, content in _classification_rows(classification, labels)],
            f"{labels['trigger']}: {_alert_trigger(alert, language)}",
            f"{labels['report_time']}: {alert['report_time'] or labels['not_available']}",
            *[f"{label}: {content}" for label, content in _freshness_rows(alert, language)],
            f"{labels['messages']}: {alert['affected_messages']}",
            f"{labels['total_messages']}: {alert['total_messages']}",
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
    if payload["links"]["host"]:
        rows.extend(
            [f"{labels['investigate']}: {payload['links']['host']}", ""]
        )
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
    classification_rows = "".join(
        f'<tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(label)}</td>'
        f'<td style="padding:9px 0;border-top:1px solid #e7eded">{value(content)}</td></tr>'
        for label, content in _classification_rows(classification, labels)
    )
    freshness_rows = "".join(
        f'<tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(label)}</td>'
        f'<td style="padding:9px 0;border-top:1px solid #e7eded">{value(content)}</td></tr>'
        for label, content in _freshness_rows(alert, language)
    )
    evidence = classification["evidence"]
    evidence_html = (
        "".join(f"<li>{value(item)}</li>" for item in evidence)
        if evidence
        else f"<li>{value(labels['not_available'])}</li>"
    )
    link = payload["links"]["dashboard"]
    alert_action = (
        f'<a href="{html.escape(link, quote=True)}" '
        f'style="display:inline-block;background:#173f43;color:#fff;'
        f'text-decoration:none;border-radius:8px;padding:11px 16px;'
        f'font-weight:700">{html.escape(labels["open"])}</a>'
        if link
        else ""
    )
    host_link = payload["links"]["host"]
    host_action = (
        f'<a href="{html.escape(host_link, quote=True)}" '
        f'style="display:inline-block;background:#fff;color:#173f43;'
        f'border:1px solid #173f43;text-decoration:none;border-radius:8px;'
        f'padding:10px 15px;font-weight:700;margin-left:8px">'
        f'{html.escape(labels["investigate"])}</a>'
        if host_link
        else ""
    )
    actions = f'<div style="margin-top:4px">{alert_action}{host_action}</div>'
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
      <h1 style="font-size:22px;line-height:1.3;margin:8px 0 0">{value(_alert_title(alert, language))}</h1>
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
        {classification_rows}
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["trigger"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(_alert_trigger(alert, language))}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["report_time"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["report_time"])}</td></tr>
        {freshness_rows}
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["messages"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["affected_messages"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["total_messages"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(alert["total_messages"])}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["dmarc"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(dmarc_value)}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["spf"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(spf_value)}</td></tr>
        <tr><td style="padding:9px 0;color:#687a7d;border-top:1px solid #e7eded">{value(labels["dkim"])}</td><td style="padding:9px 0;border-top:1px solid #e7eded">{value(dkim_value)}</td></tr>
      </table>
      <h2 style="font-size:14px;margin:0 0 8px">{value(labels["evidence"])}</h2>
      <ul style="color:#405457;margin:0 0 22px;padding-left:20px">{evidence_html}</ul>
      {actions}
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
        f"{_alert_title(payload['alert'], language)} · {alert.get('domain') or '-'}",
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
    message = value
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    message = " ".join(message.replace("\r", " ").replace("\n", " ").split())
    return message[:500]


def _smtp_rejection(
    recipient: str,
    code: int,
    detail: Any,
    secrets: tuple[str, ...],
) -> RecipientDeliveryResult:
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return RecipientDeliveryResult(
        recipient=recipient,
        status="permanent_failure" if 500 <= code < 600 else "temporary_failure",
        error=_safe_error(f"SMTP {code}: {detail}", secrets),
        smtp_code=code,
    )


def _smtp_recipient_results(
    recipients: list[str],
    refused: dict,
    secrets: tuple[str, ...],
    *,
    all_refused: bool = False,
) -> list[RecipientDeliveryResult]:
    refusals = {str(recipient).casefold(): detail for recipient, detail in refused.items()}
    results = []
    for recipient in recipients:
        refusal = refusals.get(recipient.casefold())
        if refusal is not None:
            code, detail = refusal
            results.append(_smtp_rejection(recipient, int(code), detail, secrets))
        elif all_refused:
            results.append(RecipientDeliveryResult(
                recipient, "temporary_failure",
                "SMTP rejected all recipients without an individual response",
            ))
        else:
            results.append(RecipientDeliveryResult(recipient, "accepted"))
    return results


def _recipient_failures(
    recipients: list[str],
    message: str,
    secrets: tuple[str, ...],
    *,
    permanent: bool = False,
) -> list[RecipientDeliveryResult]:
    error = _safe_error(message, secrets)
    return [
        RecipientDeliveryResult(
            recipient, "permanent_failure" if permanent else "temporary_failure", error
        )
        for recipient in recipients
    ]


def _preserve_rcpt_rejections(
    results: list[RecipientDeliveryResult],
    refused: dict,
    secrets: tuple[str, ...],
) -> list[RecipientDeliveryResult]:
    """A subsequent DATA/network error must not replace earlier RCPT replies."""
    refusals = {str(recipient).casefold(): detail for recipient, detail in refused.items()}
    return [
        _smtp_rejection(result.recipient, int(refusals[result.recipient.casefold()][0]),
                        refusals[result.recipient.casefold()][1], secrets)
        if result.recipient.casefold() in refusals else result
        for result in results
    ]


def send_smtp(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> list[RecipientDeliveryResult]:
    smtp = settings["smtp"]
    password = secret.get("smtp_password", "")
    username = str(smtp.get("username") or "")
    security = smtp["security"]
    recipients = list(settings["recipients"])
    connection: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    rcpt_rejections: dict[str, tuple[int, bytes]] = {}
    original_rcpt = None
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
        original_rcpt = connection.rcpt

        def record_rcpt(recipient: str, *args, **kwargs):
            response = original_rcpt(recipient, *args, **kwargs)
            if response[0] not in {250, 251}:
                rcpt_rejections[recipient] = response
            return response

        # Keep the stdlib's MIME/SMTPUTF8 handling, but retain RCPT responses
        # that send_message cannot return when its subsequent DATA step fails.
        connection.rcpt = record_rcpt
        refused = connection.send_message(
            message, from_addr=settings["sender"], to_addrs=recipients
        )
        return _smtp_recipient_results(recipients, refused, (password,))
    except smtplib.SMTPRecipientsRefused as exc:
        return _smtp_recipient_results(
            recipients, {**rcpt_rejections, **exc.recipients}, (password,), all_refused=True
        )
    except smtplib.SMTPResponseException as exc:
        return _preserve_rcpt_rejections(
            [_smtp_rejection(recipient, exc.smtp_code, exc.smtp_error, (password,))
             for recipient in recipients],
            rcpt_rejections, (password,),
        )
    except (smtplib.SMTPNotSupportedError, ssl.SSLCertVerificationError) as exc:
        return _preserve_rcpt_rejections(
            _recipient_failures(
                recipients, f"SMTP delivery failed: {exc}", (password,), permanent=True
            ), rcpt_rejections, (password,),
        )
    except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
        return _preserve_rcpt_rejections(
            _recipient_failures(recipients, f"SMTP delivery failed: {exc}", (password,)),
            rcpt_rejections, (password,),
        )
    finally:
        if connection is not None:
            if original_rcpt is not None:
                connection.rcpt = original_rcpt
            try:
                connection.quit()
            except (OSError, smtplib.SMTPException):
                try:
                    connection.close()
                except (OSError, smtplib.SMTPException):
                    pass


def send_msgraph(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> list[RecipientDeliveryResult]:
    graph = settings["graph"]
    client_secret = secret["graph_client_secret"]
    tenant_id = quote(str(graph["tenant_id"]), safe="")
    sender = quote(str(settings["sender"]), safe="")
    secrets_to_redact = (client_secret,)
    recipients = list(settings["recipients"])
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
            if not 200 <= token_response.status_code < 300:
                return _recipient_failures(
                    recipients,
                    f"Microsoft Entra authentication failed: HTTP {token_response.status_code}",
                    secrets_to_redact,
                    permanent=not _temporary_http_status(token_response.status_code),
                )
            token_payload = token_response.json()
            access_token = (
                str(token_payload.get("access_token") or "")
                if isinstance(token_payload, dict)
                else ""
            )
            if not access_token:
                return _recipient_failures(
                    recipients, "Microsoft Entra returned no access token", secrets_to_redact
                )
            secrets_to_redact = (client_secret, access_token)
            graph_message = copy.deepcopy(message)
            # Graph addresses MIME recipients, so retries must also narrow the
            # headers rather than retain recipients from the original message.
            for header in list(graph_message.keys()):
                if header.lower() in {"to", "cc", "bcc"} or header.lower().startswith("resent-"):
                    del graph_message[header]
            graph_message["To"] = ", ".join(recipients)
            response = client.post(
                f"{GRAPH_ROOT}/users/{sender}/sendMail",
                content=base64.b64encode(graph_message.as_bytes(policy=SMTP)),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "text/plain",
                },
            )
            if not 200 <= response.status_code < 300:
                detail = response.text
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error = payload.get("error")
                        if isinstance(error, dict):
                            detail = str(error.get("message") or detail)
                except (TypeError, ValueError):
                    pass
                return _recipient_failures(
                    recipients,
                    f"Microsoft Graph delivery failed (HTTP {response.status_code}): {detail}",
                    secrets_to_redact,
                    permanent=not _temporary_http_status(response.status_code),
                )
            return [RecipientDeliveryResult(recipient, "accepted") for recipient in recipients]
    except (httpx.HTTPError, ValueError) as exc:
        return _recipient_failures(
            recipients, f"Microsoft Graph delivery failed: {exc}", secrets_to_redact
        )


def _temporary_http_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status < 600


def send_message(
    message: EmailMessage,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> list[RecipientDeliveryResult]:
    if settings["transport"] == "smtp":
        return send_smtp(message, settings, secret)
    if settings["transport"] == "msgraph":
        return send_msgraph(message, settings, secret)
    raise NotificationDeliveryError("Unsupported notification transport")
