from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.config import Settings
from app.service import DashboardService, _score_service
from app.store import StateStore


class FakeClient:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {
            "hits": {"total": {"value": 0}},
            "aggregations": {},
        }
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    async def search(
        self,
        index: str,
        body: dict[str, Any],
        *,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((index, body, allow_missing))
        return self.response


class ServiceDetectionTests(unittest.TestCase):
    def test_smtp2go_uses_multiple_signals(self) -> None:
        result = _score_service(
            {
                "source_reverse_dns": "e3i387.smtp2go.com",
                "source_base_domain": "smtp2go.com",
                "source_as_name": "DEFT.COM",
            },
            ["smtpservice.net", "s1073568"],
        )

        self.assertEqual(result["service"], "SMTP2GO")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertGreaterEqual(len(result["evidence"]), 2)

    def test_unknown_host_is_not_invented(self) -> None:
        result = _score_service(
            {
                "source_reverse_dns": "customer.example.net",
                "source_as_name": "Example Transit",
                "source_name": "Example ISP",
                "source_type": "ISP",
            },
            [],
        )

        self.assertEqual(result["service"], "Unbekannt")
        self.assertEqual(result["confidence"], 0)


class StoreTests(unittest.TestCase):
    def test_alert_and_host_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "dashboard.db")
            store.set_alert_status("alert-1", "acknowledged")
            store.set_host_override(
                "192.0.2.10",
                service_name="Mail Provider",
                trust_status="confirmed",
                notes="Freigegeben",
            )

            self.assertEqual(
                store.alert_states()["alert-1"]["status"], "acknowledged"
            )
            self.assertEqual(
                store.host_overrides()["192.0.2.10"]["service_name"],
                "Mail Provider",
            )


class ForensicPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_forensic_query_never_loads_source_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeClient()
            settings = Settings(database_path=Path(directory) / "dashboard.db")
            service = DashboardService(
                fake,
                StateStore(settings.database_path),
                settings,
            )

            result = await service.forensics("*", 30)

            _, body, allow_missing = fake.calls[0]
            self.assertEqual(body["size"], 0)
            self.assertFalse(body["_source"])
            self.assertTrue(allow_missing)
            self.assertFalse(result["privacy"]["raw_samples_loaded"])
            serialized = str(body)
            self.assertNotIn("sample.raw", serialized)
            self.assertNotIn("original_rcpt_to", serialized)


class HostQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_query_uses_read_only_current_and_historical_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeClient()
            settings = Settings(database_path=Path(directory) / "dashboard.db")
            service = DashboardService(
                fake,
                StateStore(settings.database_path),
                settings,
            )

            result = await service.hosts("*", 90)

            self.assertEqual(result, [])
            _, body, _ = fake.calls[0]
            self.assertEqual(body["size"], 0)
            self.assertEqual(body["query"], {"match_all": {}})
            host_aggs = body["aggs"]["hosts"]["aggs"]
            self.assertIn("current", host_aggs)
            self.assertIn("previous", host_aggs)
            self.assertIn("first_seen", host_aggs)


if __name__ == "__main__":
    unittest.main()
