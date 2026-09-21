from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.auth import DUMMY_PASSWORD_HASH, hash_password
from app.config import Settings
from app.store import StateStore


class LoginThrottleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "state.db"
        self.store = StateStore(self.database_path)
        self.store.set_initial_credentials(
            admin_password_hash="admin-hash",
            read_username="reader",
            read_username_normalized="reader",
            read_password_hash="reader-hash",
            backup_mode="external",
        )
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def attempt(
        self,
        *,
        password: str = "wrong",
        username: str = "reader",
        client_ip: str = "198.51.100.25",
        now: datetime | None = None,
    ):
        return self.store.authenticate_login(
            account="read",
            client_ip=client_ip,
            username_normalized=username,
            password=password,
            dummy_password_hash=DUMMY_PASSWORD_HASH,
            verify=lambda candidate, password_hash: (
                candidate == "correct" and password_hash == "reader-hash"
            ),
            now=now or self.now,
        )

    def test_throttle_is_exponential_rounded_and_resets_after_success(self) -> None:
        for _ in range(5):
            self.assertEqual(self.attempt().status, "failed")

        blocked = self.attempt(now=self.now + timedelta(milliseconds=100))
        self.assertEqual(blocked.status, "throttled")
        self.assertEqual(blocked.retry_after, 1)

        sixth = self.attempt(now=self.now + timedelta(seconds=1, milliseconds=1))
        self.assertEqual(sixth.status, "failed")
        blocked_again = self.attempt(
            now=self.now + timedelta(seconds=1, milliseconds=801)
        )
        self.assertEqual(blocked_again.status, "throttled")
        self.assertEqual(blocked_again.retry_after, 2)

        successful = self.attempt(
            password="correct",
            now=self.now + timedelta(seconds=3, milliseconds=2),
        )
        self.assertEqual(successful.status, "authenticated")
        self.assertEqual(
            self.attempt(now=self.now + timedelta(seconds=3, milliseconds=2)).status,
            "failed",
        )

        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE login_throttles SET failure_count = 10, locked_until = NULL
                WHERE scope = 'ip' AND client_ip = '198.51.100.25'
                  AND username_normalized = ''
                """
            )
        capped_failure = self.attempt(now=self.now + timedelta(seconds=4))
        self.assertEqual(capped_failure.status, "failed")
        capped_lock = self.attempt(
            now=self.now + timedelta(seconds=4, milliseconds=100)
        )
        self.assertEqual(capped_lock.retry_after, 60)

    def test_ip_and_username_limits_are_separate_and_old_entries_are_removed(self) -> None:
        for _ in range(4):
            self.assertEqual(self.attempt().status, "failed")
        self.assertEqual(self.attempt(username="another").status, "failed")
        self.assertEqual(
            self.attempt(username="another").status,
            "throttled",
        )

        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO login_throttles (
                    scope, client_ip, username_normalized, failure_count,
                    locked_until, updated_at
                ) VALUES ('username', '203.0.113.10', 'expired', 5, NULL, ?)
                """,
                ((self.now - timedelta(hours=25)).isoformat(),),
            )
        self.attempt(now=self.now + timedelta(hours=25))
        with sqlite3.connect(self.database_path) as connection:
            expired = connection.execute(
                """
                SELECT 1 FROM login_throttles
                WHERE client_ip = '203.0.113.10'
                """
            ).fetchone()
        self.assertIsNone(expired)

    def test_unknown_user_runs_one_stable_dummy_verification(self) -> None:
        checks: list[tuple[str, str]] = []

        result = self.store.authenticate_login(
            account="read",
            client_ip="198.51.100.26",
            username_normalized="unknown-reader",
            password="wrong",
            dummy_password_hash=DUMMY_PASSWORD_HASH,
            verify=lambda password, encoded: checks.append((password, encoded)) or False,
            now=self.now,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(checks, [("wrong", DUMMY_PASSWORD_HASH)])


class AuthenticationApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.settings = Settings(database_path=root / "state.db")
        self.store = StateStore(self.settings.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_unknown_read_user_uses_the_process_dummy_hash_once(self) -> None:
        self.store.set_initial_credentials(
            admin_password_hash=hash_password("initial-admin-password"),
            read_username="reader",
            read_username_normalized="reader",
            read_password_hash=hash_password("initial-read-password"),
            backup_mode="external",
        )
        with (
            patch.object(main, "settings", self.settings),
            patch.object(main, "store", self.store),
            patch.object(main, "verify_password", wraps=main.verify_password) as verify,
            TestClient(main.app) as client,
        ):
            response = client.post(
                "/api/auth/read-login",
                json={"username": "unknown", "password": "wrong-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[1], DUMMY_PASSWORD_HASH)

    def test_read_login_uses_peer_ip_and_returns_a_rounded_retry_after(self) -> None:
        self.store.set_initial_credentials(
            admin_password_hash=hash_password("initial-admin-password"),
            read_username="reader",
            read_username_normalized="reader",
            read_password_hash=hash_password("initial-read-password"),
            backup_mode="external",
        )
        now = datetime.now(UTC)
        with sqlite3.connect(self.settings.database_path) as connection:
            connection.execute(
                """
                INSERT INTO login_throttles (
                    scope, client_ip, username_normalized, failure_count,
                    locked_until, updated_at
                ) VALUES ('ip', 'testclient', '', 5, ?, ?)
                """,
                (
                    (now + timedelta(seconds=1.9)).isoformat(),
                    now.isoformat(),
                ),
            )
        with (
            patch.object(main, "settings", self.settings),
            patch.object(main, "store", self.store),
            TestClient(main.app) as client,
        ):
            response = client.post(
                "/api/auth/read-login",
                headers={"X-Forwarded-For": "203.0.113.250"},
                json={"username": "reader", "password": "initial-read-password"},
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "2")

    def test_validation_errors_never_echo_passwords_or_context(self) -> None:
        secret = "super-secret-validation-password"
        with (
            patch.object(main, "settings", self.settings),
            patch.object(main, "store", self.store),
            TestClient(main.app) as client,
        ):
            setup_invalid = client.post(
                "/api/auth/setup",
                json={
                    "admin_password": secret,
                    "read_username": "reader",
                    "read_password": secret,
                    "backup_mode": "not-a-mode",
                },
            )
            setup = client.post(
                "/api/auth/setup",
                json={
                    "admin_password": "initial-admin-password",
                    "read_username": "reader",
                    "read_password": "initial-read-password",
                    "backup_mode": "external",
                },
            )
            read_login_invalid = client.post(
                "/api/auth/read-login",
                json={"username": "reader", "password": secret * 30},
            )
            admin_login_invalid = client.post(
                "/api/auth/admin-login",
                json={"password": secret * 30},
            )
            credentials_invalid = client.put(
                "/api/auth/read-credentials",
                json={"username": "reader", "password": secret[:8]},
            )

        self.assertEqual(setup.status_code, 201)
        for response in (
            setup_invalid,
            read_login_invalid,
            admin_login_invalid,
            credentials_invalid,
        ):
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
            for error in response.json()["detail"]:
                self.assertEqual(set(error), {"type", "loc", "msg"})
