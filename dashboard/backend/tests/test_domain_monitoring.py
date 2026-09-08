from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.domain_monitoring import canonical_domain, domain_freshness_event
from app.service import DashboardService
from app.store import StateStore
from test_alert_events import FixedClock, NOW, ReportClient, report


class DomainMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / "state.db"
        self.store = StateStore(self.path)
        self.start = datetime(2026, 9, 1, 12, tzinfo=UTC)

    def observe(self, domain="Example.COM.", days=0):
        self.store.remember_domain_reports([
            {"domain": domain, "last_report": (self.start + timedelta(days=days)).isoformat()},
        ])

    def row(self, domain="example.com", default=3):
        return self.store.list_domain_monitoring(default, domain)[0]

    def test_canonical_aliases_do_not_duplicate_manual_or_observed_domains(self):
        self.assertEqual(canonical_domain("  BÜCHER.example.  "), "xn--bcher-kva.example")
        added = self.store.add_domain_monitoring("BÜCHER.example.", 4, now=self.start)
        for alias in ("bücher.example", "XN--BCHER-KVA.EXAMPLE."):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                self.store.add_domain_monitoring(alias, 4, now=self.start)
        self.observe("Bücher.example.")
        row = self.row("xn--bcher-kva.example")
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["query_domain"], "Bücher.example.")
        self.assertEqual(row["aliases"], ["Bücher.example."])
        self.assertEqual(row["monitoring_episode_id"], added["monitoring_episode_id"])
        self.assertEqual(len(self.store.list_domain_monitoring()), 1)

    def test_invalid_inputs_and_unknown_updates_leave_registry_unchanged(self):
        for name in ("*", "", "https://example.com", "name@example.com", "a..example", "a.example..", "-bad.example", "x" * 64 + ".example", "two names.example"):
            with self.subTest(domain=name), self.assertRaises(ValueError):
                self.store.add_domain_monitoring(name, 3, now=self.start)
        for grace in (0, 366, True, 1.5, "3", []):
            with self.subTest(grace=grace), self.assertRaises(ValueError):
                self.store.add_domain_monitoring("example.com", grace, now=self.start)
        self.assertEqual(self.store.list_domain_monitoring(), [])
        with self.assertRaises(KeyError):
            self.store.update_domain_monitoring("missing.example", state="retired")
        with self.assertRaises(ValueError):
            self.store.add_domain_monitoring("example.com", 3, now=self.start.replace(tzinfo=None))

    def test_modern_idna_keeps_sharp_s_and_double_s_domains_distinct(self):
        self.assertEqual(canonical_domain("Straße.example."), "xn--strae-oqa.example")
        self.assertEqual(canonical_domain("STRASSE.example"), "strasse.example")
        first = self.store.add_domain_monitoring("Straße.example", 3, now=self.start)
        second = self.store.add_domain_monitoring("strasse.example", 3, now=self.start)
        self.assertNotEqual(first["domain"], second["domain"])
        with self.assertRaises(ValueError):
            self.store.add_domain_monitoring("xn--strae-oqa.example", 3, now=self.start)
        self.observe("straße.example")
        self.assertEqual(self.row("xn--strae-oqa.example")["state"], "active")
        self.assertEqual(self.row("strasse.example")["state"], "expected")

    def test_backfill_uses_existing_report_end_and_never_restarts_migrated_grace(self):
        end = "2026-08-01T00:00:00+00:00"
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TABLE domain_monitoring")
            connection.execute("INSERT INTO domain_report_history VALUES (?, ?)", ("Original.EXAMPLE.", end))
            old_history = connection.execute("SELECT * FROM domain_report_history").fetchall()
        migrated = StateStore(self.path)
        row = migrated.list_domain_monitoring(5)[0]
        self.assertEqual(row["state"], "active")
        self.assertIsNone(row["monitoring_started_at"])
        self.assertIsNone(row["monitoring_episode_id"])
        self.assertIsNone(row["configured_grace_days"])
        self.assertEqual(row["query_domain"], "Original.EXAMPLE.")
        self.assertEqual(row["deadline"], "2026-08-06T00:00:00+00:00")
        self.assertEqual(StateStore(self.path).list_domain_monitoring(5), [row])
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT * FROM domain_report_history").fetchall(), old_history)
        event = domain_freshness_event(row, self.start)
        self.assertEqual(event["id"], DashboardService._alert_id("v2", "stale-reports", "Original.EXAMPLE.", "all", "2026-08-01"))

    def test_report_aliases_use_latest_end_without_altering_history_or_reverting_on_old_scan(self):
        self.observe("Example.COM.")
        self.observe("example.com", 2)
        self.observe("EXAMPLE.COM", 1)
        row = self.row()
        self.assertEqual(row["query_domain"], "example.com")
        self.assertEqual(row["last_report"], (self.start + timedelta(days=2)).isoformat())
        self.assertEqual(row["aliases"], ["EXAMPLE.COM", "Example.COM.", "example.com"])
        self.assertEqual(len(self.store.remember_domain_reports([])), 3)
        self.assertEqual(len(self.store.list_domain_monitoring()), 1)
        self.assertEqual(self.store.list_domain_monitoring(3, "Example.COM."), [row])

    def test_expected_deadline_is_strict_and_empty_scans_never_move_it(self):
        row = self.store.add_domain_monitoring("first.example", 3, now=self.start)
        deadline = self.start + timedelta(days=3)
        self.assertIsNone(domain_freshness_event(row, deadline))
        event = domain_freshness_event(row, deadline + timedelta(microseconds=1))
        self.assertEqual(event["freshness_reason"], "never_observed")
        self.assertEqual(event["title"], "Erster DMARC-Report fehlt")
        self.assertIsNone(event["report_time"])
        self.store.remember_domain_reports([])
        later = StateStore(self.path).list_domain_monitoring()[0]
        self.assertEqual(row, later)
        self.assertEqual(domain_freshness_event(later, deadline + timedelta(days=30))["id"], event["id"])

    def test_expected_activates_on_first_report_and_uses_later_report_or_start_anchor(self):
        row = self.store.add_domain_monitoring("first.example", None, now=self.start, default_grace_days=4)
        self.observe("FIRST.example", -5)
        active = self.row("first.example", default=4)
        self.assertEqual(active["state"], "active")
        self.assertTrue(active["observed"])
        self.assertEqual(active["deadline"], row["deadline"])
        self.assertEqual(active["monitoring_started_at"], row["monitoring_started_at"])
        self.observe("FIRST.example", 1)
        self.assertEqual(self.row("first.example", default=4)["deadline"], (self.start + timedelta(days=5)).isoformat())

    def test_retirement_does_not_auto_reactivate_even_when_reports_arrive(self):
        self.observe()
        retired = self.store.update_domain_monitoring("example.com", state="retired", now=self.start)
        self.assertIsNone(retired["deadline"])
        self.observe("example.com", 10)
        reread = self.row()
        self.assertEqual(reread["state"], "retired")
        self.assertTrue(reread["observed"])
        self.assertIsNone(domain_freshness_event(reread, self.start + timedelta(days=100)))

    def test_invalid_report_batch_cannot_partially_activate_expected_domain(self):
        expected = self.store.add_domain_monitoring("first.example", 3, now=self.start)
        with self.assertRaises(ValueError):
            self.store.remember_domain_reports([
                {"domain": "first.example", "last_report": self.start.isoformat()},
                {"domain": "second.example", "last_report": "invalid"},
            ])
        self.assertEqual(self.store.list_domain_monitoring(), [expected])
        self.assertEqual(self.store.remember_domain_reports([]), [])

    def test_state_transitions_reject_expected_for_observed_and_active_for_unobserved(self):
        self.observe()
        with self.assertRaises(ValueError):
            self.store.update_domain_monitoring("example.com", state="expected", now=self.start)
        self.store.add_domain_monitoring("waiting.example", 3, now=self.start)
        with self.assertRaises(ValueError):
            self.store.update_domain_monitoring("waiting.example", state="active", now=self.start)
        self.store.update_domain_monitoring("waiting.example", state="retired", now=self.start)
        with self.assertRaises(ValueError):
            self.store.update_domain_monitoring("waiting.example", state="active", now=self.start)

    def test_reactivation_starts_new_grace_episode_and_same_values_never_restart_it(self):
        self.observe()
        old = domain_freshness_event(self.row(), self.start + timedelta(days=10))
        self.store.update_domain_monitoring("example.com", state="retired", now=self.start + timedelta(days=10))
        resumed_at = self.start + timedelta(days=20)
        resumed = self.store.update_domain_monitoring("example.com", state="active", now=resumed_at)
        self.assertEqual(resumed["monitoring_started_at"], resumed_at.isoformat())
        self.assertEqual(resumed["deadline"], (resumed_at + timedelta(days=3)).isoformat())
        self.assertEqual(resumed["freshness_reason"], "reactivated")
        self.assertIsNone(domain_freshness_event(resumed, resumed_at + timedelta(days=3)))
        new = domain_freshness_event(resumed, resumed_at + timedelta(days=4))
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual(new["title"], "Kein neuer DMARC-Report nach Reaktivierung")
        same = self.store.update_domain_monitoring("example.com", state="active", grace_days=None, now=resumed_at + timedelta(days=2))
        self.assertEqual(same, resumed)
        changed = self.store.update_domain_monitoring("example.com", grace_days=5, now=resumed_at + timedelta(days=2))
        self.assertEqual(changed["monitoring_started_at"], resumed["monitoring_started_at"])
        self.assertEqual(changed["monitoring_episode_id"], resumed["monitoring_episode_id"])
        self.assertEqual(changed["deadline"], (resumed_at + timedelta(days=5)).isoformat())
        reset = self.store.update_domain_monitoring("example.com", grace_days=None, default_grace_days=4)
        self.assertIsNone(reset["configured_grace_days"])
        self.assertEqual(reset["deadline"], (resumed_at + timedelta(days=4)).isoformat())

    def test_retired_unobserved_domain_can_resume_expected_with_a_distinct_episode(self):
        original = self.store.add_domain_monitoring("waiting.example", 3, now=self.start)
        self.store.update_domain_monitoring("waiting.example", state="retired", now=self.start)
        resumed = self.store.update_domain_monitoring("waiting.example", state="expected", now=self.start)
        self.assertNotEqual(original["monitoring_episode_id"], resumed["monitoring_episode_id"])
        self.assertEqual(resumed["freshness_reason"], "never_observed")

    def test_current_freshness_gate_rejects_retired_resumed_and_postponed_cached_events(self):
        self.observe()
        later = self.start + timedelta(days=4)
        stale = domain_freshness_event(self.row(), later)
        self.assertTrue(self.store.domain_freshness_allows(stale, 3, now=later))
        self.store.update_domain_monitoring("example.com", grace_days=5, now=later)
        self.assertFalse(self.store.domain_freshness_allows(stale, 3, now=later))
        self.assertFalse(self.store.domain_freshness_allows(stale, 3, now=later + timedelta(days=9)))
        refreshed = domain_freshness_event(self.row(), later + timedelta(days=9))
        self.assertTrue(self.store.domain_freshness_allows(refreshed, 3, now=later + timedelta(days=9)))
        self.store.update_domain_monitoring("example.com", state="retired", now=later)
        self.assertFalse(self.store.domain_freshness_allows(stale, 3, now=later + timedelta(days=9)))
        self.store.update_domain_monitoring("example.com", state="active", now=later)
        self.assertFalse(self.store.domain_freshness_allows(stale, 3, now=later + timedelta(days=9)))
        self.assertTrue(self.store.domain_freshness_allows({"kind": "host-fail"}, 3, now=later))

    def test_registry_edits_preserve_report_alert_workflow_and_delivery_history(self):
        self.observe()
        event = domain_freshness_event(self.row(), self.start + timedelta(days=10))
        self.store.save_alert_events([event], bootstrap=True)
        self.store.set_alert_status(event["id"], "resolved")
        self.store.claim_notification_delivery(alert_id=event["id"], destination_hash="legacy")
        configuration = {"transport": "smtp", "sender": "a@example.invalid", "recipients": ["b@example.invalid"]}
        for claim in self.store.claim_notification_recipients(alert_id="other-event", configuration=configuration):
            self.store.finish_notification_recipient(claim=claim, status="accepted")
        tables = ("domain_report_history", "alert_events", "alert_state", "alert_aliases", "notification_deliveries", "notification_recipient_deliveries")
        def history():
            with sqlite3.connect(self.path) as connection:
                return {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        before = history()
        self.store.update_domain_monitoring("example.com", state="retired", now=self.start)
        self.store.update_domain_monitoring("example.com", state="active", now=self.start + timedelta(days=10))
        self.store.add_domain_monitoring("new.example", 5, now=self.start)
        self.assertEqual(history(), before)
        self.assertEqual(self.store.stored_alert(event["id"])["status"], "resolved")


class DomainMonitoringEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = Settings(database_path=Path(directory) / "state.db")
        self.store = StateStore(self.settings.database_path)
        self.clock = self.enterContext(patch("app.alert_events.datetime", FixedClock))
        self.source = ReportClient([])
        self.service = DashboardService(self.source, self.store, self.settings)
        self.service._legacy_alerts = AsyncMock(return_value=[])

    async def test_overdue_expected_domain_on_first_bootstrap_remains_notification_eligible(self):
        self.store.add_domain_monitoring("first.example", 3, now=NOW - timedelta(days=5))
        first = await self.service.alerts("*", 30)
        second = await self.service.alerts("*", 30)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0]["notification_eligible"])
        self.assertTrue(second[0]["notification_eligible"])
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(first[0]["freshness_reason"], "never_observed")

    async def test_bootstrap_keeps_imported_events_quiet_beside_explicit_expectation(self):
        self.source.reports = [report(10)]
        self.store.add_domain_monitoring("first.example", 3, now=NOW - timedelta(days=5))
        items = await self.service.alerts("*", 30)
        self.assertTrue(next(item for item in items if item["domain"] == "first.example")["notification_eligible"])
        self.assertTrue(all(not item["notification_eligible"] for item in items if item["domain"] == "a.example"))

    async def test_retirement_removes_only_freshness_and_keeps_real_failures_and_old_links(self):
        self.source.reports = [report(10, passed=False)]
        items = await self.service.alerts("*", 30)
        stale = next(item for item in items if item["kind"] == "stale-reports")
        failure = next(item for item in items if item["priority"] == "critical")
        self.store.set_alert_status(stale["id"], "resolved")
        self.store.set_alert_status(failure["id"], "acknowledged")
        self.store.update_domain_monitoring("a.example", state="retired", now=NOW)
        remaining = await self.service.alerts("*", 30)
        self.assertEqual([item["id"] for item in remaining], [failure["id"]])
        self.assertEqual(remaining[0]["status"], "acknowledged")
        self.assertEqual(self.store.stored_alert(stale["id"])["status"], "resolved")
        self.source.reports.append(report(1, passed=False))
        self.assertEqual(len([item for item in await self.service.alerts("*", 30) if item["priority"] == "critical"]), 2)
        self.assertEqual(self.store.list_domain_monitoring()[0]["state"], "retired")

    async def test_expected_scope_does_not_leak_other_domains_and_counts_inventory(self):
        self.store.save_alert_events([], bootstrap=True)
        self.store.add_domain_monitoring("first.example", 3, now=NOW - timedelta(days=5))
        self.store.add_domain_monitoring("other.example", 3, now=NOW - timedelta(days=5))
        evaluated = await self.service.alert_evaluation("FIRST.example.", 30)
        self.assertEqual([item["domain"] for item in evaluated["items"]], ["first.example"])
        self.assertEqual(evaluated["counts"], {"domains": 1, "hosts": 0, "events": 1})

    async def test_retention_preserves_old_stale_id_and_reactivation_creates_a_new_one(self):
        self.source.reports = [report(40)]
        old = (await self.service.alerts("*", 30))[0]
        self.store.set_alert_status(old["id"], "resolved")
        self.source.reports = []
        retained = (await self.service.alerts("*", 30))[0]
        self.assertEqual(retained["id"], old["id"])
        self.assertEqual(retained["status"], "resolved")
        self.store.update_domain_monitoring("a.example", state="retired", now=NOW - timedelta(days=6))
        self.store.update_domain_monitoring("a.example", state="active", now=NOW - timedelta(days=5))
        resumed = (await self.service.alerts("*", 30))[0]
        self.assertNotEqual(resumed["id"], old["id"])
        self.assertEqual(resumed["freshness_reason"], "reactivated")
        self.assertEqual(resumed["status"], "open")
        self.assertTrue(resumed["notification_eligible"])
        self.assertEqual(self.store.stored_alert(old["id"])["status"], "resolved")

    async def test_invalid_historical_domain_keeps_legacy_freshness_without_blocking_scan(self):
        self.source.reports = [report(40, domain="invalid historical value")]
        stale = (await self.service.alerts("*", 30))[0]
        self.assertEqual(stale["id"], DashboardService._alert_id(
            "v2", "stale-reports", "invalid historical value", "all", report(40)["date_end"].date().isoformat(),
        ))
        self.assertTrue(self.store.domain_freshness_allows(stale, 3, now=NOW))
        self.assertEqual(self.store.list_domain_monitoring(), [])


if __name__ == "__main__":
    unittest.main()
