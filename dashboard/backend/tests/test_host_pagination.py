from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore


def host_bucket(
    source_ip: str,
    messages: int,
    *,
    failed: int = 0,
    spf_not_aligned: int = 0,
    dkim_not_aligned: int = 0,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def metric(value: int | float) -> dict[str, Any]:
        return {"value": value}

    now = datetime.now(UTC)
    return {
        "key": {"source_ip": source_ip},
        "first_seen": metric((now - timedelta(days=100)).timestamp() * 1000),
        "previous": {
            "dmarc_pass": {"messages": metric(20)},
            "dmarc_fail": {"messages": metric(2)},
        },
        "current": {
            "messages": metric(messages),
            "dmarc_pass": {"messages": metric(messages - failed)},
            "dmarc_fail": {"messages": metric(failed)},
            "spf_aligned": {"messages": metric(messages - spf_not_aligned)},
            "spf_not_aligned": {"messages": metric(spf_not_aligned)},
            "dkim_aligned": {"messages": metric(messages - dkim_not_aligned)},
            "dkim_not_aligned": {"messages": metric(dkim_not_aligned)},
            "last_seen": metric((now - timedelta(days=1)).timestamp() * 1000),
            "header_froms": {"buckets": [{"key": "header.example"}]},
            "envelope_froms": {"buckets": [{"key": "envelope.example"}]},
            "latest": {
                "hits": {
                    "hits": [{"_source": {"source_ip_address": source_ip, **(source or {})}}]
                }
            },
        },
    }


class CompositeClient:
    """Model ordered composite pages, including the final empty page."""

    def __init__(self, buckets: list[dict[str, Any]]) -> None:
        self.buckets = sorted(buckets, key=lambda bucket: bucket["key"]["source_ip"])
        self.calls: list[dict[str, Any]] = []

    async def search(
        self, index: str, body: dict[str, Any], *, allow_missing: bool = False
    ) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(body))
        aggregation = body["aggs"]["hosts"]
        assert "terms" not in aggregation
        composite = aggregation["composite"]
        assert composite["sources"] == [
            {"source_ip": {"terms": {"field": "source_ip_address.keyword"}}}
        ]
        candidates = self.buckets
        for query_filter in body["query"].get("bool", {}).get("filter", []):
            source_ip = query_filter.get("term", {}).get("source_ip_address.keyword")
            if source_ip:
                candidates = [bucket for bucket in candidates if bucket["key"]["source_ip"] == source_ip]
        cursor = composite.get("after", {}).get("source_ip")
        if cursor:
            candidates = [bucket for bucket in candidates if bucket["key"]["source_ip"] > cursor]
        page = candidates[:composite["size"]]
        result: dict[str, Any] = {"buckets": page}
        if page:
            result["after_key"] = page[-1]["key"]
        return {"timed_out": False, "_shards": {"failed": 0}, "aggregations": {"hosts": result}}


class SequenceClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0
        self.bodies: list[dict[str, Any]] = []

    async def search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        self.bodies.append(copy.deepcopy(args[1]))
        if self.calls > len(self.responses):
            raise AssertionError("Pagination continued beyond the supplied responses")
        return self.responses[self.calls - 1]


def response_page(
    buckets: list[dict[str, Any]], after: str | None = None, **metadata: Any
) -> dict[str, Any]:
    aggregation: dict[str, Any] = {"buckets": buckets}
    if after is not None:
        aggregation["after_key"] = {"source_ip": after}
    return {"aggregations": {"hosts": aggregation}, **metadata}


class HostPaginationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(database_path=Path(self.directory.name) / "state.db")
        self.store = StateStore(self.settings.database_path)

    def service(self, client: Any) -> DashboardService:
        return DashboardService(client, self.store, self.settings)

    async def test_reads_over_1000_hosts_and_sorts_before_limit(self) -> None:
        buckets = [host_bucket(f"10.{number // 256}.{number % 256}.1", number + 1) for number in range(1005)]
        client = CompositeClient(buckets)
        all_hosts = await self.service(client).hosts("*", 30, limit=None)
        self.assertEqual(len(all_hosts), 1005)
        self.assertEqual([host["messages"] for host in all_hosts], list(range(1005, 0, -1)))
        self.assertEqual(len(client.calls), 4)
        limited = await self.service(CompositeClient(buckets)).hosts("*", 30, limit=2, offset=1)
        self.assertEqual([host["source_ip"] for host in limited], [host["source_ip"] for host in all_hosts[1:3]])

    async def test_low_volume_risk_host_is_found_after_all_candidate_pages(self) -> None:
        buckets = [host_bucket(f"10.{number // 256}.{number % 256}.1", 100) for number in range(1005)]
        buckets.append(host_bucket("203.0.113.9", 1, failed=1, spf_not_aligned=1, dkim_not_aligned=1))
        for risk in ("critical", "spf-not-aligned", "dkim-not-aligned"):
            with self.subTest(risk=risk):
                result = await self.service(CompositeClient(buckets)).hosts("*", 30, risk=risk, limit=1)
                self.assertEqual([host["source_ip"] for host in result], ["203.0.113.9"])
                self.assertEqual(result[0]["dmarc_fail"], 1)

    async def test_page_total_and_search_apply_before_offset_and_limit(self) -> None:
        buckets = [
            host_bucket("192.0.2.2", 20, source={"source_as_name": "Target Network"}),
            host_bucket("192.0.2.1", 20, source={"source_reverse_dns": "target.example"}),
            host_bucket("192.0.2.3", 30),
            host_bucket("192.0.2.4", 1, source={"source_base_domain": "target.example"}),
            host_bucket("192.0.2.5", 0, source={"source_base_domain": "target.example"}),
        ]
        page = await self.service(CompositeClient(buckets)).hosts_page("*", 30, search=" TARGET ", limit=1, offset=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["offset"], 1)
        self.assertEqual([host["source_ip"] for host in page["items"]], ["192.0.2.2"])
        beyond_end = await self.service(CompositeClient(buckets)).hosts_page("*", 30, search="target", offset=3)
        self.assertEqual(beyond_end["total"], 3)
        self.assertEqual(beyond_end["items"], [])

    async def test_search_keeps_existing_identity_and_manual_service_fields(self) -> None:
        self.store.set_host_override("192.0.2.1", service_name="Manual Provider", trust_status="confirmed", notes=None)
        buckets = [host_bucket("192.0.2.1", 10)]
        for search in ("192.0.2.1", "manual provider", "HEADER.EXAMPLE", "envelope.example"):
            with self.subTest(search=search):
                result = await self.service(CompositeClient(buckets)).hosts_page("*", 30, search=search)
                self.assertEqual(result["total"], 1)

    async def test_exact_ip_keeps_domain_filter_and_historical_metrics(self) -> None:
        client = CompositeClient([host_bucket("192.0.2.1", 10, failed=1), host_bucket("192.0.2.2", 100)])
        result = await self.service(client).hosts("header.example", 90, source_ip="192.0.2.1", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_ip"], "192.0.2.1")
        self.assertEqual(result[0]["previous_dmarc_pass"], 20)
        self.assertEqual(result[0]["previous_dmarc_fail"], 2)
        self.assertFalse(result[0]["is_new"])
        self.assertEqual(result[0]["pass_rate"], 90)
        query = client.calls[0]
        self.assertEqual(query["query"]["bool"]["filter"], [
            {"term": {"header_from.keyword": "header.example"}},
            {"term": {"source_ip_address.keyword": "192.0.2.1"}},
        ])
        self.assertEqual(query["aggs"]["hosts"]["aggs"]["first_seen"], {"min": {"field": "date_begin"}})
        self.assertIn("current", query["aggs"]["hosts"]["aggs"])
        self.assertIn("previous", query["aggs"]["hosts"]["aggs"])
        metrics = query["aggs"]["hosts"]["aggs"]
        current_range = metrics["current"]["filter"]["range"]["date_begin"]
        self.assertNotIn("now", str(current_range))
        self.assertEqual(
            metrics["previous"]["filter"]["range"]["date_begin"]["lt"],
            current_range["gte"],
        )
        self.assertEqual(
            metrics,
            client.calls[1]["aggs"]["hosts"]["aggs"],
        )

    async def test_partial_response_on_later_page_never_returns_first_page(self) -> None:
        for metadata in (
            {"timed_out": True},
            {"terminated_early": True},
            {"_shards": {"failed": 1}},
        ):
            with self.subTest(metadata=metadata):
                client = SequenceClient([
                    response_page([host_bucket("192.0.2.1", 10)], after="192.0.2.1"),
                    response_page([host_bucket("192.0.2.2", 1, failed=1)], **metadata),
                ])
                with self.assertRaises(OpenSearchError):
                    await self.service(client).hosts("*", 30, limit=1)
                self.assertEqual(client.calls, 2)

    async def test_repeated_cursor_and_duplicate_buckets_fail_without_looping(self) -> None:
        for second_page in (
            response_page([host_bucket("192.0.2.2", 5)], after="192.0.2.1"),
            response_page([host_bucket("192.0.2.1", 5)], after="192.0.2.2"),
            response_page([], after="192.0.2.2"),
            {"aggregations": {}},
        ):
            with self.subTest(second_page=second_page):
                client = SequenceClient([
                    response_page([host_bucket("192.0.2.1", 10)], after="192.0.2.1"),
                    second_page,
                ])
                with self.assertRaises(OpenSearchError):
                    await self.service(client).hosts("*", 30)
                self.assertEqual(client.calls, 2)

    async def test_uses_server_cursor_when_it_differs_from_last_bucket(self) -> None:
        client = SequenceClient([
            response_page([host_bucket("192.0.2.1", 10)], after="192.0.2.15"),
            response_page([host_bucket("192.0.2.2", 1)]),
        ])
        result = await self.service(client).hosts("*", 30, limit=None)
        self.assertEqual(len(result), 2)
        self.assertEqual(
            client.bodies[1]["aggs"]["hosts"]["composite"]["after"],
            {"source_ip": "192.0.2.15"},
        )


if __name__ == "__main__":
    unittest.main()
