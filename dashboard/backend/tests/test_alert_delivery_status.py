from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.store import StateStore


class AlertDeliveryStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = StateStore(Path(self.directory.name) / "state.db")

    def recipient(
        self, alert_id: str, key: str, status: str, *, attempts: int = 1,
        last: str = "2026-09-08T12:00:00+00:00", next_at: str | None = None,
    ) -> None:
        with self.store._connect() as connection:
            connection.execute("""
                INSERT INTO notification_recipient_deliveries
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_id, key, f"{key}@private.example", status, attempts, last,
                next_at, last if status == "accepted" else None,
                None if status == "accepted" else "Private SMTP diagnostic for hidden@example.net",
                250 if status == "accepted" else 450,
            ))

    def legacy(
        self, alert_id: str, key: str, status: str, *, attempts: int = 1,
        last: str = "2026-09-07T11:00:00+00:00",
    ) -> None:
        with self.store._connect() as connection:
            connection.execute("""
                INSERT INTO notification_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_id, key, status, attempts, last, "2026-09-07T11:05:00+00:00",
                last if status == "sent" else None, "Private legacy transport diagnostic",
            ))

    def alias(self, old: str, canonical: str) -> None:
        event = {
            "id": canonical, "kind": "host-fail", "title": "Stored alert",
            "priority": "critical", "source_ip": "192.0.2.1", "domain": "a.example",
            "messages": 1, "report_time": "2026-09-07T00:00:00+00:00",
        }
        self.store.save_alert_events([event], aliases={old: canonical})

    def snapshot(self) -> str:
        with self.store._connect() as connection:
            return "\n".join(connection.iterdump())

    def test_read_summary_has_counts_and_retry_lower_bound_without_private_details(self) -> None:
        self.recipient("event", "accepted", "accepted")
        self.recipient("event", "temp-later", "temporary_failure", attempts=2,
                       next_at="2026-09-08T12:10:00+00:00")
        self.recipient("event", "temp-earlier", "temporary_failure",
                       next_at="2026-09-08T12:05:00+00:00")
        self.recipient("event", "permanent", "permanent_failure")
        self.recipient("event", "exhausted", "exhausted", attempts=3)
        self.recipient("event", "pending", "sending", last="2026-09-08T12:02:00+00:00")
        self.recipient("unrelated", "secret-other", "accepted")
        result = self.store.alert_delivery_summaries(["event"])["event"]
        self.assertEqual(result["mode"], "partial")
        self.assertEqual(
            [result[field] for field in ("accepted", "temporary_failure", "permanent_failure", "exhausted", "pending")],
            [1, 2, 1, 1, 1],
        )
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["attempts_total"], 9)
        self.assertEqual(result["last_attempt_at"], "2026-09-08T12:02:00+00:00")
        self.assertEqual(result["next_attempt_at"], "2026-09-08T12:05:00+00:00")
        self.assertEqual(result["legacy"]["total"], 0)
        serialized = json.dumps(result)
        for private in ("@", "smtp_code", "last_error", "recipient_key", "recipient", "Private", "secret-other"):
            self.assertNotIn(private, serialized)

    def test_modes_distinguish_acceptance_pending_and_terminal_failures(self) -> None:
        self.recipient("accepted", "one", "accepted")
        self.recipient("failed", "one", "permanent_failure")
        self.recipient("failed", "two", "exhausted", attempts=3)
        self.recipient("retrying", "one", "temporary_failure", next_at="2026-09-08T12:05:00+00:00")
        self.recipient("sending", "one", "sending")
        self.recipient("mixed-failure", "one", "permanent_failure")
        self.recipient("mixed-failure", "two", "temporary_failure")
        results = self.store.alert_delivery_summaries([
            "accepted", "failed", "retrying", "sending", "mixed-failure", "unknown",
        ])
        self.assertEqual(
            {key: value["mode"] for key, value in results.items()},
            {"accepted": "accepted", "failed": "failed", "retrying": "pending",
             "sending": "pending", "mixed-failure": "pending", "unknown": "none"},
        )
        self.assertIsNone(results["accepted"]["next_attempt_at"])
        self.assertIsNone(results["failed"]["next_attempt_at"])
        self.assertIsNone(results["sending"]["next_attempt_at"])

    def test_alias_and_canonical_calls_share_historical_recipient_status(self) -> None:
        self.alias("old-link", "canonical")
        self.recipient("canonical", "accepted", "accepted")
        self.store.set_alert_status("canonical", "resolved")
        results = self.store.alert_delivery_summaries(["old-link", "canonical"])
        self.assertEqual(results["old-link"], results["canonical"])
        self.assertEqual(results["old-link"]["alert_id"], "canonical")
        self.assertEqual(results["old-link"]["mode"], "accepted")
        self.assertEqual(self.store.alert_delivery_details("old-link"), self.store.alert_delivery_details("canonical"))
        self.assertEqual(self.store.stored_alert("old-link")["status"], "resolved")

    def test_legacy_alias_copies_count_once_and_preserve_complete_legacy_timing(self) -> None:
        self.legacy("old-link", "group-one", "failed", attempts=2)
        self.alias("old-link", "canonical")
        self.legacy("canonical", "group-two", "sent", last="2026-09-06T10:00:00+00:00")
        with self.store._connect() as connection:
            connection.execute("""
                UPDATE notification_deliveries SET attempts = 3, last_attempt_at = ?
                WHERE alert_id = 'old-link'
            """, ("2026-09-08T13:00:00+00:00",))
        results = self.store.alert_delivery_summaries(["old-link", "canonical"])
        self.assertEqual(results["old-link"], results["canonical"])
        summary = results["canonical"]
        self.assertEqual(summary["mode"], "legacy_hold")
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["attempts_total"], 0)
        self.assertEqual(summary["legacy"], {
            "total": 2, "sent": 1, "failed": 1, "pending": 0,
            "attempts_total": 4, "last_attempt_at": "2026-09-08T13:00:00+00:00",
        })
        self.assertEqual(summary["last_attempt_at"], "2026-09-08T13:00:00+00:00")
        self.assertIsNone(summary["next_attempt_at"])
        self.assertEqual(self.store.alert_delivery_details("canonical")["items"], [])
        self.assertNotIn("group-one", json.dumps(summary))
        self.assertNotIn("diagnostic", json.dumps(summary))

    def test_legacy_hold_overrides_retry_timing_but_keeps_new_counts(self) -> None:
        self.recipient("event", "one", "accepted")
        self.recipient("event", "two", "temporary_failure", next_at="2026-09-08T12:05:00+00:00")
        self.legacy("event", "old-group", "sending")
        summary = self.store.alert_delivery_summaries(["event"])["event"]
        self.assertEqual(summary["mode"], "legacy_hold")
        self.assertEqual((summary["total"], summary["accepted"], summary["temporary_failure"]), (2, 1, 1))
        self.assertEqual(summary["legacy"]["pending"], 1)
        self.assertEqual(summary["last_attempt_at"], "2026-09-08T12:00:00+00:00")
        self.assertEqual(summary["legacy"]["last_attempt_at"], "2026-09-07T11:00:00+00:00")
        self.assertIsNone(summary["next_attempt_at"])

    def test_details_are_bounded_with_full_total_and_no_other_alert_rows(self) -> None:
        for number in range(105):
            self.recipient("event", f"target-{number:03d}", "temporary_failure")
        self.recipient("other-event", "must-not-appear", "permanent_failure",
                       last="2026-09-09T12:00:00+00:00")
        details = self.store.alert_delivery_details("event")
        self.assertEqual(details["limit"], 100)
        self.assertEqual(details["total"], 105)
        self.assertEqual(len(details["items"]), 100)
        self.assertEqual(details["items"][0]["recipient"], "target-104@private.example")
        self.assertTrue(all(item["alert_id"] == "event" for item in details["items"]))
        self.assertTrue(all(item["smtp_code"] == 450 for item in details["items"]))
        self.assertTrue(all("Private SMTP" in item["last_error"] for item in details["items"]))
        self.assertNotIn("must-not-appear", json.dumps(details))
        self.assertNotIn("recipient_key", json.dumps(details))

    def test_unknown_and_legacy_only_historical_ids_remain_distinct(self) -> None:
        self.legacy("historical-old-id", "historical-group", "sent")
        results = self.store.alert_delivery_summaries(["unknown", "historical-old-id"])
        self.assertEqual(results["unknown"]["mode"], "none")
        self.assertEqual(results["unknown"]["total"], 0)
        self.assertIsNone(results["unknown"]["last_attempt_at"])
        self.assertIsNone(results["unknown"]["next_attempt_at"])
        self.assertEqual(results["historical-old-id"]["mode"], "legacy_hold")
        self.assertEqual(results["historical-old-id"]["legacy"]["sent"], 1)
        self.assertEqual(self.store.alert_delivery_details("unknown")["items"], [])
        self.assertEqual(self.store.alert_delivery_summaries([]), {})

    def test_bulk_handles_over_1000_ids_without_per_alert_queries(self) -> None:
        ids = [f"event-{number:04d}" for number in range(1205)]
        for event in (ids[0], ids[400], ids[-1]):
            self.recipient(event, "accepted", "accepted")
        statements = []
        original_connect = self.store._connect

        def traced_connect() -> sqlite3.Connection:
            connection = original_connect()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(self.store, "_connect", side_effect=traced_connect):
            results = self.store.alert_delivery_summaries(ids)
        self.assertEqual(len(results), 1205)
        self.assertEqual(sum(result["accepted"] for result in results.values()), 3)
        selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(selects), 9)
        for statement in selects:
            columns = statement.upper().split("FROM")[0]
            self.assertNotIn("LAST_ERROR", columns)
            self.assertNotIn("SMTP_CODE", columns)
            self.assertNotIn(" RECIPIENT,", columns)

    def test_reads_never_claim_retries_exhaust_attempts_or_mutate_configuration(self) -> None:
        self.recipient("event", "expired", "sending", attempts=3,
                       last="2026-01-01T00:00:00+00:00")
        self.recipient("event", "due", "temporary_failure", attempts=2,
                       next_at="2026-01-01T00:05:00+00:00")
        before = self.snapshot()
        self.store.alert_delivery_summaries(["event", "unknown"])
        details = self.store.alert_delivery_details("event")
        self.assertEqual(before, self.snapshot())
        self.assertEqual({item["status"] for item in details["items"]}, {"sending", "temporary_failure"})
        self.assertEqual(details["attempts_total"], 5)


if __name__ == "__main__":
    unittest.main()
