from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore
from test_freshness import PageClient, ReportClient


class DomainInventoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "state.db")
        self.store = StateStore(self.settings.database_path)

    async def test_complete_inventory_unites_expected_retired_history_and_original_spelling(self):
        now = datetime.now(UTC)
        reports = [{"domain": f"domain-{index:04d}.example", "date_end": now} for index in range(1101)]
        reports.append({"domain": "Mixed.Example.", "date_end": now})
        self.store.remember_domain_reports([{"domain": "retired.example", "last_report": now.isoformat()}])
        self.store.update_domain_monitoring("retired.example", state="retired")
        self.store.add_domain_monitoring("Expected.Example", 3)
        self.store.add_domain_monitoring("mixed.example", 3)
        client = ReportClient(reports)
        result = await DashboardService(client, self.store, self.settings).domains()
        domains = {item["domain"]: item for item in result}
        self.assertEqual(len(result), 1104)
        self.assertEqual(domains["retired.example"]["monitoring_state"], "retired")
        self.assertEqual(domains["expected.example"]["monitoring_state"], "expected")
        self.assertEqual(domains["Mixed.Example."]["monitoring_state"], "active")
        self.assertNotIn("mixed.example", domains)
        self.assertEqual(len(self.store.list_domain_monitoring(3)), 1104)
        self.assertEqual(len(client.calls), 3)

    async def test_inventory_counts_and_last_seen_keep_existing_meaning(self):
        end = datetime(2026, 9, 8, tzinfo=UTC).timestamp() * 1000
        begin = end - 86400000
        client = PageClient([{"aggregations": {"domains": {"buckets": [
            {"key": {"domain": "observed.example"}, "messages": {"value": 42},
             "last_seen": {"value": begin}, "last_report": {"value": end}},
        ]}}}])
        result = await DashboardService(client, self.store, self.settings).domains()
        self.assertEqual(result, [{"domain": "observed.example", "messages": 42,
                                  "last_seen": "2026-09-07T00:00:00+00:00", "monitoring_state": "active"}])
        self.assertEqual(self.store.list_domain_monitoring(3)[0]["last_report"], "2026-09-08T00:00:00+00:00")

    async def test_partial_inventory_never_updates_domain_history(self):
        client = PageClient([
            {"aggregations": {"domains": {"buckets": [{"key": {"domain": "new.example"},
              "last_report": {"value": datetime.now(UTC).timestamp() * 1000}}], "after_key": {"domain": "new.example"}}}},
            {"timed_out": True, "aggregations": {"domains": {"buckets": []}}},
        ])
        with self.assertRaises(OpenSearchError):
            await DashboardService(client, self.store, self.settings).domains()
        self.assertEqual(self.store.remember_domain_reports([]), [])
        self.assertEqual(self.store.list_domain_monitoring(3), [])


if __name__ == "__main__":
    unittest.main()
