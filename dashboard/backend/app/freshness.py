from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .opensearch import OpenSearchClient, OpenSearchError


_PAGE_SIZE = 500


async def report_freshness(
    client: OpenSearchClient,
    settings: Settings,
    domain: str = "*",
    *,
    include_inventory: bool = False,
) -> list[dict[str, Any]]:
    """Return the latest report-period end for every observed domain.

    Frische ist unabhängig vom Anzeigezeitraum. Die vollständige Historie
    bleibt deshalb auch bei langen Ausfällen die Grundlage dieser Abfrage.
    """
    items: list[dict[str, Any]] = []
    after: dict[str, Any] | None = None
    seen_cursors: set[str] = set()
    seen_domains: set[str] = set()
    while True:
        composite: dict[str, Any] = {
            "size": _PAGE_SIZE,
            "sources": [
                {"domain": {"terms": {"field": "header_from.keyword"}}}
            ],
        }
        if after is not None:
            composite["after"] = after
        body = {
            "size": 0,
            "query": (
                {"term": {"header_from.keyword": domain}}
                if domain and domain != "*"
                else {"match_all": {}}
            ),
            "aggs": {
                "domains": {
                    "composite": composite,
                    "aggs": {"last_report": {"max": {"field": "date_end"}}},
                }
            },
        }
        if include_inventory:
            body["aggs"]["domains"]["aggs"].update({
                "messages": {"sum": {"field": "message_count"}},
                "last_seen": {"max": {"field": "date_begin"}},
            })
        response = await client.search(
            settings.aggregate_index, body, allow_missing=True
        )
        if response.get("timed_out") or response.get("terminated_early") or response.get("_shards", {}).get(
            "failed", 0
        ):
            raise OpenSearchError(
                "Report-Frische konnte nicht vollständig ermittelt werden: "
                "Zeitüberschreitung oder fehlgeschlagene OpenSearch-Shards"
            )
        aggregations = response.get("aggregations")
        if aggregations is None or isinstance(aggregations, dict) and "domains" not in aggregations:
            total_hits = response.get("hits", {}).get("total")
            if isinstance(total_hits, dict):
                total_hits = total_hits.get("value")
            if after is None and not aggregations and type(total_hits) is int and total_hits == 0:
                return []
            raise OpenSearchError("Report-Frische: Aggregation fehlt in der Abfrageantwort")
        if not isinstance(aggregations, dict):
            raise OpenSearchError("Report-Frische: ungültige Aggregation")
        aggregation = aggregations["domains"]
        if not isinstance(aggregation, dict) or not isinstance(aggregation.get("buckets"), list):
            raise OpenSearchError("Report-Frische: ungültige Aggregation")
        for bucket in aggregation["buckets"]:
            report_domain = bucket["key"]["domain"]
            last_report = bucket.get("last_report", {}).get("value")
            if report_domain in (None, "", "-") or last_report is None:
                continue
            if report_domain in seen_domains:
                raise OpenSearchError("Report-Frische: Domain auf mehreren Seiten enthalten")
            seen_domains.add(report_domain)
            item = {
                "domain": str(report_domain),
                "last_report": datetime.fromtimestamp(
                    float(last_report) / 1000, tz=UTC
                ).isoformat(),
            }
            if include_inventory:
                last_seen = bucket.get("last_seen", {}).get("value")
                item.update({
                    "messages": int(round(float(bucket.get("messages", {}).get("value") or 0))),
                    "last_seen": (datetime.fromtimestamp(float(last_seen) / 1000, tz=UTC).isoformat()
                                  if last_seen is not None else None),
                })
            items.append(item)

        next_after = aggregation.get("after_key")
        if next_after is None:
            return items
        if not isinstance(next_after, dict) or not isinstance(next_after.get("domain"), str):
            raise OpenSearchError("Report-Frische: ungültiger Seitenschlüssel")
        cursor = next_after["domain"]
        if cursor in seen_cursors or (after is not None and cursor <= after["domain"]):
            raise OpenSearchError(
                "Report-Frische konnte nicht vollständig ermittelt werden: "
                "OpenSearch hat einen Seitenschlüssel wiederholt"
            )
        seen_cursors.add(cursor)
        after = next_after
