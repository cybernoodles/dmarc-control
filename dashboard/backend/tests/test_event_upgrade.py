from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.config import Settings
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore


class UpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_history_does_not_initialize_existing_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=Path(directory) / "state.db")
            state = StateStore(settings.database_path)
            state.set_alert_status("old-alert", "resolved")
            client = AsyncMock()
            client.search.return_value = {"hits": {"total": {"value": 0}}, "aggregations": {}}
            service = DashboardService(client, state, settings)
            with self.assertRaises(OpenSearchError):
                await service.alerts("*", 30)
            self.assertFalse(state.alert_model_initialized())
            self.assertEqual(state.alert_states()["old-alert"]["status"], "resolved")

    async def test_genuinely_empty_installation_initializes_without_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=Path(directory) / "state.db")
            state = StateStore(settings.database_path)
            client = AsyncMock()
            client.search.return_value = {"hits": {"total": {"value": 0}}, "aggregations": {}}
            service = DashboardService(client, state, settings)
            self.assertEqual(await service.alerts("*", 30), [])
            self.assertTrue(state.alert_model_initialized())


if __name__ == "__main__":
    unittest.main()
