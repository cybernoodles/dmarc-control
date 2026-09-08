from __future__ import annotations

import copy
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings
from app.freshness import report_freshness
from app.opensearch import OpenSearchError


class ReportClient:
    """Model date/domain filtering and domain max aggregation on report rows."""

    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.reports = reports
        self.calls: list[dict[str, Any]] = []

    async def search(self, index, body, *, allow_missing=False):
        self.calls.append(copy.deepcopy(body))
        query = body["query"]
        reports = self.reports
        if "term" in query:
            selected_domain = query["term"]["header_from.keyword"]
            reports = [r for r in reports if r["domain"] == selected_domain]
        elif query != {"match_all": {}}:
            raise AssertionError("Freshness must not depend on a date window")
        latest: dict[str, datetime] = {}
        for report in reports:
            name = report["domain"]
            if name not in latest or report["date_end"] > latest[name]:
                latest[name] = report["date_end"]
        composite = body["aggs"]["domains"]["composite"]
        after = composite.get("after", {}).get("domain")
        names = [name for name in sorted(latest) if after is None or name > after]
        page = names[: composite["size"]]
        result: dict[str, Any] = {
            "buckets": [
                {
                    "key": {"domain": name},
                    "last_report": {"value": latest[name].timestamp() * 1000},
                }
                for name in page
            ]
        }
        if len(page) < len(names):
            result["after_key"] = {"domain": page[-1]}
        return {"aggregations": {"domains": result}, "_shards": {"failed": 0}}


class PageClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    async def search(self, index, body, *, allow_missing=False):
        self.calls.append(copy.deepcopy(body))
        return next(self.pages)


class ReportFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_domain_does_not_mask_stale_domain(self) -> None:
        now = datetime(2026, 9, 8, tzinfo=UTC)
        old = now - timedelta(days=4)
        client = ReportClient(
            [
                {"domain": "active.example", "date_end": now},
                {"domain": "stale.example", "date_end": old},
                {"domain": "stale.example", "date_end": old - timedelta(days=2)},
            ]
        )

        result = await report_freshness(client, Settings())

        self.assertEqual(
            result,
            [
                {"domain": "active.example", "last_report": now.isoformat()},
                {"domain": "stale.example", "last_report": old.isoformat()},
            ],
        )
        self.assertEqual(
            client.calls[0]["aggs"]["domains"]["aggs"]["last_report"],
            {"max": {"field": "date_end"}},
        )

    async def test_outage_older_than_default_lookback_remains_known(self) -> None:
        old = datetime.now(UTC).replace(microsecond=0) - timedelta(days=45)
        client = ReportClient([{"domain": "stale.example", "date_end": old}])

        result = await report_freshness(client, Settings())

        self.assertEqual(
            result, [{"domain": "stale.example", "last_report": old.isoformat()}]
        )
        self.assertNotIn("range", str(client.calls))

    async def test_all_domains_are_returned_across_multiple_pages(self) -> None:
        end = datetime(2026, 9, 8, tzinfo=UTC)
        reports = [
            {"domain": f"domain-{index:04d}.example", "date_end": end}
            for index in range(1101)
        ]
        client = ReportClient(reports)

        result = await report_freshness(client, Settings())

        self.assertEqual(len(result), 1101)
        self.assertEqual({r["domain"] for r in result}, {r["domain"] for r in reports})
        self.assertGreater(len(client.calls), 1)

    async def test_explicit_domain_filter_excludes_other_domains(self) -> None:
        end = datetime(2026, 9, 8, tzinfo=UTC)
        client = ReportClient(
            [
                {"domain": "selected.example", "date_end": end},
                {"domain": "other.example", "date_end": end},
            ]
        )

        result = await report_freshness(client, Settings(), "selected.example")

        self.assertEqual(
            result, [{"domain": "selected.example", "last_report": end.isoformat()}]
        )

    async def test_empty_history_or_missing_index_does_not_invent_a_domain(self) -> None:
        self.assertEqual(await report_freshness(ReportClient([]), Settings()), [])
        self.assertEqual(
            await report_freshness(PageClient([{"aggregations": {}}]), Settings()),
            [],
        )

    async def test_uses_returned_cursor_instead_of_last_bucket(self) -> None:
        client = PageClient(
            [
                {
                    "aggregations": {
                        "domains": {
                            "buckets": [
                                {"key": {"domain": "a.example"}, "last_report": {"value": 0}}
                            ],
                            "after_key": {"domain": "b.example"},
                        }
                    }
                },
                {"aggregations": {"domains": {"buckets": []}}},
            ]
        )

        await report_freshness(client, Settings())

        self.assertEqual(
            client.calls[1]["aggs"]["domains"]["composite"]["after"],
            {"domain": "b.example"},
        )

    async def test_incomplete_page_is_rejected_without_partial_result(self) -> None:
        first_page = {
            "aggregations": {
                "domains": {
                    "buckets": [
                        {"key": {"domain": "a.example"}, "last_report": {"value": 0}}
                    ],
                    "after_key": {"domain": "a.example"},
                }
            }
        }
        for failure in ({"timed_out": True}, {"_shards": {"failed": 1}}):
            with self.subTest(failure=failure):
                client = PageClient([first_page, failure])
                with self.assertRaises(OpenSearchError):
                    await report_freshness(client, Settings())

    async def test_repeated_cursor_raises_instead_of_looping_forever(self) -> None:
        page = {
            "aggregations": {
                "domains": {
                    "buckets": [
                        {"key": {"domain": "a.example"}, "last_report": {"value": 0}}
                    ],
                    "after_key": {"domain": "a.example"},
                }
            }
        }
        with self.assertRaises(OpenSearchError):
            await report_freshness(PageClient([page, page]), Settings())


if __name__ == "__main__":
    unittest.main()
