from __future__ import annotations

import base64
import json
import smtplib
import ssl
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, patch

import httpx

from app.notifications import (
    NotificationDeliveryError,
    RecipientDeliveryResult,
    build_message,
    require_all_accepted,
    send_message,
    send_msgraph,
    send_smtp,
    test_alert as make_test_alert,
)


SMTP_IMPLEMENTATION = smtplib.SMTP


def configuration(transport="smtp"):
    return {
        "transport": transport,
        "sender": "sender@example.invalid",
        "recipients": ["one@example.invalid", "two@example.invalid"],
        "language": "en",
        "smtp": {"host": "smtp.invalid", "port": 25, "security": "plain", "username": ""},
        "graph": {"tenant_id": "tenant", "client_id": "client"},
    }


class SmtpRecipientResultTests(unittest.TestCase):
    def setUp(self):
        self.settings = configuration()
        self.message = build_message(make_test_alert(), self.settings)
        self.secret = {"smtp_password": "sensitive-password"}
        patched = patch("app.notifications.smtplib.SMTP")
        self.smtp_class = patched.start()
        self.addCleanup(patched.stop)
        self.smtp = self.smtp_class.return_value
        self.smtp.send_message.return_value = {}

    def test_success_records_each_requested_recipient_and_explicit_envelope(self):
        results = send_message(self.message, self.settings, self.secret)
        self.assertEqual(results, [RecipientDeliveryResult(recipient, "accepted") for recipient in self.settings["recipients"]])
        self.smtp.send_message.assert_called_once_with(
            self.message, from_addr=self.settings["sender"], to_addrs=self.settings["recipients"]
        )

    def test_partial_rejections_keep_acceptance_and_distinguish_4xx_from_5xx(self):
        self.settings["recipients"].append("three@example.invalid")
        self.smtp.send_message.return_value = {
            "two@example.invalid": (450, b"retry sensitive-password\r\nlater"),
            "three@example.invalid": (550, b"recipient does not exist"),
        }
        results = send_smtp(self.message, self.settings, self.secret)
        self.assertEqual([r.status for r in results], ["accepted", "temporary_failure", "permanent_failure"])
        self.assertEqual([r.smtp_code for r in results], [None, 450, 550])
        self.assertIn("[redacted]", results[1].error)
        self.assertNotIn("sensitive-password", str(results))
        self.assertNotIn("\n", results[1].error)

    def test_complete_rejection_is_reported_per_recipient(self):
        self.smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused({
            "one@example.invalid": (451, b"try later"),
            "two@example.invalid": (550, b"not found"),
        })
        results = send_smtp(self.message, self.settings, self.secret)
        self.assertEqual([r.status for r in results], ["temporary_failure", "permanent_failure"])
        self.assertEqual([r.smtp_code for r in results], [451, 550])

    def test_full_rejection_never_invents_acceptance_for_missing_response(self):
        self.smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused({
            "one@example.invalid": (550, b"not found"),
        })
        self.assertEqual(
            [r.status for r in send_smtp(self.message, self.settings, self.secret)],
            ["permanent_failure", "temporary_failure"],
        )

    def test_retry_envelope_excludes_previously_accepted_message_recipients(self):
        self.message["Cc"] = "never-retry@example.invalid"
        settings = {**self.settings, "recipients": ["two@example.invalid"]}
        results = send_smtp(self.message, settings, self.secret)
        self.assertEqual(results, [RecipientDeliveryResult("two@example.invalid", "accepted")])
        self.assertEqual(self.smtp.send_message.call_args.kwargs["to_addrs"], ["two@example.invalid"])

    def test_data_and_authentication_responses_preserve_smtp_classification(self):
        for exception, expected in (
            (smtplib.SMTPDataError(451, b"temporary queue failure"), "temporary_failure"),
            (smtplib.SMTPDataError(550, b"message rejected"), "permanent_failure"),
            (smtplib.SMTPAuthenticationError(535, b"bad sensitive-password"), "permanent_failure"),
        ):
            with self.subTest(exception=exception):
                self.smtp.send_message.side_effect = exception
                results = send_smtp(self.message, self.settings, self.secret)
                self.assertEqual([r.status for r in results], [expected, expected])
                self.assertTrue(all(r.smtp_code == exception.smtp_code for r in results))
                self.assertNotIn("sensitive-password", str(results))

    def test_network_errors_are_temporary_and_certificate_errors_permanent(self):
        for exception, expected in (
            (OSError("unavailable sensitive-password"), "temporary_failure"),
            (smtplib.SMTPServerDisconnected("connection lost"), "temporary_failure"),
            (ssl.SSLCertVerificationError("untrusted certificate"), "permanent_failure"),
        ):
            with self.subTest(exception=exception):
                self.smtp_class.side_effect = exception
                results = send_smtp(self.message, self.settings, self.secret)
                self.assertEqual([r.status for r in results], [expected, expected])
                self.assertNotIn("sensitive-password", str(results))

    def test_quit_failure_does_not_undo_successful_acceptance(self):
        self.smtp.quit.side_effect = smtplib.SMTPServerDisconnected("already closed")
        self.assertTrue(all(r.status == "accepted" for r in send_smtp(self.message, self.settings, self.secret)))
        self.smtp.close.assert_called_once()

    def test_real_send_message_preserves_rcpt_rejections_when_data_fails(self):
        for rcpt_code, data_code, expected in (
            (450, 550, ["temporary_failure", "permanent_failure"]),
            (550, 450, ["permanent_failure", "temporary_failure"]),
        ):
            with self.subTest(rcpt_code=rcpt_code, data_code=data_code):
                # The real stdlib implementation executes MAIL/RCPT/DATA here;
                # only the protocol responses are simulated, without a socket.
                connection = SMTP_IMPLEMENTATION()
                connection.ehlo = MagicMock(return_value=(250, b"hello"))
                connection.mail = MagicMock(return_value=(250, b"ok"))
                rcpt = MagicMock(side_effect=[(rcpt_code, b"recipient rejected"), (250, b"ok")])
                connection.rcpt = rcpt
                connection.data = MagicMock(side_effect=smtplib.SMTPDataError(data_code, b"message rejected"))
                connection.rset = MagicMock(return_value=(250, b"reset"))
                connection.quit = MagicMock()
                self.smtp_class.return_value = connection

                results = send_smtp(self.message, self.settings, self.secret)

                self.assertEqual([r.status for r in results], expected)
                self.assertEqual([r.smtp_code for r in results], [rcpt_code, data_code])
                self.assertEqual(rcpt.call_count, 2)
                connection.data.assert_called_once()
                self.assertIs(connection.rcpt, rcpt)


