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

    @staticmethod
    def _alert_delivery_scope(
        connection: sqlite3.Connection, alert_ids: list[str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        aliases = {
            row["legacy_id"]: row["alert_id"]
            for row in connection.execute("SELECT legacy_id, alert_id FROM alert_aliases")
        }
        resolved: dict[str, str] = {}

        def canonical(alert_id: str) -> str:
            visited = set()
            current = alert_id
            while current in aliases and current not in resolved:
                if current in visited:
                    raise ValueError("Cyclic alert aliases")
                visited.add(current)
                current = aliases[current]
            result = resolved.get(current, current)
            for previous in visited:
                resolved[previous] = result
            return result

        requested = {alert_id: canonical(alert_id) for alert_id in alert_ids}
        selected = set(requested.values())
        sources = {alert_id: alert_id for alert_id in selected}
        for legacy_id in aliases:
            target = canonical(legacy_id)
            if target in selected:
                sources[legacy_id] = target
        return requested, sources

    @staticmethod
    def _empty_alert_delivery_summary(alert_id: str) -> dict[str, Any]:
        return {
            "alert_id": alert_id, "mode": "none", "accepted": 0,
            "temporary_failure": 0, "permanent_failure": 0,
            "exhausted": 0, "pending": 0, "total": 0, "attempts_total": 0,
            "last_attempt_at": None, "next_attempt_at": None,
            "legacy": {
                "total": 0, "sent": 0, "failed": 0, "pending": 0,
                "attempts_total": 0, "last_attempt_at": None,
            },
        }

    @staticmethod
    def _alert_delivery_summaries(
        connection: sqlite3.Connection, sources: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        summaries = {
            alert_id: RecipientDeliveryStore._empty_alert_delivery_summary(alert_id)
            for alert_id in set(sources.values())
        }
        source_ids = list(sources)
        legacy_groups: dict[tuple[str, str], dict[str, Any]] = {}
        for offset in range(0, len(source_ids), 400):
            batch = source_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in batch)
            # Read only aggregate metadata here: addresses and transport errors
            # are loaded exclusively by the administrator detail method.
            rows = connection.execute(f"""
                SELECT alert_id, status, COUNT(*) AS count,
                       SUM(attempts) AS attempts_total,
                       MAX(last_attempt_at) AS last_attempt_at,
                       MIN(CASE WHEN status = 'temporary_failure'
                                THEN next_attempt_at END) AS next_attempt_at
                FROM notification_recipient_deliveries
                WHERE alert_id IN ({placeholders})
                GROUP BY alert_id, status
            """, batch).fetchall()
            for row in rows:
                summary = summaries[sources[row["alert_id"]]]
                status = "pending" if row["status"] == "sending" else row["status"]
                if status not in {
                    "accepted", "temporary_failure", "permanent_failure", "exhausted", "pending",
                }:
                    raise ValueError("Unknown recipient delivery status")
                summary[status] += row["count"]
                summary["total"] += row["count"]
                summary["attempts_total"] += row["attempts_total"]
                latest = summary["last_attempt_at"]
                if latest is None or row["last_attempt_at"] > latest:
                    summary["last_attempt_at"] = row["last_attempt_at"]
                upcoming = row["next_attempt_at"]
                if upcoming and (
                    summary["next_attempt_at"] is None or upcoming < summary["next_attempt_at"]
                ):
                    summary["next_attempt_at"] = upcoming

            rows = connection.execute(f"""
                SELECT alert_id, destination_hash, status, attempts, last_attempt_at
                FROM notification_deliveries WHERE alert_id IN ({placeholders})
            """, batch).fetchall()
            for row in rows:
                key = (sources[row["alert_id"]], row["destination_hash"])
                previous = legacy_groups.get(key)
                if previous is None:
                    legacy_groups[key] = dict(row)
                    continue
                # Migration retains the old row and a canonical copy. Match the
                # existing migration rule without counting that evidence twice.
                if row["status"] == "sent" or (
                    previous["status"] != "sent"
                    and row["last_attempt_at"] > previous["last_attempt_at"]
                ):
                    previous["status"] = row["status"]
                previous["attempts"] = max(previous["attempts"], row["attempts"])
                previous["last_attempt_at"] = max(
                    previous["last_attempt_at"], row["last_attempt_at"]
                )

        for (alert_id, _), row in legacy_groups.items():
            summary = summaries[alert_id]
            legacy = summary["legacy"]
            status = "pending" if row["status"] == "sending" else row["status"]
            if status not in {"sent", "failed", "pending"}:
                raise ValueError("Unknown legacy delivery status")
            legacy[status] += 1
            legacy["total"] += 1
            legacy["attempts_total"] += row["attempts"]
            if legacy["last_attempt_at"] is None or row["last_attempt_at"] > legacy["last_attempt_at"]:
                legacy["last_attempt_at"] = row["last_attempt_at"]
            if summary["last_attempt_at"] is None or row["last_attempt_at"] > summary["last_attempt_at"]:
                summary["last_attempt_at"] = row["last_attempt_at"]

        for summary in summaries.values():
            if summary["legacy"]["total"]:
                summary["mode"] = "legacy_hold"
                # No automatic recipient retry is allowed while an old group
                # outcome exists, even if recipient records also exist.
                summary["next_attempt_at"] = None
            elif not summary["total"]:
                summary["mode"] = "none"
            elif summary["accepted"] == summary["total"]:
                summary["mode"] = "accepted"
            elif summary["accepted"]:
                summary["mode"] = "partial"
            elif summary["temporary_failure"] or summary["pending"]:
                summary["mode"] = "pending"
            else:
                summary["mode"] = "failed"
        return summaries

    def alert_delivery_summaries(self, alert_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return read-safe outcomes keyed by requested ID, resolving aliases.

        ``total`` and ``attempts_total`` cover recorded recipient outcomes;
        legacy group evidence remains separate. ``next_attempt_at`` is only a
        known retry lower bound, not a scheduled send or proof of active setup.
        Unknown IDs have mode ``none``; API callers validate event existence.
        """
        if not alert_ids:
            return {}
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            requested, sources = self._alert_delivery_scope(connection, alert_ids)
            summaries = self._alert_delivery_summaries(connection, sources)
        return {
            requested_id: {**summaries[canonical], "legacy": dict(summaries[canonical]["legacy"])}
            for requested_id, canonical in requested.items()
        }

    def alert_delivery_details(self, alert_id: str) -> dict[str, Any]:
        """Administrator-only recipient details, bounded to 100 recent records.

        Authorization belongs to the API caller. Reading this method does not
        claim attempts, alter outcomes or enable notifications.
        """
        limit = 100
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            requested, sources = self._alert_delivery_scope(connection, [alert_id])
            canonical = requested[alert_id]
            summary = self._alert_delivery_summaries(connection, sources)[canonical]
            items = []
            source_ids = list(sources)
            for offset in range(0, len(source_ids), 400):
                batch = source_ids[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(f"""
                    SELECT alert_id, recipient, status, attempts, last_attempt_at,
                           next_attempt_at, accepted_at, last_error, smtp_code
                    FROM notification_recipient_deliveries
                    WHERE alert_id IN ({placeholders})
                    ORDER BY last_attempt_at DESC, alert_id DESC, recipient DESC LIMIT ?
                """, [*batch, limit]).fetchall()
                items.extend(dict(row) for row in rows)
            items.sort(
                key=lambda item: (item["last_attempt_at"], item["alert_id"], item["recipient"]),
                reverse=True,
            )
        return {
            **summary, "limit": limit,
            "items": [{**item, "alert_id": canonical} for item in items[:limit]],
        }
