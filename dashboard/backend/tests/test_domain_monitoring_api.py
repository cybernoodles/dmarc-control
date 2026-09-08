from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.store import StateStore


class DomainMonitoringApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "state.db", stale_report_days=7)
        self.store = StateStore(self.settings.database_path)
        for name, value in (("settings", self.settings), ("store", self.store)):
            patcher = patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_read_and_admin_authorization_are_required_for_all_operations(self):
        for read, admin in ((False, False), (False, True), (True, False)):
            with (patch.object(main, "is_read_authenticated", return_value=read),
                  patch.object(main, "is_admin_authenticated", return_value=admin)):
                for method, body in (("get", None),
                                     ("post", {"domain": "expected.example", "grace_days": 3}),
                                     ("patch", {"domain": "expected.example", "state": "retired"})):
                    response = self.client.request(method, "/api/settings/domains", json=body)
                    self.assertEqual(response.status_code, 401)
        self.assertEqual(self.store.list_domain_monitoring(7), [])

    def test_create_retire_reactivate_and_default_are_persistent(self):
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            result = self.client.post("/api/settings/domains", json={"domain": "BÜCHER.Example.", "grace_days": 2})
            self.assertEqual(result.status_code, 201, result.text)
            created = result.json()
            self.assertEqual(created["domain"], "xn--bcher-kva.example")
            self.assertEqual(created["state"], "expected")
            self.assertIsNone(created["last_report"])
            self.assertTrue(created["deadline"])
            duplicate = self.client.post("/api/settings/domains", json={"domain": created["domain"], "grace_days": 2})
            self.assertEqual(duplicate.status_code, 400)
            retired = self.client.patch("/api/settings/domains", json={"domain": created["domain"], "state": "retired"})
            self.assertEqual(retired.status_code, 200, retired.text)
            self.assertEqual(retired.json()["state"], "retired")
            reactivated = self.client.patch("/api/settings/domains", json={"domain": created["domain"], "state": "expected", "grace_days": 4})
            self.assertEqual(reactivated.status_code, 200, reactivated.text)
            self.assertNotEqual(reactivated.json()["monitoring_started_at"], created["monitoring_started_at"])
            unchanged = self.client.patch("/api/settings/domains", json={"domain": created["domain"], "state": "expected", "grace_days": 4})
            self.assertEqual(unchanged.json(), reactivated.json())
            reset = self.client.patch("/api/settings/domains", json={"domain": created["domain"], "grace_days": None})
            self.assertEqual(reset.json()["grace_days"], 7)
            self.assertEqual(reset.json()["monitoring_started_at"], reactivated.json()["monitoring_started_at"])
            listing = self.client.get("/api/settings/domains").json()
            self.assertEqual(listing["default_grace_days"], 7)
            self.assertEqual(listing["domains"], [reset.json()])
            self.assertEqual(StateStore(self.settings.database_path).list_domain_monitoring(7), listing["domains"])

    def test_validation_and_transitions_reject_invalid_writes_without_mutation(self):
        self.store.remember_domain_reports([{"domain": "observed.example", "last_report": datetime.now(UTC).isoformat()}])
        before = self.store.list_domain_monitoring(7)
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            for grace in (True, 0, 366, 1.5, "3"):
                result = self.client.post("/api/settings/domains", json={"domain": "new.example", "grace_days": grace})
                self.assertEqual(result.status_code, 422, result.text)
            for domain in ("*", "https://example.org", "a..example", "bad domain.example", "-bad.example"):
                result = self.client.post("/api/settings/domains", json={"domain": domain, "grace_days": 3})
                self.assertEqual(result.status_code, 400, result.text)
            for extra in ({"state": None}, {"state": "deleted"}, {"unexpected": 1}, {}):
                result = self.client.patch("/api/settings/domains", json={"domain": "observed.example", **extra})
                self.assertEqual(result.status_code, 422, result.text)
            result = self.client.patch("/api/settings/domains", json={"domain": "observed.example", "state": "expected"})
            self.assertEqual(result.status_code, 400)
            missing = self.client.patch("/api/settings/domains", json={"domain": "missing.example", "state": "retired"})
            self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.store.list_domain_monitoring(7), before)


if __name__ == "__main__":
    unittest.main()