class GraphRecipientResultTests(unittest.TestCase):
    def setUp(self):
        self.settings = configuration("msgraph")
        self.message = build_message(make_test_alert(), self.settings)
        self.secret = {"graph_client_secret": "sensitive-secret"}
        patched = patch("app.notifications.httpx.Client")
        self.client_class = patched.start()
        self.addCleanup(patched.stop)
        self.client = self.client_class.return_value.__enter__.return_value

    def responses(self, status=202):
        token = MagicMock(status_code=200)
        token.json.return_value = {"access_token": "sensitive-token"}
        sent = MagicMock(status_code=status, text="sensitive-secret sensitive-token")
        sent.json.return_value = {"error": {"message": sent.text}}
        self.client.post.side_effect = [token, sent]

    def test_graph_retry_restricts_mime_addresses_without_changing_original_message(self):
        self.responses()
        self.message["Cc"] = "cc@example.invalid"
        self.message["Bcc"] = "bcc@example.invalid"
        self.message["Resent-To"] = "resent@example.invalid"
        settings = {**self.settings, "recipients": ["two@example.invalid"]}
        results = send_msgraph(self.message, settings, self.secret)
        self.assertEqual(results, [RecipientDeliveryResult("two@example.invalid", "accepted")])
        encoded = self.client.post.call_args.kwargs["content"]
        sent = BytesParser(policy=policy.default).parsebytes(base64.b64decode(encoded))
        self.assertEqual(str(sent["To"]), "two@example.invalid")
        self.assertIsNone(sent["Cc"])
        self.assertIsNone(sent["Bcc"])
        self.assertIsNone(sent["Resent-To"])
        self.assertIn("one@example.invalid", str(self.message["To"]))
        self.assertEqual(self.message["Cc"], "cc@example.invalid")

    def test_graph_responses_classify_all_requested_recipients_and_redact_secrets(self):
        for status, expected in (
            (400, "permanent_failure"), (403, "permanent_failure"),
            (302, "permanent_failure"), (408, "temporary_failure"),
            (429, "temporary_failure"), (503, "temporary_failure"),
        ):
            with self.subTest(status=status):
                self.responses(status)
                results = send_msgraph(self.message, self.settings, self.secret)
                self.assertEqual([r.status for r in results], [expected, expected])
                self.assertNotIn("sensitive-secret", str(results))
                self.assertNotIn("sensitive-token", str(results))
                self.assertTrue(all(r.smtp_code is None for r in results))

    def test_token_error_returns_failure_without_attempting_sendmail(self):
        for status, expected in ((400, "permanent_failure"), (429, "temporary_failure")):
            with self.subTest(status=status):
                self.client.post.reset_mock()
                self.client.post.side_effect = [MagicMock(status_code=status)]
                results = send_msgraph(self.message, self.settings, self.secret)
                self.assertEqual([r.status for r in results], [expected, expected])
                self.assertEqual(self.client.post.call_count, 1)

    def test_network_and_invalid_token_response_fail_without_secret_disclosure(self):
        invalid = MagicMock(status_code=200)
        invalid.json.side_effect = ValueError("invalid sensitive-secret response")
        for response in (httpx.ConnectError("sensitive-secret unavailable"), invalid):
            with self.subTest(response=type(response).__name__):
                self.client.post.side_effect = [response]
                results = send_msgraph(self.message, self.settings, self.secret)
                self.assertTrue(all(r.status == "temporary_failure" for r in results))
                self.assertNotIn("sensitive-secret", str(results))


