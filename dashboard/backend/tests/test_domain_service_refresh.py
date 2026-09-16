from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.config import Settings
from app.store import StateStore


class DomainServiceRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_refreshes_only_due_non_retired_domains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "state.db",
                domain_dns_refresh_seconds=3600,
            )
            store = StateStore(settings.database_path)
            store.add_domain_monitoring("active.example", 3)
            store.add_domain_monitoring("retired.example", 3)
            store.update_domain_monitoring("retired.example", state="retired")
            assessor = AsyncMock()
            assessor.assess.return_value = {
                "service_id": "microsoft365",
                "label": "Microsoft 365",
                "dns_status": "fresh",
                "assessment": "configured",
                "score": 0.6,
                "evidence": [{
                    "type": "spf",
                    "value": "include:spf.protection.outlook.com",
                    "rule_id": "microsoft365.spf.commercial.include.direct",
                }],
                "contradictions": [],
                "assessed_at": datetime.now(UTC).isoformat(),
                "ttl_seconds": 3600,
            }

            with (
                patch.object(main, "settings", settings),
                patch.object(main, "store", store),
                patch.dict(
                    main.domain_dns_assessors,
                    {"microsoft365": assessor},
                ),
            ):
                first_delay = await main.refresh_due_domain_service_dns()
                second_delay = await main.refresh_due_domain_service_dns()

            assessor.assess.assert_awaited_once_with("active.example")
            active = store.domain_service_assessment(
                "active.example", "microsoft365",
            )
            retired = store.domain_service_assessment(
                "retired.example", "microsoft365",
            )
            self.assertEqual(active["dns_status"], "fresh")
            self.assertIsNone(retired["assessed_at"])
            self.assertGreater(first_delay, 0)
            self.assertLessEqual(first_delay, 3600)
            self.assertGreater(second_delay, 0)
            self.assertLessEqual(second_delay, 3600)

    async def test_short_dns_ttl_schedules_refresh_before_polling_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=Path(directory) / "state.db",
                domain_dns_refresh_seconds=3600,
            )
            store = StateStore(settings.database_path)
            store.add_domain_monitoring("active.example", 3)
            assessor = AsyncMock()
            assessor.assess.return_value = {
                "service_id": "microsoft365",
                "label": "Microsoft 365",
                "dns_status": "fresh",
                "assessment": "configured",
                "score": 0.6,
                "evidence": [{
                    "type": "spf",
                    "value": "include:spf.protection.outlook.com",
                    "rule_id": "microsoft365.spf.commercial.include.direct",
                }],
                "contradictions": [],
                "assessed_at": datetime.now(UTC).isoformat(),
                "ttl_seconds": 300,
            }

            with (
                patch.object(main, "settings", settings),
                patch.object(main, "store", store),
                patch.dict(main.domain_dns_assessors, {"microsoft365": assessor}),
            ):
                delay = await main.refresh_due_domain_service_dns()
                still_fresh_delay = await main.refresh_due_domain_service_dns()

            assessor.assess.assert_awaited_once_with("active.example")
            self.assertGreater(delay, 0)
            self.assertLessEqual(delay, 300)
            self.assertGreater(still_fresh_delay, 0)
            self.assertLessEqual(still_fresh_delay, 300)


if __name__ == "__main__":
    unittest.main()
