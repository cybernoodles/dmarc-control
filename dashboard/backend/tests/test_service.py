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
        self.assertEqual(result["profile"], "mail_service")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertGreaterEqual(len(result["evidence"]), 2)

    def test_dynamic_public_ip_uses_multiple_ptr_patterns(self) -> None:
        result = _score_service(
            {
                "source_ip_address": "157.143.102.109",
                "source_reverse_dns": "109.102.143.157.bbcs.as8758.net",
                "source_base_domain": "as8758.net",
            },
            ["dp0.ch"],
        )

        self.assertEqual(result["service"], "Dynamischer IP-Bereich")
        self.assertEqual(result["profile"], "dynamic_ip")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertEqual(len(result["evidence"]), 2)

    def test_explicit_static_ptr_is_not_classified_as_dynamic(self) -> None:
        result = _score_service(
            {
                "source_ip_address": "46.140.105.26",
                "source_reverse_dns": "46-140-105-26.static.cablecom.ch",
                "source_base_domain": "cablecom.ch",
            },
            [],
        )

        self.assertEqual(result["service"], "Unbekannt")
        self.assertEqual(result["profile"], "unknown")

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
        self.assertEqual(result["profile"], "unknown")


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
            self.assertTrue(store.clear_host_override("192.0.2.10"))
            self.assertNotIn("192.0.2.10", store.host_overrides())
            self.assertFalse(store.clear_host_override("192.0.2.10"))

    def test_alert_status_and_host_classification_remain_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "dashboard.db")
            store.set_host_override(
                "192.0.2.10",
                service_name="Mail Provider",
                trust_status="confirmed",
                notes="Administratively assigned",
            )

            store.set_alert_status("alert-1", "ignored")
            self.assertEqual(
                store.host_overrides()["192.0.2.10"]["trust_status"],
                "confirmed",
            )

            store.set_alert_status("alert-1", "resolved")
            store.set_host_override(
                "192.0.2.10",
                service_name="Mail Provider",
                trust_status="ignored",
                notes="Automatic match rejected",
            )
            self.assertEqual(store.alert_states()["alert-1"]["status"], "resolved")

    def test_global_appearance_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "dashboard.db")

            self.assertEqual(
                store.appearance_settings()["global_profile"],
                "standard",
            )
            self.assertEqual(
                store.appearance_settings()["global_color"],
                "#173f43",
            )

            stored = store.set_global_appearance(
                profile="custom",
                color="#2457a6",
            )
            self.assertEqual(stored["global_profile"], "custom")
            self.assertEqual(stored["global_color"], "#2457a6")
            self.assertEqual(store.appearance_settings(), stored)

            reset = store.set_global_appearance(
                profile="standard",
                color="#ffffff",
            )
            self.assertEqual(reset["global_profile"], "standard")
            self.assertEqual(reset["global_color"], "#173f43")


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


class OverviewQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_data_freshness_uses_report_period_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeClient()
            settings = Settings(database_path=Path(directory) / "dashboard.db")
            service = DashboardService(
                fake,
                StateStore(settings.database_path),
                settings,
            )

            await service.overview("*", 30)

            _, body, _ = fake.calls[0]
            self.assertEqual(
                body["aggs"]["last_report"],
                {"max": {"field": "date_end"}},
            )

    async def test_missing_policy_percentage_uses_application_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeClient(
                {
                    "aggregations": {
                        "messages": {"value": 1},
                        "policies": {
                            "buckets": [
                                {
                                    "key": "example.com",
                                    "messages": {"value": 1},
                                    "policy": {
                                        "buckets": [{"key": "reject"}]
                                    },
                                    "percentage": {"buckets": []},
                                }
                            ]
                        },
                    }
                }
            )
            settings = Settings(database_path=Path(directory) / "dashboard.db")
            service = DashboardService(
                fake,
                StateStore(settings.database_path),
                settings,
            )

            result = await service.overview("*", 30)

            _, body, _ = fake.calls[0]
            percentage_terms = body["aggs"]["policies"]["aggs"][
                "percentage"
            ]["terms"]
            self.assertNotIn("missing", percentage_terms)
            self.assertEqual(result["policies"][0]["percentage"], 100)


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
