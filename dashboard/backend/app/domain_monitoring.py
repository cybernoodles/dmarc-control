"""Domain-level freshness lifecycle, separate from report and alert history."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import idna


UNSET = object()
_DATETIME_TYPE = datetime


def canonical_domain(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid domain name")
    name = value.strip()
    try:
        normalized = idna.encode(
            name, uts46=True, std3_rules=True, transitional=False,
        ).decode("ascii").removesuffix(".").lower()
    except UnicodeError as exc:
        raise ValueError("Invalid domain name") from exc
    if not 1 <= len(normalized) <= 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in normalized.split(".")
    ):
        raise ValueError("Invalid domain name")
    return normalized


def _now(value: datetime | None = None) -> datetime:
    result = datetime.now(UTC) if value is None else value
    if not isinstance(result, _DATETIME_TYPE) or result.tzinfo is None:
        raise ValueError("Monitoring time must include its timezone")
    return result.astimezone(UTC)


def _grace(value: Any) -> int | None:
    if value is not None and (type(value) is not int or not 1 <= value <= 365):
        raise ValueError("Grace period must be between 1 and 365 days")
    return value


def _public(row: dict[str, Any], default_grace_days: int, aliases: list[str]) -> dict[str, Any]:
    grace = row["grace_days"] if row["grace_days"] is not None else default_grace_days
    last_report, started = row["last_report"], row["monitoring_started_at"]
    anchor = max((datetime.fromisoformat(value) for value in (last_report, started) if value), default=None)
    reason = "report_gap"
    if last_report is None:
        reason = "never_observed"
    elif row["episode_reason"] == "reactivated" and started and datetime.fromisoformat(started) > datetime.fromisoformat(last_report):
        reason = "reactivated"
    return {
        "domain": row["domain"], "query_domain": row["report_domain"] or row["domain"],
        "aliases": aliases, "state": row["state"], "last_report": last_report,
        "monitoring_started_at": started, "monitoring_episode_id": row["episode_id"],
        "grace_days": grace, "configured_grace_days": row["grace_days"],
        "deadline": (anchor + timedelta(days=grace)).isoformat() if anchor and row["state"] != "retired" else None,
        "observed": last_report is not None, "freshness_reason": reason,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def domain_freshness_event(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """Build the current freshness event, preserving pre-registry event IDs."""
    instant = _now(now)
    if item["state"] == "retired" or not item["deadline"] or instant <= datetime.fromisoformat(item["deadline"]):
        return None
    last_report, started = item["last_report"], item["monitoring_started_at"]
    reason = item["freshness_reason"]
    if started is None:
        parts = ("v2", "stale-reports", item["query_domain"], "all", last_report[:10])
    else:
        # The episode separates a resumed expectation from an earlier resolved
        # outage; the report day still separates later genuinely new gaps.
        parts = ("v2", "stale-reports", item["domain"], "monitoring",
                 item["monitoring_episode_id"], reason, last_report[:10] if last_report else "first-report")
    if reason == "never_observed":
        title = "Erster DMARC-Report fehlt"
        trigger = "Seit Beginn der Überwachung wurden keine DMARC-Reports beobachtet; die Wartefrist ist abgelaufen"
    elif reason == "reactivated":
        title = "Kein neuer DMARC-Report nach Reaktivierung"
        trigger = "Seit der Reaktivierung ist kein neuer Berichtszeitraum eingegangen; die Wartefrist ist abgelaufen"
    else:
        title = "DMARC-Reports bleiben aus"
        age = instant - datetime.fromisoformat(last_report)
        trigger = f"Letzter Berichtszeitraum endete vor {age.days} Tagen; übliche Zustellverzögerung berücksichtigt"
    return {
        "id": hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:20],
        "priority": "warning", "kind": "stale-reports", "title": title,
        "source_ip": None, "country": None, "domain": item["query_domain"],
        "monitoring_domain": item["domain"], "freshness_reason": reason,
        "monitoring_started_at": started, "monitoring_episode_id": item["monitoring_episode_id"],
        "grace_days": item["grace_days"], "deadline": item["deadline"],
        "trigger": trigger, "report_time": last_report, "messages": 0, "total_messages": 0,
    }


class DomainMonitoringStore:
    @staticmethod
    def initialize_domain_monitoring(connection: sqlite3.Connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS domain_monitoring (
                domain TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK (state IN ('active', 'expected', 'retired')),
                report_domain TEXT,
                last_report TEXT,
                monitoring_started_at TEXT,
                episode_id TEXT,
                episode_reason TEXT,
                grace_days INTEGER CHECK (grace_days IS NULL OR grace_days BETWEEN 1 AND 365),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        history = connection.execute("SELECT domain,last_report FROM domain_report_history ORDER BY domain").fetchall()
        DomainMonitoringStore._sync_domain_monitoring(connection, [dict(row) for row in history])

    @staticmethod
    def _sync_domain_monitoring(connection: sqlite3.Connection, reports: list[dict[str, str]]) -> None:
        timestamp = datetime.now(UTC).isoformat()
        for report in sorted(reports, key=lambda item: item["domain"]):
            try:
                key = canonical_domain(report["domain"])
            except ValueError:
                # Invalid historical values keep the old freshness path; they
                # must not break a complete evaluation or become manual inputs.
                continue
            ended = datetime.fromisoformat(report["last_report"])
            if ended.tzinfo is None:
                raise ValueError("Report time must include its timezone")
            last_report = ended.astimezone(UTC).isoformat()
            connection.execute("""
                INSERT INTO domain_monitoring
                    (domain,state,report_domain,last_report,created_at,updated_at)
                VALUES (?, 'active', ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    state = CASE WHEN domain_monitoring.state = 'expected' THEN 'active' ELSE domain_monitoring.state END,
                    report_domain = excluded.report_domain,
                    last_report = excluded.last_report,
                    updated_at = excluded.updated_at
                WHERE domain_monitoring.last_report IS NULL OR excluded.last_report > domain_monitoring.last_report
            """, (key, report["domain"], last_report, timestamp, timestamp))

    @staticmethod
    def _monitoring_rows(connection: sqlite3.Connection, default_grace_days: int, domain: str) -> list[dict[str, Any]]:
        aliases: dict[str, list[str]] = {}
        for report in connection.execute("SELECT domain FROM domain_report_history ORDER BY domain"):
            try:
                key = canonical_domain(report["domain"])
            except ValueError:
                continue
            aliases.setdefault(key, []).append(report["domain"])
        query = "SELECT * FROM domain_monitoring"
        parameters: tuple = ()
        if domain and domain != "*":
            try:
                key = canonical_domain(domain)
            except ValueError:
                return []
            query += " WHERE domain = ?"
            parameters = (key,)
        return [_public(dict(row), default_grace_days, aliases.get(row["domain"], []))
                for row in connection.execute(query + " ORDER BY domain", parameters)]

    def list_domain_monitoring(self, default_grace_days: int = 3, domain: str = "*") -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            return self._monitoring_rows(connection, default_grace_days, domain)

    def add_domain_monitoring(self, domain: str, grace_days: int | None = None,
                              now: datetime | None = None, default_grace_days: int = 3) -> dict[str, Any]:
        key, grace, timestamp = canonical_domain(domain), _grace(grace_days), _now(now).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM domain_monitoring WHERE domain = ?", (key,)).fetchone():
                raise ValueError("Domain is already monitored")
            connection.execute("""
                INSERT INTO domain_monitoring
                    (domain,state,monitoring_started_at,episode_id,episode_reason,grace_days,created_at,updated_at)
                VALUES (?, 'expected', ?, ?, 'expected', ?, ?, ?)
            """, (key, timestamp, uuid.uuid4().hex, grace, timestamp, timestamp))
            return self._monitoring_rows(connection, default_grace_days, key)[0]

    def update_domain_monitoring(self, domain: str, state: str | None = None,
                                 grace_days: Any = UNSET, now: datetime | None = None,
                                 default_grace_days: int = 3) -> dict[str, Any]:
        key = canonical_domain(domain)
        if state is not None and (not isinstance(state, str) or state not in {"active", "expected", "retired"}):
            raise ValueError("Invalid monitoring state")
        if grace_days is not UNSET:
            _grace(grace_days)
        timestamp = _now(now).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT * FROM domain_monitoring WHERE domain = ?", (key,)).fetchone()
            if previous is None:
                raise KeyError("Domain not found")
            row = dict(previous)
            desired_state = row["state"] if state is None else state
            desired_grace = row["grace_days"] if grace_days is UNSET else grace_days
            if desired_state == "expected" and row["last_report"] is not None:
                raise ValueError("Observed domains cannot be set to expected")
            if desired_state == "active" and row["last_report"] is None:
                raise ValueError("Domains without reports must be set to expected")
            if desired_state == row["state"] and desired_grace == row["grace_days"]:
                return self._monitoring_rows(connection, default_grace_days, key)[0]
            if row["state"] == "retired" and desired_state != "retired":
                row.update(monitoring_started_at=timestamp, episode_id=uuid.uuid4().hex, episode_reason="reactivated")
            connection.execute("""
                UPDATE domain_monitoring SET state=?, grace_days=?, monitoring_started_at=?,
                    episode_id=?, episode_reason=?, updated_at=? WHERE domain=?
            """, (desired_state, desired_grace, row["monitoring_started_at"], row["episode_id"],
                  row["episode_reason"], timestamp, key))
            return self._monitoring_rows(connection, default_grace_days, key)[0]

    def domain_freshness_allows(self, alert: dict[str, Any], default_grace_days: int,
                               now: datetime | None = None) -> bool:
        if alert.get("kind") != "stale-reports":
            return True
        key = alert.get("monitoring_domain") or alert.get("domain")
        if not isinstance(key, str) or key in {"", "*"}:
            return False
        try:
            canonical = canonical_domain(key)
        except ValueError:
            # Historical malformed names retain their exact report key. This
            # check is read-only and does not need to resynchronize inventory.
            with self._lock, self._connect() as connection:
                report = connection.execute(
                    "SELECT domain,last_report FROM domain_report_history WHERE domain = ?", (key,),
                ).fetchone()
            current = domain_freshness_event(legacy_domain_monitoring(dict(report), default_grace_days), now) if report else None
            return current is not None and current["id"] == alert.get("id")
        # Read this domain's current lifecycle immediately before the claim.
        # Alias lists are only presentation data; constructing all of them for
        # every alert made a complete dispatch cycle quadratic in domain count.
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM domain_monitoring WHERE domain = ?", (canonical,),
            ).fetchone()
        current = domain_freshness_event(_public(dict(row), default_grace_days, []), now) if row else None
        return (
            current is not None and current["id"] == alert.get("id")
            and ("deadline" not in alert or current["deadline"] == alert["deadline"])
        )


def legacy_domain_monitoring(report: dict[str, str], default_grace_days: int) -> dict[str, Any]:
    """Represent an invalid historical name without changing its old event key."""
    return _public({
        "domain": report["domain"], "report_domain": report["domain"], "state": "active",
        "last_report": report["last_report"], "monitoring_started_at": None,
        "episode_id": None, "episode_reason": None, "grace_days": None,
        "created_at": None, "updated_at": None,
    }, default_grace_days, [report["domain"]])
