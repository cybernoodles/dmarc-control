from __future__ import annotations

import sqlite3
import threading
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
