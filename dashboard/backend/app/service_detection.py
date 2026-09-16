"""Mail-service hints with explicit provenance, not sender authorization.

Aggregated identities describe observations, not successful authentication. Even
a successful provider-domain SPF/DKIM result does not establish DMARC alignment
with the user's From domain or approval to send for that domain.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class DomainRule:
    service: str
    domain: str
    rule_id: str
    identifies_service: bool = True


# Most-specific matching rule wins for each observed value. Broader hosting
# identities can support a mail-service hint but cannot create one themselves.
DOMAIN_RULES = (
    DomainRule("SMTP2GO", "smtp2go.com", "smtp2go.primary_domain"),
    DomainRule("SMTP2GO", "smtpservice.net", "smtp2go.signing_domain"),
    DomainRule("SMTP2GO", "deft.com", "smtp2go.hosting_domain", False),
    DomainRule("Microsoft 365", "outbound.protection.outlook.com", "microsoft365.outbound_domain"),
    DomainRule("Microsoft 365", "protection.outlook.com", "microsoft365.protection_domain"),
    DomainRule("Microsoft 365", "onmicrosoft.com", "microsoft365.tenant_domain"),
    DomainRule("Microsoft 365", "outlook.com", "microsoft365.mail_domain"),
    DomainRule("Microsoft 365", "microsoft.com", "microsoft365.organization_domain", False),
    DomainRule("Google Workspace", "_spf.google.com", "google_workspace.spf_domain"),
    DomainRule("Google Workspace", "googlemail.com", "google_workspace.mail_domain"),
    DomainRule("Google Workspace", "google.com", "google_workspace.organization_domain", False),
    DomainRule("Amazon SES", "amazonses.com", "amazon_ses.mail_domain"),
    DomainRule("Amazon SES", "amazonaws.com", "amazon_ses.hosting_domain", False),
    DomainRule("Mailchimp", "mailchimp.com", "mailchimp.primary_domain"),
    DomainRule("Mailchimp", "mandrillapp.com", "mailchimp.transactional_domain"),
)

_TRUSTED_SOURCE_TYPES = {"saas", "email service", "esp", "mail provider"}
_NAME_ALIASES = {
    "smtp2go": "SMTP2GO",
    "microsoft 365": "Microsoft 365",
    "office 365": "Microsoft 365",
    "microsoft office 365": "Microsoft 365",
    "exchange online": "Microsoft 365",
    "google workspace": "Google Workspace",
    "g suite": "Google Workspace",
    "gsuite": "Google Workspace",
    "amazon ses": "Amazon SES",
    "amazon simple email service": "Amazon SES",
    "mailchimp": "Mailchimp",
    "mandrill": "Mailchimp",
    "mailchimp transactional": "Mailchimp",
}
_SERVICE_IDS = {
    "SMTP2GO": "smtp2go",
    "Microsoft 365": "microsoft365",
    "Google Workspace": "google_workspace",
    "Amazon SES": "amazon_ses",
    "Mailchimp": "mailchimp",
}
_ASN_NAMES = (
    ("SMTP2GO", r"\bdeft\b", "smtp2go.asn_name"),
    ("Microsoft 365", r"\bmicrosoft\b", "microsoft365.asn_name"),
    ("Google Workspace", r"\bgoogle\b", "google_workspace.asn_name"),
    ("Amazon SES", r"\bamazon(?:aws)?\b", "amazon_ses.asn_name"),
    ("Mailchimp", r"\b(?:mailchimp|mandrill)\b", "mailchimp.asn_name"),
)
_AUTH_RESULTS = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "policy"}


def _domain(value: Any) -> str | None:
    """Normalize a DNS name; URLs, addresses and deceptive suffixes stay invalid."""
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    if name.endswith("."):
        name = name[:-1]
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if len(name) > 253 or "." not in name:
        return None
    labels = name.split(".")
    if any(not re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?", label) for label in labels):
        return None
    return name


def _matching_rule(value: str) -> DomainRule | None:
    matches = [rule for rule in DOMAIN_RULES if value == rule.domain or value.endswith("." + rule.domain)]
    return max(matches, key=lambda rule: len(rule.domain), default=None)


@dataclass
class _Candidate:
    weights: dict[str, float] = field(default_factory=dict)
    details: list[dict[str, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    identifies_service: bool = False
    authenticated_identity: bool = False

    def add(self, *, origin: str, value: str, rule_id: str, group: str,
            weight: float, label: str, identifies_service: bool,
            auth_result: str | None = None) -> None:
        detail: dict[str, Any] = {
            "origin": origin, "value": value, "rule_id": rule_id,
            "independence_group": group,
        }
        if auth_result is not None:
            detail["auth_result"] = auth_result
        if detail not in self.details:
            self.details.append(detail)
            self.labels.append(label)
        self.weights[group] = max(self.weights.get(group, 0), weight)
        self.identifies_service |= identifies_service
        # A successful generic cloud identity is not a successful mail-service
        # identity and must not unlock a high-confidence provider attribution.
        self.authenticated_identity |= identifies_service and auth_result == "pass"

    def confidence(self) -> float:
        score = round(sum(self.weights.values()), 2)
        if len(self.weights) < 2 or not self.authenticated_identity:
            score = min(score, 0.79)
        return min(score, 0.99)


def _dynamic_profile(source: dict[str, Any], trusted_source: bool) -> dict[str, Any] | None:
    ptr = _domain(source.get("source_reverse_dns"))
    if not ptr or trusted_source:
        return None
    try:
        address = ipaddress.ip_address(str(source.get("source_ip_address") or ""))
    except ValueError:
        return None
    if address.version != 4 or not address.is_global:
        return None
    tokens = set(re.findall(r"[a-z0-9]+", ptr))
    dynamic = {"bbcs", "broadband", "cable", "dhcp", "dial", "dialup", "dsl", "dyn", "dynamic", "pool", "ppp", "pppoe", "residential"}
    if not tokens & dynamic or tokens & {"static", "fixed", "dedicated"}:
        return None
    octets = str(address).split(".")
    patterns = {separator.join(parts) for parts in (octets, list(reversed(octets))) for separator in (".", "-")}
    if not any(re.search(r"(?<![0-9])" + re.escape(pattern) + r"(?![0-9])", ptr) for pattern in patterns):
        return None
    return {
        "service": "Dynamischer IP-Bereich", "service_id": None,
        "confidence": 0.54,
        "confidence_label": "Niedrig", "profile": "dynamic_ip",
        "evidence": ["PTR: Quell-IP eingebettet", "PTR: dynamisches Anschlussmuster"],
        "evidence_details": [
            {"origin": "source_reverse_dns", "value": ptr, "rule_id": rule,
             "independence_group": "network_identity"}
            for rule in ("dynamic_ip.embedded_address", "dynamic_ip.connection_pattern")
        ],
    }


def score_service(
    source: dict[str, Any], *, spf_domains: Iterable[str] = (),
    dkim_domains: Iterable[str] = (), dkim_selectors: Iterable[str] = (),
) -> dict[str, Any]:
    """Return an explainable provider hint from observations of one source IP.

    Selectors are accepted for caller compatibility but do not identify a
    provider. Domain/result pairs are read together only from individual raw
    result entries. Flat aggregation terms never imply an authentication pass.
    """
    candidates: dict[str, _Candidate] = {}

    def observe_domain(raw: Any, *, origin: str, group: str, weight: float,
                       label: str, auth_result: str | None = None) -> None:
        value = _domain(raw)
        rule = _matching_rule(value) if value else None
        if rule is None:
            return
        # ASN identities and generic hosting domains are supporting context.
        identifies = rule.identifies_service and group != "asn"
        candidates.setdefault(rule.service, _Candidate()).add(
            origin=origin, value=value, rule_id=rule.rule_id, group=group,
            weight=weight if identifies else min(weight, 0.15),
            label=f"{label}: {value}", identifies_service=identifies,
            auth_result=auth_result,
        )

    for origin, label in (("source_reverse_dns", "PTR"), ("source_base_domain", "PTR-Basisdomain")):
        observe_domain(source.get(origin), origin=origin, group="network_identity", weight=0.30, label=label)
    observe_domain(source.get("source_as_domain"), origin="source_as_domain", group="asn", weight=0.15, label="ASN-Domain")
    as_name = str(source.get("source_as_name") or "").strip()
    for service, pattern, rule_id in _ASN_NAMES:
        if re.search(pattern, as_name.lower()):
            candidates.setdefault(service, _Candidate()).add(
                origin="source_as_name", value=as_name, rule_id=rule_id,
                group="asn", weight=0.15, label=f"ASN-Name: {as_name}",
                identifies_service=False,
            )

    trusted_source = str(source.get("source_type") or "").strip().lower() in _TRUSTED_SOURCE_TYPES
    name = str(source.get("source_name") or "").strip()
    service = _NAME_ALIASES.get(" ".join(name.lower().split()))
    if trusted_source and service:
        candidates.setdefault(service, _Candidate()).add(
            origin="source_name", value=name, rule_id="parsedmarc.service_name",
            group="network_identity", weight=0.50, label=f"parsedmarc: {name}",
            identifies_service=True,
        )

    for mechanism, domains in (("spf", spf_domains), ("dkim", dkim_domains)):
        for value in domains:
            observe_domain(value, origin=f"{mechanism}_domains", group=mechanism,
                           weight=0.20, label=f"{mechanism.upper()}-Domain (aggregiert, Ergebnis unbekannt)")
        results = source.get(f"{mechanism}_results")
        # Do not reconstruct domain/result pairs from separate arrays or terms.
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            raw_result = result.get("result")
            auth_result = raw_result.strip().lower() if isinstance(raw_result, str) else "unknown"
            if auth_result not in _AUTH_RESULTS:
                auth_result = "unknown"
            observe_domain(result.get("domain"), origin=f"{mechanism}_results.domain",
                           group=mechanism, weight=0.45 if auth_result == "pass" else 0.10,
                           label=f"{mechanism.upper()} ({auth_result})", auth_result=auth_result)

    identified = [(service, item) for service, item in candidates.items() if item.identifies_service]
    if not identified:
        dynamic = _dynamic_profile(source, trusted_source)
        if dynamic:
            return dynamic
        return {"service": "Unbekannt", "service_id": None,
                "confidence": 0, "confidence_label": "Keine Zuordnung",
                "evidence": [], "evidence_details": [], "profile": "unknown"}
    service, result = min(identified, key=lambda item: (-item[1].confidence(), item[0]))
    confidence = result.confidence()
    labels = list(result.labels)
    details = list(result.details)
    conflicting_services = sorted(
        name for name, candidate in identified
        if name != service and candidate.authenticated_identity
    )
    if conflicting_services:
        # Several successful provider identities can describe forwarding or
        # shared infrastructure. They do not uniquely establish this provider.
        confidence = min(confidence, 0.79)
        authenticated_services = sorted(
            name for name, candidate in identified if candidate.authenticated_identity
        )
        if len(authenticated_services) > 1:
            conflict_value = ", ".join(authenticated_services)
            labels.append("Mehrdeutige Provider-Herkunft: bestandene Authentifizierungen für " + conflict_value)
            details.append({
                "origin": "source_auth_conflict", "value": conflict_value,
                "rule_id": "service.multiple_authenticated_providers",
                "independence_group": "auth_conflict", "auth_result": "pass",
            })
    return {
        "service": service, "service_id": _SERVICE_IDS[service],
        "confidence": confidence,
        "confidence_label": "Hoch" if confidence >= 0.80 else "Mittel" if confidence >= 0.55 else "Niedrig",
        "evidence": labels, "evidence_details": details,
        "profile": "mail_service",
    }
