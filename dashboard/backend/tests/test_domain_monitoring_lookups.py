from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import domain_monitoring
from app.domain_monitoring import domain_freshness_event, legacy_domain_monitoring
from app.store import StateStore


class TracedStore(StateStore):
    def __init__(self, path):
        self.statements = []
        super().__init__(path)

    def _connect(self):
        connection = super()._connect()
        connection.set_trace_callback(self.statements.append)
        return connection


class DomainFreshnessLookupTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "state.db"
        self.store = TracedStore(self.path)
        self.now = datetime(2026, 9, 9, 12, tzinfo=UTC)
        self.ended = self.now - timedelta(days=10)

    def remember(self, domain, ended=None):
        self.store.remember_domain_reports([
            {"domain": domain, "last_report": (ended or self.ended).isoformat()},
        ])

    def event(self, domain="example.com", now=None):
        row = self.store.list_domain_monitoring(3, domain)[0]
        return domain_freshness_event(row, now or self.now)

    def test_one_check_is_bounded_even_with_one_thousand_unrelated_domains(self):
        self.store.remember_domain_reports([
            {"domain": f"domain-{index:04d}.example", "last_report": self.ended.isoformat()}
            for index in range(1000)
        ])
        event = self.event("domain-0500.example")
        self.store.statements.clear()
        with patch.object(domain_monitoring, "canonical_domain", wraps=domain_monitoring.canonical_domain) as canonical:
            self.assertTrue(self.store.domain_freshness_allows(event, 3, now=self.now))
        self.assertEqual(canonical.call_count, 1)
        queries = [" ".join(sql.lower().split()) for sql in self.store.statements]
        self.assertEqual(len(queries), 1)
        self.assertIn("from domain_monitoring where domain =", queries[0])
        self.assertNotIn("domain_report_history", queries[0])

    def test_other_store_retirement_and_reactivation_are_visible_on_the_next_check(self):
        self.remember("example.com")
        cached = self.event()
        self.assertTrue(self.store.domain_freshness_allows(cached, 3, now=self.now))
        other = StateStore(self.path)
        other.update_domain_monitoring("example.com", state="retired", now=self.now)
        self.assertFalse(self.store.domain_freshness_allows(cached, 3, now=self.now))
        other.update_domain_monitoring("example.com", state="active", now=self.now)
        later = self.now + timedelta(days=4)
        self.assertFalse(self.store.domain_freshness_allows(cached, 3, now=later))
        resumed = self.event(now=later)
        self.assertNotEqual(resumed["id"], cached["id"])
        self.assertTrue(self.store.domain_freshness_allows(resumed, 3, now=later))

    def test_changed_deadline_is_rechecked_even_when_old_and_new_deadlines_are_due(self):
        self.remember("example.com")
        cached = self.event()
        StateStore(self.path).update_domain_monitoring("example.com", grace_days=5)
        self.assertFalse(self.store.domain_freshness_allows(cached, 3, now=self.now))
        updated = self.event()
        self.assertEqual(updated["id"], cached["id"])
        self.assertNotEqual(updated["deadline"], cached["deadline"])
        self.assertTrue(self.store.domain_freshness_allows(updated, 3, now=self.now))
        self.remember("example.com", self.ended + timedelta(days=1))
        self.assertFalse(self.store.domain_freshness_allows(updated, 3, now=self.now))

    def test_unicode_and_original_spelling_work_without_building_alias_lists(self):
        self.remember("Straße.example.")
        self.remember("STRASSE.example")
        before = self.store.list_domain_monitoring()
        event = self.event("xn--strae-oqa.example")
        self.assertEqual(event["domain"], "Straße.example.")
        for alias in ("Straße.example.", "xn--strae-oqa.example"):
            with self.subTest(alias=alias):
                self.assertTrue(self.store.domain_freshness_allows({**event, "monitoring_domain": alias}, 3, now=self.now))
        self.assertFalse(self.store.domain_freshness_allows({**event, "monitoring_domain": "strasse.example"}, 3, now=self.now))
        self.assertEqual(self.store.list_domain_monitoring(), before)

    def test_historical_invalid_name_uses_only_exact_read_without_a_write_transaction(self):
        domain = "old'name OR 1=1"
        self.remember(domain)
        self.remember("other invalid name")
        report = {"domain": domain, "last_report": self.ended.isoformat()}
        event = domain_freshness_event(legacy_domain_monitoring(report, 3), self.now)
        self.store.statements.clear()
        self.assertTrue(self.store.domain_freshness_allows(event, 3, now=self.now))
        queries = [" ".join(sql.lower().split()) for sql in self.store.statements]
        self.assertEqual(len(queries), 1)
        self.assertIn("from domain_report_history where domain =", queries[0])
        self.assertFalse(self.store.domain_freshness_allows({**event, "monitoring_domain": "missing invalid name"}, 3, now=self.now))
        self.remember(domain, self.ended + timedelta(days=1))
        self.assertFalse(self.store.domain_freshness_allows(event, 3, now=self.now))

    def test_missing_or_nonspecific_domain_cannot_fall_back_to_another_registry_row(self):
        self.remember("example.com")
        event = self.event()
        for domain in ("missing.example", "*", "", None):
            with self.subTest(domain=domain):
                self.assertFalse(self.store.domain_freshness_allows({
                    **event, "monitoring_domain": domain, "domain": domain,
                }, 3, now=self.now))


if __name__ == "__main__":
    unittest.main()
