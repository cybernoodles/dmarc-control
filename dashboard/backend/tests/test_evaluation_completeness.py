from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.config import Settings
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore
from test_alert_events import FixedClock, ReportClient, report
from test_notifications import notification_configuration


EMPTY_INDEX = {"hits": {"total": {"value": 0}}, "aggregations": {}}


class FaultyPageClient(ReportClient):
    def __init__(self, reports, *, stage, followup, malformed):
        super().__init__(reports)
        self.stage = stage
        self.followup = followup
        self.malformed = malformed
        self.injected = False

    async def search(self, index, body, *, allow_missing=False):
        name = next(iter(body["aggs"]))
        composite = body["aggs"][name]["composite"]
        stage = "freshness" if name == "domains" else (
            "daily" if "day" in composite["sources"][0] else "history"
        )
        if stage == self.stage and ("after" in composite) == self.followup:
            self.injected = True
            return {"hits": {"total": {"value": 0}}, "aggregations": {name: copy.deepcopy(self.malformed)}}
        return await super().search(index, body, allow_missing=allow_missing)


class EvaluationCompletenessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "state.db")
        self.store = StateStore(self.settings.database_path)
        self.store.save_alert_events([], bootstrap=True)
        clock = patch("app.alert_events.datetime", FixedClock)
        clock.start()
        self.addCleanup(clock.stop)

    @staticmethod
    def rows(stage):
        if stage == "freshness":
            return [report(1, domain=f"domain-{index:04d}.example", passed=False) for index in range(520)]
        return [report(1, source_ip=f"10.0.{index // 256}.{index % 256}", passed=False) for index in range(260)]

    async def test_named_aggregation_must_contain_list_buckets_on_first_and_later_pages(self):
        for stage in ("daily", "freshness"):
            for followup in (False, True):
                for malformed in ({}, {"other": []}, {"buckets": None}, {"buckets": {}}, {"buckets": "invalid"}, None, []):
                    with self.subTest(stage=stage, followup=followup, malformed=malformed):
                        client = FaultyPageClient(
                            self.rows(stage), stage=stage, followup=followup, malformed=malformed,
                        )
                        service = DashboardService(client, self.store, self.settings)
                        with self.assertRaises(OpenSearchError):
                            await service.alert_evaluation("*", 30)
                        self.assertTrue(client.injected)

    async def test_missing_aggregation_requires_explicit_empty_hit_count_on_initial_page(self):
        for response in ({"aggregations": {}}, {}, {"hits": {"total": {"value": 1}}, "aggregations": {}}):
            with self.subTest(response=response):
                client = AsyncMock()
                client.search.return_value = response
                service = DashboardService(client, self.store, self.settings)
                with self.assertRaises(OpenSearchError):
                    await service.alert_evaluation("*", 30)

    async def test_explicit_empty_index_response_is_a_complete_zero_result(self):
        for response in (EMPTY_INDEX, {"hits": {"total": {"value": 0}}}):
            with self.subTest(response=response):
                client = AsyncMock()
                client.search.return_value = response
                service = DashboardService(client, self.store, self.settings)
                result = await service.alert_evaluation("*", 30)
                self.assertEqual(result, {"items": [], "counts": {"domains": 0, "hosts": 0, "events": 0}})

    async def test_normal_empty_final_page_preserves_all_260_events(self):
        client = ReportClient(self.rows("daily"))
        result = await DashboardService(client, self.store, self.settings).alert_evaluation("*", 30)
        self.assertEqual(len(result["items"]), 260)
        self.assertEqual(len({item["id"] for item in result["items"]}), 260)
        self.assertEqual(result["counts"], {"domains": 1, "hosts": 260, "events": 260})

    async def test_freshness_pages_keep_all_520_domains_and_events(self):
        client = ReportClient(self.rows("freshness"))
        result = await DashboardService(client, self.store, self.settings).alert_evaluation("*", 30)
        self.assertEqual(len(result["items"]), 520)
        self.assertEqual(result["counts"], {"domains": 520, "hosts": 1, "events": 520})

    async def test_malformed_followup_marks_dispatch_failure_and_never_sends(self):
        configuration = notification_configuration()
        configuration["cases"] = ["new-host-fail"]
        self.store.save_notification_settings(settings=configuration, secret_ciphertext="unused")
        previous_id = self.store.start_evaluation({"domain": "*", "days": 30})
        self.store.finish_evaluation(previous_id, "success", 1, {"domains": 0, "hosts": 0, "events": 0})
        previous = self.store.evaluation_status()["last_success"]
        for stage in ("daily", "freshness"):
            with self.subTest(stage=stage):
                client = FaultyPageClient(self.rows(stage), stage=stage, followup=True, malformed={})
                service = DashboardService(client, self.store, self.settings)
                with (
                    patch.object(main, "store", self.store),
                    patch.object(main, "service", service),
                    patch.object(main, "_resolved_notification_configuration", return_value=(configuration, {})),
                    patch.object(main, "send_message", return_value=[]) as sender,
                ):
                    with self.assertRaises(OpenSearchError):
                        await main.dispatch_notification_cycle()
                sender.assert_not_called()
                status = self.store.evaluation_status()
                self.assertEqual(status["latest"]["status"], "failure")
                self.assertEqual(status["latest"]["counts"], {"domains": None, "hosts": None, "events": None})
                self.assertEqual(status["last_success"], previous)
                self.assertEqual(self.store.recipient_delivery_summary()["total"], 0)


if __name__ == "__main__":
    unittest.main()
