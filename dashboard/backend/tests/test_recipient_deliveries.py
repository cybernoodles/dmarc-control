from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.notifications import RecipientDeliveryResult, test_alert as example_alert
from app.store import StateStore
from test_notifications import notification_configuration


class RecipientDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.db"
        self.store = StateStore(self.path)
        self.config = notification_configuration()
        self.now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        clock = patch("app.recipient_deliveries.datetime", wraps=datetime)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.side_effect = lambda *_: self.now

    def claim(self, alert_id="event"):
        return self.store.claim_notification_recipients(
            alert_id=alert_id, configuration=self.config,
        )

    def finish(self, claim, status):
        self.store.finish_notification_recipient(
            claim=claim, status=status, error="refused" if status != "accepted" else None,
        )

    def test_partial_acceptance_retries_only_temporary_recipient_after_restart(self):
        claims = self.claim()
        self.finish(claims[0], "accepted")
        self.finish(claims[1], "temporary_failure")
        self.assertEqual(self.claim(), [])
        self.store = StateStore(self.path)
        self.now += timedelta(minutes=6)
        retry = self.claim()
        self.assertEqual([item["recipient"] for item in retry], [self.config["recipients"][1]])
        self.assertEqual(retry[0]["attempt"], 2)
        self.finish(retry[0], "accepted")
        self.assertEqual(self.claim(), [])
        self.assertEqual(self.store.recipient_delivery_summary()["accepted"], 2)

    def test_permanent_failure_is_terminal_and_temporary_budget_is_persistent(self):
        claims = self.claim()
        self.finish(claims[0], "permanent_failure")
        self.finish(claims[1], "temporary_failure")
        for attempt in (2, 3):
            self.now += timedelta(hours=1)
            self.store = StateStore(self.path)
            retry = self.claim()
            self.assertEqual(len(retry), 1)
            self.assertEqual(retry[0]["attempt"], attempt)
            self.finish(retry[0], "temporary_failure")
        self.now += timedelta(days=1)
        self.assertEqual(self.claim(), [])
        summary = self.store.recipient_delivery_summary()
        self.assertEqual((summary["permanent_failure"], summary["exhausted"]), (1, 1))
        self.assertTrue(all(item["next_attempt_at"] is None for item in summary["items"]))

    def test_recipient_changes_preserve_acceptance_and_retry_budget(self):
        claims = self.claim()
        self.finish(claims[0], "accepted")
        self.finish(claims[1], "temporary_failure")
        a, b = self.config["recipients"]
        self.config["recipients"] = [a.upper(), "new@example.com"]
        self.now += timedelta(hours=1)
        added = self.claim()
        self.assertEqual([item["recipient"] for item in added], ["new@example.com"])
        self.finish(added[0], "accepted")
        self.config["recipients"] = [b, a, "new@example.com"]
        resumed = self.claim()
        self.assertEqual([(item["recipient"], item["attempt"]) for item in resumed], [(b, 2)])

    def test_parallel_claims_and_late_results_cannot_overwrite_new_attempt(self):
        first = self.claim()
        other = StateStore(self.path)
        self.assertEqual(other.claim_notification_recipients(
            alert_id="event", configuration=self.config), [])
        self.now += timedelta(minutes=16)
        second = self.claim()
        self.finish(second[0], "accepted")
        self.finish(first[0], "temporary_failure")
        self.assertEqual(self.store.recipient_delivery_summary()["accepted"], 1)

    def test_expired_final_claim_exhausts_without_fourth_attempt(self):
        for attempt in (1, 2, 3):
            claims = self.claim()
            self.assertTrue(all(item["attempt"] == attempt for item in claims))
            self.now += timedelta(minutes=16)
        self.assertEqual(self.claim(), [])
        self.assertEqual(self.store.recipient_delivery_summary()["exhausted"], 2)

    def test_legacy_outcomes_remain_held_across_config_changes_and_aliases(self):
        for index, success in enumerate((True, False, None)):
            legacy = f"old-{index}"
            self.store.claim_notification_delivery(alert_id=legacy, destination_hash="unknown-group")
            if success is not None:
                self.store.finish_notification_delivery(
                    alert_id=legacy, destination_hash="unknown-group", success=success,
                )
            event = {**example_alert(), "id": f"canonical-{index}"}
            self.store.save_alert_events([event], aliases={legacy: event["id"]})
            self.assertEqual(self.claim(legacy), [])
            self.config["recipients"] = ["changed@example.com"]
            self.config["transport"] = "msgraph"
            self.assertEqual(self.claim(event["id"]), [])
        self.assertEqual(self.store.recipient_delivery_summary()["total"], 0)
        summary = self.store.notification_delivery_summary()
        self.assertEqual((summary["sent"], summary["failed"], summary["pending"]), (1, 1, 1))

    def test_dispatch_builds_retry_message_for_only_due_recipient(self):
        alert = {**example_alert(), "kind": "new-host-fail", "status": "open"}
        calls = []

        def send(message, configuration, secret):
            recipients = configuration["recipients"]
            calls.append(recipients)
            self.assertEqual(str(message["To"]), ", ".join(recipients))
            if len(calls) == 1:
                return [RecipientDeliveryResult(recipients[0], "accepted"),
                        RecipientDeliveryResult(recipients[1], "temporary_failure", "450 retry", 450)]
            return [RecipientDeliveryResult(recipient, "accepted") for recipient in recipients]

        with (
            patch.object(main, "store", self.store),
            patch.object(self.store, "notification_settings", return_value={"settings": self.config}),
            patch.object(main, "_resolved_notification_configuration", return_value=(self.config, {})),
            patch.object(main.service, "alerts", new=AsyncMock(return_value=[alert])),
            patch.object(main, "send_message", side_effect=send),
        ):
            asyncio.run(main.dispatch_notification_cycle())
            asyncio.run(main.dispatch_notification_cycle())
            self.now += timedelta(minutes=6)
            asyncio.run(main.dispatch_notification_cycle())
            asyncio.run(main.dispatch_notification_cycle())
        self.assertEqual(calls, [self.config["recipients"], [self.config["recipients"][1]]])
        self.assertEqual(self.store.recipient_delivery_summary()["accepted"], 2)

    def test_explicit_test_reports_partial_failure_without_enabling_alerting(self):
        self.config["enabled"] = False
        self.store.save_notification_settings(settings=self.config, secret_ciphertext="unused")
        results = [RecipientDeliveryResult(self.config["recipients"][0], "accepted"),
                   RecipientDeliveryResult(self.config["recipients"][1], "temporary_failure", "450 retry", 450)]
        with (
            patch.object(main, "store", self.store),
            patch.object(main, "require_admin"),
            patch.object(main, "_resolved_notification_configuration", return_value=(self.config, {})),
            patch.object(main, "send_message", return_value=results),
            patch.object(main, "public_notification_state", side_effect=lambda value: value),
        ):
            result = asyncio.run(main.test_notification_settings(None))
        self.assertEqual(result["test_status"], "failure")
        self.assertFalse(result["settings"]["enabled"])
        self.assertIn("450", result["test_message"])
        self.assertEqual(self.store.recipient_delivery_summary()["total"], 0)


if __name__ == "__main__":
    unittest.main()
