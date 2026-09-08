from __future__ import annotations

import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.notifications import build_message, test_alert as example_alert
from app.opensearch import OpenSearchError
from app.service import DashboardService
from app.store import StateStore
from test_alert_events import FixedClock, ReportClient, report
from test_notifications import notification_configuration


class AlertStatusCountTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        settings = Settings(database_path=Path(directory) / "state.db")
        self.store = StateStore(settings.database_path)
        self.store.save_alert_events([], bootstrap=True)
        reports = ReportClient([
            report(1, domain="a.example", source_ip="192.0.2.1", passed=False),
            report(1, domain="a.example", source_ip="192.0.2.2", passed=False),
            report(1, domain="b.example", source_ip="192.0.2.3", passed=False),
            report(50, domain="a.example", source_ip="192.0.2.4", passed=False),
        ])
        self.service = DashboardService(reports, self.store, settings)
        self.service.alerts = AsyncMock(wraps=self.service.alerts)
        self.enterContext(patch("app.alert_events.datetime", FixedClock))
        self.enterContext(patch.object(main, "store", self.store))
        self.enterContext(patch.object(main, "service", self.service))
        self.enterContext(patch.object(main, "notification_delivery_loop", new=AsyncMock()))
        self.send = self.enterContext(patch.object(main, "send_message"))
        self.http = self.enterContext(TestClient(main.app))
        session = main.create_read_session(self.store)
        self.http.cookies.set(main.READ_SESSION_COOKIE, session.token)
        statuses = {
            "192.0.2.1": "resolved", "192.0.2.2": "open",
            "192.0.2.3": "ignored", "192.0.2.4": "acknowledged",
        }
        seeded = self.http.get("/api/alerts?days=90")
        self.assertEqual(seeded.status_code, 200, seeded.text)
        self.assertEqual(len(seeded.json()["items"]), 4)
        for event in seeded.json()["items"]:
            self.store.set_alert_status(event["id"], statuses[event["source_ip"]])
        self.service.alerts.reset_mock()

    def test_counts_follow_domain_and_days_but_are_independent_of_selected_status(self):
        scopes = [
            ("*", 90, (4, 1, 1, 1, 1)),
            ("*", 30, (3, 1, 0, 1, 1)),
            ("a.example", 90, (3, 1, 1, 1, 0)),
            ("a.example", 30, (2, 1, 0, 1, 0)),
            ("b.example", 30, (1, 0, 0, 0, 1)),
        ]
        names = ("all", "open", "acknowledged", "resolved", "ignored")
        for domain, days, counts in scopes:
            expected = dict(zip(names, counts))
            for status in names:
                with self.subTest(domain=domain, days=days, status=status):
                    self.service.alerts.reset_mock()
                    response = self.http.get("/api/alerts", params={
                        "domain": domain, "days": days, "status": status,
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    payload = response.json()
                    self.assertEqual(payload["scope"], {"domain": domain, "days": days})
                    self.assertEqual(payload["status_counts"], expected)
                    self.assertEqual(len(payload["items"]), expected[status])
                    self.assertTrue(all("delivery" in item for item in payload["items"]))
                    if status != "all":
                        self.assertTrue(all(item["status"] == status for item in payload["items"]))
                    self.service.alerts.assert_awaited_once_with(domain, days)
        self.send.assert_not_called()

    def test_read_authentication_is_required_before_counts_are_evaluated(self):
        self.http.cookies.clear()
        response = self.http.get("/api/alerts?status=resolved")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("status_counts", response.json())
        self.service.alerts.assert_not_awaited()

    def test_evaluation_failure_remains_an_error_instead_of_zero_counts(self):
        self.service.alerts.side_effect = OpenSearchError("Incomplete event query")
        response = self.http.get("/api/alerts?domain=a.example&days=90&status=ignored")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Incomplete event query"})
        self.service.alerts.assert_awaited_once_with("a.example", 90)

    def test_successful_empty_scope_has_all_five_zero_counts(self):
        response = self.http.get("/api/alerts?domain=missing.example&status=open")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["status_counts"], {
            "all": 0, "open": 0, "acknowledged": 0, "resolved": 0, "ignored": 0,
        })
        self.service.alerts.assert_awaited_once_with("missing.example", 30)


class MailNavigationContextTests(unittest.TestCase):
    @staticmethod
    def message_payload(event, configuration):
        message = build_message(event, configuration)
        return message, json.loads(next(message.iter_attachments()).get_content())

    def assert_link_context(self, payload, *, domain, days, alert_id, source_ip):
        dashboard = parse_qs(urlsplit(payload["links"]["dashboard"]).query)
        self.assertEqual(dashboard, {
            "view": ["alerts"], "alert": [alert_id], "domain": [domain], "days": [str(days)],
        })
        host = parse_qs(urlsplit(payload["links"]["host"]).query)
        self.assertEqual(host, {
            "view": ["hosts"], "host": [source_ip], "from_alert": [alert_id],
            "domain": [domain], "days": [str(days)],
        })

    def test_de_and_en_mail_links_preserve_encoded_domain_context_and_historical_ids(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                event = {**example_alert(), "id": "legacy-7034669", "domain": "Bücher.example", "source_ip": "2001:db8::1"}
                configuration = {**notification_configuration(), "language": language, "lookback_days": 95}
                message, payload = self.message_payload(event, configuration)
                self.assertEqual(payload["schema"], "dmarc-control.alert.v1")
                self.assertEqual(message["X-DMARC-Control-Alert-ID"], event["id"])
                self.assert_link_context(payload, domain=event["domain"], days=95,
                                         alert_id=event["id"], source_ip=event["source_ip"])
                plain = message.get_body(preferencelist=("plain",)).get_content()
                html_body = message.get_body(preferencelist=("html",)).get_content()
                for link in payload["links"].values():
                    self.assertIn("domain=B%C3%BCcher.example", link)
                    self.assertIn(link, plain)
                    self.assertIn(html.escape(link), html_body)
                self.assertIn("Open alert" if language == "en" else "DMARC Control öffnen", plain)

    def test_days_are_bounded_integers_with_legacy_fallback(self):
        event = example_alert()
        for raw, expected in (
            (1, 1), (730, 730), (95, 95), ("90", 90), (" 365 ", 365),
            (None, 30), (0, 30), (-1, 30), (731, 30), (10**30, 30),
            (True, 30), (False, 30), (1.5, 30), (90.0, 30),
            ("invalid", 30), ("1.5", 30), ("0", 30), ("731", 30),
            ([], 30), ({}, 30),
        ):
            with self.subTest(raw=raw):
                configuration = {**notification_configuration(), "lookback_days": raw}
                _, payload = self.message_payload(event, configuration)
                self.assert_link_context(payload, domain=event["domain"], days=expected,
                                         alert_id=event["id"], source_ip=event["source_ip"])
        legacy_configuration = notification_configuration()
        legacy_configuration.pop("lookback_days")
        _, payload = self.message_payload(event, legacy_configuration)
        self.assertEqual(parse_qs(urlsplit(payload["links"]["dashboard"]).query)["days"], ["30"])

    def test_invalid_or_missing_domains_use_all_domains_without_url_injection(self):
        for raw, expected in (
            (None, "*"), ("", "*"), ("*", "*"), ("   ", "*"),
            ("  Example.COM  ", "Example.COM"), ("mail.example.", "mail.example."),
            ("mail.example..", "*"), ("example.com&days=730", "*"),
            ("https://example.com", "*"), ("user@example.com", "*"),
            ("example.com/path", "*"), ("example.com#alert=other", "*"),
            ("two domains.example", "*"), ("example.com\nInjected", "*"),
            ("a" * 64 + ".example", "*"), ("-mail.example", "*"),
            (".".join(["a" * 63] * 4), "*"), (123, "*"),
        ):
            with self.subTest(raw=raw):
                event = {**example_alert(), "domain": raw}
                _, payload = self.message_payload(event, notification_configuration())
                self.assert_link_context(payload, domain=expected, days=30,
                                         alert_id=event["id"], source_ip=event["source_ip"])
        legacy = example_alert()
        legacy.pop("domain")
        configuration = notification_configuration()
        configuration.pop("lookback_days")
        _, payload = self.message_payload(legacy, configuration)
        self.assert_link_context(payload, domain="*", days=30,
                                 alert_id=legacy["id"], source_ip=legacy["source_ip"])

    def test_missing_dashboard_or_source_keeps_existing_optional_links(self):
        configuration = {**notification_configuration(), "dashboard_url": ""}
        _, payload = self.message_payload(example_alert(), configuration)
        self.assertEqual(payload["links"], {"dashboard": None, "host": None})
        event = {**example_alert(), "source_ip": None}
        _, payload = self.message_payload(event, notification_configuration())
        self.assertIsNone(payload["links"]["host"])
        self.assertEqual(parse_qs(urlsplit(payload["links"]["dashboard"]).query)["domain"], [event["domain"]])


if __name__ == "__main__":
    unittest.main()
