from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from .host_classification import classify_host
from .domain_monitoring import canonical_domain, domain_freshness_event, legacy_domain_monitoring
from .service_detection import score_service
from .freshness import report_freshness
from .opensearch import OpenSearchError
from .service import AGGREGATE_SOURCE_FIELDS, _iso_from_epoch, _latest_source, _sum, _top_keys


class AlertEngine:
    """Build domain/IP/day events from evidence, independently of UI host pages."""

    def __init__(self, service) -> None:
        self.service = service
        self.client = service.client
        self.store = service.store
        self.settings = service.settings
        self._lock = asyncio.Lock()

    async def _pages(self, query: dict, sources: list, aggs: dict) -> list[dict]:
        result = []
        after = None
        seen = set()
        seen_keys = set()
        source_names = [next(iter(source)) for source in sources]
        while True:
            composite = {"size": 200, "sources": sources}
            if after is not None:
                composite["after"] = after
            response = await self.client.search(
                self.settings.aggregate_index,
                {"size": 0, "query": query,
                 "aggs": {"events": {"composite": composite, "aggs": aggs}}},
                allow_missing=True,
            )
            if (response.get("timed_out") or response.get("terminated_early")
                    or response.get("_shards", {}).get("failed", 0)):
                raise OpenSearchError("Unvollständige Ereignisauswertung; bitte erneut versuchen")
            aggregations = response.get("aggregations")
            if aggregations is None or isinstance(aggregations, dict) and "events" not in aggregations:
                total_hits = response.get("hits", {}).get("total")
                if isinstance(total_hits, dict):
                    total_hits = total_hits.get("value")
                if after is None and not aggregations and type(total_hits) is int and total_hits == 0:
                    return []
                raise OpenSearchError("Ereignisaggregation fehlt in der Abfrageantwort")
            if not isinstance(aggregations, dict):
                raise OpenSearchError("Ungültige Ereignisaggregation")
            aggregation = aggregations["events"]
            if not isinstance(aggregation, dict) or not isinstance(aggregation.get("buckets"), list):
                raise OpenSearchError("Ungültige Ereignisaggregation")
            buckets = aggregation["buckets"]
            for bucket in buckets:
                key = bucket.get("key", {})
                if not isinstance(key, dict) or set(key) != set(source_names):
                    raise OpenSearchError("Ungültiger Ereignisschlüssel")
                marker = tuple(key[name] for name in source_names)
                if marker in seen_keys:
                    raise OpenSearchError("Doppelte Ereignisgruppe in OpenSearch")
                seen_keys.add(marker)
            result.extend(buckets)
            next_after = aggregation.get("after_key")
            if next_after is None:
                break
            if not isinstance(next_after, dict) or set(next_after) != set(source_names):
                raise OpenSearchError("Ungültiger Cursor der Ereignisauswertung")
            marker = tuple(next_after[name] for name in source_names)
            if not buckets or marker in seen:
                raise OpenSearchError("Ungültiger Cursor der Ereignisauswertung")
            if after is not None and marker <= tuple(after[name] for name in source_names):
                raise OpenSearchError("Cursor der Ereignisauswertung läuft rückwärts")
            seen.add(marker)
            after = next_after
        return result

    @staticmethod
    def _query(domain: str, time_filter: dict | None = None) -> dict:
        filters = []
        if domain != "*":
            filters.append({"term": {"header_from.keyword": domain}})
        if time_filter:
            filters.append(time_filter)
        return {"bool": {"filter": filters}} if filters else {"match_all": {}}

    async def _evaluate(self, domain: str, days: int, now: datetime, *,
                        evaluation_counts: dict[str, int] | None = None) -> list[dict[str, Any]]:
        start = (now - timedelta(days=max(days - 1, 0))).replace(hour=0, minute=0, second=0, microsecond=0)
        total = {"sum": {"field": "message_count"}}
        mechanisms = {
            "dmarc_pass": ("passed_dmarc", True), "dmarc_fail": ("passed_dmarc", False),
            "spf_aligned": ("spf_aligned", True), "spf_not_aligned": ("spf_aligned", False),
            "dkim_aligned": ("dkim_aligned", True), "dkim_not_aligned": ("dkim_aligned", False),
        }
        metrics = {key: {"filter": {"term": {field: value}}, "aggs": {"messages": total}}
                   for key, (field, value) in mechanisms.items()}
        keys = [{"domain": {"terms": {"field": "header_from.keyword"}}},
                {"ip": {"terms": {"field": "source_ip_address.keyword"}}}]
        history_buckets = await self._pages(
            self._query(domain), keys,
            {"first_seen": {"min": {"field": "date_begin"}},
             "previous": {"filter": {"range": {"date_begin": {"lt": start.isoformat()}}},
                          "aggs": {key: metrics[key] for key in ("dmarc_pass", "dmarc_fail")}}},
        )
        history = {
            (item["key"]["domain"], item["key"]["ip"]): {
                "first_seen": _iso_from_epoch(item.get("first_seen", {}).get("value")),
                "passed": _sum(item.get("previous", {}).get("dmarc_pass", {})),
                "failed": _sum(item.get("previous", {}).get("dmarc_fail", {})),
            } for item in history_buckets
        }
        identity_fields = {
            "envelope_froms": "envelope_from.keyword", "spf_domains": "spf_results.domain.keyword",
            "dkim_domains": "dkim_results.domain.keyword", "dkim_selectors": "dkim_results.selector.keyword",
        }
        buckets = await self._pages(
            self._query(domain, {"range": {"date_begin": {"gte": start.isoformat(), "lte": now.isoformat()}}}),
            [{"day": {"date_histogram": {"field": "date_begin", "calendar_interval": "day", "time_zone": "UTC"}}}, *keys],
            {"messages": total, **metrics,
             "alignment_affected": {
                 "filter": {"bool": {
                     "should": [
                         {"term": {"spf_aligned": False}},
                         {"term": {"dkim_aligned": False}},
                     ],
                     "minimum_should_match": 1,
                 }},
                 "aggs": {"messages": total},
             },
             **{key: {"terms": {"field": field, "size": 10}} for key, field in identity_fields.items()},
             "latest": {"top_hits": {"size": 1, "sort": [{"date_begin": "desc"}],
                                     "_source": {"includes": AGGREGATE_SOURCE_FIELDS}}}},
        )
        overrides = self.store.host_overrides()
        events = []
        # Composite day is the leading key. Sort explicitly for deterministic
        # historical classification even with synthetic or reordered responses.
        for bucket in sorted(buckets, key=lambda item: (item["key"]["day"], item["key"]["domain"], item["key"]["ip"])):
            key = bucket["key"]
            report_time = _iso_from_epoch(key["day"])
            report_day = report_time[:10]
            source_ip, event_domain = key["ip"], key["domain"]
            prior = history.setdefault((event_domain, source_ip), {"first_seen": report_time, "passed": 0, "failed": 0})
            first_seen = prior["first_seen"] or report_time
            counts = {name: _sum(bucket.get(name, {})) for name in mechanisms}
            messages = _sum(bucket)
            if messages <= 0:
                continue
            elapsed_days = (datetime.fromisoformat(report_time).date() - datetime.fromisoformat(first_seen).date()).days
            source = _latest_source(bucket)
            automatic = score_service(
                source,
                spf_domains=_top_keys(bucket, "spf_domains"),
                dkim_domains=_top_keys(bucket, "dkim_domains"),
                dkim_selectors=_top_keys(bucket, "dkim_selectors"),
            )
            detection, _ = classify_host(automatic, overrides.get(source_ip))
            context = {
                "source_ip": source_ip, "domain": event_domain, "country": source.get("source_country"),
                "report_time": report_time, "source_profile": detection.get("profile"),
                "reverse_dns": source.get("source_reverse_dns"), "asn": source.get("source_asn"),
                "as_name": source.get("source_as_name"), "service": detection.get("service"),
                "service_confidence": detection.get("confidence"), "service_evidence": detection.get("evidence", []),
                "classification_mode": detection["classification_mode"],
                "manual_service_name": detection["manual_service_name"],
                "automatic_detection": detection["automatic_detection"],
                "service_evidence_details": detection.get("evidence_details", []),
                "header_froms": [event_domain], "total_messages": messages,
                **{name: _top_keys(bucket, name, 10) for name in identity_fields}, **counts,
            }
            if counts["dmarc_fail"]:
                if elapsed_days < self.settings.new_host_window_days:
                    kind = "new-host-fail"
                    title = "Neuer unbekannter Sender mit DMARC-Fail"
                elif prior["passed"] > 0 and prior["failed"] == 0:
                    kind = "host-degradation"
                    title = "Bekannter Sending Host hat sich verschlechtert"
                else:
                    kind, title = "host-fail", "DMARC-Fehlerquelle erkannt"
                if detection.get("profile") == "dynamic_ip":
                    title = "DMARC-Fail aus dynamischem IP-Bereich"
                events.append({**context,
                    "id": self.service._alert_id("v2", "dmarc-fail", event_domain, source_ip, report_day),
                    "priority": "critical", "kind": kind, "title": title,
                    "trigger": f"{counts['dmarc_fail']} × passed_dmarc:false",
                    "messages": counts["dmarc_fail"],
                })
            elif elapsed_days == 0:
                events.append({**context,
                    "id": self.service._alert_id("v2", "new-source-ip", event_domain, source_ip, report_day),
                    "priority": "warning", "kind": "new-source-ip", "title": "Neue Source-IP erkannt",
                    "trigger": f"Erstmals gesehen am {first_seen[:10]}", "messages": messages,
                })
            elif counts["spf_not_aligned"] or counts["dkim_not_aligned"]:
                names = [label for name, label in (("spf_not_aligned", "SPF nicht aligned"),
                                                  ("dkim_not_aligned", "DKIM nicht aligned")) if counts[name]]
                events.append({**context,
                    "id": self.service._alert_id("v2", "compensated-alignment", event_domain, source_ip, report_day),
                    "priority": "info", "kind": "compensated-alignment", "title": "Kompensiertes Alignment-Problem",
                    "trigger": f"{', '.join(names)} · DMARC bestanden",
                    "messages": _sum(bucket.get("alignment_affected", {})),
                })
            prior["passed"] += counts["dmarc_pass"]
            prior["failed"] += counts["dmarc_fail"]

        fresh = await report_freshness(self.client, self.settings, domain)
        known = self.store.remember_domain_reports(fresh, domain)
        monitored = self.store.list_domain_monitoring(self.settings.stale_report_days, domain)
        for item in known:
            try:
                canonical_domain(item["domain"])
            except ValueError:
                monitored.append(legacy_domain_monitoring(item, self.settings.stale_report_days))
        for item in monitored:
            event = domain_freshness_event(item, now)
            if event is not None:
                events.append(event)
        if evaluation_counts is not None:
            # Include evaluated report history even when it creates no warning.
            domains = set()
            for value in [item["key"]["domain"] for item in history_buckets + buckets] + [item["domain"] for item in monitored]:
                try:
                    domains.add(canonical_domain(value))
                except ValueError:
                    domains.add(value)
            hosts = {item["key"]["ip"] for item in history_buckets + buckets}
            evaluation_counts.update(domains=len(domains), hosts=len(hosts), events=len(events))
        return events

    @staticmethod
    def _legacy_aliases(legacy: list[dict], events: list[dict]) -> dict[str, str]:
        aliases = {}
        for old in legacy:
            # Never transfer a cross-domain aggregate's workflow to one domain.
            if old.get("source_ip") and old.get("header_froms") != [old["domain"]]:
                continue
            candidates = [event for event in events
                          if event["domain"] == old["domain"]
                          and event["source_ip"] == old["source_ip"]
                          and ((event["priority"] == old["priority"] == "critical")
                               or event["kind"] == old["kind"])]
            if len(candidates) == 1:
                candidate = candidates[0]
                # The old compensated-alignment count represented all messages.
                # Compare that same evidence scope while migrating its workflow.
                candidate_count = (
                    candidate["total_messages"]
                    if candidate["kind"] == "compensated-alignment"
                    else candidate["messages"]
                )
                if candidate_count == old["messages"]:
                    aliases[old["id"]] = candidate["id"]
        return aliases

    async def alerts(self, domain: str, days: int) -> list[dict[str, Any]]:
        return (await self.evaluate(domain, days))["items"]

    async def evaluate(self, domain: str, days: int) -> dict[str, Any]:
        async with self._lock:
            now = datetime.now(UTC)
            counts = {}
            if not self.store.alert_model_initialized():
                # Match the existing automatic lookback before enabling the new
                # model. Old baseline findings stay visible without bulk mail.
                baseline = await self._evaluate("*", 30, now, evaluation_counts=counts)
                if not self.store.remember_domain_reports([], "*"):
                    deliveries = self.store.notification_delivery_summary()
                    if self.store.alert_states() or any(deliveries[name] for name in ("sent", "failed", "pending")):
                        raise OpenSearchError(
                            "Bestehende Warnungszustände, aber keine Report-Historie verfügbar. "
                            "Die Ereignisübernahme wartet auf die historischen Daten."
                        )
                legacy = await self.service._legacy_alerts("*", 30)
                initial = self.store.save_alert_events(
                    baseline, bootstrap=True, aliases=self._legacy_aliases(legacy, baseline),
                )
                if domain == "*" and days == 30:
                    return {"items": self._sort(initial), "counts": counts}
            evaluated = await self._evaluate(domain, days, now, evaluation_counts=counts)
            return {"items": self._sort(self.store.save_alert_events(evaluated)), "counts": counts}

    @staticmethod
    def _sort(events: list[dict]) -> list[dict]:
        return sorted(events, key=lambda event: ({"critical": 0, "warning": 1, "info": 2}.get(event["priority"], 9),
                                                  event.get("report_time") or "", event["id"]))
