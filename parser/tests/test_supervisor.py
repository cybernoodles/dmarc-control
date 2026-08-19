from __future__ import annotations

import configparser
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SUPERVISOR_PATH = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("parser_supervisor", SUPERVISOR_PATH)
assert SPEC and SPEC.loader
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


class ManagedConfigurationTests(unittest.TestCase):
    def test_graph_runtime_config_contains_one_mailbox_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.ini"
            runtime = Path(directory) / "runtime.ini"
            base.write_text(
                "[general]\nsave_aggregate = True\n"
                "[opensearch]\nhosts = opensearch:9200\nssl = False\n",
                encoding="utf-8",
            )
            connection = {
                "provider": "msgraph",
                "auth_method": "ClientSecret",
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret-value",
                "mailbox": "dmarc@example.com",
                "reports_folder": "Inbox/DMARC",
                "archive_folder": "Inbox/DMARC/Processed",
            }
            with (
                patch.object(supervisor, "BASE_CONFIG", base),
                patch.object(supervisor, "RUNTIME_CONFIG", runtime),
                patch.dict(
                    os.environ,
                    {"PARSER_SAVE_FAILURE": "true"},
                    clear=True,
                ),
            ):
                result = supervisor.render_managed_configuration(connection)

            config = configparser.RawConfigParser()
            config.read(result, encoding="utf-8")
            self.assertTrue(config.has_section("msgraph"))
            self.assertFalse(config.has_section("imap"))
            self.assertEqual(config["msgraph"]["client_secret"], "secret-value")
            self.assertEqual(config["mailbox"]["watch"], "True")
            self.assertEqual(config["mailbox"]["delete"], "False")
            self.assertEqual(config["general"]["save_failure"], "True")
            self.assertEqual(config["opensearch"]["monthly_indexes"], "True")
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)

    def test_imap_runtime_config_forces_tls_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base.ini"
            runtime = Path(directory) / "runtime.ini"
            base.write_text(
                "[general]\nsave_aggregate = True\n"
                "[opensearch]\nhosts = opensearch:9200\nssl = False\n",
                encoding="utf-8",
            )
            connection = {
                "provider": "imap",
                "host": "imap.example.com",
                "port": 993,
                "ssl": True,
                "skip_certificate_verification": False,
                "user": "dmarc@example.com",
                "password": "imap-secret",
                "reports_folder": "INBOX",
                "archive_folder": "Archive",
            }
            with (
                patch.object(supervisor, "BASE_CONFIG", base),
                patch.object(supervisor, "RUNTIME_CONFIG", runtime),
                patch.dict(
                    os.environ,
                    {"PARSER_OPENSEARCH_MONTHLY_INDEXES": "false"},
                    clear=True,
                ),
            ):
                supervisor.render_managed_configuration(connection)

            config = configparser.RawConfigParser()
            config.read(runtime, encoding="utf-8")
            self.assertTrue(config.has_section("imap"))
            self.assertFalse(config.has_section("msgraph"))
            self.assertEqual(config["imap"]["ssl"], "True")
            self.assertEqual(
                config["imap"]["skip_certificate_verification"],
                "False",
            )
            self.assertEqual(config["opensearch"]["monthly_indexes"], "False")


if __name__ == "__main__":
    unittest.main()
