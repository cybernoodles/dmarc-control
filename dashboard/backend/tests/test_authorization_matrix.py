"""Authorization matrix for the visible Operator and Admin roles.

The persisted session, cookie, API path, and configuration names deliberately
retain their legacy ``read`` spelling.  This test describes the product roles
instead: Operator may read and perform triage, while Admin controls global
configuration.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.auth import hash_password
from app.config import Settings
from app.store import StateStore


# Keep every non-internal protected API route in exactly one role bucket.  A
# newly added route makes ``test_route_registry_is_complete`` fail until its
# authorization decision is reviewed explicitly.
OPERATOR_READ_REQUESTS = (
    ("get", "/api/domains", None),
    ("get", "/api/settings/appearance", None),
    ("get", "/api/settings/backup", None),
    ("get", "/api/settings/notifications/status", None),
    ("get", "/api/overview", None),
    ("get", "/api/hosts", None),
    ("get", "/api/hosts/203.0.113.1", None),
    ("get", "/api/alerts/evaluation/status", None),
    ("get", "/api/alerts", None),
    ("get", "/api/alerts/example-alert", None),
    ("get", "/api/forensics", None),
)

OPERATOR_TRIAGE_REQUESTS = (
    ("put", "/api/hosts/203.0.113.1/classification", {
        "trust_status": "confirmed", "notes": "Reviewed",
    }),
    ("patch", "/api/hosts/203.0.113.1/classification", {
        "trust_status": "ignored",
    }),
    ("delete", "/api/hosts/203.0.113.1/classification", None),
    ("patch", "/api/alerts/example-alert", {"status": "resolved"}),
)

ADMIN_REQUESTS = (
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
    ("post", "/api/auth/change-password", {
        "current_password": "initial-admin-password",
        "new_password": "replacement-admin-password",
    }),
    ("put", "/api/auth/read-credentials", {
        "username": "operator", "password": "replacement-operator-password",
    }),
    ("put", "/api/settings/appearance", {
        "profile": "standard", "color": None,
    }),
    ("put", "/api/settings/backup", {"mode": "external"}),
    ("get", "/api/settings/mailbox", None),
    ("put", "/api/settings/mailbox", {
        "provider": "imap", "host": "imap.example", "user": "operator",
        "password": "mailbox-password",
    }),
    ("post", "/api/settings/mailbox/test", None),
    ("post", "/api/settings/mailbox/activate", None),
    ("get", "/api/settings/notifications", None),
    ("put", "/api/settings/notifications", {
        "sender": "alerts@example.invalid", "recipients": ["ops@example.invalid"],
    }),
    ("post", "/api/settings/notifications/test", None),
    ("get", "/api/alerts/example-alert/delivery", None),
)

AUTH_REQUESTS = {
    ("get", "/api/auth/status"),
    ("post", "/api/auth/setup"),
    ("post", "/api/settings/backup/setup"),
    ("post", "/api/auth/read-login"),
    ("post", "/api/auth/read-logout"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
    ("get", "/api/health"),
}


class AuthorizationMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = Settings(
            database_path=Path(directory.name) / "state.db",
            connection_key_path=Path(directory.name) / "connection.key",
        )
        store = StateStore(settings.database_path)
        self.assertTrue(store.set_initial_credentials(
            admin_password_hash=hash_password("initial-admin-password"),
            read_username="operator",
            read_username_normalized="operator",
            read_password_hash=hash_password("initial-operator-password"),
            backup_mode="external",
        ))
        for name, value in (("settings", settings), ("store", store)):
            patcher = patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def request(self, method: str, path: str, body: dict | None):
        return self.client.request(method, path, json=body)

    def test_route_registry_is_complete(self) -> None:
        registered = {
            (method.lower(), route.path)
            for route in main.app.routes
            if getattr(route, "path", "").startswith("/api/")
            and not route.path.startswith("/api/internal/")
            and route.path not in {"/api/docs", "/api/openapi.json"}
            for method in route.methods or ()
        }
        def route_path(method: str, path: str) -> str:
            return next(
                route.path
                for route in main.app.routes
                if method.upper() in (route.methods or ())
                and route.path_regex.fullmatch(path)
            )

        expected = {
            *((method, route_path(method, path))
              for method, path, _body in OPERATOR_READ_REQUESTS),
            *((method, route_path(method, path))
              for method, path, _body in OPERATOR_TRIAGE_REQUESTS),
            *((method, route_path(method, path))
              for method, path, _body in ADMIN_REQUESTS),
            *AUTH_REQUESTS,
        }
        self.assertSetEqual(registered, expected)

    def test_anonymous_requests_are_rejected_for_every_protected_route(self) -> None:
        for method, path, body in (
            *OPERATOR_READ_REQUESTS,
            *OPERATOR_TRIAGE_REQUESTS,
            *ADMIN_REQUESTS,
        ):
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, body).status_code, 401)

    def test_operator_can_read_and_perform_only_triage_mutations(self) -> None:
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=False)):
            for method, path, body in (
                *OPERATOR_READ_REQUESTS,
                *OPERATOR_TRIAGE_REQUESTS,
            ):
                with self.subTest(method=method, path=path):
                    self.assertNotEqual(self.request(method, path, body).status_code, 401)
            for method, path, body in ADMIN_REQUESTS:
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.request(method, path, body).status_code, 401)

    def test_admin_can_access_every_admin_function(self) -> None:
        with (patch.object(main, "is_read_authenticated", return_value=True),
              patch.object(main, "is_admin_authenticated", return_value=True)):
            for method, path, body in ADMIN_REQUESTS:
                with self.subTest(method=method, path=path):
                    self.assertNotEqual(self.request(method, path, body).status_code, 401)


if __name__ == "__main__":
    unittest.main()
