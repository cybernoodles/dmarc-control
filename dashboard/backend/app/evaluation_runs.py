"""Durable automatic evaluation status, independent of notification delivery."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


_HISTORY_LIMIT = 20
_COUNT_FIELDS = ("events", "domains", "hosts")
_INTERRUPTED_MESSAGE = "Der vorherige Prüflauf wurde durch einen Neustart unterbrochen."


def _scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Store only the public scope fields, never a complete configuration."""
    domain = scope.get("domain", "*")
    days = scope.get("days", 30)
    cases = scope.get("cases", [])
    if not isinstance(domain, str) or not domain or len(domain) > 255:
        raise ValueError("Evaluation domain is invalid")
    if type(days) is not int or not 1 <= days <= 730:
        raise ValueError("Evaluation days must be between 1 and 730")
    if not isinstance(cases, list) or any(
        not isinstance(case, str) or len(case) > 100 for case in cases
    ):
        raise ValueError("Evaluation cases must be short strings")
    return {"domain": domain, "days": days, "cases": list(dict.fromkeys(cases))}


def _counts(counts: dict[str, int | None] | None) -> dict[str, int | None]:
    values = {key: (counts or {}).get(key) for key in _COUNT_FIELDS}
    if any(value is not None and (type(value) is not int or value < 0)
           for value in values.values()):
        raise ValueError("Evaluation counts must be non-negative integers or null")
    return values


class EvaluationRunStore:
    """Uses the StateStore connection/lock; errors must be public caller messages."""

    @staticmethod
    def initialize_evaluation_runs(connection: sqlite3.Connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL CHECK (
                    status IN ('running', 'success', 'failure', 'interrupted')
                ),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                scope_json TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                error TEXT
            )
        """)

    @staticmethod
    def _prune_evaluation_runs(connection: sqlite3.Connection) -> None:
        # Keep recent runs, every unfinished run and the most recent success
        # even when a prolonged outage makes that success much older.
        connection.execute("""
            DELETE FROM evaluation_runs
            WHERE status != 'running'
              AND run_id NOT IN (
                  SELECT run_id FROM evaluation_runs ORDER BY run_id DESC LIMIT ?
              )
              AND run_id != COALESCE((
                  SELECT MAX(run_id) FROM evaluation_runs WHERE status = 'success'
              ), -1)
        """, (_HISTORY_LIMIT,))

    def start_evaluation(self, scope: dict[str, Any]) -> int:
        public_scope = _scope(scope)
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("""
                INSERT INTO evaluation_runs (status, started_at, scope_json, counts_json)
                VALUES ('running', ?, ?, ?)
            """, (now, json.dumps(public_scope), json.dumps(_counts(None))))
            run_id = int(cursor.lastrowid)
            self._prune_evaluation_runs(connection)
        return run_id

    def finish_evaluation(
        self,
        run_id: int,
        status: str,
        duration_ms: int,
        counts: dict[str, int | None] | None = None,
        error: str | None = None,
    ) -> bool:
        """Finish only this still-running attempt; repeated/late finishes are inert.

        The caller must supply a categorized public message, never raw transport
        responses, exception strings or credentials. No traceback is persisted.
        """
        if status not in {"success", "failure", "interrupted"}:
            raise ValueError("Evaluation outcome is invalid")
        if type(duration_ms) is not int or duration_ms < 0:
            raise ValueError("Evaluation duration must be non-negative milliseconds")
        if error is not None and not isinstance(error, str):
            raise ValueError("Evaluation errors must be public text")
        public_counts = _counts(counts)
        public_error = " ".join(error.split())[:500] if error else None
        if status == "success":
            public_error = None
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("""
                UPDATE evaluation_runs
                SET status = ?, finished_at = ?, duration_ms = ?, counts_json = ?, error = ?
                WHERE run_id = ? AND status = 'running'
            """, (status, now, duration_ms, json.dumps(public_counts), public_error, run_id))
            changed = cursor.rowcount == 1
            self._prune_evaluation_runs(connection)
        return changed

    def interrupt_running_evaluations(self) -> int:
        """Called once at application startup, before starting the new worker."""
        now = datetime.now(UTC)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                "SELECT run_id, started_at FROM evaluation_runs WHERE status = 'running'"
            ).fetchall()
            for row in running:
                elapsed = now - datetime.fromisoformat(row["started_at"])
                connection.execute("""
                    UPDATE evaluation_runs
                    SET status = 'interrupted', finished_at = ?, duration_ms = ?, error = ?
                    WHERE run_id = ? AND status = 'running'
                """, (now.isoformat(), max(0, int(elapsed.total_seconds() * 1000)),
                      _INTERRUPTED_MESSAGE, row["run_id"]))
            self._prune_evaluation_runs(connection)
        return len(running)

    @staticmethod
    def _evaluation_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["run_id"], "status": row["status"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "scope": json.loads(row["scope_json"]),
            "counts": json.loads(row["counts_json"]), "error": row["error"],
        }

    def evaluation_status(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            # One read transaction presents a coherent latest/last-success pair.
            connection.execute("BEGIN")
            latest = connection.execute(
                "SELECT * FROM evaluation_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            last_success = connection.execute("""
                SELECT * FROM evaluation_runs WHERE status = 'success'
                ORDER BY run_id DESC LIMIT 1
            """).fetchone()
        return {
            "latest": self._evaluation_run(latest),
            "last_success": self._evaluation_run(last_success),
        }
