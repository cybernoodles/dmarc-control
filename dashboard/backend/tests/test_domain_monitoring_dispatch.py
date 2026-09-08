from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.config import Settings
from app.domain_monitoring import domain_freshness_event
from app.notifications import RecipientDeliveryResult, test_alert as sample_alert
from app.store import StateStore
from test_notifications import notification_configuration


class DomainMonitoringDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_expectation_blocks_a_previously_evaluated_freshness_send(self):
        for change in ("retire", "reactivate", "extend_grace", "report_arrived"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                settings = Settings(database_path=Path(directory) / "state.db")
                state = StateStore(settings.database_path)
                item = state.add_domain_monitoring("expected.example", 1, now=datetime.now(UTC) - timedelta(days=5))
                event = domain_freshness_event(item)
                self.assertIsNotNone(event)
                alert = state.save_alert_events([event])[0]
                config = notification_configuration()

                async def evaluated(*_):
                    # The evaluation started earlier; an admin change or a
                    # discovery completed before the recipient claim.
                    if change in {"retire", "reactivate"}:
                        state.update_domain_monitoring(item["domain"], state="retired")
                    if change == "reactivate":
                        state.update_domain_monitoring(item["domain"], state="expected")
                    if change == "extend_grace":
                        state.update_domain_monitoring(item["domain"], grace_days=30)
                    if change == "report_arrived":
                        state.remember_domain_reports([{"domain": item["domain"], "last_report": datetime.now(UTC).isoformat()}])
                    return {"items": [alert], "counts": {"events": 1, "domains": 1, "hosts": 0}}

                with (patch.object(main, "settings", settings), patch.object(main, "store", state),
                      patch.object(state, "notification_settings", return_value={"settings": config}),
                      patch.object(main, "_resolved_notification_configuration", return_value=(config, {})),
                      patch.object(main.service, "alert_evaluation", new=AsyncMock(side_effect=evaluated)),
                      patch.object(main, "send_message") as send):
                    await main.dispatch_notification_cycle()
                send.assert_not_called()
                self.assertEqual(state.recipient_delivery_summary()["total"], 0)
                self.assertIsNotNone(state.stored_alert(alert["id"]))

    async def test_retired_domain_still_dispatches_real_dmarc_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=Path(directory) / "state.db")
            state = StateStore(settings.database_path)
            state.add_domain_monitoring("example.invalid", 3)
            state.update_domain_monitoring("example.invalid", state="retired")
            alert = {**sample_alert(), "kind": "new-host-fail", "status": "open"}
            config = notification_configuration()
            with (patch.object(main, "settings", settings), patch.object(main, "store", state),
                  patch.object(state, "notification_settings", return_value={"settings": config}),
                  patch.object(main, "_resolved_notification_configuration", return_value=(config, {})),
                  patch.object(main.service, "alert_evaluation", new=AsyncMock(return_value={
                      "items": [alert], "counts": {"events": 1, "domains": 1, "hosts": 1}})),
                  patch.object(main, "send_message", return_value=[
                      RecipientDeliveryResult(recipient, "accepted") for recipient in config["recipients"]
                  ]) as send):
                await main.dispatch_notification_cycle()
            send.assert_called_once()
            self.assertEqual(state.recipient_delivery_summary()["accepted"], 2)


if __name__ == "__main__":
    unittest.main()
