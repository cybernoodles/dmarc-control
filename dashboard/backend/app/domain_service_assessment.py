"""DNS-backed, explainable domain-to-mail-service assessment.

This module deliberately does not decide whether an individual message or source
IP is authorized.  It describes the *current* DNS configuration of a domain and
keeps every network failure distinguishable from a negative DNS result.

The resolver protocol and parsing helpers are intentionally small so callers can
inject deterministic fakes without importing or patching dnspython internals.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol

import idna


DnsLookupStatus = Literal[
    "answer", "nxdomain", "nodata", "timeout", "servfail", "refused", "unavailable"
]
DnsStatus = Literal["fresh", "negative", "invalid", "unavailable"]
Assessment = Literal["unknown", "configured", "strong"]


SERVICE_CATALOG: Mapping[str, Mapping[str, Any]] = {
    "microsoft365": {
        "label": "Microsoft 365",
        # Exchange Online MX records have a tenant-specific label before this
        # suffix.  The bare suffix is intentionally not accepted.
        "mx_suffixes": (
            "mail.protection.outlook.com",
            "mail.protection.office365.us",
            "mail.protection.partner.outlook.cn",
            "mx.microsoft",
        ),
        "spf_domains": {
            "spf.protection.outlook.com": "commercial",
            "spf.protection.office365.us": "gcc",
            "spf.protection.partner.outlook.cn": "21vianet",
        },
        # Microsoft supports both its established onmicrosoft.com delegation and
        # the newer dedicated DKIM namespace.
        "dkim_suffixes": {
            "onmicrosoft.com": "onmicrosoft",
            "dkim.mail.microsoft": "mail_microsoft",
        },
        "selectors": ("selector1", "selector2"),
    },
}


@dataclass(frozen=True)
class DnsLookup:
    """Normalized resolver result.

    ``values`` contain complete TXT strings or normalized presentation values
    for MX/CNAME.  ``ttl_seconds`` is the authoritative answer/negative-cache
    TTL when available; zero means that the result must not be cached.
    """

    status: DnsLookupStatus
    values: tuple[str, ...] = ()
    ttl_seconds: int = 0


class DnsResolver(Protocol):
    async def resolve(self, name: str, rdtype: str) -> DnsLookup:
        """Resolve one absolute DNS name without applying a search suffix."""


@dataclass(frozen=True)
class SpfReference:
    kind: Literal["include", "redirect"]
    domain: str
    qualifier: str
    positive: bool
    reachable: bool = True


@dataclass(frozen=True)
class ParsedSpf:
    references: tuple[SpfReference, ...]
    errors: tuple[str, ...] = ()
    dns_lookup_terms: int = 0


def normalize_dns_name(value: Any, *, allow_underscores: bool = False) -> str | None:
    """Return a strict lower-case A-label DNS name or ``None``.

    URLs, addresses, wildcard labels and deceptive appended suffixes are not
    coerced into hostnames.  A trailing root dot is accepted.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip().removesuffix(".")
    if not candidate:
        return None
    try:
        if allow_underscores:
            normalized_labels = []
            for label in candidate.split("."):
                if "_" in label:
                    if not label.isascii():
                        return None
                    normalized_labels.append(label.lower())
                else:
                    normalized_labels.append(idna.encode(
                        label, uts46=True, std3_rules=True, transitional=False,
                    ).decode("ascii").lower())
            normalized = ".".join(normalized_labels)
        else:
            normalized = idna.encode(
                candidate, uts46=True, std3_rules=True, transitional=False,
            ).decode("ascii").lower()
    except (UnicodeError, idna.IDNAError):
        return None
    if not 1 <= len(normalized) <= 253:
        return None
    if not all(
        re.fullmatch(
            (r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?"
             if allow_underscores else
             r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"),
            label,
        )
        for label in normalized.split(".")
    ):
        return None
    return normalized


def is_strict_subdomain(value: Any, suffix: str) -> bool:
    """Match a DNS suffix at a label boundary, requiring a child label."""

    name = normalize_dns_name(value, allow_underscores=True)
    parent = normalize_dns_name(suffix)
    return bool(name and parent and name != parent and name.endswith("." + parent))


def spf_records(values: tuple[str, ...]) -> tuple[str, ...]:
    """Select complete SPF TXT records without accepting prefix lookalikes."""

    return tuple(
        value.strip() for value in values
        if isinstance(value, str) and re.match(r"(?i)^v=spf1(?:\s|$)", value.strip())
    )


_SPF_MACRO_EXPANSION = re.compile(
    r"%\{[slodiphcrtv][0-9]*r?[.\-+,/_=]*\}", re.IGNORECASE,
)
_SPF_NAME = re.compile(r"[a-z][a-z0-9_.-]*", re.IGNORECASE)
_SPF_MECHANISMS = {"all", "include", "a", "mx", "ptr", "ip4", "ip6", "exists"}


def _valid_macro_string(value: str) -> bool:
    """Validate SPF macro syntax without expanding transaction-dependent data."""

    index = 0
    while index < len(value):
        character = value[index]
        if not "!" <= character <= "~":
            return False
        if character != "%":
            index += 1
            continue
        if index + 1 >= len(value):
            return False
        if value[index + 1] in {"%", "_", "-"}:
            index += 2
            continue
        expansion = _SPF_MACRO_EXPANSION.match(value, index)
        if expansion is None:
            return False
        index = expansion.end()
    return True


def _normalize_spf_domain_spec(value: str) -> str | None:
    """Return a static SPF target, or ``None`` for valid macro-based targets."""

    if not value or not _valid_macro_string(value):
        raise ValueError("Invalid SPF domain specification")
    if "%" in value:
        return None
    domain = normalize_dns_name(value, allow_underscores=True)
    if domain is None:
        raise ValueError("Invalid SPF domain specification")
    labels = domain.split(".")
    top_label = labels[-1]
    if (
        len(labels) < 2
        or "_" in top_label
        or (
            "-" not in top_label
            and not any("a" <= char <= "z" for char in top_label)
        )
    ):
        raise ValueError("Invalid SPF domain specification")
    return domain


def _valid_cidr_length(value: str | None, maximum: int) -> bool:
    if value is None:
        return True
    return bool(
        (value == "0" or re.fullmatch(r"[1-9][0-9]{0,2}", value))
        and int(value) <= maximum
    )


def _parse_a_or_mx(term: str, mechanism: str) -> bool:
    match = re.fullmatch(
        rf"({mechanism}(?::.+?)?)(?:/([0-9]+))?(?://([0-9]+))?",
        term,
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    base, ipv4_length, ipv6_length = match.groups()
    if not _valid_cidr_length(ipv4_length, 32):
        return False
    if not _valid_cidr_length(ipv6_length, 128):
        return False
    if ":" not in base:
        return base.lower() == mechanism
    name, domain_spec = base.split(":", 1)
    if name.lower() != mechanism:
        return False
    try:
        _normalize_spf_domain_spec(domain_spec)
    except ValueError:
        return False
    return True


def _valid_ip_mechanism(term: str, version: int) -> bool:
    prefix = f"ip{version}:"
    if not term.lower().startswith(prefix):
        return False
    value = term[len(prefix):]
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return network.version == version


def _all_mechanism(term: str) -> bool:
    directive = term[1:] if term[:1] in "+-~?" else term
    return directive.lower() == "all"


def parse_spf_record(record: str) -> ParsedSpf:
    """Extract the SPF references relevant to service attribution.

    Only a default/``+`` include can authorize the included policy.  Other
    qualifiers and mechanisms placed after an ``all`` mechanism are retained as
    non-positive references.  A redirect is effective only when the record has
    no ``all`` mechanism.  DNS-triggering terms are counted without evaluating
    ``a``, ``mx``, ``ptr`` or ``exists`` against a client address.  This is not
    a full SPF evaluator; it purposefully follows only include/redirect policy
    references.
    """

    value = str(record)
    if any(character.isspace() and character != " " for character in value):
        return ParsedSpf((), ("invalid_syntax",))
    text = value.strip(" ")
    terms = re.split(r" +", text) if text else []
    if not terms or terms[0].lower() != "v=spf1":
        return ParsedSpf((), ("invalid_version",))

    body = terms[1:]
    all_positions = [
        index for index, term in enumerate(body)
        if _all_mechanism(term)
    ]
    first_all = min(all_positions, default=None)
    errors: list[str] = []
    references: list[SpfReference] = []
    dns_lookup_terms = 0
    redirect_count = 0
    explanation_count = 0

    for index, term in enumerate(body):
        qualifier = term[0] if term[:1] in "+-~?" else "+"
        directive = term[1:] if term[:1] in "+-~?" else term
        reachable = first_all is None or index < first_all

        if "=" in directive:
            if term[:1] in "+-~?":
                errors.append("invalid_modifier")
                continue
            name, modifier_value = directive.split("=", 1)
            if _SPF_NAME.fullmatch(name) is None or not _valid_macro_string(
                modifier_value,
            ):
                errors.append("invalid_modifier")
                continue
            name = name.lower()
            if name == "redirect":
                redirect_count += 1
                try:
                    domain = _normalize_spf_domain_spec(modifier_value)
                except ValueError:
                    errors.append("invalid_redirect_domain")
                    continue
                redirect_reachable = first_all is None
                if redirect_reachable:
                    dns_lookup_terms += 1
                if domain is not None:
                    references.append(SpfReference(
                        "redirect", domain, "+", redirect_reachable,
                        redirect_reachable,
                    ))
            elif name == "exp":
                explanation_count += 1
                try:
                    _normalize_spf_domain_spec(modifier_value)
                except ValueError:
                    errors.append("invalid_explanation_domain")
            # Unknown, syntactically valid modifiers are intentionally ignored.
            continue

        lower = directive.lower()
        if lower == "all":
            continue

        if lower.startswith("include:"):
            domain_spec = directive[len("include:"):]
            try:
                domain = _normalize_spf_domain_spec(domain_spec)
            except ValueError:
                errors.append("invalid_include_domain")
                continue
            if reachable:
                dns_lookup_terms += 1
            if domain is not None:
                references.append(SpfReference(
                    "include", domain, qualifier,
                    qualifier == "+" and reachable,
                    reachable,
                ))
            continue

        if _parse_a_or_mx(directive, "a"):
            if reachable:
                dns_lookup_terms += 1
            continue
        if _parse_a_or_mx(directive, "mx"):
            if reachable:
                dns_lookup_terms += 1
            continue

        if lower == "ptr" or lower.startswith("ptr:"):
            if ":" in directive:
                try:
                    _normalize_spf_domain_spec(directive.split(":", 1)[1])
                except ValueError:
                    errors.append("invalid_ptr")
                    continue
            if reachable:
                dns_lookup_terms += 1
            continue

        if lower.startswith("exists:"):
            try:
                _normalize_spf_domain_spec(directive[len("exists:"):])
            except ValueError:
                errors.append("invalid_exists")
                continue
            if reachable:
                dns_lookup_terms += 1
            continue

        if lower.startswith("ip4:"):
            if not _valid_ip_mechanism(directive, 4):
                errors.append("invalid_ip4")
            continue
        if lower.startswith("ip6:"):
            if not _valid_ip_mechanism(directive, 6):
                errors.append("invalid_ip6")
            continue

        mechanism_name = re.split(r"[:/]", lower, maxsplit=1)[0]
        errors.append(
            f"invalid_{mechanism_name}"
            if mechanism_name in _SPF_MECHANISMS
            else "unknown_mechanism"
        )

    if redirect_count > 1:
        errors.append("multiple_redirects")
    if explanation_count > 1:
        errors.append("multiple_explanations")

    return ParsedSpf(
        tuple(references),
        tuple(dict.fromkeys(errors)),
        dns_lookup_terms,
    )


class DnspythonAsyncResolver:
    """Small adapter around dnspython's asynchronous system resolver."""

    def __init__(
        self,
        resolver: Any | None = None,
        *,
        lifetime_seconds: float = 3.0,
        negative_ttl_seconds: int = 300,
    ) -> None:
        self._lifetime = max(0.1, float(lifetime_seconds))
        self._negative_ttl = max(0, int(negative_ttl_seconds))
        self._dns: dict[str, Any] | None = None
        try:
            import dns.asyncresolver
            import dns.exception
            import dns.resolver
        except ImportError:
            self._resolver = None
        else:
            self._dns = {
                "exception": dns.exception,
                "resolver": dns.resolver,
            }
            try:
                self._resolver = resolver or dns.asyncresolver.Resolver()
            except Exception:
                self._resolver = None

    async def resolve(self, name: str, rdtype: str) -> DnsLookup:
        if self._resolver is None or self._dns is None:
            return DnsLookup("unavailable")
        try:
            answer = await self._resolver.resolve(
                name, rdtype, search=False, lifetime=self._lifetime,
            )
        except self._dns["resolver"].NXDOMAIN:
            return DnsLookup("nxdomain", ttl_seconds=self._negative_ttl)
        except self._dns["resolver"].NoAnswer:
            return DnsLookup("nodata", ttl_seconds=self._negative_ttl)
        except self._dns["exception"].Timeout:
            return DnsLookup("timeout")
        except self._dns["resolver"].NoNameservers as exc:
            # Resolver exception text is intentionally neither returned nor
            # persisted.  REFUSED is useful as a category when exposed by the
            # nameserver response; every other no-nameserver case is SERVFAIL.
            category: DnsLookupStatus = (
                "refused" if "REFUSED" in str(exc).upper() else "servfail"
            )
            return DnsLookup(category)
        except Exception:
            return DnsLookup("unavailable")

        rrset = getattr(answer, "rrset", None)
        if rrset is None:
            return DnsLookup("nodata", ttl_seconds=self._negative_ttl)
        ttl = max(0, int(getattr(rrset, "ttl", 0) or 0))
        values: list[str] = []
        try:
            for item in answer:
                if rdtype.upper() == "TXT":
                    chunks = getattr(item, "strings", ())
                    values.append(b"".join(chunks).decode("utf-8", "replace"))
                elif rdtype.upper() == "MX":
                    values.append(str(item.exchange))
                elif rdtype.upper() == "CNAME":
                    values.append(str(item.target))
                else:
                    values.append(item.to_text())
        except Exception:
            return DnsLookup("unavailable")
        return DnsLookup("answer", tuple(values), ttl)


@dataclass
class _AssessmentState:
    evidence: list[dict[str, str]] = field(default_factory=list)
    contradictions: list[dict[str, str]] = field(default_factory=list)
    ttls: list[int] = field(default_factory=list)
    unavailable: bool = False
    invalid: bool = False

    @staticmethod
    def _append_unique(target: list[dict[str, str]], item: dict[str, str]) -> None:
        if item not in target:
            target.append(item)

    def add_evidence(self, evidence_type: str, value: str, rule_id: str) -> None:
        self._append_unique(self.evidence, {
            "type": evidence_type, "value": value, "rule_id": rule_id,
        })

    def add_contradiction(self, contradiction_type: str, value: str, rule_id: str) -> None:
        self._append_unique(self.contradictions, {
            "type": contradiction_type, "value": value, "rule_id": rule_id,
        })

    def observe(self, lookup: DnsLookup, *, name: str, rdtype: str) -> None:
        if lookup.ttl_seconds > 0:
            self.ttls.append(int(lookup.ttl_seconds))
        if lookup.status in {"timeout", "servfail", "refused", "unavailable"}:
            self.unavailable = True
            self.add_contradiction(
                "dns", f"{rdtype.upper()} {name}", f"dns.{lookup.status}",
            )

    def mark_invalid(self, value: str, rule_id: str) -> None:
        self.invalid = True
        self.add_contradiction("spf", value, rule_id)


class DomainDnsAssessor:
    """Assess current DNS configuration for a catalogued mail service.

    The numerical score is an internal deterministic expectation score, not a
    probability and not evidence that a particular sender or tenant is allowed
    to use the assessed Header-From domain.
    """

    def __init__(
        self,
        resolver: DnsResolver | None = None,
        *,
        service_id: str = "microsoft365",
        max_spf_lookups: int = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if service_id not in SERVICE_CATALOG:
            raise ValueError("Unknown service id")
        if not 1 <= max_spf_lookups <= 50:
            raise ValueError("max_spf_lookups must be between 1 and 50")
        self.resolver = resolver or DnspythonAsyncResolver()
        self.service_id = service_id
        self.catalog = SERVICE_CATALOG[service_id]
        self.max_spf_lookups = max_spf_lookups
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _resolve(self, name: str, rdtype: str) -> DnsLookup:
        try:
            result = await self.resolver.resolve(name, rdtype)
        except Exception:
            return DnsLookup("unavailable")
        if not isinstance(result, DnsLookup) or result.status not in {
            "answer", "nxdomain", "nodata", "timeout", "servfail", "refused", "unavailable",
        }:
            return DnsLookup("unavailable")
        try:
            values = tuple(
                value for value in result.values if isinstance(value, str)
            )
            ttl = max(0, int(result.ttl_seconds))
        except (TypeError, ValueError):
            return DnsLookup("unavailable")
        return DnsLookup(result.status, values, ttl)

    @staticmethod
    def _mx_host(value: str) -> str | None:
        # Accept both the adapter's normalized hostname and conventional MX
        # presentation text ("10 host.example.") from simple test/other adapters.
        fields = value.strip().split()
        candidate = fields[-1] if fields and fields[0].isdigit() else value
        return normalize_dns_name(candidate)

    def _inspect_mx(self, lookup: DnsLookup, state: _AssessmentState, domain: str) -> None:
        state.observe(lookup, name=domain, rdtype="MX")
        if lookup.status != "answer":
            return
        for raw in lookup.values:
            host = self._mx_host(raw)
            if host and any(
                is_strict_subdomain(host, suffix)
                for suffix in self.catalog["mx_suffixes"]
            ):
                state.add_evidence(
                    "mx", host, f"{self.service_id}.mx.exchange_online",
                )

    def _inspect_dkim(
        self,
        lookup: DnsLookup,
        state: _AssessmentState,
        *,
        query_name: str,
        selector: str,
    ) -> None:
        state.observe(lookup, name=query_name, rdtype="CNAME")
        if lookup.status != "answer":
            return
        for raw in lookup.values:
            target = normalize_dns_name(raw, allow_underscores=True)
            if target is None:
                continue
            for suffix, variant in self.catalog["dkim_suffixes"].items():
                if is_strict_subdomain(target, suffix):
                    state.add_evidence(
                        "dkim", target,
                        f"{self.service_id}.dkim.{variant}.{selector}",
                    )
                    break

    async def _inspect_spf(
        self,
        domain: str,
        root_lookup: DnsLookup,
        state: _AssessmentState,
    ) -> None:
        cache: dict[str, DnsLookup] = {domain: root_lookup}
        lookup_terms = 0
        active: set[str] = set()

        async def walk(current: str, path_positive: bool, depth: int) -> None:
            nonlocal lookup_terms
            if current in active:
                state.mark_invalid(current, "spf.include_loop")
                return
            active.add(current)
            try:
                lookup = cache.get(current)
                if lookup is None:
                    lookup = await self._resolve(current, "TXT")
                    cache[current] = lookup
                state.observe(lookup, name=current, rdtype="TXT")
                if lookup.status != "answer":
                    return
                records = spf_records(lookup.values)
                if len(records) > 1:
                    state.mark_invalid(current, "spf.multiple_records")
                    return
                if not records:
                    return
                parsed = parse_spf_record(records[0])
                for error in parsed.errors:
                    state.mark_invalid(current, f"spf.{error}")
                if parsed.errors:
                    return
                if lookup_terms + parsed.dns_lookup_terms > self.max_spf_lookups:
                    state.mark_invalid(
                        str(self.max_spf_lookups), "spf.lookup_limit",
                    )
                    return
                lookup_terms += parsed.dns_lookup_terms

                for reference in parsed.references:
                    positive = path_positive and reference.positive
                    variant = self.catalog["spf_domains"].get(reference.domain)
                    if variant:
                        value = f"{reference.kind}:{reference.domain}"
                        if positive:
                            scope = "direct" if depth == 0 else "transitive"
                            state.add_evidence(
                                "spf", value,
                                f"{self.service_id}.spf.{variant}.{reference.kind}.{scope}",
                            )
                        else:
                            state.add_contradiction(
                                "spf", value,
                                f"{self.service_id}.spf.nonpositive_reference",
                            )
                        continue
                    if not reference.reachable:
                        continue
                    await walk(reference.domain, positive, depth + 1)
            finally:
                active.discard(current)

        await walk(domain, True, 0)

    def _result(self, state: _AssessmentState, assessed_at: datetime) -> dict[str, Any]:
        mx = any(item["type"] == "mx" for item in state.evidence)
        spf = any(item["type"] == "spf" for item in state.evidence)
        dkim_count = len({item["rule_id"] for item in state.evidence if item["type"] == "dkim"})

        score = min(1.0, (0.20 if mx else 0) + (0.60 if spf else 0) + min(2, dkim_count) * 0.25)
        if state.contradictions:
            score = max(0.0, score - 0.10 * sum(
                item["rule_id"].endswith("nonpositive_reference")
                for item in state.contradictions
            ))
        strong = (spf and (mx or dkim_count > 0)) or dkim_count >= 2
        assessment: Assessment = "strong" if strong else "configured" if state.evidence else "unknown"
        dns_status: DnsStatus
        if state.invalid:
            dns_status = "invalid"
        elif state.evidence:
            # Positive evidence remains useful when an unrelated selector query
            # times out; the categorized partial failure remains visible below.
            dns_status = "fresh"
        elif state.unavailable:
            dns_status = "unavailable"
        else:
            dns_status = "negative"
        if dns_status != "fresh":
            # Retain the individual observations for diagnostics, but an
            # invalid or incomplete DNS result cannot establish configuration.
            assessment = "unknown"

        return {
            "service_id": self.service_id,
            "label": self.catalog["label"],
            "dns_status": dns_status,
            "assessment": assessment,
            "score": round(score, 2),
            "evidence": state.evidence,
            "contradictions": state.contradictions,
            "assessed_at": assessed_at.astimezone(UTC).isoformat(),
            "ttl_seconds": min(state.ttls, default=0),
        }

    async def assess(self, domain: str) -> dict[str, Any]:
        assessed_at = self.clock()
        if assessed_at.tzinfo is None:
            assessed_at = assessed_at.replace(tzinfo=UTC)
        else:
            assessed_at = assessed_at.astimezone(UTC)
        normalized = normalize_dns_name(domain)
        state = _AssessmentState()
        if normalized is None:
            state.invalid = True
            state.add_contradiction(
                "domain", str(domain), "dns.invalid_domain",
            )
            return self._result(state, assessed_at)

        selector_queries = [
            (selector, f"{selector}._domainkey.{normalized}")
            for selector in self.catalog["selectors"]
        ]
        pending: list[Awaitable[DnsLookup]] = [
            self._resolve(normalized, "MX"),
            self._resolve(normalized, "TXT"),
            *(self._resolve(query, "CNAME") for _, query in selector_queries),
        ]
        mx_lookup, spf_lookup, *dkim_lookups = await asyncio.gather(*pending)
        self._inspect_mx(mx_lookup, state, normalized)
        await self._inspect_spf(normalized, spf_lookup, state)
        for (selector, query), lookup in zip(selector_queries, dkim_lookups):
            self._inspect_dkim(
                lookup, state, query_name=query, selector=selector,
            )
        return self._result(state, assessed_at)


__all__ = [
    "SERVICE_CATALOG",
    "DnsLookup",
    "DnsResolver",
    "DnspythonAsyncResolver",
    "DomainDnsAssessor",
    "ParsedSpf",
    "SpfReference",
    "is_strict_subdomain",
    "normalize_dns_name",
    "parse_spf_record",
    "spf_records",
]
