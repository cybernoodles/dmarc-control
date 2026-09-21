from __future__ import annotations

import json
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.notifications import (
    RecipientDeliveryResult,
    build_message,
    destination_hash,
    send_msgraph,
    send_smtp,
    test_alert as notification_test_alert,
)
from app.store import StateStore


def notification_configuration(transport: str = "smtp") -> dict:
    return {
        "enabled": True,
        "transport": transport,
        "recipients": ["soc@example.com", "security@example.com"],
        "sender": "dmarc-alerts@example.com",
        "language": "en",
        "dashboard_url": "https://dmarc.example.com",
        "cases": ["new-host-fail", "stale-reports"],
        "lookback_days": 30,
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "username": "dmarc-alerts@example.com",
        },
        "graph": {
            "reuse_mailbox_connection": False,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "client_id": "22222222-2222-2222-2222-222222222222",
        },
    }


class NotificationMessageTests(unittest.TestCase):
    def test_message_contains_html_plain_text_headers_and_json(self) -> None:
        configuration = notification_configuration()
        message = build_message(
            notification_test_alert(),
            configuration,
            test=True,
        )
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())

        self.assertEqual(
            parsed["X-DMARC-Control-Schema"],
            "dmarc-control.alert.v1",
        )
        self.assertEqual(parsed["X-DMARC-Control-Event-Type"], "test")
        self.assertEqual(parsed["Auto-Submitted"], "auto-generated")
        self.assertIn("text/plain", [part.get_content_type() for part in parsed.walk()])
        self.assertIn("text/html", [part.get_content_type() for part in parsed.walk()])
        attachment = next(parsed.iter_attachments())
        self.assertEqual(attachment.get_filename(), "dmarc-alert.json")
        payload = json.loads(attachment.get_content())
        self.assertEqual(payload["schema"], "dmarc-control.alert.v1")
        self.assertTrue(payload["test"])
        self.assertEqual(payload["alert"]["event_type"], "test")
        self.assertIn("view=alerts", payload["links"]["dashboard"])
        self.assertIn(f"alert={payload['alert']['id']}", payload["links"]["dashboard"])
        self.assertIn("view=hosts", payload["links"]["host"])
        self.assertIn("host=192.0.2.1", payload["links"]["host"])
        self.assertIn(
            f"from_alert={payload['alert']['id']}",
            payload["links"]["host"],
        )

    def test_destination_changes_when_recipients_change(self) -> None:
        first = notification_configuration()
        second = notification_configuration()
        second["recipients"] = ["another@example.com"]

        self.assertNotEqual(destination_hash(first), destination_hash(second))


class NotificationTransportTests(unittest.TestCase):
    @patch("app.notifications.smtplib.SMTP")
    def test_smtp_uses_starttls_authentication_and_message(
        self,
        smtp_class: MagicMock,
    ) -> None:
        connection = smtp_class.return_value
        connection.send_message.return_value = {}
        message = build_message(
            notification_test_alert(),
            notification_configuration(),
            test=True,
        )

        send_smtp(
            message,
            notification_configuration(),
            {"smtp_password": "smtp-secret"},
        )

        smtp_class.assert_called_once_with(
            host="smtp.example.com",
            port=587,
            timeout=20,
        )
        connection.starttls.assert_called_once()
        connection.login.assert_called_once_with(
            "dmarc-alerts@example.com",
            "smtp-secret",
        )
        connection.send_message.assert_called_once_with(
            message, from_addr="dmarc-alerts@example.com",
            to_addrs=["soc@example.com", "security@example.com"],
        )

    @patch("app.notifications.httpx.Client")
    def test_graph_posts_the_shared_mime_message(
        self,
        client_class: MagicMock,
    ) -> None:
        client = client_class.return_value.__enter__.return_value
        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {"access_token": "access-token"}
        send_response = MagicMock(status_code=202)
        client.post.side_effect = [token_response, send_response]
        configuration = notification_configuration("msgraph")
        message = build_message(
            notification_test_alert(),
            configuration,
            test=True,
        )

        send_msgraph(
            message,
            configuration,
            {"graph_client_secret": "graph-secret"},
        )

        self.assertEqual(client.post.call_count, 2)
        send_call = client.post.call_args_list[1]
        self.assertIn(
            "/users/dmarc-alerts%40example.com/sendMail",
            send_call.args[0],
        )
        self.assertEqual(
            send_call.kwargs["headers"]["Content-Type"],
            "text/plain",
        )
        self.assertNotIn(b"graph-secret", send_call.kwargs["content"])


