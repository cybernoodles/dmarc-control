from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

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
                for method, path, body in (
                    ("get", "/api/settings/domains", None),
                    ("post", "/api/settings/domains", {
                        "domain": "expected.example", "grace_days": 3,
                    }),
                    ("patch", "/api/settings/domains", {
                        "domain": "expected.example", "state": "retired",
                    }),
                    ("put", "/api/settings/domains/expected.example/services/microsoft365", {
                        "decision": "confirmed",
                    }),
                    ("post", "/api/settings/domains/expected.example/services/microsoft365/refresh", None),
                ):
                    response = self.client.request(method, path, json=body)
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
            self.assertEqual(
                StateStore(self.settings.database_path).list_domain_monitoring(7),
                [
                    {
                        key: value for key, value in item.items()
                        if key != "service_assessments"
                    }
                    for item in listing["domains"]
                ],
            )
            service = listing["domains"][0]["service_assessments"][0]
            self.assertEqual(service["service_id"], "microsoft365")
            self.assertEqual(service["dns_status"], "pending")
            self.assertEqual(service["effective_status"], "unknown")

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

    def test_admin_can_confirm_reject_and_restore_automatic_service_policy(self):
        self.store.add_domain_monitoring(
            "example.com", 3, default_grace_days=7,
        )
        path = "/api/settings/domains/example.com/services/microsoft365"
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            confirmed = self.client.put(path, json={"decision": "confirmed"})
            rejected = self.client.put(path, json={"decision": "rejected"})
            automatic = self.client.put(path, json={"decision": "automatic"})
            listing = self.client.get("/api/settings/domains")

        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["effective_status"], "expected")
        self.assertEqual(rejected.json()["effective_status"], "rejected")
        self.assertEqual(automatic.json()["decision"], "automatic")
        self.assertEqual(automatic.json()["effective_status"], "unknown")
        self.assertEqual(
            listing.json()["domains"][0]["service_assessments"][0]["decision"],
            "automatic",
        )

    def test_manual_dns_refresh_persists_explainable_microsoft365_evidence(self):
        self.store.add_domain_monitoring(
            "example.com", 3, default_grace_days=7,
        )
        assessor = AsyncMock()
        assessor.assess.return_value = {
            "service_id": "microsoft365",
            "label": "Microsoft 365",
            "dns_status": "fresh",
            "assessment": "strong",
            "score": 1.0,
            "evidence": [{
                "type": "spf",
                "value": "include:spf.protection.outlook.com",
                "rule_id": "microsoft365.spf.commercial.include.direct",
            }],
            "contradictions": [{
                "type": "dns",
                "value": "CNAME selector2._domainkey.example.com",
                "rule_id": "dns.timeout",
            }],
            "assessed_at": datetime.now(UTC).isoformat(),
            "ttl_seconds": 60,
        }
        wakeup = Mock()
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True),
              patch.dict(main.domain_dns_assessors, {"microsoft365": assessor}),
              patch.object(
                  main.app.state, "domain_dns_wakeup", wakeup, create=True,
              )):
            response = self.client.post(
                "/api/settings/domains/example.com/services/microsoft365/refresh"
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["dns_status"], "fresh")
        self.assertEqual(result["assessment"], "strong")
        self.assertEqual(result["evidence"][0]["type"], "spf")
        self.assertIn("dns.timeout", result["contradictions"][0])
        assessor.assess.assert_awaited_once_with("example.com")
        wakeup.set.assert_called_once_with()
        stored = self.store.domain_service_assessment(
            "example.com", "microsoft365",
        )
        self.assertEqual(stored["assessment"], "strong")

    def test_expired_dns_snapshot_is_presented_as_stale(self):
        self.store.add_domain_monitoring(
            "example.com", 3, default_grace_days=7,
        )
        now = datetime.now(UTC)
        self.store.save_domain_service_dns_assessment(
            "example.com",
            {
                "service_id": "microsoft365",
                "dns_status": "fresh",
                "assessment": "configured",
                "assessed_at": now - timedelta(hours=2),
                "expires_at": now - timedelta(hours=1),
                "evidence": [{
                    "type": "spf",
                    "value": "include:spf.protection.outlook.com",
                    "rule_id": "microsoft365.spf.commercial.include.direct",
                }],
                "contradictions": [],
            },
        )
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            response = self.client.get("/api/settings/domains")

        assessment = response.json()["domains"][0]["service_assessments"][0]
        self.assertEqual(assessment["dns_status"], "stale")
        self.assertEqual(assessment["effective_status"], "suggested")

    def test_service_operations_reject_unknown_services_and_domains(self):
        self.store.add_domain_monitoring(
            "example.com", 3, default_grace_days=7,
        )
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            unknown_service = self.client.put(
                "/api/settings/domains/example.com/services/lookalike365",
                json={"decision": "confirmed"},
            )
            unknown_domain = self.client.put(
                "/api/settings/domains/missing.example/services/microsoft365",
                json={"decision": "confirmed"},
            )
        # Domain existence is checked before a provider policy may be created.
        self.assertEqual(unknown_service.status_code, 404)
        self.assertEqual(unknown_domain.status_code, 404)


if __name__ == "__main__":
    unittest.main()
