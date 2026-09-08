from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from .config import Settings
from .opensearch import OpenSearchClient, OpenSearchError
from .store import StateStore


AGGREGATE_SOURCE_FIELDS = [
    "date_begin",
    "date_end",
    "source_ip_address",
    "source_reverse_dns",
    "source_base_domain",
    "source_country",
    "source_type",
    "source_name",
    "source_asn",
    "source_as_name",
    "source_as_domain",
    "header_from",
    "envelope_from",
    "disposition",
    "passed_dmarc",
    "spf_aligned",
    "dkim_aligned",
    "spf_results",
    "dkim_results",
    "published_policy",
    "org_name",
]


def _range(field: str, days: int) -> dict[str, Any]:
    return {"range": {field: {"gte": f"now-{max(days - 1, 0)}d/d", "lte": "now"}}}


def _filters(
    *,
    field: str,
    days: int | None = None,
    domain_field: str,
    domain: str = "*",
    source_ip: str | None = None,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if days is not None:
        filters.append(_range(field, days))
    if domain and domain != "*":
        filters.append({"term": {domain_field: domain}})
    if source_ip:
        filters.append({"term": {"source_ip_address.keyword": source_ip}})
    return filters


def _sum(bucket: dict[str, Any], name: str = "messages") -> int:
    return int(round(float(bucket.get(name, {}).get("value") or 0)))


def _value(bucket: dict[str, Any], name: str) -> Any:
    return bucket.get(name, {}).get("value")


def _iso_from_epoch(value: Any) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()


def _latest_source(bucket: dict[str, Any]) -> dict[str, Any]:
    hits = (
        bucket.get("latest", {})
        .get("hits", {})
        .get("hits", [])
    )
    return hits[0].get("_source", {}) if hits else {}


def _top_keys(bucket: dict[str, Any], name: str, limit: int = 5) -> list[str]:
    return [
        str(item["key"])
        for item in bucket.get(name, {}).get("buckets", [])[:limit]
        if item.get("key") not in (None, "", "-")
    ]


def _weighted_terms(aggregation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": bucket["key"], "messages": _sum(bucket)}
        for bucket in aggregation.get("buckets", [])
    ]


def _score_service(source: dict[str, Any], evidence: Iterable[str]) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}

    def add(
        service: str,
        weight: float,
        signal: str,
        *,
        profile: str = "mail_service",
    ) -> None:
        item = candidates.setdefault(
            service,
            {"score": 0.0, "evidence": [], "profile": profile},
        )
        item["score"] += weight
        if signal not in item["evidence"]:
            item["evidence"].append(signal)

    explicit_name = str(source.get("source_name") or "").strip()
    source_type = str(source.get("source_type") or "").strip().lower()
    trusted_source_types = {"saas", "email service", "esp", "mail provider"}
    trusted_source = source_type in trusted_source_types
    if (
        explicit_name
        and explicit_name.lower() not in {"unknown", "none"}
        and trusted_source
    ):
        add(explicit_name, 0.72, f"parsedmarc: {explicit_name}")

    haystack = " ".join(
        str(value or "").lower()
        for value in [
            source.get("source_reverse_dns"),
            source.get("source_base_domain"),
            source.get("source_as_name"),
            source.get("source_as_domain"),
            *evidence,
        ]
    )

    signatures = {
        "SMTP2GO": [
            ("smtp2go.com", 0.62, "PTR/Domain: smtp2go.com"),
            ("smtpservice.net", 0.38, "DKIM: smtpservice.net"),
            ("deft.com", 0.18, "ASN: DEFT.COM"),
        ],
        "Microsoft 365": [
            ("protection.outlook.com", 0.62, "Mail-Domain: protection.outlook.com"),
            ("outbound.protection.outlook.com", 0.62, "PTR: Microsoft EOP"),
            ("onmicrosoft.com", 0.32, "Identität: onmicrosoft.com"),
            ("microsoft", 0.28, "ASN: Microsoft"),
            ("outlook.com", 0.24, "Mail-Domain: outlook.com"),
        ],
        "Google Workspace": [
            ("google.com", 0.28, "Domain/ASN: Google"),
            ("googlemail.com", 0.5, "PTR: googlemail.com"),
            ("_spf.google.com", 0.5, "SPF: Google"),
        ],
        "Amazon SES": [
            ("amazonses.com", 0.66, "Mail-Domain: amazonses.com"),
            ("amazonaws.com", 0.32, "PTR/ASN: AWS"),
        ],
        "Mailchimp": [
            ("mailchimp.com", 0.66, "Mail-Domain: mailchimp.com"),
            ("mandrillapp.com", 0.6, "Mail-Domain: mandrillapp.com"),
        ],
    }
    for service, signals in signatures.items():
        for needle, weight, label in signals:
            if needle in haystack:
                add(service, weight, label)

    ptr = str(source.get("source_reverse_dns") or "").strip().lower().rstrip(".")
    ptr_tokens = set(re.findall(r"[a-z0-9]+", ptr))
    dynamic_markers = {
        "bbcs",
        "broadband",
        "cable",
        "dhcp",
        "dial",
        "dialup",
        "dsl",
        "dyn",
        "dynamic",
        "pool",
        "ppp",
        "pppoe",
        "residential",
    }
    static_markers = {"static", "fixed", "dedicated"}
    address_in_ptr = False
    public_ipv4 = False
    try:
        address = ipaddress.ip_address(str(source.get("source_ip_address") or ""))
        public_ipv4 = address.version == 4 and address.is_global
        if public_ipv4 and ptr:
            octets = str(address).split(".")
            reverse_octets = list(reversed(octets))
            address_patterns = {
                ".".join(octets),
                "-".join(octets),
                ".".join(reverse_octets),
                "-".join(reverse_octets),
            }
            address_in_ptr = any(pattern in ptr for pattern in address_patterns)
    except ValueError:
        pass

    dynamic_marker = bool(ptr_tokens & dynamic_markers)
    explicitly_static = bool(ptr_tokens & static_markers)
    if (
        public_ipv4
        and address_in_ptr
        and dynamic_marker
        and not explicitly_static
        and not trusted_source
    ):
        add(
            "Dynamischer IP-Bereich",
            0.54,
            "PTR: umgekehrte Quell-IP eingebettet",
            profile="dynamic_ip",
        )
        add(
            "Dynamischer IP-Bereich",
            0.34,
            "PTR: dynamisches Anschlussmuster",
            profile="dynamic_ip",
        )

    if not candidates:
        return {
            "service": "Unbekannt",
            "confidence": 0,
            "confidence_label": "Keine Zuordnung",
            "evidence": [],
            "profile": "unknown",
        }

    service, result = max(candidates.items(), key=lambda item: item[1]["score"])
    confidence = min(round(result["score"], 2), 0.99)
    if confidence >= 0.8:
        label = "Hoch"
    elif confidence >= 0.55:
        label = "Mittel"
    else:
        label = "Niedrig"
    return {
        "service": service,
        "confidence": confidence,
        "confidence_label": label,
        "evidence": result["evidence"],
        "profile": result["profile"],
    }