class MessageVolumeAndExplicitTestTests(unittest.TestCase):
    def test_all_message_representations_share_affected_and_total_counts(self):
        alert = make_test_alert()
        alert.update(kind="compensated-alignment", messages=1, total_messages=1000,
                     dmarc_pass=1000, dmarc_fail=0, spf_not_aligned=1, dkim_not_aligned=0)
        for language, affected_label, total_label in (
            ("en", "Affected messages", "Total messages"),
            ("de", "Betroffene Nachrichten", "Nachrichten insgesamt"),
        ):
            with self.subTest(language=language):
                message = build_message(alert, {**configuration(), "language": language})
                payload = json.loads(next(message.iter_attachments()).get_content())
                self.assertEqual(payload["schema"], "dmarc-control.alert.v1")
                self.assertEqual(payload["alert"]["affected_messages"], 1)
                self.assertEqual(payload["alert"]["total_messages"], 1000)
                self.assertIn(f"{affected_label}: 1\n", message.get_body(("plain",)).get_content())
                self.assertIn(f"{total_label}: 1000\n", message.get_body(("plain",)).get_content())
                html = message.get_body(("html",)).get_content()
                self.assertRegex(html, affected_label + r"</td><td[^>]*>1</td>")
                self.assertRegex(html, total_label + r"</td><td[^>]*>1000</td>")

    def test_legacy_total_uses_authentication_volume_or_original_message_count(self):
        for alert, expected in (
            ({"id": "old-1", "messages": 1, "dmarc_pass": 999, "dmarc_fail": 1}, 1000),
            ({"id": "old-2", "messages": 7}, 7),
        ):
            with self.subTest(alert=alert["id"]):
                message = build_message(alert, configuration())
                payload = json.loads(next(message.iter_attachments()).get_content())
                self.assertEqual(payload["alert"]["total_messages"], expected)
                self.assertEqual(payload["alert"]["affected_messages"], alert["messages"])

    def test_explicit_test_requires_every_recipient_to_be_accepted(self):
        accepted = RecipientDeliveryResult("one@example.invalid", "accepted")
        failed = RecipientDeliveryResult("two@example.invalid", "temporary_failure", "SMTP 450: try later", 450)
        self.assertIsNone(require_all_accepted([accepted]))
        with self.assertRaisesRegex(NotificationDeliveryError, "1 of 2 recipients accepted"):
            require_all_accepted([accepted, failed])
        with self.assertRaises(NotificationDeliveryError):
            require_all_accepted([])


if __name__ == "__main__":
    unittest.main()
