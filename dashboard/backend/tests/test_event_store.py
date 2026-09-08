from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.store import StateStore


def event(event_id: str = "event-1", **updates) -> dict:
    return {
        "id": event_id,
        "kind": "host-fail",
        "title": "DMARC-Fehlerquelle erkannt",
        "domain": "example.invalid",
        "source_ip": "192.0.2.1",
        "report_time": "2026-09-08T00:00:00+00:00",
        "messages": 1,
        **updates,
    }


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.db"
        self.store = StateStore(self.path)

    def delivery(self, alert_id, status, *, attempts=1, target="target-1") -> None:
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO notification_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, target, status, attempts, old,
                 old if status == "failed" else None,
                 old if status == "sent" else None,
                 "temporary failure" if status == "failed" else None),
            )

    def test_bootstrap_is_quiet_but_later_events_are_eligible(self) -> None:
        initial = self.store.save_alert_events([event("baseline")], bootstrap=True)
        later = self.store.save_alert_events([event("baseline"), event("new")])
        self.assertFalse(initial[0]["notification_eligible"])
        self.assertFalse(later[0]["notification_eligible"])
        self.assertTrue(later[1]["notification_eligible"])
        self.assertTrue(StateStore(self.path).alert_model_initialized())

    def test_second_bootstrap_cannot_suppress_new_events(self) -> None:
        self.store.save_alert_events([], bootstrap=True)
        second = StateStore(self.path).save_alert_events([event()], bootstrap=True)
        self.assertTrue(second[0]["notification_eligible"])

    def test_updates_preserve_workflow_type_and_delivery_eligibility(self) -> None:
        self.store.save_alert_events([event()], bootstrap=True)
        state = self.store.set_alert_status("event-1", "resolved")
        updated = self.store.save_alert_events(
            [event(kind="new-host-fail", title="Changed", messages=2,
                   status="open", notification_eligible=True)]
        )[0]
        self.assertEqual(updated["messages"], 2)
        self.assertEqual(updated["kind"], "host-fail")
        self.assertEqual(updated["title"], event()["title"])
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["status_updated_at"], state["updated_at"])
        self.assertFalse(updated["notification_eligible"])

    def test_alias_retains_legacy_status_and_accepts_later_user_updates(self) -> None:
        self.store.set_alert_status("legacy", "ignored")
        self.store.save_alert_events([event()], bootstrap=True, aliases={"legacy": "event-1"})
        self.assertEqual(self.store.stored_alert("legacy")["status"], "ignored")
        self.store.set_alert_status("legacy", "resolved")
        self.store.save_alert_events([event()], aliases={"legacy": "event-1"})
        self.assertEqual(self.store.stored_alert("event-1")["status"], "resolved")
        self.assertEqual(self.store.stored_alert("legacy")["id"], "event-1")

    def test_sent_alias_prevents_resend_without_doubling_summary(self) -> None:
        self.delivery("legacy", "sent")
        self.store.save_alert_events([event()], bootstrap=True, aliases={"legacy": "event-1"})
        self.assertFalse(self.store.claim_notification_delivery(alert_id="event-1", destination_hash="target-1"))
        self.assertEqual(self.store.notification_delivery_summary()["sent"], 1)

    def test_failed_alias_resumes_existing_retry_budget(self) -> None:
        self.delivery("legacy", "failed", attempts=2)
        saved = self.store.save_alert_events([event()], bootstrap=True, aliases={"legacy": "event-1"})
        self.assertTrue(saved[0]["notification_eligible"])
        self.assertTrue(self.store.claim_notification_delivery(alert_id="event-1", destination_hash="target-1"))
        self.store.finish_notification_delivery(alert_id="event-1", destination_hash="target-1", success=False)
        with self.store._connect() as connection:
            connection.execute("UPDATE notification_deliveries SET next_attempt_at = NULL WHERE alert_id = 'event-1'")
        self.assertFalse(self.store.claim_notification_delivery(alert_id="event-1", destination_hash="target-1"))
        self.assertEqual(self.store.notification_delivery_summary()["failed"], 1)

    def test_any_positive_sent_record_wins_over_failed_aliases(self) -> None:
        for sent_first in (True, False):
            with self.subTest(sent_first=sent_first):
                suffix = str(sent_first)
                canonical = "event-" + suffix
                sent_id, failed_id = "sent-" + suffix, "failed-" + suffix
                self.delivery(sent_id, "sent")
                self.delivery(failed_id, "failed", attempts=2)
                keys = (sent_id, failed_id) if sent_first else (failed_id, sent_id)
                self.store.save_alert_events([event(canonical)], aliases={key: canonical for key in keys})
                self.assertFalse(self.store.claim_notification_delivery(alert_id=canonical, destination_hash="target-1"))

    def test_sent_legacy_evidence_supersedes_existing_canonical_failure(self) -> None:
        self.store.save_alert_events([event()])
        self.delivery("event-1", "failed", attempts=2)
        self.delivery("legacy", "sent")
        self.store.save_alert_events([event()], aliases={"legacy": "event-1"})
        self.assertFalse(self.store.claim_notification_delivery(alert_id="event-1", destination_hash="target-1"))

    def test_alias_merge_does_not_reset_an_exhausted_retry_budget(self) -> None:
        self.delivery("legacy-exhausted", "failed", attempts=3)
        self.delivery("legacy-newer", "failed", attempts=1)
        self.store.save_alert_events(
            [event()],
            aliases={"legacy-exhausted": "event-1", "legacy-newer": "event-1"},
        )
        self.assertFalse(self.store.claim_notification_delivery(alert_id="event-1", destination_hash="target-1"))

    def test_unmapped_legacy_links_retain_only_known_information(self) -> None:
        self.store.set_alert_status("legacy-state", "acknowledged")
        self.delivery("legacy-delivery", "sent")
        state = self.store.stored_alert("legacy-state")
        self.assertEqual(state["status"], "acknowledged")
        for legacy_id in ("legacy-state", "legacy-delivery"):
            saved = self.store.stored_alert(legacy_id)
            self.assertEqual(saved["id"], legacy_id)
            self.assertEqual(saved["kind"], "legacy")
            self.assertIsNone(saved["source_ip"])
            self.assertIsNone(saved["report_time"])
            self.assertFalse(saved["notification_eligible"])
            self.assertTrue(saved["historical"])
        self.assertIsNone(self.store.stored_alert("unknown"))

    def test_payload_failure_rolls_back_entire_baseline(self) -> None:
        with self.assertRaises(TypeError):
            self.store.save_alert_events([event("first"), event("broken", unsupported=object())], bootstrap=True)
        self.assertIsNone(self.store.stored_alert("first"))
        self.assertFalse(self.store.alert_model_initialized())

    def test_invalid_alias_rolls_back_events_and_marker(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save_alert_events([event()], bootstrap=True, aliases={"legacy": "missing"})
        self.assertIsNone(self.store.stored_alert("event-1"))
        self.assertFalse(self.store.alert_model_initialized())

    def test_alias_failure_rolls_back_prior_alias_state_and_delivery_migration(self) -> None:
        self.store.set_alert_status("legacy", "resolved")
        self.delivery("legacy", "sent")
        with self.assertRaises(ValueError):
            self.store.save_alert_events(
                [event()], bootstrap=True,
                aliases={"legacy": "event-1", "broken": "missing"},
            )
        self.assertIsNone(self.store.stored_alert("event-1"))
        self.assertEqual(self.store.stored_alert("legacy")["kind"], "legacy")
        self.assertEqual(self.store.stored_alert("legacy")["status"], "resolved")
        self.assertEqual(self.store.notification_delivery_summary()["sent"], 1)
        self.assertFalse(self.store.alert_model_initialized())

    def test_known_domain_survives_missing_results_and_process_restart(self) -> None:
        report = {"domain": "stale.example", "last_report": "2026-07-01T00:00:00+00:00"}
        self.store.remember_domain_reports([report])
        self.assertEqual(StateStore(self.path).remember_domain_reports([]), [report])

    def test_domain_history_keeps_newest_end_and_filters_returned_scope(self) -> None:
        self.store.remember_domain_reports([
            {"domain": "a.example", "last_report": "2026-09-07T22:00:00-05:00"},
            {"domain": "b.example", "last_report": "2026-09-08T00:00:00+00:00"},
        ])
        result = self.store.remember_domain_reports([
            {"domain": "a.example", "last_report": "2026-09-08T01:00:00+00:00"},
        ], "a.example")
        self.assertEqual(result, [{"domain": "a.example", "last_report": "2026-09-08T03:00:00+00:00"}])
        self.assertEqual(self.store.remember_domain_reports([], "unknown.example"), [])

    def test_empty_installation_does_not_invent_domain_history(self) -> None:
        self.assertEqual(self.store.remember_domain_reports([]), [])

    def test_invalid_domain_report_does_not_partially_update_history(self) -> None:
        with self.assertRaises(ValueError):
            self.store.remember_domain_reports([
                {"domain": "a.example", "last_report": "2026-09-08T00:00:00+00:00"},
                {"domain": "b.example", "last_report": "invalid timestamp"},
            ])
        self.assertEqual(self.store.remember_domain_reports([]), [])


if __name__ == "__main__":
    unittest.main()
