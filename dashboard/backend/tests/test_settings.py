from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.auth import hash_password, verify_password
from app.config import Settings
from app.store import StateStore


class PasswordHashTests(unittest.TestCase):
    def test_password_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse battery")
        second = hash_password("correct horse battery")

        self.assertNotEqual(first, second)
        self.assertNotIn("correct horse battery", first)
        self.assertTrue(verify_password("correct horse battery", first))
        self.assertFalse(verify_password("wrong password", first))


class AdminSettingsApiTests(unittest.TestCase):
    def test_first_run_setup_login_change_and_global_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
            )
            test_store = StateStore(test_settings.database_path)

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                TestClient(main.app) as client,
            ):
                initial = client.get("/api/auth/status")
                denied_before_setup = client.put(
                    "/api/settings/appearance",
                    json={"profile": "custom", "color": "#2457a6"},
                )
                short_password = client.post(
                    "/api/auth/setup",
                    json={"password": "too-short"},
                )
                setup = client.post(
                    "/api/auth/setup",
                    json={"password": "initial-admin-password"},
                )
                duplicate_setup = client.post(
                    "/api/auth/setup",
                    json={"password": "different-admin-password"},
                )
                authenticated = client.get("/api/auth/status")
                updated = client.put(
                    "/api/settings/appearance",
                    json={"profile": "custom", "color": "#2457a6"},
                )
                wrong_current_password = client.post(
                    "/api/auth/change-password",
                    json={
                        "current_password": "wrong-current-password",
                        "new_password": "replacement-admin-password",
                    },
                )
                changed = client.post(
                    "/api/auth/change-password",
                    json={
                        "current_password": "initial-admin-password",
                        "new_password": "replacement-admin-password",
                    },
                )
                logged_out = client.post("/api/auth/logout")
                denied_after_logout = client.put(
                    "/api/settings/appearance",
                    json={"profile": "standard", "color": None},
                )
                old_login = client.post(
                    "/api/auth/login",
                    json={"password": "initial-admin-password"},
                )
                new_login = client.post(
                    "/api/auth/login",
                    json={"password": "replacement-admin-password"},
                )

            self.assertEqual(
                initial.json(),
                {"setup_required": True, "authenticated": False},
            )
            self.assertEqual(denied_before_setup.status_code, 401)
            self.assertEqual(short_password.status_code, 422)
            self.assertEqual(setup.status_code, 201)
            self.assertEqual(duplicate_setup.status_code, 409)
            self.assertTrue(authenticated.json()["authenticated"])
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["global_profile"], "custom")
            self.assertEqual(wrong_current_password.status_code, 403)
            self.assertEqual(changed.status_code, 200)
            self.assertFalse(logged_out.json()["authenticated"])
            self.assertEqual(denied_after_logout.status_code, 401)
            self.assertEqual(old_login.status_code, 401)
            self.assertEqual(new_login.status_code, 200)
            self.assertNotIn(
                "replacement-admin-password",
                test_store.admin_password_hash() or "",
            )
            self.assertEqual(
                test_store.appearance_settings()["global_color"],
                "#2457a6",
            )


if __name__ == "__main__":
    unittest.main()
