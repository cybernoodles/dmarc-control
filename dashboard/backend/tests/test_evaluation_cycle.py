from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.notifications import NotificationDeliveryError, RecipientDeliveryResult, test_alert as example_alert
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore
from test_alert_events import FixedClock, ReportClient, report
from test_notifications import notification_configuration


class EvaluationCycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "state.db")
        self.store = StateStore(self.settings.database_path)
        self.config = notification_configuration()
        self.config["cases"] = ["host-fail"]
        self.store.save_notification_settings(settings=self.config, secret_ciphertext="unused")
        self.store.save_alert_events([], bootstrap=True)
        for target, value in (("store", self.store),):
            patched = patch.object(main, target, value)
            patched.start()
            self.addCleanup(patched.stop)
        resolved = patch.object(main, "_resolved_notification_configuration", return_value=(self.config, {}))
        self.resolve = resolved.start()
        self.addCleanup(resolved.stop)
        clock = patch("app.alert_events.datetime", FixedClock)
        clock.start()
        self.addCleanup(clock.stop)
        self.sender = patch.object(main, "send_message").start()
        self.addCleanup(patch.stopall)

    def real_service(self, rows):
        client = ReportClient(rows)
        service = DashboardService(client, self.store, self.settings)
        return service, client

    async def test_empty_success_is_persisted_and_manual_queries_do_not_count(self):
        service, _ = self.real_service([])
        await service.alerts("*", 30)
        self.assertIsNone(self.store.evaluation_status()["latest"])
        with patch.object(main, "service", service):
            await main.dispatch_notification_cycle()
        status = StateStore(self.settings.database_path).evaluation_status()
        self.assertEqual(status["latest"]["status"], "success")
        self.assertEqual(status["latest"]["counts"], {"domains": 0, "hosts": 0, "events": 0})
        self.assertEqual(status["latest"], status["last_success"])
        self.sender.assert_not_called()

    async def test_scope_counts_include_healthy_hosts_without_current_warnings(self):
        service, _ = self.real_service([
            report(40), report(0),
            report(40, domain="b.example", source_ip="192.0.2.2"),
            report(0, domain="b.example", source_ip="192.0.2.2"),
        ])
        with patch.object(main, "service", service):
            await main.dispatch_notification_cycle()
        self.assertEqual(self.store.evaluation_status()["latest"]["counts"],
                         {"domains": 2, "hosts": 2, "events": 0})
        self.sender.assert_not_called()

    async def test_incomplete_followup_preserves_last_success_and_sends_nothing(self):
        service, client = self.real_service([report(1, passed=False)])
        # Establish an earlier complete run without delivering its unselected case.
        with patch.object(main, "service", service):
            await main.dispatch_notification_cycle()
            previous = self.store.evaluation_status()["last_success"]
            client.daily_followup_failure = {"aggregations": {}, "timed_out": False}
            with self.assertRaises(OpenSearchError):
                await main.dispatch_notification_cycle()
        status = self.store.evaluation_status()
        self.assertEqual(status["latest"]["status"], "failure")
        self.assertEqual(status["last_success"], previous)
        self.assertEqual(status["latest"]["counts"], {"domains": None, "hosts": None, "events": None})
        self.sender.assert_not_called()

    async def test_opensearch_failure_before_first_send_does_not_expose_exception(self):
        service, _ = self.real_service([])
        with patch.object(main, "service", service), patch.object(
            service, "alert_evaluation", side_effect=OpenSearchError("https://name:secret@private.example raw body"),
        ):
            with self.assertRaises(OpenSearchError):
                await main.dispatch_notification_cycle()
        public = main.public_evaluation_status()
        self.assertEqual(public["evaluation"]["latest"]["status"], "failure")
        self.assertIsNone(public["evaluation"]["last_success"])
        self.assertNotIn("secret", json.dumps(public))
        self.assertNotIn("private.example", json.dumps(public))
        self.assertNotIn("cases", public["evaluation"]["latest"]["scope"])
        self.sender.assert_not_called()

    async def test_configuration_failure_is_recorded_before_evaluation(self):
        self.resolve.side_effect = NotificationDeliveryError("secret detail")
        with self.assertRaises(NotificationDeliveryError):
            await main.dispatch_notification_cycle()
        latest = self.store.evaluation_status()["latest"]
        self.assertEqual(latest["status"], "failure")
        self.assertIn("Benachrichtigungseinstellungen", latest["error"])
        self.assertNotIn("secret", latest["error"])
        self.sender.assert_not_called()

    async def test_smtp_failure_does_not_change_successful_evaluation(self):
        alert = {**example_alert(), "kind": "host-fail", "status": "open"}
        self.sender.return_value = [RecipientDeliveryResult(recipient, "permanent_failure", "SMTP 550", 550)
                                    for recipient in self.config["recipients"]]
        evaluated = {"items": [alert], "counts": {"events": 1, "domains": 1, "hosts": 1}}
        with patch.object(main.service, "alert_evaluation", new=AsyncMock(return_value=evaluated)):
            await main.dispatch_notification_cycle()
        self.assertEqual(self.store.evaluation_status()["latest"]["status"], "success")
        self.assertEqual(self.store.recipient_delivery_summary()["permanent_failure"], 2)

    async def test_cancelled_evaluation_is_interrupted_and_reraises(self):
        with patch.object(main.service, "alert_evaluation", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await main.dispatch_notification_cycle()
        self.assertEqual(self.store.evaluation_status()["latest"]["status"], "interrupted")
        self.assertIsNone(self.store.evaluation_status()["last_success"])
        self.sender.assert_not_called()

    async def test_pausing_does_not_replace_previous_outcome(self):
        run = self.store.start_evaluation({"domain": "*", "days": 30})
        self.store.finish_evaluation(run, "failure", 12, error="Public error")
        before = self.store.evaluation_status()
        self.config["enabled"] = False
        self.store.save_notification_settings(settings=self.config, secret_ciphertext="unused")
        await main.dispatch_notification_cycle()
        self.assertEqual(self.store.evaluation_status(), before)
        self.assertFalse(main.public_evaluation_status()["enabled"])
        self.sender.assert_not_called()


class EvaluationApiTests(unittest.TestCase):
    def test_read_access_exposes_status_not_configuration_or_recipient_details(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.db")
            event = {**example_alert(), "id": "event"}
            state.save_alert_events([event], bootstrap=True)
            configuration = notification_configuration()
            state.save_notification_settings(settings=configuration, secret_ciphertext="unused")
            run = state.start_evaluation({"domain": "*", "days": 30, "cases": configuration["cases"]})
            state.finish_evaluation(run, "success", 123, {"events": 1, "domains": 1, "hosts": 1})
            claims = state.claim_notification_recipients(alert_id="event", configuration=configuration)
            state.finish_notification_recipient(claim=claims[0], status="temporary_failure", error="private server response", smtp_code=450)
            with patch.object(main, "store", state), TestClient(main.app) as client:
                self.assertEqual(client.get("/api/alerts/evaluation/status").status_code, 401)
                self.assertEqual(client.get("/api/alerts/event/delivery").status_code, 401)
                with patch.object(main, "is_read_authenticated", return_value=True):
                    runtime = client.get("/api/alerts/evaluation/status")
                    self.assertEqual(runtime.status_code, 200)
                    self.assertEqual(runtime.json()["evaluation"]["latest"]["duration_ms"], 123)
                    self.assertNotIn("cases", runtime.json()["evaluation"]["latest"]["scope"])
                    summary = client.get("/api/alerts/event").json()["delivery"]
                    self.assertEqual(summary["temporary_failure"], 1)
                    self.assertNotIn("recipient", json.dumps(summary))
                    self.assertNotIn("private server response", json.dumps(summary))
                    self.assertEqual(client.get("/api/alerts/event/delivery").status_code, 401)
                    with patch.object(main, "is_admin_authenticated", return_value=True):
                        details = client.get("/api/alerts/event/delivery")
                        self.assertEqual(details.status_code, 200)
                        self.assertEqual(len(details.json()["items"]), 2)
                        self.assertEqual(client.get("/api/alerts/missing/delivery").status_code, 404)


if __name__ == "__main__":
    unittest.main()
