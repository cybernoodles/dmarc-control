from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.notifications import RecipientDeliveryResult, test_alert
from app.store import StateStore


class AlertApiTests(unittest.TestCase):
    def test_host_page_query_and_historical_alias_are_read_authenticated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.db")
            event = {**test_alert(), "id": "event-1", "kind": "host-fail"}
            state.set_alert_status("legacy-1", "resolved")
            state.save_alert_events([event], bootstrap=True, aliases={"legacy-1": "event-1"})
            service = SimpleNamespace(hosts_page=AsyncMock(return_value={"items": [], "total": 201, "limit": 100, "offset": 100}), alerts=AsyncMock(return_value=[]))
            with patch.object(main, "store", state), patch.object(main, "service", service), TestClient(main.app) as client:
                self.assertEqual(client.get("/api/alerts/legacy-1").status_code, 401)
                with patch.object(main, "is_read_authenticated", return_value=True):
                    page = client.get("/api/hosts?risk=critical&domain=example.com&days=90&limit=100&offset=100&search=mail")
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.json()["total"], 201)
                    service.hosts_page.assert_awaited_once_with("example.com", 90, risk="critical", limit=100, offset=100, search="mail")
                    detail = client.get("/api/alerts/legacy-1")
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.json()["id"], "event-1")
                    self.assertEqual(detail.json()["status"], "resolved")
                    self.assertTrue(detail.json()["historical"])
                    updated = client.patch("/api/alerts/legacy-1", json={"status": "acknowledged"})
                    self.assertEqual(updated.json()["alert_id"], "event-1")
                    self.assertEqual(client.get("/api/alerts/event-1").json()["status"], "acknowledged")
                    self.assertEqual(client.get("/api/alerts/missing").status_code, 404)


class EventNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_does_not_mail_but_new_events_send_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.db")
            baseline = {**test_alert(), "id": "baseline", "kind": "host-fail"}
            new = {**baseline, "id": "new-report-day"}
            state.save_alert_events([baseline], bootstrap=True)
            events = state.save_alert_events([baseline, new])
            configuration = {"enabled": True, "transport": "smtp", "sender": "alerts@example.invalid",
                             "recipients": ["admin@example.invalid"], "language": "de", "dashboard_url": "",
                             "cases": ["host-fail"], "lookback_days": 30}
            state.save_notification_settings(settings=configuration, secret_ciphertext="unused")
            service = SimpleNamespace(alert_evaluation=AsyncMock(return_value={
                "items": events, "counts": {"events": len(events), "domains": 1, "hosts": 1},
            }))
            with patch.object(main, "store", state), patch.object(main, "service", service), patch.object(main, "_resolved_notification_configuration", return_value=(configuration, {})), patch.object(main, "send_message", return_value=[RecipientDeliveryResult("admin@example.invalid", "accepted")]) as send:
                await main.dispatch_notification_cycle()
                await main.dispatch_notification_cycle()
            self.assertEqual(send.call_count, 1)
            self.assertEqual(state.recipient_delivery_summary()["accepted"], 1)
            self.assertEqual(send.call_args.args[0]["X-DMARC-Control-Alert-ID"], "new-report-day")


if __name__ == "__main__":
    unittest.main()
