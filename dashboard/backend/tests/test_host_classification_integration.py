from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.notifications import RecipientDeliveryResult, build_message
from app.service import DashboardService
from app.store import StateStore
from test_alert_events import FixedClock, ReportClient, report
from test_host_pagination import CompositeClient, host_bucket
from test_notifications import notification_configuration


SOURCE_IP = "192.0.2.1"
CLASSIFICATION_URL = f"/api/hosts/{SOURCE_IP}/classification"


def provider_source(name: str = "Microsoft 365") -> dict[str, Any]:
    domain = "outbound.protection.outlook.com" if name == "Microsoft 365" else "smtp2go.com"
    return {
        "source_type": "saas",
        "source_name": name,
        "source_reverse_dns": f"mail.{domain}",
        # A provider SPF pass is independent of the From-domain alignment.
        "spf_results": [{"domain": domain, "result": "pass"}],
    }


class ClassificationClient:
    """Use both existing OpenSearch fixtures, including top-hit projection."""

    def __init__(self) -> None:
        self.hosts = CompositeClient([])
        self.events = ReportClient([])
        self.replace_provider("Microsoft 365")

    def replace_provider(self, name: str) -> None:
        source = provider_source(name)
        self.hosts.buckets = [host_bucket(
            SOURCE_IP, 4, failed=4, spf_not_aligned=4, dkim_not_aligned=4,
            source=source,
        )]
        self.events.reports = [report(60), {**report(1, messages=4, passed=False), **source}]

    async def search(self, index, body, *, allow_missing=False):
        fixture = self.hosts if "hosts" in body["aggs"] else self.events
        result = copy.deepcopy(await fixture.search(index, body, allow_missing=allow_missing))

        def project(aggregation, response):
            for name, definition in aggregation.get("aggs", {}).items():
                if name not in response:
                    continue
                actual = response[name]
                if "top_hits" in definition:
                    fields = definition["top_hits"]["_source"]["includes"]
                    for hit in actual["hits"]["hits"]:
                        hit["_source"] = {key: value for key, value in hit["_source"].items() if key in fields}
                elif "buckets" in actual:
                    for bucket in actual["buckets"]:
                        project(definition, bucket)
                else:
                    project(definition, actual)

        project(body, result["aggregations"])
        return result


class HostClassificationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = Settings(database_path=Path(directory) / "state.db")
        self.store = StateStore(self.settings.database_path)
        self.search = ClassificationClient()
        self.service = DashboardService(self.search, self.store, self.settings)
        # This models an already migrated installation; each evaluated failure
        # is eligible and exercises the real recipient-deduplication path.
        self.store.save_alert_events([], bootstrap=True)
        self.enterContext(patch("app.alert_events.datetime", FixedClock))
        self.enterContext(patch.object(main, "store", self.store))
        self.enterContext(patch.object(main, "service", self.service))
        self.enterContext(patch.object(main, "notification_delivery_loop", new=AsyncMock()))
        self.send = self.enterContext(patch.object(
            main, "send_message", side_effect=lambda message, configuration, secret: [
                RecipientDeliveryResult(recipient, "accepted")
                for recipient in configuration["recipients"]
            ],
        ))
        self.http = self.enterContext(TestClient(main.app))
        # Exercise the actual cookie/session middleware without password hashing
        # or mocking its authentication decision.
        session = main.create_read_session(self.store)
        self.http.cookies.set(main.READ_SESSION_COOKIE, session.token)

    def patch_classification(self, changes):
        result = self.http.patch(CLASSIFICATION_URL, json=changes)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def host(self):
        result = self.http.get(f"/api/hosts/{SOURCE_IP}?days=30")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def alert(self):
        result = self.http.get("/api/alerts?days=30")
        self.assertEqual(result.status_code, 200, result.text)
        events = [item for item in result.json()["items"] if item["priority"] == "critical"]
        self.assertEqual(len(events), 1)
        return events[0]

    def test_patch_requires_valid_read_session_and_never_mutates_when_unauthenticated(self):
        self.http.cookies.clear()
        for token in (None, "invalid-session-token"):
            with self.subTest(token=token):
                if token:
                    self.http.cookies.set(main.READ_SESSION_COOKIE, token)
                response = self.http.patch(CLASSIFICATION_URL, json={"notes": "Untrusted edit"})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.store.host_overrides(), {})
        self.send.assert_not_called()

    def test_partial_patch_preserves_omitted_fields_and_accepts_explicit_note_clear(self):
        first = self.patch_classification({"notes": "Monitoring owner"})
        self.assertEqual(first["classification_mode"], "automatic")
        self.assertIsNone(first["manual_service_name"])
        self.assertIsNone(first["service_name"])
        self.assertEqual(first["trust_status"], "automatic")
        manual = self.patch_classification({
            "classification_mode": "manual", "manual_service_name": "Internal relay",
            "trust_status": "confirmed",
        })
        self.assertEqual(manual["notes"], first["notes"])
        renamed = self.patch_classification({"manual_service_name": "Renamed relay"})
        self.assertEqual(renamed["trust_status"], "confirmed")
        self.assertEqual(renamed["notes"], first["notes"])
        cleared = self.patch_classification({"notes": None})
        self.assertIsNone(cleared["notes"])
        self.assertEqual(cleared["manual_service_name"], "Renamed relay")
        self.assertEqual(cleared["classification_mode"], "manual")
        self.assertEqual(cleared["trust_status"], "confirmed")

    def test_invalid_patch_is_422_and_atomic(self):
        self.patch_classification({
            "classification_mode": "manual", "manual_service_name": "Keep this name",
            "trust_status": "confirmed", "notes": "Keep this note",
        })
        before = self.store.host_overrides()
        invalid = [
            {"classification_mode": None}, {"trust_status": None},
            {"classification_mode": "legacy_preserved"},
            {"service_name": "Wrong field"}, {"unknown_field": True},
            {"manual_service_name": None}, {"manual_service_name": "  "},
            {"manual_service_name": "x" * 121}, {"notes": "x" * 501},
            {"classification_mode": "automatic", "manual_service_name": "Contradiction"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.http.patch(CLASSIFICATION_URL, json={"notes": "Must not leak through", **payload})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.store.host_overrides(), before)

    def test_note_only_keeps_service_and_alert_detection_dynamic(self):
        self.assertEqual(self.host()["service_detection"]["service"], "Microsoft 365")
        original_event = self.alert()
        self.patch_classification({"notes": "Keep observing this IP"})
        self.search.replace_provider("SMTP2GO")
        host = self.host()
        event = self.alert()
        self.assertEqual(host["service_detection"]["service"], "SMTP2GO")
        self.assertEqual(event["service"], "SMTP2GO")
        self.assertEqual(event["id"], original_event["id"])
        self.assertEqual(host["service_detection"]["classification_mode"], "automatic")
        self.assertFalse(host["service_detection"]["manual_override"])
        self.assertIsNone(host["override"]["manual_service_name"])
        self.assertEqual(host["override"]["notes"], "Keep observing this IP")
        self.assertEqual(host["service_detection"]["automatic_detection"], event["automatic_detection"])
        self.assertEqual(host["service_detection"]["confidence"], event["service_confidence"])
        self.assertEqual(host["service_detection"]["evidence_details"], event["service_evidence_details"])
        # Strong provider hints and a saved note do not turn failures healthy.
        self.assertGreaterEqual(event["service_confidence"], .80)
        self.assertEqual((host["risk"], host["dmarc_fail"], event["priority"]), ("critical", 4, "critical"))

    def test_manual_name_has_no_borrowed_confidence_and_automatic_alternative_still_updates(self):
        self.patch_classification({
            "classification_mode": "manual", "manual_service_name": "Internal relay",
            "trust_status": "confirmed", "notes": "Preserve on reset",
        })
        for name in ("Microsoft 365", "SMTP2GO"):
            with self.subTest(automatic_service=name):
                self.search.replace_provider(name)
                host, event = self.host(), self.alert()
                detection = host["service_detection"]
                self.assertEqual(detection["service"], "Internal relay")
                self.assertEqual(event["service"], "Internal relay")
                self.assertIsNone(detection["confidence"])
                self.assertIsNone(event["service_confidence"])
                self.assertEqual(detection["evidence"], [])
                self.assertEqual(detection["evidence_details"], [])
                self.assertEqual(event["service_evidence"], [])
                self.assertEqual(event["service_evidence_details"], [])
                self.assertEqual(event["automatic_detection"]["service"], name)
                self.assertGreaterEqual(event["automatic_detection"]["confidence"], .80)
                self.assertTrue(event["automatic_detection"]["evidence_details"])
                self.assertEqual(detection["automatic_detection"], event["automatic_detection"])
                self.assertEqual(host["trust_status"], "confirmed")
                self.assertEqual(host["risk"], "critical")
        restored = self.patch_classification({"classification_mode": "automatic"})
        self.assertIsNone(restored["manual_service_name"])
        self.assertIsNone(restored["service_name"])
        self.assertEqual(restored["trust_status"], "automatic")
        self.assertEqual(restored["notes"], "Preserve on reset")
        self.assertEqual(self.host()["service_detection"]["service"], "SMTP2GO")
        self.patch_classification({"classification_mode": "manual", "manual_service_name": "Manual again"})
        explicit = self.patch_classification({"classification_mode": "automatic", "trust_status": "ignored"})
        self.assertEqual(explicit["trust_status"], "ignored")
        self.assertEqual(self.host()["trust_status"], "ignored")

    def test_mode_switch_preserves_event_workflow_and_recipient_history_without_resending(self):
        configuration = notification_configuration()
        configuration["cases"] = ["host-degradation", "host-fail", "new-host-fail"]
        self.store.save_notification_settings(settings=configuration, secret_ciphertext="unused")
        with patch.object(main, "_resolved_notification_configuration", return_value=(configuration, {})):
            self.http.portal.call(main.dispatch_notification_cycle)
            original = self.alert()
            self.assertEqual(self.send.call_count, 1)
            history = self.store.recipient_delivery_summary()
            self.assertEqual(history["accepted"], 2)
            changed = self.http.patch(f"/api/alerts/{original['id']}", json={"status": "resolved"})
            self.assertEqual(changed.status_code, 200)
            for changes in (
                {"notes": "Only documentation"},
                {"classification_mode": "manual", "manual_service_name": "Internal relay"},
                {"classification_mode": "automatic"},
            ):
                with self.subTest(changes=changes):
                    self.patch_classification(changes)
                    current = self.alert()
                    self.assertEqual(current["id"], original["id"])
                    self.assertEqual(current["kind"], original["kind"])
                    self.assertEqual(current["status"], "resolved")
                    self.assertEqual(current["notification_eligible"], original["notification_eligible"])
                    self.assertEqual(current["delivery"]["accepted"], 2)
                    self.assertEqual(self.store.recipient_delivery_summary(), history)
                    self.http.portal.call(main.dispatch_notification_cycle)
            # Reopening is also unable to send the already accepted recipients
            # again, even after all classification changes and a store restart.
            response = self.http.patch(f"/api/alerts/{original['id']}", json={"status": "open"})
            self.assertEqual(response.status_code, 200)
            restarted = StateStore(self.settings.database_path)
            self.assertEqual(restarted.recipient_delivery_summary(), history)
            self.assertEqual(restarted.claim_notification_recipients(
                alert_id=original["id"], configuration=configuration,
            ), [])
            self.http.portal.call(main.dispatch_notification_cycle)
        self.assertEqual(self.send.call_count, 1)

    def test_legacy_put_and_delete_remain_compatible_with_explicit_mode(self):
        result = self.http.put(CLASSIFICATION_URL, json={
            "service_name": "Existing label", "trust_status": "confirmed", "notes": "Existing note",
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["classification_mode"], "legacy_preserved")
        updated = self.patch_classification({"notes": "Updated note"})
        self.assertEqual(updated["classification_mode"], "legacy_preserved")
        self.assertEqual(updated["manual_service_name"], "Existing label")
        self.assertEqual(self.alert()["classification_mode"], "legacy_preserved")
        manual = self.patch_classification({"classification_mode": "manual"})
        self.assertEqual(manual["manual_service_name"], "Existing label")
        deleted = self.http.delete(CLASSIFICATION_URL)
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["override_removed"])
        self.assertEqual(self.store.host_overrides(), {})
        self.assertEqual(self.host()["service_detection"]["service"], "Microsoft 365")

    def test_manual_mail_classification_is_separate_translated_and_html_escaped(self):
        name = "<script>Manual</script>"
        self.patch_classification({"classification_mode": "manual", "manual_service_name": name})
        event = self.alert()
        for language, mode_label, alternative_label in (
            ("de", "Zuordnung: Manuell", "Automatische Alternative: Microsoft 365"),
            ("en", "Assignment: Manual", "Automatic alternative: Microsoft 365"),
        ):
            with self.subTest(language=language):
                configuration = {**notification_configuration(), "language": language}
                message = build_message(event, configuration)
                payload = json.loads(next(message.iter_attachments()).get_content())
                classification = payload["classification"]
                self.assertEqual(payload["schema"], "dmarc-control.alert.v1")
                self.assertEqual(payload["alert"]["id"], event["id"])
                self.assertEqual(classification["mode"], "manual")
                self.assertEqual(classification["service"], name)
                self.assertIsNone(classification["confidence"])
                self.assertEqual(classification["evidence"], [])
                self.assertEqual(classification["evidence_details"], [])
                self.assertEqual(classification["automatic_detection"], event["automatic_detection"])
                plain = message.get_body(preferencelist=("plain",)).get_content()
                html = message.get_body(preferencelist=("html",)).get_content()
                self.assertIn(mode_label, plain)
                self.assertIn(alternative_label, plain)
                self.assertIn(name, plain)
                self.assertNotIn(name, html)
                self.assertIn("&lt;script&gt;Manual&lt;/script&gt;", html)
                self.assertIn(alternative_label.split(": ")[0], html)
                self.assertIn("Microsoft 365", html)
        self.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
