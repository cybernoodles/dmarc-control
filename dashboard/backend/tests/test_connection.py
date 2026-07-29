from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.connection import (
    SecretVault,
    test_imap_connection,
    test_msgraph_connection,
)
from app.store import StateStore


class SecretVaultTests(unittest.TestCase):
    def test_credentials_are_encrypted_and_key_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "connection.key"
            vault = SecretVault(key_path)
            encrypted = vault.encrypt({"client_secret": "top-secret-value"})

            self.assertNotIn("top-secret-value", encrypted)
            self.assertEqual(
                SecretVault(key_path).decrypt(encrypted),
                {"client_secret": "top-secret-value"},
            )
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)


class ReadOnlyConnectionTests(unittest.TestCase):
    def test_graph_probe_only_posts_token_and_gets_folders(self) -> None:
        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {"access_token": "access-token"}
        inbox = MagicMock(status_code=200)
        inbox.json.return_value = {"id": "inbox-id", "displayName": "Inbox"}
        dmarc_children = MagicMock(status_code=200)
        dmarc_children.json.return_value = {
            "value": [{"id": "dmarc-id", "displayName": "DMARC"}]
        }
        processed_children = MagicMock(status_code=200)
        processed_children.json.return_value = {
            "value": [{"id": "processed-id", "displayName": "Processed"}]
        }
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = token_response
        client.get.side_effect = [
            inbox,
            dmarc_children,
            inbox,
            dmarc_children,
            processed_children,
        ]

        with patch("app.connection.httpx.Client", return_value=client):
            message = test_msgraph_connection(
                {
                    "tenant_id": "tenant-id",
                    "client_id": "client-id",
                    "mailbox": "dmarc@example.com",
                    "reports_folder": "Inbox/DMARC",
                    "archive_folder": "Inbox/DMARC/Processed",
                },
                {"client_secret": "top-secret"},
            )

        self.assertEqual(
            message,
            "Microsoft-365-Postfach und Ordner sind erreichbar.",
        )
        self.assertEqual(client.post.call_count, 1)
        self.assertEqual(client.get.call_count, 5)
        self.assertFalse(client.patch.called)
        self.assertFalse(client.put.called)
        self.assertFalse(client.delete.called)

    def test_imap_probe_selects_folders_read_only(self) -> None:
        connection = MagicMock()
        connection.login.return_value = ("OK", [])
        connection.select.return_value = ("OK", [b"0"])

        with patch(
            "app.connection.imaplib.IMAP4_SSL",
            return_value=connection,
        ):
            message = test_imap_connection(
                {
                    "host": "imap.example.com",
                    "port": 993,
                    "user": "dmarc@example.com",
                    "reports_folder": "INBOX",
                    "archive_folder": "Archive",
                },
                {"password": "top-secret"},
            )

        self.assertEqual(
            message,
            "IMAP-Postfach und Ordner sind erreichbar.",
        )
        self.assertEqual(
            connection.select.call_args_list,
            [
                call('"INBOX"', readonly=True),
                call('"Archive"', readonly=True),
            ],
        )
        self.assertFalse(connection.fetch.called)
        self.assertFalse(connection.store.called)
        self.assertFalse(connection.copy.called)
        connection.logout.assert_called_once()


class MailboxSettingsApiTests(unittest.TestCase):
    def test_draft_test_activation_and_parser_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test_settings = Settings(
                database_path=root / "dashboard.db",
                connection_key_path=root / "connection.key",
                parser_control_token_file=root / "control" / "control.token",
            )
            test_store = StateStore(test_settings.database_path)
            connection = {
                "provider": "msgraph",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "client_id": "22222222-2222-2222-2222-222222222222",
                "client_secret": "api-client-secret",
                "mailbox": "dmarc@example.com",
                "reports_folder": "Inbox/DMARC",
                "archive_folder": "Inbox/DMARC/Processed",
            }

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                patch.object(
                    main,
                    "test_mailbox_connection",
                    return_value=(
                        "Microsoft-365-Postfach und Ordner sind erreichbar."
                    ),
                ) as connection_test,
                TestClient(main.app) as client,
            ):
                unauthorized = client.get("/api/settings/mailbox")
                client.post(
                    "/api/auth/setup",
                    json={"password": "initial-admin-password"},
                )
                saved = client.put(
                    "/api/settings/mailbox",
                    json=connection,
                )
                tested = client.post("/api/settings/mailbox/test")
                activated = client.post("/api/settings/mailbox/activate")
                wrong_internal = client.get(
                    "/api/internal/parser/config",
                    headers={"X-Parser-Control-Token": "wrong"},
                )
                control_token = test_settings.parser_control_token_file.read_text(
                    encoding="utf-8"
                ).strip()
                internal = client.get(
                    "/api/internal/parser/config",
                    headers={"X-Parser-Control-Token": control_token},
                )
                status = client.post(
                    "/api/internal/parser/status",
                    headers={"X-Parser-Control-Token": control_token},
                    json={
                        "mode": "managed",
                        "state": "running",
                        "revision": 1,
                        "version": "10.4.0",
                        "message": None,
                        "pid": 123,
                    },
                )
                visible = client.get("/api/settings/mailbox")

            self.assertEqual(unauthorized.status_code, 401)
            self.assertEqual(saved.status_code, 200)
            self.assertNotIn("client_secret", str(saved.json()))
            self.assertEqual(tested.json()["test_status"], "success")
            self.assertEqual(activated.json()["active_revision"], 1)
            self.assertEqual(wrong_internal.status_code, 403)
            self.assertEqual(
                internal.json()["connection"]["client_secret"],
                "api-client-secret",
            )
            self.assertEqual(status.status_code, 200)
            self.assertEqual(visible.json()["parser"]["state"], "running")
            self.assertNotIn(
                b"api-client-secret",
                test_settings.database_path.read_bytes(),
            )
            connection_test.assert_called_once()


if __name__ == "__main__":
    unittest.main()