class DashboardService:
    def __init__(
        self,
        client: OpenSearchClient,
        store: StateStore,
        settings: Settings,
    ) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        # Import after this module's helpers are defined; the event engine shares
        # their source normalization without using the paginated UI host list.
        from .alert_events import AlertEngine
        self._alert_engine = AlertEngine(self)

    async def domains(self) -> list[dict[str, Any]]:
        body = {
            "size": 0,
            "query": {"match_all": {}},
            "aggs": {
                "domains": {
                    "terms": {
                        "field": "header_from.keyword",
                        "size": 250,
                        "order": {"messages": "desc"},
                    },
                    "aggs": {
                        "messages": {"sum": {"field": "message_count"}},
                        "last_seen": {"max": {"field": "date_begin"}},
                    },
                }
            },
        }
        response = await self.client.search(
            self.settings.aggregate_index, body, allow_missing=True
        )
        return [
            {
                "domain": bucket["key"],
                "messages": _sum(bucket),
                "last_seen": _iso_from_epoch(_value(bucket, "last_seen")),
            }
            for bucket in response.get("aggregations", {})
            .get("domains", {})
            .get("buckets", [])
        ]

    async def overview(self, domain: str, days: int) -> dict[str, Any]:
        query_filters = _filters(
            field="date_begin",
            days=days,
            domain_field="header_from.keyword",
            domain=domain,
        )
        sum_messages = {"sum": {"field": "message_count"}}
        body = {
            "size": 0,
            "query": {"bool": {"filter": query_filters}},
            "aggs": {
                "messages": sum_messages,
                "last_report": {"max": {"field": "date_end"}},
                "dmarc_pass": {
                    "filter": {"term": {"passed_dmarc": True}},
                    "aggs": {"messages": sum_messages},
                },
                "dmarc_fail": {
                    "filter": {"term": {"passed_dmarc": False}},
                    "aggs": {"messages": sum_messages},
                },
                "spf_aligned": {
                    "filter": {"term": {"spf_aligned": True}},
                    "aggs": {"messages": sum_messages},
                },
                "spf_not_aligned": {
                    "filter": {"term": {"spf_aligned": False}},
                    "aggs": {"messages": sum_messages},
                },
                "dkim_aligned": {
                    "filter": {"term": {"dkim_aligned": True}},
                    "aggs": {"messages": sum_messages},
                },
                "dkim_not_aligned": {
                    "filter": {"term": {"dkim_aligned": False}},
                    "aggs": {"messages": sum_messages},
                },
                "trend": {
                    "date_histogram": {
                        "field": "date_begin",
                        "calendar_interval": "day",
                        "min_doc_count": 0,
                        "extended_bounds": {
                            "min": f"now-{max(days - 1, 0)}d/d",
                            "max": "now/d",
                        },
                    },
                    "aggs": {
                        "pass": {
                            "filter": {"term": {"passed_dmarc": True}},
                            "aggs": {"messages": sum_messages},
                        },
                        "fail": {
                            "filter": {"term": {"passed_dmarc": False}},
                            "aggs": {"messages": sum_messages},
                        },
                    },
                },
                "domains": {
                    "terms": {
                        "field": "header_from.keyword",
                        "size": 50,
                        "order": {"messages": "desc"},
                    },
                    "aggs": {"messages": sum_messages},
                },
                "reporters": {
                    "terms": {
                        "field": "org_name.keyword",
                        "size": 50,
                        "order": {"messages": "desc"},
                    },
                    "aggs": {"messages": sum_messages},
                },
                "policies": {
                    "terms": {
                        "field": "published_policy.domain.keyword",
                        "size": 50,
                        "order": {"messages": "desc"},
                    },
                    "aggs": {
                        "messages": sum_messages,
                        "policy": {
                            "terms": {
                                "field": "published_policy.p.keyword",
                                "size": 5,
                                "order": {"_count": "desc"},
                            }
                        },
                        "percentage": {
                            "terms": {
                                "field": "published_policy.pct",
                                "size": 5,
                                "order": {"_count": "desc"},
                            }
                        },
                    },
                },
                "critical_sources": {
                    "filter": {"term": {"passed_dmarc": False}},
                    "aggs": {
                        "sources": {
                            "terms": {
                                "field": "source_ip_address.keyword",
                                "size": 50,
                                "order": {"messages": "desc"},
                            },
                            "aggs": {
                                "messages": sum_messages,
                                "last_seen": {"max": {"field": "date_begin"}},
                                "latest": {
                                    "top_hits": {
                                        "size": 1,
                                        "sort": [{"date_begin": {"order": "desc"}}],
                                        "_source": {"includes": AGGREGATE_SOURCE_FIELDS},
                                    }
                                },
                            },
                        }
                    },
                },
            },
        }
        response = await self.client.search(
            self.settings.aggregate_index, body, allow_missing=True
        )
        aggregations = response.get("aggregations", {})
        total = _sum(aggregations)
        passed = _sum(aggregations.get("dmarc_pass", {}))
        failed = _sum(aggregations.get("dmarc_fail", {}))
        trend = [
            {
                "date": bucket.get("key_as_string", "")[:10],
                "pass": _sum(bucket.get("pass", {})),
                "fail": _sum(bucket.get("fail", {})),
            }
            for bucket in aggregations.get("trend", {}).get("buckets", [])
        ]
        critical_sources = []
        for bucket in (
            aggregations.get("critical_sources", {})
            .get("sources", {})
            .get("buckets", [])
        ):
            source = _latest_source(bucket)
            critical_sources.append(
                {
                    "source_ip": bucket["key"],
                    "reverse_dns": source.get("source_reverse_dns"),
                    "base_domain": source.get("source_base_domain"),
                    "country": source.get("source_country"),
                    "header_from": source.get("header_from"),
                    "envelope_from": source.get("envelope_from"),
                    "spf_aligned": source.get("spf_aligned"),
                    "dkim_aligned": source.get("dkim_aligned"),
                    "messages": _sum(bucket),
                    "last_seen": _iso_from_epoch(_value(bucket, "last_seen")),
                }
            )

        policies = []
        for bucket in aggregations.get("policies", {}).get("buckets", []):
            policy_buckets = bucket.get("policy", {}).get("buckets", [])
            pct_buckets = bucket.get("percentage", {}).get("buckets", [])
            policies.append(
                {
                    "domain": bucket["key"],
                    "policy": policy_buckets[0]["key"] if policy_buckets else "-",
                    "percentage": int(pct_buckets[0]["key"]) if pct_buckets else 100,
                    "messages": _sum(bucket),
                }
            )

        return {
            "scope": {"domain": domain, "days": days},
            "totals": {
                "messages": total,
                "dmarc_pass": passed,
                "dmarc_fail": failed,
                "pass_rate": round((passed / total * 100), 2) if total else 0,
                "critical_sources": len(critical_sources),
                "last_report": _iso_from_epoch(_value(aggregations, "last_report")),
            },
            "alignment": {
                "spf_aligned": _sum(aggregations.get("spf_aligned", {})),
                "spf_not_aligned": _sum(aggregations.get("spf_not_aligned", {})),
                "dkim_aligned": _sum(aggregations.get("dkim_aligned", {})),
                "dkim_not_aligned": _sum(aggregations.get("dkim_not_aligned", {})),
                "dmarc_pass": passed,
                "dmarc_fail": failed,
            },
            "trend": trend,
            "critical_sources": critical_sources,
            "domains": _weighted_terms(aggregations.get("domains", {})),
            "reporting_organisations": _weighted_terms(
                aggregations.get("reporters", {})
            ),
            "policies": policies,
        }

    async def hosts(
        self,
        domain: str,
        days: int,
        *,
        risk: str = "all",
        limit: int | None = 100,
        source_ip: str | None = None,
        search: str = "",
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive or None")
        if offset < 0:
            raise ValueError("offset must not be negative")
        global_filters = _filters(
            field="date_begin",
            days=None,
            domain_field="header_from.keyword",
            domain=domain,
            source_ip=source_ip,
        )
        query_time = datetime.now(UTC)
        current_start = (query_time - timedelta(days=max(days - 1, 0))).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        current_filter = {
            "range": {
                "date_begin": {
                    "gte": current_start.isoformat(),
                    "lte": query_time.isoformat(),
                }
            }
        }
        sum_messages = {"sum": {"field": "message_count"}}
        global_query: dict[str, Any] = (
            {"bool": {"filter": global_filters}}
            if global_filters
            else {"match_all": {}}
        )
        body = {
            "size": 0,
            "query": global_query,
            "aggs": {
                "hosts": {
                    "composite": {
                        "size": 500,
                        "sources": [
                            {
                                "source_ip": {
                                    "terms": {"field": "source_ip_address.keyword"}
                                }
                            }
                        ],
                    },
                    "aggs": {
                        "first_seen": {"min": {"field": "date_begin"}},
                        "previous": {
                            "filter": {
                                "range": {
                                    "date_begin": {
                                        "lt": current_start.isoformat()
                                    }
                                }
                            },
                            "aggs": {
                                "dmarc_pass": {
                                    "filter": {"term": {"passed_dmarc": True}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "dmarc_fail": {
                                    "filter": {"term": {"passed_dmarc": False}},
                                    "aggs": {"messages": sum_messages},
                                },
                            },
                        },
                        "current": {
                            "filter": current_filter,
                            "aggs": {
                                "messages": sum_messages,
                                "last_seen": {"max": {"field": "date_begin"}},
                                "dmarc_pass": {
                                    "filter": {"term": {"passed_dmarc": True}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "dmarc_fail": {
                                    "filter": {"term": {"passed_dmarc": False}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "spf_aligned": {
                                    "filter": {"term": {"spf_aligned": True}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "spf_not_aligned": {
                                    "filter": {"term": {"spf_aligned": False}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "dkim_aligned": {
                                    "filter": {"term": {"dkim_aligned": True}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "dkim_not_aligned": {
                                    "filter": {"term": {"dkim_aligned": False}},
                                    "aggs": {"messages": sum_messages},
                                },
                                "header_froms": {
                                    "terms": {
                                        "field": "header_from.keyword",
                                        "size": 10,
                                        "order": {"_count": "desc"},
                                    }
                                },
                                "envelope_froms": {
                                    "terms": {
                                        "field": "envelope_from.keyword",
                                        "size": 10,
                                        "order": {"_count": "desc"},
                                        "missing": "-",
                                    }
                                },
                                "spf_domains": {
                                    "terms": {
                                        "field": "spf_results.domain.keyword",
                                        "size": 10,
                                        "order": {"_count": "desc"},
                                        "missing": "-",
                                    }
                                },
                                "dkim_domains": {
                                    "terms": {
                                        "field": "dkim_results.domain.keyword",
                                        "size": 10,
                                        "order": {"_count": "desc"},
                                        "missing": "-",
                                    }
                                },
                                "dkim_selectors": {
                                    "terms": {
                                        "field": "dkim_results.selector.keyword",
                                        "size": 10,
                                        "order": {"_count": "desc"},
                                        "missing": "-",
                                    }
                                },
                                "latest": {
                                    "top_hits": {
                                        "size": 1,
                                        "sort": [{"date_begin": {"order": "desc"}}],
                                        "_source": {"includes": AGGREGATE_SOURCE_FIELDS},
                                    }
                                },
                            },
                        },
                    },
                }
            },
        }
        buckets = await self._host_buckets(body)
        overrides = self.store.host_overrides()
        items = []
        new_cutoff = query_time - timedelta(
            days=self.settings.new_host_window_days
        )
        for bucket in buckets:
            host_ip = bucket["key"]["source_ip"]
            current = bucket.get("current", {})
            previous = bucket.get("previous", {})
            total = _sum(current)
            if total <= 0:
                continue
            passed = _sum(current.get("dmarc_pass", {}))
            failed = _sum(current.get("dmarc_fail", {}))
            spf_not_aligned = _sum(current.get("spf_not_aligned", {}))
            dkim_not_aligned = _sum(current.get("dkim_not_aligned", {}))
            if failed:
                host_risk = "critical"
            elif spf_not_aligned or dkim_not_aligned:
                host_risk = "warning"
            else:
                host_risk = "healthy"
            if risk == "spf-not-aligned" and not spf_not_aligned:
                continue
            if risk == "dkim-not-aligned" and not dkim_not_aligned:
                continue
            if (
                risk
                not in {"all", "spf-not-aligned", "dkim-not-aligned"}
                and host_risk != risk
            ):
                continue

            latest = _latest_source(current)
            identity_evidence = [
                *_top_keys(current, "spf_domains"),
                *_top_keys(current, "dkim_domains"),
                *_top_keys(current, "dkim_selectors"),
                str(latest.get("source_as_name") or ""),
            ]
            detection = _score_service(latest, identity_evidence)
            override = overrides.get(host_ip)
            if override:
                detection["automatic_service"] = detection["service"]
                if override.get("service_name"):
                    detection["service"] = override["service_name"]
                detection["manual_override"] = True
                trust_status = override["trust_status"]
            else:
                detection["manual_override"] = False
                trust_status = (
                    "automatic"
                    if detection["confidence"] >= 0.55
                    else "unconfirmed"
                )

            first_seen = _iso_from_epoch(_value(bucket, "first_seen"))
            is_new = False
            if first_seen:
                is_new = datetime.fromisoformat(first_seen) >= new_cutoff
            items.append(
                {
                    "source_ip": host_ip,
                    "reverse_dns": latest.get("source_reverse_dns"),
                    "base_domain": latest.get("source_base_domain"),
                    "country": latest.get("source_country"),
                    "asn": latest.get("source_asn"),
                    "as_name": latest.get("source_as_name"),
                    "as_domain": latest.get("source_as_domain"),
                    "source_type": latest.get("source_type"),
                    "header_froms": _top_keys(current, "header_froms", 10),
                    "envelope_froms": _top_keys(current, "envelope_froms", 10),
                    "spf_domains": _top_keys(current, "spf_domains", 10),
                    "dkim_domains": _top_keys(current, "dkim_domains", 10),
                    "dkim_selectors": _top_keys(current, "dkim_selectors", 10),
                    "messages": total,
                    "dmarc_pass": passed,
                    "dmarc_fail": failed,
                    "previous_dmarc_pass": _sum(previous.get("dmarc_pass", {})),
                    "previous_dmarc_fail": _sum(previous.get("dmarc_fail", {})),
                    "pass_rate": round(passed / total * 100, 2) if total else 0,
                    "spf_aligned": _sum(current.get("spf_aligned", {})),
                    "spf_not_aligned": spf_not_aligned,
                    "dkim_aligned": _sum(current.get("dkim_aligned", {})),
                    "dkim_not_aligned": dkim_not_aligned,
                    "first_seen": first_seen,
                    "last_seen": _iso_from_epoch(_value(current, "last_seen")),
                    "is_new": is_new,
                    "risk": host_risk,
                    "trust_status": trust_status,
                    "service_detection": detection,
                    "override": override,
                }
            )
        needle = search.strip().lower()
        if needle:
            items = [
                item
                for item in items
                if needle in " ".join(
                    str(value or "")
                    for value in [
                        item["source_ip"],
                        item["reverse_dns"],
                        item["base_domain"],
                        item["service_detection"]["service"],
                        item["as_name"],
                        *item["header_froms"],
                        *item["envelope_froms"],
                    ]
                ).lower()
            ]
        items.sort(key=lambda item: (-item["messages"], item["source_ip"]))
        return items[offset:] if limit is None else items[offset : offset + limit]

    async def _host_buckets(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """Read every IP bucket; never turn a partial search into a healthy view."""
        buckets: list[dict[str, Any]] = []
        previous_cursor: str | None = None
        previous_ip: str | None = None
        composite = body["aggs"]["hosts"]["composite"]
        while True:
            response = await self.client.search(
                self.settings.aggregate_index, body, allow_missing=True
            )
            if (
                response.get("timed_out")
                or response.get("terminated_early")
                or response.get("_shards", {}).get("failed", 0)
            ):
                raise OpenSearchError("Sending-Host-Abfrage lieferte unvollständige Daten")
            aggregation = response.get("aggregations", {}).get("hosts")
            if aggregation is None:
                if previous_cursor is not None:
                    raise OpenSearchError("Sending-Host-Abfrage lieferte keine Folgeseite")
                return []
            page = aggregation.get("buckets", [])
            for bucket in page:
                key = bucket.get("key")
                host_ip = key.get("source_ip") if isinstance(key, dict) else None
                if not isinstance(host_ip, str) or (
                    previous_ip is not None and host_ip <= previous_ip
                ):
                    raise OpenSearchError("Sending-Host-Abfrage lieferte ungültige Seiten")
                previous_ip = host_ip
            buckets.extend(page)
            after_key = aggregation.get("after_key")
            if not after_key:
                return buckets
            cursor = after_key.get("source_ip") if isinstance(after_key, dict) else None
            if not page or not isinstance(cursor, str) or (
                previous_cursor is not None and cursor <= previous_cursor
            ):
                raise OpenSearchError(
                    "Sending-Host-Abfrage konnte nicht vollständig gelesen werden"
                )
            previous_cursor = cursor
            composite["after"] = after_key

    async def hosts_page(
        self,
        domain: str,
        days: int,
        *,
        risk: str = "all",
        limit: int = 100,
        source_ip: str | None = None,
        search: str = "",
        offset: int = 0,
    ) -> dict[str, Any]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        items = await self.hosts(
            domain, days, risk=risk, limit=None, source_ip=source_ip, search=search
        )
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    async def alerts(self, domain: str, days: int) -> list[dict[str, Any]]:
        return await self._alert_engine.alerts(domain, days)

    async def alert_evaluation(self, domain: str, days: int) -> dict[str, Any]:
        return await self._alert_engine.evaluate(domain, days)

    async def _legacy_alerts(self, domain: str, days: int) -> list[dict[str, Any]]:
        """One-time reconstruction of identifiable pre-v2 workflow references."""
        hosts = await self.hosts(domain, days, limit=250)
        overview = await self.overview(domain, days)
        states = self.store.alert_states()
        alerts: list[dict[str, Any]] = []

        for host in hosts:
            report_day = (host.get("last_seen") or "unknown")[:10]
            alert_domain = host["header_froms"][0] if host["header_froms"] else domain
            notification_context = {
                "source_profile": host["service_detection"].get("profile"),
                "reverse_dns": host.get("reverse_dns"),
                "asn": host.get("asn"),
                "as_name": host.get("as_name"),
                "service": host["service_detection"].get("service"),
                "service_confidence": host["service_detection"].get(
                    "confidence"
                ),
                "service_evidence": host["service_detection"].get(
                    "evidence", []
                ),
                "header_froms": host.get("header_froms", []),
                "envelope_froms": host.get("envelope_froms", []),
                "spf_domains": host.get("spf_domains", []),
                "dkim_domains": host.get("dkim_domains", []),
                "dkim_selectors": host.get("dkim_selectors", []),
                "dmarc_pass": host.get("dmarc_pass", 0),
                "dmarc_fail": host.get("dmarc_fail", 0),
                "spf_aligned": host.get("spf_aligned", 0),
                "spf_not_aligned": host.get("spf_not_aligned", 0),
                "dkim_aligned": host.get("dkim_aligned", 0),
                "dkim_not_aligned": host.get("dkim_not_aligned", 0),
            }
            if host["dmarc_fail"]:
                degraded = (
                    host["previous_dmarc_pass"] > 0
                    and host["previous_dmarc_fail"] == 0
                )
                if host["is_new"]:
                    trigger = "new-host-fail"
                    title = "Neuer unbekannter Sender mit DMARC-Fail"
                elif degraded:
                    trigger = "host-degradation"
                    title = "Bekannter Sending Host hat sich verschlechtert"
                else:
                    trigger = "host-fail"
                    title = "DMARC-Fehlerquelle erkannt"
                if (
                    host["service_detection"].get("profile")
                    == "dynamic_ip"
                ):
                    title = "DMARC-Fail aus dynamischem IP-Bereich"
                alert_id = self._alert_id(
                    trigger, alert_domain, host["source_ip"], report_day
                )
                alerts.append(
                    self._with_state(
                        {
                            "id": alert_id,
                            "priority": "critical",
                            "title": title,
                            "source_ip": host["source_ip"],
                            "country": host["country"],
                            "domain": alert_domain,
                            "trigger": f"{host['dmarc_fail']} × passed_dmarc:false",
                            "report_time": host["last_seen"],
                            "messages": host["dmarc_fail"],
                            "kind": trigger,
                            **notification_context,
                        },
                        states,
                    )
                )
            elif host["is_new"]:
                alert_id = self._alert_id(
                    "new-source-ip",
                    alert_domain,
                    host["source_ip"],
                    report_day,
                )
                alerts.append(
                    self._with_state(
                        {
                            "id": alert_id,
                            "priority": "warning",
                            "title": "Neue Source-IP erkannt",
                            "source_ip": host["source_ip"],
                            "country": host["country"],
                            "domain": alert_domain,
                            "trigger": (
                                f"Erstmals gesehen am "
                                f"{(host.get('first_seen') or 'unbekannt')[:10]}"
                            ),
                            "report_time": host["last_seen"],
                            "messages": host["messages"],
                            "kind": "new-source-ip",
                            **notification_context,
                        },
                        states,
                    )
                )
            elif host["spf_not_aligned"] or host["dkim_not_aligned"]:
                mechanisms = []
                if host["spf_not_aligned"]:
                    mechanisms.append("SPF nicht aligned")
                if host["dkim_not_aligned"]:
                    mechanisms.append("DKIM nicht aligned")
                alert_id = self._alert_id(
                    "compensated-alignment",
                    alert_domain,
                    host["source_ip"],
                    report_day,
                )
                alerts.append(
                    self._with_state(
                        {
                            "id": alert_id,
                            "priority": "info",
                            "title": "Kompensiertes Alignment-Problem",
                            "source_ip": host["source_ip"],
                            "country": host["country"],
                            "domain": alert_domain,
                            "trigger": f"{', '.join(mechanisms)} · DMARC bestanden",
                            "report_time": host["last_seen"],
                            "messages": host["messages"],
                            "kind": "compensated-alignment",
                            **notification_context,
                        },
                        states,
                    )
                )

        latest = overview.get("totals", {}).get("last_report")
        if latest:
            age = datetime.now(UTC) - datetime.fromisoformat(latest)
            if age > timedelta(days=self.settings.stale_report_days):
                report_day = latest[:10]
                alert_id = self._alert_id(
                    "stale-reports", domain, "all", report_day
                )
                alerts.append(
                    self._with_state(
                        {
                            "id": alert_id,
                            "priority": "warning",
                            "title": "DMARC-Reports bleiben aus",
                            "source_ip": None,
                            "country": None,
                            "domain": domain,
                            "trigger": (
                                f"Letzter Berichtszeitraum endete vor "
                                f"{age.days} Tagen; "
                                "übliche Zustellverzögerung berücksichtigt"
                            ),
                            "report_time": latest,
                            "messages": 0,
                            "kind": "stale-reports",
                        },
                        states,
                    )
                )

        priority_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(
            key=lambda item: (
                priority_order.get(item["priority"], 9),
                item.get("report_time") or "",
            ),
            reverse=False,
        )
        return alerts

    async def forensics(
        self, domain: str, days: int, failure_type: str = "*"
    ) -> dict[str, Any]:
        query_filters = _filters(
            field="arrival_date",
            days=days,
            domain_field="domain.keyword",
            domain=domain,
        )
        if failure_type and failure_type != "*":
            query_filters.append({"term": {"auth_failure.keyword": failure_type}})
        body = {
            "size": 0,
            "track_total_hits": True,
            "_source": False,
            "query": {"bool": {"filter": query_filters}},
            "aggs": {
                "last_report": {"max": {"field": "arrival_date"}},
                "failure_types": {
                    "terms": {
                        "field": "auth_failure.keyword",
                        "size": 20,
                        "order": {"_count": "desc"},
                    }
                },
                "domains": {
                    "terms": {
                        "field": "domain.keyword",
                        "size": 50,
                        "order": {"_count": "desc"},
                    }
                },
                "countries": {
                    "terms": {
                        "field": "source_country.keyword",
                        "size": 50,
                        "order": {"_count": "desc"},
                        "missing": "Unbekannt",
                    }
                },
                "sources": {
                    "terms": {
                        "field": "source_ip_address.keyword",
                        "size": 50,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "reverse_dns": {
                            "terms": {
                                "field": "source_reverse_dns.keyword",
                                "size": 3,
                                "missing": "-",
                            }
                        },
                        "base_domain": {
                            "terms": {
                                "field": "source_base_domain.keyword",
                                "size": 3,
                                "missing": "-",
                            }
                        },
                        "country": {
                            "terms": {
                                "field": "source_country.keyword",
                                "size": 3,
                                "missing": "Unbekannt",
                            }
                        },
                        "last_seen": {"max": {"field": "arrival_date"}},
                    },
                },
                "evidence": {
                    "terms": {
                        "field": "authentication_results.keyword",
                        "size": 20,
                        "order": {"_count": "desc"},
                        "missing": "-",
                    },
                    "aggs": {
                        "delivery": {
                            "terms": {
                                "field": "delivery_results.keyword",
                                "size": 5,
                                "missing": "-",
                            }
                        },
                        "failure": {
                            "terms": {
                                "field": "auth_failure.keyword",
                                "size": 10,
                                "missing": "-",
                            }
                        },
                    },
                },
            },
        }
        response = await self.client.search(
            self.settings.forensic_index, body, allow_missing=True
        )
        aggregations = response.get("aggregations", {})
        total_value = response.get("hits", {}).get("total", 0)
        total = (
            int(total_value.get("value", 0))
            if isinstance(total_value, dict)
            else int(total_value or 0)
        )
        sources = []
        for bucket in aggregations.get("sources", {}).get("buckets", []):
            sources.append(
                {
                    "source_ip": bucket["key"],
                    "samples": int(bucket.get("doc_count", 0)),
                    "reverse_dns": (_top_keys(bucket, "reverse_dns", 1) or [None])[0],
                    "base_domain": (_top_keys(bucket, "base_domain", 1) or [None])[0],
                    "country": (_top_keys(bucket, "country", 1) or ["Unbekannt"])[0],
                    "last_seen": _iso_from_epoch(_value(bucket, "last_seen")),
                }
            )
        evidence = []
        for bucket in aggregations.get("evidence", {}).get("buckets", []):
            evidence.append(
                {
                    "authentication_result": bucket["key"],
                    "delivery_results": _top_keys(bucket, "delivery"),
                    "failure_types": _top_keys(bucket, "failure"),
                    "samples": int(bucket.get("doc_count", 0)),
                }
            )
        return {
            "scope": {
                "domain": domain,
                "days": days,
                "failure_type": failure_type,
            },
            "samples": total,
            "last_report": _iso_from_epoch(_value(aggregations, "last_report")),
            "failure_types": [
                {"name": item["key"], "samples": int(item["doc_count"])}
                for item in aggregations.get("failure_types", {}).get("buckets", [])
            ],
            "domains": [
                {"name": item["key"], "samples": int(item["doc_count"])}
                for item in aggregations.get("domains", {}).get("buckets", [])
            ],
            "countries": [
                {"name": item["key"], "samples": int(item["doc_count"])}
                for item in aggregations.get("countries", {}).get("buckets", [])
            ],
            "sources": sources,
            "evidence": evidence,
            "privacy": {
                "raw_samples_loaded": False,
                "excluded_fields": [
                    "sample.raw",
                    "sample.headers",
                    "sample.body",
                    "sample.subject",
                    "original_rcpt_to",
                    "original_mail_from",
                ],
            },
        }

    @staticmethod
    def _alert_id(*parts: str) -> str:
        value = ":".join(parts)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _with_state(
        alert: dict[str, Any], states: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        state = states.get(alert["id"])
        alert["status"] = state["status"] if state else "open"
        alert["status_updated_at"] = state["updated_at"] if state else None
        return alert
