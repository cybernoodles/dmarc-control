from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_BRAND_COLOR = "#173f43"


class StateStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = threading.Lock()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_state (
                    alert_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS host_overrides (
                    source_ip TEXT PRIMARY KEY,
                    service_name TEXT,
                    trust_status TEXT NOT NULL,
                    notes TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_credentials (
                    credential_id INTEGER PRIMARY KEY CHECK (credential_id = 1),
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    session_hash TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS read_credentials (
                    credential_id INTEGER PRIMARY KEY CHECK (credential_id = 1),
                    username TEXT NOT NULL,
                    username_normalized TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS read_sessions (
                    session_hash TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mailbox_connection_versions (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    secret_ciphertext TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mailbox_connection_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    draft_revision INTEGER,
                    tested_revision INTEGER,
                    active_revision INTEGER,
                    test_status TEXT NOT NULL DEFAULT 'untested',
                    test_message TEXT,
                    tested_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parser_runtime_status (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    status_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_settings (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    settings_json TEXT NOT NULL,
                    secret_ciphertext TEXT NOT NULL,
                    test_status TEXT NOT NULL DEFAULT 'untested',
                    test_message TEXT,
                    tested_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    alert_id TEXT NOT NULL,
                    destination_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_attempt_at TEXT NOT NULL,
                    next_attempt_at TEXT,
                    sent_at TEXT,
                    last_error TEXT,
                    PRIMARY KEY (alert_id, destination_hash)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backup_settings (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_hours INTEGER NOT NULL DEFAULT 24,
                    retention_count INTEGER NOT NULL DEFAULT 14,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backup_runs (
                    backup_id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_name TEXT,
                    manifest_path TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                """
                UPDATE backup_runs
                SET status = 'failed',
                    error = 'Dashboard restarted before backup completion',
                    completed_at = ?
                WHERE status = 'running'
                """,
                (datetime.now(UTC).isoformat(),),
            )

    def admin_configured(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE credential_id = 1"
            ).fetchone()
        return row is not None

    def read_configured(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM read_credentials WHERE credential_id = 1"
            ).fetchone()
        return row is not None

    def setup_complete(self) -> bool:
        return self.admin_configured() and self.read_configured()

    def read_username(self) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT username
                FROM read_credentials
                WHERE credential_id = 1
                """
            ).fetchone()
        return row["username"] if row else None

    def read_password_hash(self, username_normalized: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT password_hash
                FROM read_credentials
                WHERE credential_id = 1 AND username_normalized = ?
                """,
                (username_normalized,),
            ).fetchone()
        return row["password_hash"] if row else None

    def admin_password_hash(self) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT password_hash
                FROM admin_credentials
                WHERE credential_id = 1
                """
            ).fetchone()
        return row["password_hash"] if row else None

    def set_initial_admin_password(self, password_hash: str) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO admin_credentials (
                    credential_id, password_hash, created_at, updated_at
                )
                VALUES (1, ?, ?, ?)
                """,
                (password_hash, timestamp, timestamp),
            )
        return cursor.rowcount == 1

    def set_initial_credentials(
        self,
        *,
        admin_password_hash: str,
        read_username: str,
        read_username_normalized: str,
        read_password_hash: str,
    ) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            admin_exists = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE credential_id = 1"
            ).fetchone()
            read_exists = connection.execute(
                "SELECT 1 FROM read_credentials WHERE credential_id = 1"
            ).fetchone()
            if admin_exists or read_exists:
                return False
            connection.execute(
                """
                INSERT INTO admin_credentials (
                    credential_id, password_hash, created_at, updated_at
                )
                VALUES (1, ?, ?, ?)
                """,
                (admin_password_hash, timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO read_credentials (
                    credential_id, username, username_normalized,
                    password_hash, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                (
                    read_username,
                    read_username_normalized,
                    read_password_hash,
                    timestamp,
                    timestamp,
                ),
            )
        return True

    def set_initial_read_credentials(
        self,
        *,
        expected_admin_hash: str,
        read_username: str,
        read_username_normalized: str,
        read_password_hash: str,
    ) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO read_credentials (
                    credential_id, username, username_normalized,
                    password_hash, created_at, updated_at
                )
                SELECT 1, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1
                    FROM admin_credentials
                    WHERE credential_id = 1 AND password_hash = ?
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM read_credentials
                    WHERE credential_id = 1
                )
                """,
                (
                    read_username,
                    read_username_normalized,
                    read_password_hash,
                    timestamp,
                    timestamp,
                    expected_admin_hash,
                ),
            )
        return cursor.rowcount == 1

    def replace_read_credentials(
        self,
        *,
        read_username: str,
        read_username_normalized: str,
        password_hash: str,
    ) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE read_credentials
                SET username = ?, username_normalized = ?,
                    password_hash = ?, updated_at = ?
                WHERE credential_id = 1
                """,
                (
                    read_username,
                    read_username_normalized,
                    password_hash,
                    timestamp,
                ),
            )
            if cursor.rowcount == 1:
                connection.execute("DELETE FROM read_sessions")
        return cursor.rowcount == 1

    def replace_admin_password(
        self,
        *,
        expected_hash: str,
        password_hash: str,
    ) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE admin_credentials
                SET password_hash = ?, updated_at = ?
                WHERE credential_id = 1 AND password_hash = ?
                """,
                (password_hash, timestamp, expected_hash),
            )
            if cursor.rowcount == 1:
                connection.execute("DELETE FROM admin_sessions")
        return cursor.rowcount == 1

    def create_admin_session(
        self,
        *,
        session_hash: str,
        expires_at: datetime,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?",
                (created_at,),
            )
            connection.execute(
                """
                INSERT INTO admin_sessions (session_hash, expires_at, created_at)
                VALUES (?, ?, ?)
                """,
                (session_hash, expires_at.isoformat(), created_at),
            )

    def admin_session_valid(self, session_hash: str) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?",
                (timestamp,),
            )
            row = connection.execute(
                """
                SELECT 1
                FROM admin_sessions
                WHERE session_hash = ? AND expires_at > ?
                """,
                (session_hash, timestamp),
            ).fetchone()
        return row is not None

    def delete_admin_session(self, session_hash: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE session_hash = ?",
                (session_hash,),
            )

    def create_read_session(
        self,
        *,
        session_hash: str,
        expires_at: datetime,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM read_sessions WHERE expires_at <= ?",
                (created_at,),
            )
            connection.execute(
                """
                INSERT INTO read_sessions (session_hash, expires_at, created_at)
                VALUES (?, ?, ?)
                """,
                (session_hash, expires_at.isoformat(), created_at),
            )

    def read_session_valid(self, session_hash: str) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM read_sessions
                WHERE session_hash = ? AND expires_at > ?
                """,
                (session_hash, timestamp),
            ).fetchone()
        return row is not None

    def delete_read_session(self, session_hash: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM read_sessions WHERE session_hash = ?",
                (session_hash,),
            )

    @staticmethod
    def _mailbox_version_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "revision": row["revision"],
            "provider": row["provider"],
            "settings": json.loads(row["settings_json"]),
            "secret_ciphertext": row["secret_ciphertext"],
            "created_at": row["created_at"],
        }

    def mailbox_connection_state(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            state = connection.execute(
                """
                SELECT draft_revision, tested_revision, active_revision,
                       test_status, test_message, tested_at, updated_at
                FROM mailbox_connection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            if state is None:
                draft = None
                active = None
            else:
                draft = connection.execute(
                    """
                    SELECT revision, provider, settings_json,
                           secret_ciphertext, created_at
                    FROM mailbox_connection_versions
                    WHERE revision = ?
                    """,
                    (state["draft_revision"],),
                ).fetchone()
                active = connection.execute(
                    """
                    SELECT revision, provider, settings_json,
                           secret_ciphertext, created_at
                    FROM mailbox_connection_versions
                    WHERE revision = ?
                    """,
                    (state["active_revision"],),
                ).fetchone()
            runtime = connection.execute(
                """
                SELECT status_json, updated_at
                FROM parser_runtime_status
                WHERE singleton_id = 1
                """
            ).fetchone()

        return {
            "draft": self._mailbox_version_from_row(draft),
            "active": self._mailbox_version_from_row(active),
            "draft_revision": state["draft_revision"] if state else None,
            "tested_revision": state["tested_revision"] if state else None,
            "active_revision": state["active_revision"] if state else None,
            "test_status": state["test_status"] if state else "untested",
            "test_message": state["test_message"] if state else None,
            "tested_at": state["tested_at"] if state else None,
            "updated_at": state["updated_at"] if state else None,
            "runtime": (
                {
                    **json.loads(runtime["status_json"]),
                    "updated_at": runtime["updated_at"],
                }
                if runtime
                else None
            ),
        }

    def save_mailbox_connection(
        self,
        *,
        provider: str,
        settings: dict[str, Any],
        secret_ciphertext: str,
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO mailbox_connection_versions (
                    provider, settings_json, secret_ciphertext, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    provider,
                    json.dumps(settings, sort_keys=True, separators=(",", ":")),
                    secret_ciphertext,
                    timestamp,
                ),
            )
            revision = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO mailbox_connection_state (
                    singleton_id, draft_revision, tested_revision,
                    active_revision, test_status, test_message,
                    tested_at, updated_at
                )
                VALUES (1, ?, NULL, NULL, 'untested', NULL, NULL, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    draft_revision = excluded.draft_revision,
                    tested_revision = NULL,
                    test_status = 'untested',
                    test_message = NULL,
                    tested_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (revision, timestamp),
            )
        return self.mailbox_connection_state()

    def record_mailbox_test(
        self,
        *,
        revision: int,
        status: str,
        message: str,
    ) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE mailbox_connection_state
                SET tested_revision = ?,
                    test_status = ?,
                    test_message = ?,
                    tested_at = ?,
                    updated_at = ?
                WHERE singleton_id = 1 AND draft_revision = ?
                """,
                (revision, status, message, timestamp, timestamp, revision),
            )
        return cursor.rowcount == 1

    def activate_mailbox_connection(self, revision: int) -> bool:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE mailbox_connection_state
                SET active_revision = ?, updated_at = ?
                WHERE singleton_id = 1
                  AND draft_revision = ?
                  AND tested_revision = ?
                  AND test_status = 'success'
                """,
                (revision, timestamp, revision, revision),
            )
        return cursor.rowcount == 1

    def set_parser_runtime_status(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        payload = json.dumps(status, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO parser_runtime_status (
                    singleton_id, status_json, updated_at
                )
                VALUES (1, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    status_json = excluded.status_json,
                    updated_at = excluded.updated_at
                """,
                (payload, timestamp),
            )
        return {**status, "updated_at": timestamp}

    def notification_settings(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT settings_json, secret_ciphertext, test_status,
                       test_message, tested_at, updated_at
                FROM notification_settings
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "settings": json.loads(row["settings_json"]),
            "secret_ciphertext": row["secret_ciphertext"],
            "test_status": row["test_status"],
            "test_message": row["test_message"],
            "tested_at": row["tested_at"],
            "updated_at": row["updated_at"],
        }

    def save_notification_settings(
        self,
        *,
        settings: dict[str, Any],
        secret_ciphertext: str,
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        payload = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_settings (
                    singleton_id, settings_json, secret_ciphertext,
                    test_status, test_message, tested_at, updated_at
                )
                VALUES (1, ?, ?, 'untested', NULL, NULL, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    secret_ciphertext = excluded.secret_ciphertext,
                    test_status = 'untested',
                    test_message = NULL,
                    tested_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (payload, secret_ciphertext, timestamp),
            )
        return self.notification_settings() or {}

    def record_notification_test(
        self,
        *,
        status: str,
        message: str,
    ) -> dict[str, Any] | None:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE notification_settings
                SET test_status = ?, test_message = ?, tested_at = ?
                WHERE singleton_id = 1
                """,
                (status, message[:500], timestamp),
            )
        return self.notification_settings()

    def claim_notification_delivery(
        self,
        *,
        alert_id: str,
        destination_hash: str,
        max_attempts: int = 3,
    ) -> bool:
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, attempts, last_attempt_at, next_attempt_at
                FROM notification_deliveries
                WHERE alert_id = ? AND destination_hash = ?
                """,
                (alert_id, destination_hash),
            ).fetchone()
            if row is not None:
                if row["status"] == "sent":
                    return False
                if (
                    row["status"] == "sending"
                    and row["last_attempt_at"]
                    > (now - timedelta(minutes=15)).isoformat()
                ):
                    return False
                if int(row["attempts"]) >= max_attempts:
                    return False
                if (
                    row["next_attempt_at"]
                    and row["next_attempt_at"] > timestamp
                ):
                    return False
                attempts = int(row["attempts"]) + 1
                connection.execute(
                    """
                    UPDATE notification_deliveries
                    SET status = 'sending', attempts = ?,
                        last_attempt_at = ?, next_attempt_at = NULL,
                        last_error = NULL
                    WHERE alert_id = ? AND destination_hash = ?
                    """,
                    (attempts, timestamp, alert_id, destination_hash),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO notification_deliveries (
                        alert_id, destination_hash, status, attempts,
                        last_attempt_at, next_attempt_at, sent_at, last_error
                    )
                    VALUES (?, ?, 'sending', 1, ?, NULL, NULL, NULL)
                    """,
                    (alert_id, destination_hash, timestamp),
                )
        return True

    def finish_notification_delivery(
        self,
        *,
        alert_id: str,
        destination_hash: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT attempts
                FROM notification_deliveries
                WHERE alert_id = ? AND destination_hash = ?
                """,
                (alert_id, destination_hash),
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"])
            if success:
                connection.execute(
                    """
                    UPDATE notification_deliveries
                    SET status = 'sent', sent_at = ?,
                        next_attempt_at = NULL, last_error = NULL
                    WHERE alert_id = ? AND destination_hash = ?
                    """,
                    (timestamp, alert_id, destination_hash),
                )
                return
            retry_minutes = min(60, 5 * (2 ** max(0, attempts - 1)))
            next_attempt = datetime.fromtimestamp(
                now.timestamp() + retry_minutes * 60,
                tz=UTC,
            ).isoformat()
            connection.execute(
                """
                UPDATE notification_deliveries
                SET status = 'failed', next_attempt_at = ?, last_error = ?
                WHERE alert_id = ? AND destination_hash = ?
                """,
                (
                    next_attempt,
                    (error or "Notification delivery failed")[:500],
                    alert_id,
                    destination_hash,
                ),
            )

    def notification_delivery_summary(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM notification_deliveries
                GROUP BY status
                """
            ).fetchall()
            latest = connection.execute(
                """
                SELECT status, last_attempt_at, sent_at, last_error
                FROM notification_deliveries
                ORDER BY last_attempt_at DESC
                LIMIT 1
                """
            ).fetchone()
        counts = {row["status"]: int(row["count"]) for row in rows}
        return {
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "pending": counts.get("sending", 0),
            "latest": dict(latest) if latest else None,
        }

    def backup_settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT enabled, interval_hours, retention_count, updated_at
                FROM backup_settings
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return {
                "enabled": False,
                "interval_hours": 24,
                "retention_count": 14,
                "updated_at": None,
            }
        return {
            "enabled": bool(row["enabled"]),
            "interval_hours": int(row["interval_hours"]),
            "retention_count": int(row["retention_count"]),
            "updated_at": row["updated_at"],
        }

    def save_backup_settings(
        self,
        *,
        enabled: bool,
        interval_hours: int,
        retention_count: int,
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_settings (
                    singleton_id, enabled, interval_hours,
                    retention_count, updated_at
                )
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_hours = excluded.interval_hours,
                    retention_count = excluded.retention_count,
                    updated_at = excluded.updated_at
                """,
                (
                    1 if enabled else 0,
                    interval_hours,
                    retention_count,
                    timestamp,
                ),
            )
        return self.backup_settings()

    def start_backup_run(
        self,
        *,
        backup_id: str,
        trigger: str,
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_runs (
                    backup_id, trigger, status, started_at
                )
                VALUES (?, ?, 'running', ?)
                """,
                (backup_id, trigger, timestamp),
            )
        return {
            "backup_id": backup_id,
            "trigger": trigger,
            "status": "running",
            "snapshot_name": None,
            "manifest_path": None,
            "error": None,
            "started_at": timestamp,
            "completed_at": None,
        }

    def finish_backup_run(
        self,
        *,
        backup_id: str,
        status: str,
        snapshot_name: str | None = None,
        manifest_path: str | None = None,
        error: str | None = None,
    ) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE backup_runs
                SET status = ?, snapshot_name = ?, manifest_path = ?,
                    error = ?, completed_at = ?
                WHERE backup_id = ?
                """,
                (
                    status,
                    snapshot_name,
                    manifest_path,
                    error[:1000] if error else None,
                    timestamp,
                    backup_id,
                ),
            )

    def backup_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT backup_id, trigger, status, snapshot_name,
                       manifest_path, error, started_at, completed_at
                FROM backup_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def backup_due(self, interval_hours: int) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at
                FROM backup_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return True
        try:
            started_at = datetime.fromisoformat(row["started_at"])
        except (TypeError, ValueError):
            return True
        return started_at <= datetime.now(UTC) - timedelta(hours=interval_hours)

    def successful_backups_after_retention(
        self,
        retention_count: int,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT backup_id, snapshot_name
                FROM backup_runs
                WHERE status = 'success' AND snapshot_name IS NOT NULL
                ORDER BY completed_at DESC
                LIMIT -1 OFFSET ?
                """,
                (retention_count,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_backup_run(self, backup_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM backup_runs WHERE backup_id = ?",
                (backup_id,),
            )

    def alert_states(self) -> dict[str, dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT alert_id, status, updated_at FROM alert_state"
            ).fetchall()
        return {
            row["alert_id"]: {
                "status": row["status"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def set_alert_status(self, alert_id: str, status: str) -> dict[str, str]:
        updated_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO alert_state (alert_id, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (alert_id, status, updated_at),
            )
        return {"alert_id": alert_id, "status": status, "updated_at": updated_at}

    def host_overrides(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_ip, service_name, trust_status, notes, updated_at
                FROM host_overrides
                """
            ).fetchall()
        return {
            row["source_ip"]: {
                "service_name": row["service_name"],
                "trust_status": row["trust_status"],
                "notes": row["notes"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def set_host_override(
        self,
        source_ip: str,
        *,
        service_name: str | None,
        trust_status: str,
        notes: str | None,
    ) -> dict[str, Any]:
        updated_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO host_overrides (
                    source_ip, service_name, trust_status, notes, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_ip) DO UPDATE SET
                    service_name = excluded.service_name,
                    trust_status = excluded.trust_status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (source_ip, service_name, trust_status, notes, updated_at),
            )
        return {
            "source_ip": source_ip,
            "service_name": service_name,
            "trust_status": trust_status,
            "notes": notes,
            "updated_at": updated_at,
        }

    def clear_host_override(self, source_ip: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM host_overrides WHERE source_ip = ?",
                (source_ip,),
            )
        return cursor.rowcount == 1

    def appearance_settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT setting_key, setting_value, updated_at
                FROM app_settings
                WHERE setting_key IN (
                    'appearance.global_profile',
                    'appearance.global_color'
                )
                """
            ).fetchall()
        values = {row["setting_key"]: row["setting_value"] for row in rows}
        profile = values.get("appearance.global_profile", "standard")
        if profile not in {"standard", "custom"}:
            profile = "standard"
        color = values.get("appearance.global_color", DEFAULT_BRAND_COLOR)
        if profile == "standard":
            color = DEFAULT_BRAND_COLOR
        updated_at = max(
            (row["updated_at"] for row in rows),
            default=None,
        )
        return {
            "global_profile": profile,
            "global_color": color,
            "updated_at": updated_at,
        }

    def set_global_appearance(
        self,
        *,
        profile: str,
        color: str,
    ) -> dict[str, Any]:
        updated_at = datetime.now(UTC).isoformat()
        effective_color = DEFAULT_BRAND_COLOR if profile == "standard" else color
        rows = (
            ("appearance.global_profile", profile, updated_at),
            ("appearance.global_color", effective_color, updated_at),
        )
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return {
            "global_profile": profile,
            "global_color": effective_color,
            "updated_at": updated_at,
        }
