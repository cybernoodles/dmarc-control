from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.store import StateStore


class SettingsTokenTests(unittest.TestCase):
    def test_token_file_authorizes_global_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "settings.token"
            token_file.write_text("test-secret\n", encoding="utf-8")
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
                settings_token_file=token_file,
                settings_token="",
            )

            with patch.object(main, "settings", test_settings):
                main.require_settings_token("test-secret")
                with self.assertRaises(HTTPException) as invalid:
                    main.require_settings_token("wrong-secret")

            self.assertEqual(invalid.exception.status_code, 403)

    def test_missing_token_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
                settings_token_file=Path(directory) / "missing.token",
                settings_token="",
            )

            with patch.object(main, "settings", test_settings):
                with self.assertRaises(HTTPException) as missing:
                    main.require_settings_token("anything")

            self.assertEqual(missing.exception.status_code, 503)


class AppearanceApiTests(unittest.TestCase):
    def test_global_profile_requires_token_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "settings.token"
            token_file.write_text("api-secret\n", encoding="utf-8")
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
                settings_token_file=token_file,
                settings_token="",
            )
            test_store = StateStore(test_settings.database_path)

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                TestClient(main.app) as client,
            ):
                initial = client.get("/api/settings/appearance")
                denied = client.put(
                    "/api/settings/appearance",
                    json={"profile": "custom", "color": "#2457a6"},
                    headers={"X-Dashboard-Settings-Token": "wrong"},
                )
                updated = client.put(
                    "/api/settings/appearance",
                    json={"profile": "custom", "color": "#2457a6"},
                    headers={"X-Dashboard-Settings-Token": "api-secret"},
                )

            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["global_profile"], "standard")
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["global_profile"], "custom")
            self.assertEqual(
                test_store.appearance_settings()["global_color"],
                "#2457a6",
            )


if __name__ == "__main__":
    unittest.main()