class NotificationSettingsApiTests(unittest.TestCase):
    def test_read_user_sees_notification_status_without_sensitive_settings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
                connection_key_path=Path(directory) / "connection.key",
            )
            test_store = StateStore(test_settings.database_path)
            payload = notification_configuration()
            payload["smtp"]["password"] = "smtp-secret"

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                patch.object(
                    main,
                    "dispatch_notification_cycle",
                    new_callable=AsyncMock,
                ),
                TestClient(main.app) as client,
            ):
                client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "initial-admin-password",
                        "read_username": "dmarc-reader",
                        "read_password": "initial-read-password",
                        "backup_mode": "external",
                    },
                )
                saved = client.put(
                    "/api/settings/notifications",
                    json=payload,
                )
                client.post("/api/auth/logout")

                status = client.get("/api/settings/notifications/status")
                protected = client.get("/api/settings/notifications")

                client.post("/api/auth/read-logout")
                unauthenticated = client.get(
                    "/api/settings/notifications/status"
                )

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(
                status.json(),
                {"configured": True, "enabled": True},
            )
            self.assertEqual(protected.status_code, 401)
            self.assertEqual(
                protected.json(),
                {"detail": "Admin login required"},
            )
            self.assertEqual(unauthenticated.status_code, 401)
            self.assertEqual(
                unauthenticated.json(),
                {"detail": "Operator login required"},
            )

    def test_admin_can_save_masked_settings_and_send_explicit_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_settings = Settings(
                database_path=Path(directory) / "dashboard.db",
                connection_key_path=Path(directory) / "connection.key",
            )
            test_store = StateStore(test_settings.database_path)
            payload = {
                "enabled": False,
                "transport": "smtp",
                "recipients": ["soc@example.com"],
                "sender": "dmarc-alerts@example.com",
                "language": "de",
                "dashboard_url": "https://dmarc.example.com",
                "cases": ["new-host-fail", "dynamic-ip-fail"],
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "security": "starttls",
                    "username": "dmarc-alerts@example.com",
                    "password": "smtp-secret",
                },
                "graph": {
                    "reuse_mailbox_connection": True,
                    "tenant_id": "",
                    "client_id": "",
                },
            }

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                patch.object(main, "send_message", return_value=[
                    RecipientDeliveryResult("soc@example.com", "accepted"),
                ]) as mocked_send,
                TestClient(main.app) as client,
            ):
                client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "initial-admin-password",
                        "read_username": "dmarc-reader",
                        "read_password": "initial-read-password",
                        "backup_mode": "external",
                    },
                )
                initial = client.get("/api/settings/notifications")
                saved = client.put(
                    "/api/settings/notifications",
                    json=payload,
                )
                tested = client.post("/api/settings/notifications/test")

            self.assertEqual(initial.status_code, 200)
            self.assertFalse(initial.json()["configured"])
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json()["smtp"]["password_configured"])
            self.assertNotIn("password", saved.json()["smtp"])
            stored = test_store.notification_settings()
            self.assertIsNotNone(stored)
            self.assertNotIn(
                "smtp-secret",
                str(stored["secret_ciphertext"]),
            )
            self.assertEqual(tested.status_code, 200)
            self.assertEqual(tested.json()["test_status"], "success")
            mocked_send.assert_called_once()

    def test_delivery_claim_is_persistent_and_retry_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "dashboard.db")
            claimed = store.claim_notification_delivery(
                alert_id="alert-1",
                destination_hash="target-1",
            )
            duplicate = store.claim_notification_delivery(
                alert_id="alert-1",
                destination_hash="target-1",
            )
            store.finish_notification_delivery(
                alert_id="alert-1",
                destination_hash="target-1",
                success=True,
            )
            after_success = store.claim_notification_delivery(
                alert_id="alert-1",
                destination_hash="target-1",
            )

            self.assertTrue(claimed)
            self.assertFalse(duplicate)
            self.assertFalse(after_success)
            self.assertEqual(store.notification_delivery_summary()["sent"], 1)


if __name__ == "__main__":
    unittest.main()
