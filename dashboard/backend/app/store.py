from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from .recipient_deliveries import RecipientDeliveryStore
from .evaluation_runs import EvaluationRunStore
from .domain_monitoring import DomainMonitoringStore
from .domain_services import DomainServiceStore

DEFAULT_BRAND_COLOR = "#173f43"
BACKUP_MODES = {"integrated", "external", "none"}
LOGIN_THROTTLE_RETENTION = timedelta(hours=24)
LOGIN_THROTTLE_MAX_SECONDS = 60


@dataclass(frozen=True)
class LoginAuthenticationResult:
    status: Literal["authenticated", "failed", "throttled", "setup_required"]
    retry_after: int | None = None


class StateStore(
    RecipientDeliveryStore,
    EvaluationRunStore,
    DomainMonitoringStore,
    DomainServiceStore,
):
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = threading.Lock()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
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
                    updated_at TEXT NOT NULL,
                    classification_mode TEXT NOT NULL DEFAULT 'legacy_preserved'
                        CHECK (classification_mode IN ('automatic', 'manual', 'legacy_preserved'))
                )
                """
            )
            host_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(host_overrides)")
            }
            if "classification_mode" not in host_columns:
                # Existing names/notes do not establish the user's original
                # intent. Preserve every old field and timestamp unchanged.
                connection.execute("""
                    ALTER TABLE host_overrides
                    ADD COLUMN classification_mode TEXT NOT NULL DEFAULT 'legacy_preserved'
                        CHECK (classification_mode IN ('automatic', 'manual', 'legacy_preserved'))
                """)
            # A rolled-back release can write a name without updating the new
            # mode column. Preserve that legacy assignment on the next upgrade;
            # current automatic writes always clear service_name themselves.
            connection.execute("""
                UPDATE host_overrides SET classification_mode = 'legacy_preserved'
                WHERE classification_mode = 'automatic'
                  AND TRIM(COALESCE(service_name, '')) <> ''
            """)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    alert_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notification_eligible INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_aliases (
                    legacy_id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_report_history (
                    domain TEXT PRIMARY KEY,
                    last_report TEXT NOT NULL
                )
                """
            )
            self.initialize_domain_monitoring(connection)
            self.initialize_domain_services(connection)
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
                CREATE TABLE IF NOT EXISTS login_throttles (
                    scope TEXT NOT NULL CHECK (scope IN ('ip', 'username')),
                    client_ip TEXT NOT NULL,
                    username_normalized TEXT NOT NULL,
                    failure_count INTEGER NOT NULL,
                    locked_until TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, client_ip, username_normalized)
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
                    mode TEXT NOT NULL CHECK (
                        mode IN ('integrated', 'external', 'none')
                    ),
                    configured_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backup_runtime_status (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    status_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            self.initialize_recipient_deliveries(connection)
            self.initialize_evaluation_runs(connection)

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

    def backup_configured(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM backup_settings WHERE singleton_id = 1"
            ).fetchone()
        return row is not None

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

    def authenticate_login(
        self,
        *,
        account: Literal["admin", "read"],
        client_ip: str,
        username_normalized: str,
        password: str,
        dummy_password_hash: str,
        verify: Callable[[str, str], bool],
        now: datetime | None = None,
    ) -> LoginAuthenticationResult:
        """Perform one complete, serialized authentication attempt.

        The immediate transaction makes the lock check and the failed-attempt
        update atomic across processes.  This method is intentionally
        synchronous: callers run the whole operation in a worker thread.
        """
        timestamp = now or datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamp = timestamp.astimezone(UTC)
        timestamp_text = timestamp.isoformat()
        # The peer-IP limit deliberately applies across all accounts. The
        # identity limit must not: an Operator named "admin" is a different
        # principal from the administrator and must not reset its failures.
        username_key = f"{account}:{username_normalized}"
        throttle_keys = (
            ("ip", client_ip, ""),
            ("username", client_ip, username_key),
        )

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM login_throttles WHERE updated_at <= ?",
                    ((timestamp - LOGIN_THROTTLE_RETENTION).isoformat(),),
                )

                if account == "admin":
                    configured = connection.execute(
                        "SELECT password_hash FROM admin_credentials "
                        "WHERE credential_id = 1"
                    ).fetchone()
                else:
                    configured = connection.execute(
                        "SELECT 1 FROM admin_credentials WHERE credential_id = 1"
                    ).fetchone()
                    read_configured = connection.execute(
                        "SELECT 1 FROM read_credentials WHERE credential_id = 1"
                    ).fetchone()
                    if not configured or not read_configured:
                        connection.commit()
                        return LoginAuthenticationResult("setup_required")

                if not configured:
                    connection.commit()
                    return LoginAuthenticationResult("setup_required")

                retry_after = self._login_retry_after(
                    connection, throttle_keys, timestamp,
                )
                if retry_after is not None:
                    connection.commit()
                    return LoginAuthenticationResult("throttled", retry_after)

                if account == "admin":
                    password_hash = configured["password_hash"]
                    known_user = True
                else:
                    credential = connection.execute(
                        """
                        SELECT password_hash FROM read_credentials
                        WHERE credential_id = 1 AND username_normalized = ?
                        """,
                        (username_normalized,),
                    ).fetchone()
                    known_user = credential is not None
                    password_hash = (
                        credential["password_hash"]
                        if credential is not None
                        else dummy_password_hash
                    )

                # Always perform exactly one scrypt verification, including for
                # an unknown username, using the stable process-local dummy.
                password_valid = verify(password, password_hash)
                authenticated = known_user and password_valid

                if authenticated:
                    for scope, ip, username in throttle_keys:
                        connection.execute(
                            """
                            DELETE FROM login_throttles
                            WHERE scope = ? AND client_ip = ?
                              AND username_normalized = ?
                            """,
                            (scope, ip, username),
                        )
                    connection.commit()
                    return LoginAuthenticationResult("authenticated")

                for scope, ip, username in throttle_keys:
                    failure_count = self._record_login_failure(
                        connection,
                        scope=scope,
                        client_ip=ip,
                        username_normalized=username,
                        timestamp_text=timestamp_text,
                    )
                    if failure_count >= 5:
                        lock_seconds = min(
                            2 ** (failure_count - 5),
                            LOGIN_THROTTLE_MAX_SECONDS,
                        )
                        connection.execute(
                            """
                            UPDATE login_throttles SET locked_until = ?
                            WHERE scope = ? AND client_ip = ?
                              AND username_normalized = ?
                            """,
                            (
                                (timestamp + timedelta(seconds=lock_seconds)).isoformat(),
                                scope,
                                ip,
                                username,
                            ),
                        )
                connection.commit()
                return LoginAuthenticationResult("failed")
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _login_retry_after(
        connection: sqlite3.Connection,
        throttle_keys: tuple[tuple[str, str, str], ...],
        timestamp: datetime,
    ) -> int | None:
        retry_after: int | None = None
        for scope, client_ip, username_normalized in throttle_keys:
            row = connection.execute(
                """
                SELECT locked_until FROM login_throttles
                WHERE scope = ? AND client_ip = ? AND username_normalized = ?
                """,
                (scope, client_ip, username_normalized),
            ).fetchone()
            if not row or not row["locked_until"]:
                continue
            try:
                locked_until = datetime.fromisoformat(row["locked_until"])
            except ValueError:
                continue
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=UTC)
            remaining = (locked_until - timestamp).total_seconds()
            if remaining > 0:
                rounded = max(1, math.ceil(remaining))
                retry_after = max(retry_after or 0, rounded)
        return retry_after

    @staticmethod
    def _record_login_failure(
        connection: sqlite3.Connection,
        *,
        scope: str,
        client_ip: str,
        username_normalized: str,
        timestamp_text: str,
    ) -> int:
        connection.execute(
            """
            INSERT INTO login_throttles (
                scope, client_ip, username_normalized, failure_count,
                locked_until, updated_at
            ) VALUES (?, ?, ?, 1, NULL, ?)
            ON CONFLICT(scope, client_ip, username_normalized) DO UPDATE SET
                failure_count = login_throttles.failure_count + 1,
                locked_until = NULL,
                updated_at = excluded.updated_at
            """,
            (scope, client_ip, username_normalized, timestamp_text),
        )
        row = connection.execute(
            """
            SELECT failure_count FROM login_throttles
            WHERE scope = ? AND client_ip = ? AND username_normalized = ?
            """,
            (scope, client_ip, username_normalized),
        ).fetchone()
        return int(row["failure_count"])

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
        backup_mode: str,
    ) -> bool:
        if backup_mode not in BACKUP_MODES:
            raise ValueError("Unsupported backup mode")
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
            connection.execute(
                """
                INSERT INTO backup_settings (
                    singleton_id, mode, configured_at, updated_at
                )
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    mode = excluded.mode,
                    updated_at = excluded.updated_at
                """,
                (backup_mode, timestamp, timestamp),
            )
        return True

    def set_initial_read_credentials(
        self,
        *,
        expected_admin_hash: str,
        read_username: str,
        read_username_normalized: str,
        read_password_hash: str,
        backup_mode: str,
    ) -> bool:
        if backup_mode not in BACKUP_MODES:
            raise ValueError("Unsupported backup mode")
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
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    INSERT INTO backup_settings (
                        singleton_id, mode, configured_at, updated_at
                    )
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        mode = excluded.mode,
                        updated_at = excluded.updated_at
                    """,
                    (backup_mode, timestamp, timestamp),
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
                FROM notification_deliveries d
                WHERE NOT EXISTS (
                    SELECT 1 FROM alert_aliases a WHERE a.legacy_id = d.alert_id
                )
                GROUP BY status
                """
            ).fetchall()
            latest = connection.execute(
                """
                SELECT status, last_attempt_at, sent_at, last_error
                FROM notification_deliveries d
                WHERE NOT EXISTS (
                    SELECT 1 FROM alert_aliases a WHERE a.legacy_id = d.alert_id
                )
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
            "recipient_delivery": self.recipient_delivery_summary(),
        }

    def backup_settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            configured = connection.execute(
                """
                SELECT mode, configured_at, updated_at
                FROM backup_settings
                WHERE singleton_id = 1
                """
            ).fetchone()
            runtime = connection.execute(
                """
                SELECT status_json, updated_at
                FROM backup_runtime_status
                WHERE singleton_id = 1
                """
            ).fetchone()
        return {
            "configured": configured is not None,
            "mode": configured["mode"] if configured else "unconfigured",
            "configured_at": (
                configured["configured_at"] if configured else None
            ),
            "updated_at": configured["updated_at"] if configured else None,
            "runtime": (
                {
                    **json.loads(runtime["status_json"]),
                    "updated_at": runtime["updated_at"],
                }
                if runtime
                else None
            ),
        }

    def set_backup_settings(
        self,
        mode: str,
        *,
        only_if_unconfigured: bool = False,
    ) -> dict[str, Any] | None:
        if mode not in BACKUP_MODES:
            raise ValueError("Unsupported backup mode")
        timestamp = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            if only_if_unconfigured:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO backup_settings (
                        singleton_id, mode, configured_at, updated_at
                    )
                    VALUES (1, ?, ?, ?)
                    """,
                    (mode, timestamp, timestamp),
                )
                if cursor.rowcount != 1:
                    return None
            else:
                connection.execute(
                    """
                    INSERT INTO backup_settings (
                        singleton_id, mode, configured_at, updated_at
                    )
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        mode = excluded.mode,
                        updated_at = excluded.updated_at
                    """,
                    (mode, timestamp, timestamp),
                )
        return self.backup_settings()

    def set_backup_runtime_status(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()
        payload = json.dumps(status, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_runtime_status (
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

    def alert_model_initialized(self) -> bool:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM app_settings WHERE setting_key = 'alert_events_v2'"
            ).fetchone() is not None

    def remember_domain_reports(
        self,
        reports: list[dict[str, str]],
        domain: str = "*",
    ) -> list[dict[str, str]]:
        """Retain known report ends when index retention removes their reports."""
        normalized = []
        for report in reports:
            ended = datetime.fromisoformat(report["last_report"])
            if ended.tzinfo is None:
                raise ValueError("Report time must include its timezone")
            normalized.append(
                (report["domain"], ended.astimezone(UTC).isoformat())
            )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO domain_report_history (domain, last_report)
                VALUES (?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    last_report = excluded.last_report
                WHERE excluded.last_report > domain_report_history.last_report
                """,
                normalized,
            )
            self._sync_domain_monitoring(connection, [
                {"domain": name, "last_report": ended} for name, ended in normalized
            ])
            query = "SELECT domain, last_report FROM domain_report_history"
            parameters = ()
            if domain and domain != "*":
                query += " WHERE domain = ?"
                parameters = (domain,)
            rows = connection.execute(query + " ORDER BY domain", parameters).fetchall()
        return [dict(row) for row in rows]

    def save_alert_events(
        self,
        events: list[dict[str, Any]],
        *,
        bootstrap: bool = False,
        aliases: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Persist evidence snapshots without resetting workflow or delivery state.

        The first complete global scan records a quiet upgrade baseline. Subsequent
        previously unseen events are eligible for normal notifications. Bootstrap
        and its marker commit atomically, so a failed scan never suppresses events.
        """
        timestamp = datetime.now(UTC).isoformat()
        saved = []
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if bootstrap and connection.execute(
                "SELECT 1 FROM app_settings WHERE setting_key = 'alert_events_v2'"
            ).fetchone():
                bootstrap = False
            for event in events:
                payload = {key: value for key, value in event.items()
                           if key not in {"status", "status_updated_at", "notification_eligible"}}
                old = connection.execute(
                    "SELECT payload_json FROM alert_events WHERE alert_id = ?",
                    (event["id"],),
                ).fetchone()
                if old:
                    # A later historical backfill may change the inferred host
                    # history, but never silently change an observed event's type.
                    original = json.loads(old["payload_json"])
                    payload["kind"] = original["kind"]
                    payload["title"] = original["title"]
                # An explicitly added/resumed monitoring episode is new user
                # intent, even when its first due event coincides with bootstrap.
                explicit_expectation = (
                    bootstrap and event.get("kind") == "stale-reports"
                    and event.get("monitoring_episode_id")
                    and connection.execute(
                        "SELECT 1 FROM domain_monitoring WHERE domain = ? AND episode_id = ?",
                        (event.get("monitoring_domain"), event["monitoring_episode_id"]),
                    ).fetchone() is not None
                )
                connection.execute(
                    """
                    INSERT INTO alert_events VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(alert_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (event["id"], json.dumps(payload), timestamp, timestamp,
                     0 if bootstrap and not explicit_expectation else 1),
                )
            for legacy_id, event_id in (aliases or {}).items():
                existing = connection.execute(
                    "SELECT alert_id FROM alert_aliases WHERE legacy_id = ?", (legacy_id,)
                ).fetchone()
                if existing and existing["alert_id"] != event_id:
                    continue
                if not connection.execute(
                    "SELECT 1 FROM alert_events WHERE alert_id = ?", (event_id,)
                ).fetchone():
                    raise ValueError("A legacy alert alias requires a stored event")
                if legacy_id == event_id:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO alert_aliases VALUES (?, ?)",
                    (legacy_id, event_id),
                )
                connection.execute(
                    """
                    INSERT INTO alert_state (alert_id, status, updated_at)
                    SELECT ?, status, updated_at FROM alert_state WHERE alert_id = ?
                    ON CONFLICT(alert_id) DO UPDATE SET
                        status = excluded.status, updated_at = excluded.updated_at
                    WHERE excluded.updated_at > alert_state.updated_at
                    """, (event_id, legacy_id),
                )
                self._merge_alias_deliveries(connection, legacy_id, event_id)
            for event_id in set((aliases or {}).values()):
                # Resume only a positively identified unfinished delivery.
                connection.execute(
                    """
                    UPDATE alert_events SET notification_eligible = 1
                    WHERE alert_id = ? AND EXISTS (
                        SELECT 1 FROM notification_deliveries
                        WHERE alert_id = ? AND status != 'sent'
                    )
                    """, (event_id, event_id),
                )
            if bootstrap:
                connection.execute(
                    "INSERT INTO app_settings VALUES ('alert_events_v2', '1', ?)",
                    (timestamp,),
                )
            for event in events:
                saved.append(self._stored_alert(connection, event["id"]))
        return saved

    @staticmethod
    def _merge_alias_deliveries(
        connection: sqlite3.Connection,
        legacy_id: str,
        event_id: str,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM notification_deliveries WHERE alert_id = ?",
            (legacy_id,),
        ).fetchall()
        for legacy in rows:
            current = connection.execute(
                """
                SELECT * FROM notification_deliveries
                WHERE alert_id = ? AND destination_hash = ?
                """,
                (event_id, legacy["destination_hash"]),
            ).fetchone()
            selected = legacy
            if current and (
                current["status"] == "sent"
                or (
                    legacy["status"] != "sent"
                    and current["last_attempt_at"] > legacy["last_attempt_at"]
                )
            ):
                selected = current
            attempts = max(legacy["attempts"], current["attempts"] if current else 0)
            connection.execute(
                """
                INSERT INTO notification_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id, destination_hash) DO UPDATE SET
                    status = excluded.status, attempts = excluded.attempts,
                    last_attempt_at = excluded.last_attempt_at,
                    next_attempt_at = excluded.next_attempt_at,
                    sent_at = excluded.sent_at, last_error = excluded.last_error
                """,
                (event_id, selected["destination_hash"], selected["status"], attempts,
                 selected["last_attempt_at"], selected["next_attempt_at"],
                 selected["sent_at"], selected["last_error"]),
            )

    @staticmethod
    def _stored_alert(connection: sqlite3.Connection, alert_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT e.payload_json, e.notification_eligible, s.status, s.updated_at
            FROM alert_events e LEFT JOIN alert_state s ON e.alert_id = s.alert_id
            WHERE e.alert_id = ?
            """, (alert_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            **json.loads(row["payload_json"]),
            "notification_eligible": bool(row["notification_eligible"]),
            "status": row["status"] or "open",
            "status_updated_at": row["updated_at"],
        }

    def stored_alert(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            alias = connection.execute(
                "SELECT alert_id FROM alert_aliases WHERE legacy_id = ?", (alert_id,)
            ).fetchone()
            canonical_id = alias["alert_id"] if alias else alert_id
            result = self._stored_alert(connection, canonical_id)
            if result:
                return {**result, "historical": True}
            # Old versions persisted only hashes/status, never report snapshots.
            # Retain those links honestly instead of inventing missing evidence.
            state = connection.execute(
                "SELECT status, updated_at FROM alert_state WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            delivery = connection.execute(
                "SELECT 1 FROM notification_deliveries WHERE alert_id = ? LIMIT 1", (alert_id,)
            ).fetchone()
            if state or delivery:
                return {
                    "id": alert_id, "title": "Frühere Warnung", "priority": "info",
                    "domain": "*", "source_ip": None, "country": None,
                    "kind": "legacy", "report_time": None, "messages": 0,
                    "trigger": "Die frühere Version speicherte keinen Ereignisinhalt. Der Bearbeitungsstatus bleibt erhalten; Details stehen gegebenenfalls in der ursprünglichen E-Mail.",
                    "status": state["status"] if state else "open",
                    "status_updated_at": state["updated_at"] if state else None,
                    "historical": True, "notification_eligible": False,
                }
            return None

    def set_alert_status(self, alert_id: str, status: str) -> dict[str, str]:
        updated_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            alias = connection.execute(
                "SELECT alert_id FROM alert_aliases WHERE legacy_id = ?", (alert_id,)
            ).fetchone()
            if alias:
                alert_id = alias["alert_id"]
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
                SELECT source_ip, service_name, trust_status, notes, updated_at,
                       classification_mode
                FROM host_overrides
                """
            ).fetchall()
        return {
            row["source_ip"]: self._host_classification(row)
            for row in rows
        }

    @staticmethod
    def _host_classification(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return {
            "source_ip": row["source_ip"],
            "classification_mode": row["classification_mode"],
            "service_name": row["service_name"],
            "manual_service_name": row["service_name"],
            "trust_status": row["trust_status"],
            "notes": row["notes"],
            "updated_at": row["updated_at"],
        }

    def patch_host_classification(
        self, source_ip: str, changes: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"classification_mode", "manual_service_name", "trust_status", "notes"}
        if set(changes) - allowed:
            raise ValueError("Unsupported classification field")
        if "classification_mode" in changes and (
            not isinstance(changes["classification_mode"], str)
            or changes["classification_mode"] not in {"automatic", "manual"}
        ):
            raise ValueError("Unsupported classification mode")
        if "trust_status" in changes and (
            not isinstance(changes["trust_status"], str)
            or changes["trust_status"] not in {"automatic", "unconfirmed", "confirmed", "ignored"}
        ):
            raise ValueError("Unsupported trust status")

        updates = dict(changes)
        for field, label, limit in (
            ("manual_service_name", "Manual service name", 120),
            ("notes", "Notes", 500),
        ):
            if field not in updates or updates[field] is None:
                continue
            value = updates[field]
            if not isinstance(value, str):
                raise ValueError(f"{label} must be text or null")
            if len(value) > limit:
                raise ValueError(f"{label} must not exceed {limit} characters")
            updates[field] = value.strip() or None

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM host_overrides WHERE source_ip = ?", (source_ip,)
            ).fetchone()
            if not updates:
                if row is None:
                    raise ValueError("No classification changes were provided")
                return self._host_classification(row)
            current = dict(row) if row is not None else {
                "source_ip": source_ip, "classification_mode": "automatic",
                "service_name": None, "trust_status": "automatic", "notes": None,
            }
            for field in ("classification_mode", "trust_status", "notes"):
                if field in updates:
                    current[field] = updates[field]
            if "manual_service_name" in updates:
                current["service_name"] = updates["manual_service_name"]

            if current["classification_mode"] == "automatic":
                if updates.get("manual_service_name"):
                    raise ValueError("Choose manual classification before setting a service name")
                current["service_name"] = None
                if updates.get("classification_mode") == "automatic" and "trust_status" not in updates:
                    current["trust_status"] = "automatic"
            elif current["classification_mode"] == "manual" and not (
                current["service_name"] and current["service_name"].strip()
            ):
                raise ValueError("Manual service name is required")

            current["updated_at"] = datetime.now(UTC).isoformat()
            connection.execute("""
                INSERT INTO host_overrides (
                    source_ip, service_name, trust_status, notes, updated_at, classification_mode
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_ip) DO UPDATE SET
                    service_name = excluded.service_name,
                    trust_status = excluded.trust_status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at,
                    classification_mode = excluded.classification_mode
            """, (source_ip, current["service_name"], current["trust_status"],
                  current["notes"], current["updated_at"], current["classification_mode"]))
        return self._host_classification(current)

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
                    source_ip, service_name, trust_status, notes, updated_at, classification_mode
                )
                VALUES (?, ?, ?, ?, ?, 'legacy_preserved')
                ON CONFLICT(source_ip) DO UPDATE SET
                    service_name = excluded.service_name,
                    trust_status = excluded.trust_status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at,
                    classification_mode = 'legacy_preserved'
                """,
                (source_ip, service_name, trust_status, notes, updated_at),
            )
        return {
            "source_ip": source_ip,
            "service_name": service_name,
            "manual_service_name": service_name,
            "classification_mode": "legacy_preserved",
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
