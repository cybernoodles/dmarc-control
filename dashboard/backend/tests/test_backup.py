from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.backup import OnlineBackupManager, create_backup_id
from app.config import Settings
from app.store import StateStore


class FakeBackupManager(OnlineBackupManager):
    def __init__(self, directory: Path) -> None:
        database = directory / "dashboard.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('preserved')")
        connection.commit()
        connection.close()
        (directory / "connection.key").write_bytes(b"key-material")
        (directory / "control.token").write_text("token\n", encoding="utf-8")
        self.deleted: list[str] = []
        super().__init__(
            opensearch_url="http://opensearch:9200",
            database_path=database,
            connection_key_path=directory / "connection.key",
            parser_control_token_path=directory / "control.token",
            output_path=directory / "backups",
            repository_name="dmarc-control",
            repository_path="/mnt/snapshots",
            index_pattern="dmarc_*",
            timeout_seconds=30,
            application_version="test",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        allow_missing: bool = False,
    ) -> dict:
        if method == "GET" and path == "/":
            return {
                "cluster_name": "test-cluster",
                "version": {"number": "2.19.3"},
            }
        if method == "DELETE":
            self.deleted.append(path)
            return {"acknowledged": True}
        if "wait_for_completion=true" in path:
            return {
                "snapshot": {
                    "snapshot": path.split("?")[0].rsplit("/", 1)[-1],
                    "state": "SUCCESS",
                    "indices": ["dmarc_aggregate-2026-08"],
                    "shards": {"total": 1, "failed": 0, "successful": 1},
                    "start_time": "2026-08-04T08:00:00.000Z",
                    "end_time": "2026-08-04T08:00:01.000Z",
                }
            }
        return {"acknowledged": True}


class OnlineBackupTests(unittest.TestCase):
    def test_snapshot_and_consistent_control_bundle_share_backup_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manager = FakeBackupManager(directory)
            backup_id = create_backup_id()

            result = asyncio.run(manager.create(backup_id))

            backup_path = directory / "backups" / backup_id
            manifest = json.loads(
                (backup_path / "manifest.json").read_text(encoding="utf-8")
            )
            restored = sqlite3.connect(backup_path / "dashboard.db")
            try:
                value = restored.execute("SELECT value FROM sample").fetchone()[0]
            finally:
                restored.close()

            self.assertEqual(value, "preserved")
            self.assertEqual(manifest["backup_id"], backup_id)
            self.assertEqual(manifest["control"]["sqlite_integrity_check"], "ok")
            self.assertTrue(manifest["control"]["connection_key_present"])
            self.assertTrue(manifest["control"]["parser_control_token_present"])
            self.assertEqual(
                manifest["opensearch"]["snapshot"],
                result["snapshot_name"],
            )
            self.assertIn("dashboard.db", manifest["control"]["files"])

    def test_delete_uses_snapshot_api_and_removes_only_matching_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manager = FakeBackupManager(directory)
            backup_id = create_backup_id()
            result = asyncio.run(manager.create(backup_id))

            asyncio.run(
                manager.delete(
                    backup_id=backup_id,
                    snapshot_name=result["snapshot_name"],
                )
            )

            self.assertFalse((directory / "backups" / backup_id).exists())
            self.assertEqual(len(manager.deleted), 1)
            self.assertIn(result["snapshot_name"], manager.deleted[0])


class BackupSettingsApiTests(unittest.TestCase):
    def test_admin_can_configure_and_start_online_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "backups"
            output.mkdir()
            test_settings = Settings(
                database_path=directory / "dashboard.db",
                connection_key_path=directory / "connection.key",
                parser_control_token_file=directory / "control.token",
                backup_output_path=output,
                backup_target_label="/mnt/backup/parsedmarc",
            )
            test_store = StateStore(test_settings.database_path)

            with (
                patch.object(main, "settings", test_settings),
                patch.object(main, "store", test_store),
                patch.object(
                    main,
                    "launch_online_backup",
                    return_value="20260804t080000z-12345678",
                ),
                TestClient(main.app) as client,
            ):
                client.post(
                    "/api/auth/setup",
                    json={
                        "admin_password": "initial-admin-password",
                        "read_username": "dmarc-reader",
                        "read_password": "initial-read-password",
                    },
                )
                saved = client.put(
                    "/api/settings/backups",
                    json={
                        "enabled": True,
                        "interval_hours": 12,
                        "retention_count": 10,
                    },
                )
                started = client.post("/api/settings/backups/run")

            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json()["enabled"])
            self.assertEqual(saved.json()["interval_hours"], 12)
            self.assertEqual(saved.json()["retention_count"], 10)
            self.assertEqual(saved.json()["target"], "/mnt/backup/parsedmarc")
            self.assertEqual(started.status_code, 202)
            self.assertEqual(
                started.json()["started_backup_id"],
                "20260804t080000z-12345678",
            )


if __name__ == "__main__":
    unittest.main()
