from __future__ import annotations

import sqlite3
import threading
import json
from datetime import UTC, datetime
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

    def admin_configured(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE credential_id = 1"
            ).fetchone()
        return row is not None

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
