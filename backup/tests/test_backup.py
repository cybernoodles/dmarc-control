from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


BACKUP_PATH = Path(__file__).resolve().parents[1] / "backup.py"
SPEC = importlib.util.spec_from_file_location("dmarc_backup", BACKUP_PATH)
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)


def test_config(root: Path) -> backup.Config:
    return backup.Config(
        backup_root=root / "backups",
        dashboard_data=root / "dashboard",
        parser_control=root / "parser-control",
        stack_config=root / "stack",
        dashboard_url="http://dashboard.invalid",
        opensearch_url="http://opensearch.invalid",
        schedule="0 2 * * *",
        retention_days=30,
        poll_seconds=5,
        parser_pause_timeout=10,
        release_version="test",
        recovery_key_file=root / "dashboard" / "backup.key",
    )


class ScheduleTests(unittest.TestCase):
    def test_next_daily_run_uses_utc_and_rolls_to_next_day(self) -> None:
        before = datetime(2026, 8, 21, 1, 30, tzinfo=UTC)
        after = datetime(2026, 8, 21, 2, 30, tzinfo=UTC)

        self.assertEqual(
            backup.next_daily_run("0 2 * * *", before),
            datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
        )
        self.assertEqual(
            backup.next_daily_run("0 2 * * *", after),
            datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
        )

    def test_non_daily_cron_is_rejected(self) -> None:
        with self.assertRaisesRegex(backup.BackupError, "must be numbers"):
            backup.parse_daily_schedule("*/5 * * * *")

    def test_existing_backup_is_not_repeated_on_daemon_restart(self) -> None:
        now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        latest = {"created_at": "2026-08-21T02:00:05Z"}

        self.assertEqual(
            backup.next_run_from_latest("0 2 * * *", latest, now),
            datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
        )
        self.assertEqual(
            backup.next_run_from_latest("0 2 * * *", None, now),
            now,
        )


class ArchiveTests(unittest.TestCase):
    def test_authenticated_archive_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            encrypted = root / "source.tar.gz.aes"
            decrypted = root / "decrypted.tar.gz"
            key = os.urandom(32)
            source.write_bytes(b"example backup payload")

            backup.encrypt_archive(source, encrypted, key)
            backup.decrypt_archive(encrypted, decrypted, key)
            self.assertEqual(decrypted.read_bytes(), source.read_bytes())

            payload = bytearray(encrypted.read_bytes())
            payload[-1] ^= 1
            encrypted.write_bytes(payload)
            with self.assertRaisesRegex(
                backup.BackupError,
                "authentication failed",
            ):
                backup.decrypt_archive(encrypted, decrypted, key)

    def test_control_archive_contains_consistent_sqlite_and_can_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = test_config(root)
            config.dashboard_data.mkdir(parents=True)
            config.parser_control.mkdir(parents=True)
            config.stack_config.mkdir(parents=True)
            key = os.urandom(32)
            config.recovery_key_file.write_bytes(key)
            (config.dashboard_data / "connection.key").write_bytes(
                os.urandom(32)
            )
            config.control_token.write_text("control-token\n", encoding="utf-8")
            (config.stack_config / ".env").write_text(
                "EXAMPLE=value\n", encoding="utf-8"
            )
            with sqlite3.connect(config.dashboard_data / "dashboard.db") as db:
                db.execute("CREATE TABLE state (value TEXT NOT NULL)")
                db.execute("INSERT INTO state VALUES ('preserved')")

            controller = backup.BackupController(config)
            controller.prepare_directories()
            self.assertEqual(
                config.snapshot_repository.stat().st_mode & 0o0777,
                0o0770,
            )
            archive, integrity, included, fingerprint = (
                controller.create_control_archive("dmarc-20260821t020000z")
            )
            manifest = {
                "schema": backup.SCHEMA,
                "backup_id": "dmarc-20260821t020000z",
                "created_at": "2026-08-21T02:00:00Z",
                "release_version": "test",
                "opensearch": {
                    "version": "2.19.6",
                    "repository": backup.REPOSITORY,
                    "snapshot": "dmarc-20260821t020000z",
                    "state": "SUCCESS",
                    "indices": [],
                    "shards": {"failed": 0},
                },
                "control": {
                    "archive": archive.name,
                    "sha256": backup.sha256_file(archive),
                    "encryption": "AES-256-GCM",
                    "key_fingerprint": fingerprint,
                    "sqlite_integrity_check": integrity,
                    "included": included,
                },
                "consistency": {
                    "parser_paused": True,
                    "notification_delivery_paused": True,
                },
            }
            controller.write_manifest(manifest)

            result = controller.verify_manifest(manifest, online=False)

            self.assertTrue(result["valid"])
            self.assertEqual(integrity, "ok")
            self.assertTrue(included["stack/.env"])
            self.assertEqual(fingerprint, backup.key_fingerprint(key))

    def test_control_backup_succeeds_before_first_history_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = test_config(root)
            config.dashboard_data.mkdir(parents=True)
            config.parser_control.mkdir(parents=True)
            config.recovery_key_file.write_bytes(os.urandom(32))
            config.control_token.write_text("control-token\n", encoding="utf-8")
            with sqlite3.connect(config.dashboard_data / "dashboard.db") as db:
                db.execute("CREATE TABLE state (value TEXT NOT NULL)")

            controller = backup.BackupController(config)
            controller.configuration = lambda: {"mode": "integrated"}
            controller.dashboard_request = lambda *_args, **_kwargs: {}
            controller.wait_for_parser_pause = lambda: None
            controller.register_repository = lambda: None
            controller.opensearch_version = lambda: "2.19.6"
            controller.indices = lambda: []
            controller.prune_locked = lambda: []

            result = controller.create_backup()
            manifest = controller.select_manifest(result["backup_id"])

            self.assertEqual(result["state"], "success")
            self.assertEqual(manifest["opensearch"]["indices"], [])
            self.assertIsNone(manifest["opensearch"]["snapshot"])
            self.assertEqual(manifest["opensearch"]["state"], "NOT_REQUIRED")
            self.assertTrue(
                controller.verify_manifest(manifest, online=True)["valid"]
            )


class InventoryTests(unittest.TestCase):
    def test_system_indices_are_excluded_from_transportable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = backup.BackupController(test_config(Path(directory)))
            controller.opensearch_request = lambda _path: [
                {
                    "index": ".opensearch-observability",
                    "docs.count": "3",
                },
                {
                    "index": "dmarc_aggregate-2026-08",
                    "docs.count": "42",
                    "store.size": "1mb",
                    "status": "open",
                    "health": "green",
                },
            ]

            self.assertEqual(
                controller.indices(),
                [
                    {
                        "name": "dmarc_aggregate-2026-08",
                        "documents": 42,
                        "store_size": "1mb",
                        "status": "open",
                        "health": "green",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
