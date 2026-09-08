"""Persistent recipient outcomes; legacy group outcomes remain an explicit hold."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any


def recipient_key(configuration: dict, recipient: str) -> str:
    identity = [configuration["transport"], configuration["sender"].casefold(),
                recipient.casefold()]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


class RecipientDeliveryStore:
    """Uses the StateStore connection and lock, including its existing aliases."""

    @staticmethod
    def initialize_recipient_deliveries(connection: sqlite3.Connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS notification_recipient_deliveries (
                alert_id TEXT NOT NULL,
                recipient_key TEXT NOT NULL,
                recipient TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                last_attempt_at TEXT NOT NULL,
                next_attempt_at TEXT,
                accepted_at TEXT,
                last_error TEXT,
                smtp_code INTEGER,
                PRIMARY KEY (alert_id, recipient_key)
            )
        """)

    def claim_notification_recipients(
        self, *, alert_id: str, configuration: dict, max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        stale_before = (now - timedelta(minutes=15)).isoformat()
        claims = []
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            alias = connection.execute(
                "SELECT alert_id FROM alert_aliases WHERE legacy_id = ?", (alert_id,),
            ).fetchone()
            alert_id = alias["alert_id"] if alias else alert_id
            # The old group hash cannot establish which recipients accepted mail.
            # Keep all old attempts intact and hold this event across config changes.
            legacy = connection.execute("""
                SELECT 1 FROM notification_deliveries d
                WHERE d.alert_id = ? OR d.alert_id IN (
                    SELECT legacy_id FROM alert_aliases WHERE alert_id = ?
                ) LIMIT 1
            """, (alert_id, alert_id)).fetchone()
            if legacy:
                return []
            seen = set()
            for recipient in configuration["recipients"]:
                key = recipient_key(configuration, recipient)
                if key in seen:
                    continue
                seen.add(key)
                row = connection.execute("""
                    SELECT * FROM notification_recipient_deliveries
                    WHERE alert_id = ? AND recipient_key = ?
                """, (alert_id, key)).fetchone()
                if row:
                    if row["status"] in {"accepted", "permanent_failure", "exhausted"}:
                        continue
                    if row["status"] == "sending" and row["last_attempt_at"] > stale_before:
                        continue
                    if row["attempts"] >= max_attempts:
                        connection.execute("""
                            UPDATE notification_recipient_deliveries
                            SET status = 'exhausted', next_attempt_at = NULL
                            WHERE alert_id = ? AND recipient_key = ?
                        """, (alert_id, key))
                        continue
                    if row["next_attempt_at"] and row["next_attempt_at"] > timestamp:
                        continue
                attempt = row["attempts"] + 1 if row else 1
                connection.execute("""
                    INSERT INTO notification_recipient_deliveries
                        (alert_id, recipient_key, recipient, status, attempts, last_attempt_at)
                    VALUES (?, ?, ?, 'sending', ?, ?)
                    ON CONFLICT(alert_id, recipient_key) DO UPDATE SET
                        recipient = excluded.recipient, status = 'sending',
                        attempts = excluded.attempts, last_attempt_at = excluded.last_attempt_at,
                        next_attempt_at = NULL, last_error = NULL, smtp_code = NULL
                """, (alert_id, key, recipient, attempt, timestamp))
                claims.append({"alert_id": alert_id, "recipient_key": key,
                               "recipient": recipient, "attempt": attempt})
        return claims

    def finish_notification_recipient(
        self, *, claim: dict, status: str, error: str | None = None,
        smtp_code: int | None = None, max_attempts: int = 3,
    ) -> None:
        if status not in {"accepted", "temporary_failure", "permanent_failure"}:
            raise ValueError("Unknown recipient delivery outcome")
        now = datetime.now(UTC)
        next_attempt = None
        if status == "temporary_failure":
            if claim["attempt"] >= max_attempts:
                status = "exhausted"
            else:
                next_attempt = (now + timedelta(minutes=5 * 2 ** (claim["attempt"] - 1))).isoformat()
        with self._lock, self._connect() as connection:
            # An expired attempt cannot overwrite a newer worker's claim/result.
            connection.execute("""
                UPDATE notification_recipient_deliveries
                SET status = ?, next_attempt_at = ?, accepted_at = ?,
                    last_error = ?, smtp_code = ?
                WHERE alert_id = ? AND recipient_key = ?
                  AND status = 'sending' AND attempts = ?
            """, (status, next_attempt, now.isoformat() if status == "accepted" else None,
                  None if status == "accepted" else (error or "Notification delivery failed")[:500],
                  smtp_code, claim["alert_id"], claim["recipient_key"], claim["attempt"]))

    def recipient_delivery_summary(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("""
                SELECT status, COUNT(*) AS count FROM notification_recipient_deliveries
                GROUP BY status
            """).fetchall()
            items = connection.execute("""
                SELECT alert_id, recipient, status, attempts, last_attempt_at,
                       next_attempt_at, accepted_at, last_error, smtp_code
                FROM notification_recipient_deliveries
                ORDER BY last_attempt_at DESC, alert_id, recipient LIMIT 100
            """).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {"accepted": counts.get("accepted", 0),
                "temporary_failure": counts.get("temporary_failure", 0),
                "permanent_failure": counts.get("permanent_failure", 0),
                "exhausted": counts.get("exhausted", 0),
                "pending": counts.get("sending", 0),
                "items": [dict(row) for row in items], "limit": 100,
                "total": sum(counts.values())}
