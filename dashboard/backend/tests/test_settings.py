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
    def test_first_run_read_and_admin_sessions(self) -> None:
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
                    json={
                        "admin_password": "too-short",
                        "read_username": "dmarc-reader",
                        "read_password": "also-too-short",
                    },
                )
                setup = client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "initial-admin-password",
                        "read_username": "DMARC-Reader",
                        "read_password": "initial-read-password",
                    },
                )
                duplicate_setup = client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "different-admin-password",
                        "read_username": "another-reader",
                        "read_password": "different-read-password",
                    },
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
                admin_logged_out = client.post("/api/auth/logout")
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
                read_credentials_updated = client.put(
                    "/api/auth/read-credentials",
                    json={
                        "username": "security-reader",
                        "password": "replacement-read-password",
                    },
                )
                read_logged_out = client.post("/api/auth/read-logout")
                denied_without_read_session = client.get(
                    "/api/settings/appearance"
                )
                old_read_login = client.post(
                    "/api/auth/read-login",
                    json={
                        "username": "DMARC-Reader",
                        "password": "initial-read-password",
                    },
                )
                invalid_read_login = client.post(
                    "/api/auth/read-login",
                    json={
                        "username": "security-reader",
                        "password": "wrong-read-password",
                    },
                )
                read_login = client.post(
                    "/api/auth/read-login",
                    json={
                        "username": "SECURITY-READER",
                        "password": "replacement-read-password",
                    },
                )
                read_only_status = client.get("/api/auth/status")
                appearance_as_read = client.get("/api/settings/appearance")

            self.assertEqual(
                initial.json(),
                {
                    "setup_required": True,
                    "admin_configured": False,
                    "read_authenticated": False,
                    "read_username": None,
                    "authenticated": False,
                },
            )
            self.assertEqual(denied_before_setup.status_code, 401)
            self.assertEqual(short_password.status_code, 422)
            self.assertEqual(setup.status_code, 201)
            setup_cookies = setup.headers.get_list("set-cookie")
            self.assertTrue(
                any("dmarc_read_session=" in value for value in setup_cookies)
            )
            self.assertTrue(
                any("dmarc_admin_session=" in value for value in setup_cookies)
            )
            self.assertTrue(
                all("HttpOnly" in value for value in setup_cookies)
            )
            self.assertEqual(duplicate_setup.status_code, 409)
            self.assertTrue(authenticated.json()["authenticated"])
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["global_profile"], "custom")
            self.assertEqual(wrong_current_password.status_code, 403)
            self.assertEqual(changed.status_code, 200)
            self.assertFalse(admin_logged_out.json()["authenticated"])
            self.assertTrue(admin_logged_out.json()["read_authenticated"])
            self.assertEqual(denied_after_logout.status_code, 401)
            self.assertEqual(old_login.status_code, 401)
            self.assertEqual(new_login.status_code, 200)
            self.assertEqual(read_credentials_updated.status_code, 200)
            self.assertFalse(read_logged_out.json()["read_authenticated"])
            self.assertEqual(denied_without_read_session.status_code, 401)
            self.assertEqual(
                denied_without_read_session.json()["detail"],
                "Read login required",
            )
            self.assertEqual(old_read_login.status_code, 401)
            self.assertEqual(invalid_read_login.status_code, 401)
            self.assertEqual(read_login.status_code, 200)
            self.assertEqual(
                read_login.json()["read_username"],
                "security-reader",
            )
            self.assertTrue(read_only_status.json()["read_authenticated"])
            self.assertFalse(read_only_status.json()["authenticated"])
            self.assertEqual(
                read_only_status.json()["read_username"],
                "security-reader",
            )
            self.assertEqual(appearance_as_read.status_code, 200)
            self.assertNotIn(
                "replacement-admin-password",
                test_store.admin_password_hash() or "",
            )
            self.assertNotIn(
                "replacement-read-password",
                test_store.read_password_hash("security-reader") or "",
            )
            self.assertEqual(
                test_store.appearance_settings()["global_color"],
                "#2457a6",
            )

    def test_existing_admin_must_authorize_read_user_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
            )
            test_store = StateStore(test_settings.database_path)
            test_store.set_initial_admin_password(
                hash_password("existing-admin-password")
            )

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                TestClient(main.app) as client,
            ):
                initial = client.get("/api/auth/status")
                wrong_admin = client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "wrong-admin-password",
                        "read_username": "dmarc-reader",
                        "read_password": "initial-read-password",
                    },
                )
                migrated = client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "existing-admin-password",
                        "read_username": "dmarc-reader",
                        "read_password": "initial-read-password",
                    },
                )

            self.assertTrue(initial.json()["setup_required"])
            self.assertTrue(initial.json()["admin_configured"])
            self.assertEqual(wrong_admin.status_code, 401)
            self.assertEqual(migrated.status_code, 201)
            self.assertTrue(migrated.json()["read_authenticated"])
            self.assertTrue(migrated.json()["authenticated"])


if __name__ == "__main__":
    unittest.main()
