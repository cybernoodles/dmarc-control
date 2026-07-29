from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
