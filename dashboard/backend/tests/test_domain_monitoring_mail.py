from __future__ import annotations

import json
import unittest

from app.notifications import build_message, test_alert as sample_alert
from test_notifications import notification_configuration


class DomainMonitoringMailTests(unittest.TestCase):
    def test_first_report_and_reactivation_are_distinguished_in_all_formats(self):
        for reason, expected in (("never_observed", "First DMARC report is missing"),
                                 ("reactivated", "No new DMARC report after reactivation")):
            for language in ("de", "en"):
                with self.subTest(reason=reason, language=language):
                    alert = {**sample_alert(), "id": "expected-episode", "kind": "stale-reports",
                             "freshness_reason": reason, "report_time": None, "source_ip": None,
                             "monitoring_started_at": "2026-09-01T00:00:00+00:00",
                             "deadline": "2026-09-04T00:00:00+00:00", "grace_days": 3,
                             "monitoring_episode_id": "episode-1", "messages": 0, "total_messages": 0}
                    config = {**notification_configuration(), "language": language}
                    message = build_message(alert, config)
                    plain = message.get_body(preferencelist=("plain",)).get_content()
                    html = message.get_body(preferencelist=("html",)).get_content()
                    payload = json.loads(next(message.iter_attachments()).get_content())
                    if language == "en":
                        self.assertIn(expected, message["Subject"])
                        self.assertIn(expected, plain)
                        self.assertIn(expected, html)
                    for field in ("freshness_reason", "report_time", "monitoring_started_at", "monitoring_episode_id", "grace_days", "deadline"):
                        self.assertEqual(payload["alert"][field], alert[field])
                    self.assertIn(alert["deadline"], plain)
                    self.assertIn(alert["monitoring_started_at"], html)
                    self.assertNotIn("Report time: None", plain)
                    self.assertEqual(message["X-DMARC-Control-Event-Type"], "stale-reports")


if __name__ == "__main__":
    unittest.main()
