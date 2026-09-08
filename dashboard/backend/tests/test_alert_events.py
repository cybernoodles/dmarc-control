from __future__ import annotations

import copy
import tempfile
import unittest
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from app.alert_events import AlertEngine
from app.config import Settings
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore


NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def report(
    days_ago: int,
    *,
    domain: str = "a.example",
    source_ip: str = "192.0.2.1",
    messages: int = 1,
    passed: bool = True,
) -> dict[str, Any]:
    begin = (NOW - timedelta(days=days_ago)).replace(hour=0)
    return {
        "date_begin": begin,
        "date_end": begin + timedelta(days=1),
        "header_from": domain,
        "envelope_from": domain,
        "source_ip_address": source_ip,
        "source_country": "CH",
        "message_count": messages,
        "passed_dmarc": passed,
        "spf_aligned": passed,
        "dkim_aligned": passed,
    }


class ReportClient:
    """Evaluate the engine's composite history, daily and freshness queries.

    Fixture data represents aggregate-report rows, rather than precomputed alert
    payloads, so pagination and date/domain scoping are exercised together.
    """

    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.reports = reports
        self.calls: list[dict[str, Any]] = []
        self.daily_followup_failure: dict[str, Any] | None = None

    @staticmethod
    def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
        if "match_all" in query:
            return True
        if "bool" in query:
            return all(ReportClient._matches(row, part) for part in query["bool"]["filter"])
        if "term" in query:
            return all(row.get(field.removesuffix(".keyword")) == value for field, value in query["term"].items())
        if "range" in query:
            for field, conditions in query["range"].items():
                value = row[field]
                for operator, bound in conditions.items():
                    boundary = datetime.fromisoformat(bound)
                    if operator == "lt" and not value < boundary:
                        return False
                    if operator == "gte" and not value >= boundary:
                        return False
                    if operator == "lte" and not value <= boundary:
                        return False
            return True
        raise AssertionError(f"Unsupported query: {query}")

    @staticmethod
    def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        mechanisms = {
            "dmarc_pass": ("passed_dmarc", True),
            "dmarc_fail": ("passed_dmarc", False),
            "spf_aligned": ("spf_aligned", True),
            "spf_not_aligned": ("spf_aligned", False),
            "dkim_aligned": ("dkim_aligned", True),
            "dkim_not_aligned": ("dkim_aligned", False),
        }
        return {
            name: {"messages": {"value": sum(row["message_count"] for row in rows if row[field] == value)}}
            for name, (field, value) in mechanisms.items()
        }

    async def search(
        self, index: str, body: dict[str, Any], *, allow_missing: bool = False
    ) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(body))
        name = next(iter(body["aggs"]))
        aggregation = body["aggs"][name]
        composite = aggregation["composite"]
        source_names = [next(iter(source)) for source in composite["sources"]]
        daily = source_names[0] == "day"
        if daily and "after" in composite and self.daily_followup_failure is not None:
            return copy.deepcopy(self.daily_followup_failure)

        groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for row in self.reports:
            if not self._matches(row, body["query"]):
                continue
            values = {
                "domain": row["header_from"],
                "ip": row["source_ip_address"],
                "day": int(row["date_begin"].timestamp() * 1000),
            }
            groups[tuple(values[source] for source in source_names)].append(row)
        after = composite.get("after")
        after_values = tuple(after[source] for source in source_names) if after else None
        keys = [key for key in sorted(groups) if after_values is None or key > after_values]
        buckets = []
        for key in keys[:composite["size"]]:
            rows = groups[key]
            bucket: dict[str, Any] = {"key": dict(zip(source_names, key))}
            if name == "domains":
                bucket["last_report"] = {"value": max(row["date_end"].timestamp() * 1000 for row in rows)}
            elif daily:
                latest = max(rows, key=lambda row: row["date_begin"])
                bucket.update({
                    "messages": {"value": sum(row["message_count"] for row in rows)},
                    **self._metrics(rows),
                    "latest": {"hits": {"hits": [{"_source": latest}]}},
                    "envelope_froms": {"buckets": [{"key": latest["envelope_from"]}]},
                })
            else:
                previous_query = aggregation["aggs"]["previous"]["filter"]
                previous = [row for row in rows if self._matches(row, previous_query)]
                bucket.update({
                    "first_seen": {"value": min(row["date_begin"].timestamp() * 1000 for row in rows)},
                    "previous": self._metrics(previous),
                })
            buckets.append(bucket)
        result: dict[str, Any] = {"buckets": buckets}
        if buckets:
            result["after_key"] = buckets[-1]["key"]
        return {"aggregations": {name: result}, "timed_out": False, "_shards": {"failed": 0}}


class AlertEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(database_path=Path(self.directory.name) / "state.db")
        self.store = StateStore(self.settings.database_path)
        clock = patch("app.alert_events.datetime", FixedClock)
        clock.start()
        self.addCleanup(clock.stop)

    def engine(self, reports: list[dict[str, Any]]) -> tuple[AlertEngine, ReportClient]:
        client = ReportClient(reports)
        service = DashboardService(client, self.store, self.settings)
        # Legacy migration itself is covered separately; use the real event/store
        # path and avoid unrelated old host aggregation queries in these tests.
        service._legacy_alerts = AsyncMock(return_value=[])
        return AlertEngine(service), client

    @staticmethod
    def failures(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [event for event in events if event["priority"] == "critical"]

    async def test_resolved_fail_keeps_id_status_and_day_when_later_reports_pass(self) -> None:
        engine, client = self.engine([report(60), report(2, messages=4, passed=False)])
        original = self.failures(await engine.alerts("*", 30))[0]
        self.store.set_alert_status(original["id"], "resolved")
        client.reports.append(report(1, messages=100))
        current = self.failures(await engine.alerts("*", 30))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["id"], original["id"])
        self.assertEqual(current[0]["status"], "resolved")
        self.assertEqual(current[0]["report_time"], original["report_time"])
        self.assertEqual(current[0]["messages"], 4)
        self.assertEqual(current[0]["dmarc_pass"], 0)
        self.assertFalse(current[0]["notification_eligible"])

    async def test_new_failure_day_creates_only_one_new_eligible_event(self) -> None:
        engine, client = self.engine([report(60), report(2, messages=4, passed=False), report(1)])
        original = self.failures(await engine.alerts("*", 30))[0]
        self.store.set_alert_status(original["id"], "resolved")
        client.reports.append(report(0, messages=3, passed=False))
        failures = self.failures(await engine.alerts("*", 30))
        self.assertEqual(len(failures), 2)
        previous = next(event for event in failures if event["id"] == original["id"])
        latest = next(event for event in failures if event["id"] != original["id"])
        self.assertEqual(previous["status"], "resolved")
        self.assertEqual(latest["status"], "open")
        self.assertTrue(latest["notification_eligible"])
        self.assertEqual(latest["messages"], 3)
        self.assertEqual(latest["report_time"][:10], NOW.date().isoformat())
        self.assertEqual(len(self.failures(await engine.alerts("*", 30))), 2)

    async def test_global_and_domain_views_share_event_id_and_status_without_mixing_domains(self) -> None:
        engine, _ = self.engine([
            report(60), report(60, domain="b.example"),
            report(2, messages=4, passed=False),
            report(2, domain="b.example", messages=200),
            report(1), report(1, domain="b.example"),
        ])
        global_event = self.failures(await engine.alerts("*", 30))[0]
        self.assertEqual(global_event["domain"], "a.example")
        self.assertEqual(global_event["header_froms"], ["a.example"])
        self.assertEqual(global_event["messages"], 4)
        self.store.set_alert_status(global_event["id"], "acknowledged")
        domain_event = self.failures(await engine.alerts("a.example", 30))[0]
        self.assertEqual(domain_event["id"], global_event["id"])
        self.assertEqual(domain_event["status"], "acknowledged")
        self.assertEqual(self.failures(await engine.alerts("b.example", 30)), [])

    async def test_all_260_hosts_produce_events_across_composite_pages(self) -> None:
        rows = [report(1, source_ip=f"10.0.{number // 256}.{number % 256}", passed=False) for number in range(260)]
        engine, client = self.engine(rows)
        failures = self.failures(await engine.alerts("*", 30))
        self.assertEqual(len(failures), 260)
        self.assertEqual(len({event["id"] for event in failures}), 260)
        daily_queries = [call for call in client.calls if "events" in call["aggs"] and "day" in call["aggs"]["events"]["composite"]["sources"][0]]
        self.assertEqual(len(daily_queries), 3)
        self.assertTrue(self.store.alert_model_initialized())

    async def test_event_kind_uses_history_at_event_day_across_display_windows(self) -> None:
        engine, _ = self.engine([report(60), report(20, passed=False), report(2, passed=False), report(1)])
        wide = self.failures(await engine._evaluate("a.example", 30, NOW))
        narrow = self.failures(await engine._evaluate("a.example", 7, NOW))
        self.assertEqual(wide[0]["kind"], "host-degradation")
        self.assertEqual(wide[1]["kind"], "host-fail")
        self.assertEqual(narrow[0]["id"], wide[1]["id"])
        self.assertEqual(narrow[0]["kind"], wide[1]["kind"])

        engine, _ = self.engine([report(15), report(12, passed=False), report(1)])
        wide = self.failures(await engine._evaluate("a.example", 30, NOW))
        narrow = self.failures(await engine._evaluate("a.example", 14, NOW))
        self.assertEqual(wide[0]["kind"], "new-host-fail")
        self.assertEqual(narrow[0]["kind"], "new-host-fail")
        self.assertEqual(narrow[0]["id"], wide[0]["id"])

    async def test_first_seen_event_occurs_once_instead_of_each_report_day(self) -> None:
        engine, client = self.engine([report(2), report(1)])
        initial = await engine.alerts("*", 30)
        self.assertEqual([event["kind"] for event in initial], ["new-source-ip"])
        client.reports.append(report(0))
        later = await engine.alerts("*", 30)
        self.assertEqual(len(later), 1)
        self.assertEqual(later[0]["id"], initial[0]["id"])
        self.assertEqual(later[0]["report_time"][:10], (NOW - timedelta(days=2)).date().isoformat())

    async def test_event_snapshot_and_status_remain_available_outside_display_window(self) -> None:
        engine, _ = self.engine([report(60), report(2, messages=4, passed=False), report(0)])
        original = self.failures(await engine.alerts("*", 30))[0]
        self.store.set_alert_status(original["id"], "resolved")
        self.assertEqual(self.failures(await engine.alerts("*", 1)), [])
        historical = self.store.stored_alert(original["id"])
        self.assertIsNotNone(historical)
        self.assertTrue(historical["historical"])
        self.assertEqual(historical["status"], "resolved")
        self.assertEqual(historical["domain"], "a.example")
        self.assertEqual(historical["messages"], 4)
        self.assertEqual(historical["report_time"], original["report_time"])

    async def test_incomplete_later_page_never_commits_upgrade_baseline(self) -> None:
        failures = [
            {"timed_out": True, "aggregations": {"events": {"buckets": []}}},
            {"_shards": {"failed": 1}, "aggregations": {"events": {"buckets": []}}},
            {"terminated_early": True, "aggregations": {"events": {"buckets": []}}},
            {"aggregations": {}},
        ]
        for response in failures:
            with self.subTest(response=response):
                rows = [report(1, source_ip=f"10.0.{number // 256}.{number % 256}", passed=False) for number in range(260)]
                engine, client = self.engine(rows)
                client.daily_followup_failure = response
                with self.assertRaises(OpenSearchError):
                    await engine.alerts("*", 30)
                self.assertFalse(self.store.alert_model_initialized())
                self.assertEqual(self.store.alert_states(), {})
                first_event_id = DashboardService._alert_id(
                    "v2", "dmarc-fail", "a.example", "10.0.0.0",
                    (NOW - timedelta(days=1)).date().isoformat(),
                )
                self.assertIsNone(self.store.stored_alert(first_event_id))
        client.daily_followup_failure = None
        recovered = await engine.alerts("*", 30)
        self.assertEqual(len(self.failures(recovered)), 260)
        self.assertTrue(self.store.alert_model_initialized())
        self.assertTrue(all(not event["notification_eligible"] for event in recovered))


if __name__ == "__main__":
    unittest.main()
