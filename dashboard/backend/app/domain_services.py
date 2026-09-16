"""Persistent domain-specific expectations for detected sending services."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .domain_monitoring import canonical_domain


DOMAIN_SERVICE_DECISIONS = {"automatic", "confirmed", "rejected"}
SERVICE_IDS = ("microsoft365",)
DNS_STATUSES = {"fresh", "negative", "invalid", "unavailable"}
DNS_ASSESSMENTS = {"unknown", "configured", "strong"}
DNS_CONFIGURED_ASSESSMENTS = {"configured", "strong"}
_SERVICE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]{0,119})$")
_MISSING = object()
_DNS_COLUMNS = {
    "domain", "service_id", "assessment_json", "dns_status", "assessment",
    "assessed_at", "expires_at", "updated_at",
}


def canonical_service_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid service ID")
    service_id = value.strip().lower()
    if not _SERVICE_ID.fullmatch(service_id):
        raise ValueError("Invalid service ID")
    return service_id


def _now(value: datetime | None = None) -> datetime:
    result = datetime.now(UTC) if value is None else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError("Assessment time must include its timezone")
    return result.astimezone(UTC)


def _timestamp(value: Any, label: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{label} must include its timezone")
    return result.astimezone(UTC).isoformat()


def _count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _observation_value(observation: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in observation:
            return observation[name]
    return _MISSING


def _validated_observation(
    domain: str,
    service_id: str,
    observation: dict[str, Any],
) -> tuple[str, str, tuple[int, int, int, int, str | None]]:
    key, service = canonical_domain(domain), canonical_service_id(service_id)
    if not isinstance(observation, dict):
        raise ValueError("Service observation must be an object")
    raw_messages = _observation_value(observation, "messages")
    raw_pass = _observation_value(observation, "pass", "dmarc_pass", "passed")
    raw_fail = _observation_value(observation, "fail", "dmarc_fail", "failed")
    raw_days = _observation_value(observation, "distinct_days")
    if _MISSING in (raw_messages, raw_pass, raw_fail, raw_days):
        raise ValueError("Service observation is incomplete")
    messages = _count(raw_messages, "messages")
    passed = _count(raw_pass, "pass")
    failed = _count(raw_fail, "fail")
    distinct_days = _count(raw_days, "distinct_days")
    if passed + failed > messages:
        raise ValueError("pass and fail counts must not exceed messages")
    last_seen = _timestamp(
        observation.get("last_seen"), "last_seen", optional=True,
    )
    return key, service, (messages, passed, failed, distinct_days, last_seen)


def _create_dns_assessment_table(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE domain_service_dns_assessments (
            domain TEXT NOT NULL,
            service_id TEXT NOT NULL,
            assessment_json TEXT NOT NULL,
            dns_status TEXT NOT NULL CHECK (
                dns_status IN ('fresh', 'negative', 'invalid', 'unavailable')
            ),
            assessment TEXT NOT NULL CHECK (
                assessment IN ('unknown', 'configured', 'strong')
            ),
            assessed_at TEXT NOT NULL,
            expires_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (domain, service_id)
        )
    """)


def _migrate_dns_assessment_table(connection: sqlite3.Connection) -> None:
    """Upgrade the short-lived single-status schema without losing snapshots."""
    legacy = "domain_service_dns_assessments_legacy"
    connection.execute(f"DROP TABLE IF EXISTS {legacy}")
    connection.execute(
        "ALTER TABLE domain_service_dns_assessments "
        f"RENAME TO {legacy}"
    )
    _create_dns_assessment_table(connection)
    for row in connection.execute(f"SELECT * FROM {legacy}"):
        columns = set(row.keys())
        try:
            snapshot = json.loads(row["assessment_json"])
        except (TypeError, ValueError):
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {"legacy_snapshot": snapshot}
        service_value = snapshot.get("service_id", SERVICE_IDS[0])
        try:
            service_id = canonical_service_id(service_value)
        except ValueError:
            service_id = SERVICE_IDS[0]

        legacy_status = row["status"] if "status" in columns else None
        dns_status = snapshot.get("dns_status")
        if dns_status not in DNS_STATUSES:
            dns_status = (
                legacy_status if legacy_status in DNS_STATUSES
                else "fresh" if legacy_status in {"configured", "verified"}
                else "unavailable"
            )
        assessment = snapshot.get("assessment")
        if assessment not in DNS_ASSESSMENTS:
            assessment = (
                "configured" if legacy_status in {"configured", "verified"}
                else "unknown"
            )
        if dns_status != "fresh":
            assessment = "unknown"
        raw_assessed_at = (
            snapshot.get("assessed_at")
            or (row["fetched_at"] if "fetched_at" in columns else None)
            or row["updated_at"]
        )
        raw_expires_at = (
            row["expires_at"] if "expires_at" in columns else None
        )
        migration_valid = True
        try:
            assessed_at = _timestamp(raw_assessed_at, "legacy assessed_at")
        except ValueError:
            assessed_at = datetime(1970, 1, 1, tzinfo=UTC).isoformat()
            migration_valid = False
        try:
            expires_at = _timestamp(
                raw_expires_at, "legacy expires_at", optional=True,
            )
        except ValueError:
            expires_at = None
            migration_valid = False
        if expires_at is None:
            # Current snapshots always require an expiry.  A legacy row without
            # one is retained for audit, but must never remain trusted forever.
            expires_at = assessed_at
            migration_valid = False
        try:
            updated_at = _timestamp(row["updated_at"], "legacy updated_at")
        except ValueError:
            updated_at = assessed_at
            migration_valid = False
        if not migration_valid:
            dns_status = "unavailable"
            assessment = "unknown"
        snapshot.update(
            service_id=service_id,
            dns_status=dns_status,
            assessment=assessment,
            assessed_at=assessed_at,
            expires_at=expires_at,
        )
        connection.execute(f"""
            INSERT INTO domain_service_dns_assessments (
                domain, service_id, assessment_json, dns_status, assessment,
                assessed_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["domain"], service_id,
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            dns_status, assessment, assessed_at, expires_at, updated_at,
        ))
    connection.execute(f"DROP TABLE {legacy}")


class DomainServiceStore:
    """Uses the StateStore lock and connection for service expectation snapshots."""

    @staticmethod
    def initialize_domain_services(connection: sqlite3.Connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS domain_service_policies (
                domain TEXT NOT NULL,
                service_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (
                    decision IN ('automatic', 'confirmed', 'rejected')
                ),
                effective_from TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (domain, service_id)
            )
        """)
        dns_table = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'domain_service_dns_assessments'
        """).fetchone()
        if dns_table is None:
            _create_dns_assessment_table(connection)
        else:
            dns_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(domain_service_dns_assessments)"
                )
            }
            if not _DNS_COLUMNS <= dns_columns:
                _migrate_dns_assessment_table(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS domain_service_observations (
                domain TEXT NOT NULL,
                service_id TEXT NOT NULL,
                messages INTEGER NOT NULL CHECK (messages >= 0),
                pass_messages INTEGER NOT NULL CHECK (pass_messages >= 0),
                fail_messages INTEGER NOT NULL CHECK (fail_messages >= 0),
                distinct_days INTEGER NOT NULL CHECK (distinct_days >= 0),
                last_seen TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (domain, service_id),
                CHECK (pass_messages + fail_messages <= messages)
            )
        """)

    @staticmethod
    def _dns_public(row: dict[str, Any] | sqlite3.Row | None,
                    instant: datetime) -> dict[str, Any]:
        if row is None:
            return {
                "dns_status": "unavailable", "assessment": "unknown",
                "evidence": [], "contradictions": [], "assessed_at": None,
                "dns_fetched_at": None, "dns_expires_at": None,
                "dns_expired": False,
                "dns_updated_at": None,
            }
        snapshot = json.loads(row["assessment_json"])
        expires_at = row["expires_at"]
        try:
            expiry = datetime.fromisoformat(expires_at)
            expired = expiry.tzinfo is None or instant >= expiry.astimezone(UTC)
        except (TypeError, ValueError):
            # Corrupt or pre-migration timestamps are diagnostic data only;
            # they cannot establish a current provider expectation.
            expired = True
        # The stored value is the assessor's result.  Once the snapshot expires,
        # its current public freshness is unavailable; the original result is
        # still retained in assessment_json for auditability.
        dns_status = "unavailable" if expired else row["dns_status"]
        return {
            "dns_status": dns_status,
            "assessment": row["assessment"],
            "evidence": snapshot.get("evidence", []),
            "contradictions": snapshot.get("contradictions", []),
            "assessed_at": row["assessed_at"],
            "dns_fetched_at": row["assessed_at"],
            "dns_expires_at": expires_at,
            "dns_expired": expired,
            "dns_updated_at": row["updated_at"],
        }

    @staticmethod
    def _observation_public(row: dict[str, Any] | sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        messages = row["messages"]
        return {
            "messages": messages,
            "pass": row["pass_messages"],
            "fail": row["fail_messages"],
            "dmarc_pass": row["pass_messages"],
            "dmarc_fail": row["fail_messages"],
            "distinct_days": row["distinct_days"],
            "last_seen": row["last_seen"],
            "pass_rate": round(row["pass_messages"] / messages * 100, 2)
            if messages else 0,
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _public_assessment(
        cls,
        domain: str,
        service_id: str,
        policy: dict[str, Any] | sqlite3.Row | None,
        dns: dict[str, Any] | sqlite3.Row | None,
        observation: dict[str, Any] | sqlite3.Row | None,
        instant: datetime,
    ) -> dict[str, Any]:
        decision = policy["decision"] if policy is not None else "automatic"
        dns_public = cls._dns_public(dns, instant)
        observation_public = cls._observation_public(observation)
        # MX alone describes inbound routing and must not automatically approve
        # an outbound sender. SPF or DKIM evidence is required unless the DNS
        # assessor has already established a strong multi-signal result.
        outbound_dns_evidence = bool(
            dns_public["assessment"] == "strong"
            or any(
                isinstance(item, dict)
                and item.get("type") in {"spf", "dkim"}
                for item in dns_public["evidence"]
            )
        )
        qualifies = bool(
            observation is not None
            and observation["messages"] >= 100
            and observation["distinct_days"] >= 7
            and observation["pass_messages"] / observation["messages"] >= 0.99
            and dns_public["dns_status"] == "fresh"
            and dns_public["assessment"] in DNS_CONFIGURED_ASSESSMENTS
            and outbound_dns_evidence
        )
        if decision == "confirmed":
            effective_status = "expected"
        elif decision == "rejected":
            effective_status = "rejected"
        elif qualifies:
            effective_status = "expected"
        elif (
            observation_public is not None
            or dns_public["assessment"] in DNS_CONFIGURED_ASSESSMENTS
        ):
            effective_status = "suggested"
        else:
            effective_status = "unknown"
        updated_values = [
            value for value in (
                policy["updated_at"] if policy is not None else None,
                dns["updated_at"] if dns is not None else None,
                observation["updated_at"] if observation is not None else None,
            ) if value is not None
        ]
        return {
            "domain": domain,
            "service_id": service_id,
            "decision": decision,
            "effective_status": effective_status,
            "evidence": dns_public["evidence"],
            "contradictions": dns_public["contradictions"],
            "dns_status": dns_public["dns_status"],
            "assessment": dns_public["assessment"],
            "assessed_at": dns_public["assessed_at"],
            "dns_fetched_at": dns_public["dns_fetched_at"],
            "dns_expires_at": dns_public["dns_expires_at"],
            "dns_expired": dns_public["dns_expired"],
            "observation": observation_public,
            "effective_from": policy["effective_from"] if policy is not None else None,
            "updated_at": max(updated_values) if updated_values else None,
        }

    @staticmethod
    def _rows_for_assessment(
        connection: sqlite3.Connection, domain: str, service_id: str,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None, sqlite3.Row | None]:
        policy = connection.execute("""
            SELECT * FROM domain_service_policies
            WHERE domain = ? AND service_id = ?
        """, (domain, service_id)).fetchone()
        dns = connection.execute("""
            SELECT * FROM domain_service_dns_assessments
            WHERE domain = ? AND service_id = ?
        """, (domain, service_id)).fetchone()
        observation = connection.execute("""
            SELECT * FROM domain_service_observations
            WHERE domain = ? AND service_id = ?
        """, (domain, service_id)).fetchone()
        return policy, dns, observation

    def domain_service_assessment(
        self, domain: str, service_id: str, *, now: datetime | None = None,
    ) -> dict[str, Any]:
        key, service = canonical_domain(domain), canonical_service_id(service_id)
        instant = _now(now)
        with self._lock, self._connect() as connection:
            rows = self._rows_for_assessment(connection, key, service)
        return self._public_assessment(key, service, *rows, instant)

    def domain_service_assessments(
        self, domain: str = "*", *, now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        key = domain if domain == "*" else canonical_domain(domain)
        instant = _now(now)
        clause, parameters = ("", ()) if key == "*" else (" WHERE domain = ?", (key,))
        with self._lock, self._connect() as connection:
            policies = {
                (row["domain"], row["service_id"]): row
                for row in connection.execute(
                    "SELECT * FROM domain_service_policies" + clause, parameters,
                )
            }
            observations = {
                (row["domain"], row["service_id"]): row
                for row in connection.execute(
                    "SELECT * FROM domain_service_observations" + clause, parameters,
                )
            }
            dns_rows = {
                (row["domain"], row["service_id"]): row
                for row in connection.execute(
                    "SELECT * FROM domain_service_dns_assessments" + clause, parameters,
                )
            }
            keys = sorted(set(policies) | set(observations) | set(dns_rows))
            return [
                self._public_assessment(
                    item_domain, service_id, policies.get((item_domain, service_id)),
                    dns_rows.get((item_domain, service_id)),
                    observations.get((item_domain, service_id)),
                    instant,
                )
                for item_domain, service_id in keys
            ]

    def set_domain_service_decision(
        self,
        domain: str,
        service_id: str,
        decision: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        key, service = canonical_domain(domain), canonical_service_id(service_id)
        if not isinstance(decision, str) or decision not in DOMAIN_SERVICE_DECISIONS:
            raise ValueError("Invalid domain service decision")
        instant = _now(now)
        timestamp = instant.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("""
                SELECT * FROM domain_service_policies
                WHERE domain = ? AND service_id = ?
            """, (key, service)).fetchone()
            if current is None:
                connection.execute("""
                    INSERT INTO domain_service_policies
                        (domain, service_id, decision, effective_from, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (key, service, decision, timestamp, timestamp))
            elif current["decision"] != decision:
                connection.execute("""
                    UPDATE domain_service_policies
                    SET decision = ?, effective_from = ?, updated_at = ?
                    WHERE domain = ? AND service_id = ?
                """, (decision, timestamp, timestamp, key, service))
            rows = self._rows_for_assessment(connection, key, service)
            return self._public_assessment(key, service, *rows, instant)

    def save_domain_service_dns_assessment(
        self,
        domain: str,
        assessment: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        key = canonical_domain(domain)
        if not isinstance(assessment, dict):
            raise ValueError("DNS assessment must be an object")
        service = canonical_service_id(
            assessment.get("service_id", SERVICE_IDS[0])
        )
        raw_dns_status = assessment.get("dns_status")
        dns_status = (
            raw_dns_status.strip().lower()
            if isinstance(raw_dns_status, str) else ""
        )
        if dns_status not in DNS_STATUSES:
            raise ValueError("Invalid DNS status")
        raw_assessment = assessment.get("assessment")
        assessment_status = (
            raw_assessment.strip().lower()
            if isinstance(raw_assessment, str) else ""
        )
        if assessment_status not in DNS_ASSESSMENTS:
            raise ValueError("Invalid DNS assessment")
        if dns_status != "fresh" and assessment_status != "unknown":
            raise ValueError("Only fresh DNS results can establish configuration")
        instant = _now(now)
        assessed_at = _timestamp(
            assessment.get("assessed_at", assessment.get("fetched_at", instant)),
            "DNS assessment time",
        )
        expires_value = assessment.get("expires_at", _MISSING)
        if expires_value is _MISSING:
            ttl_seconds = _count(
                assessment.get("ttl_seconds"), "DNS ttl_seconds",
            )
            expires_value = datetime.fromisoformat(assessed_at) + timedelta(
                seconds=ttl_seconds,
            )
        expires_at = _timestamp(expires_value, "DNS expiry time", optional=True)
        if expires_at is None:
            raise ValueError("DNS assessments require an expiry time")
        if expires_at < assessed_at:
            raise ValueError("DNS expiry time must not precede assessment time")
        snapshot = dict(assessment)
        snapshot.update(
            service_id=service,
            dns_status=dns_status,
            assessment=assessment_status,
            assessed_at=assessed_at,
            expires_at=expires_at,
        )
        try:
            payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("DNS assessment must be JSON serializable") from exc
        updated_at = instant.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT * FROM domain_service_dns_assessments
                   WHERE domain = ? AND service_id = ?""", (key, service),
            ).fetchone()
            unchanged = current is not None and all((
                current["assessment_json"] == payload,
                current["dns_status"] == dns_status,
                current["assessment"] == assessment_status,
                current["assessed_at"] == assessed_at,
                current["expires_at"] == expires_at,
            ))
            replace = current is None
            if current is not None and not unchanged:
                try:
                    current_assessed_at = datetime.fromisoformat(
                        current["assessed_at"]
                    )
                    incoming_assessed_at = datetime.fromisoformat(assessed_at)
                except (TypeError, ValueError):
                    # A validated current schema should not reach this path;
                    # allowing the validated incoming row repairs it.
                    replace = True
                else:
                    if current_assessed_at.tzinfo is None:
                        replace = True
                    elif incoming_assessed_at > current_assessed_at.astimezone(UTC):
                        replace = True
                    elif incoming_assessed_at == current_assessed_at.astimezone(UTC):
                        # Equal assessment instants are resolved deterministically
                        # and conservatively, independent of completion order.
                        permissiveness = {
                            ("fresh", "strong"): 2,
                            ("fresh", "configured"): 1,
                        }
                        current_rank = permissiveness.get(
                            (current["dns_status"], current["assessment"]), 0,
                        )
                        incoming_rank = permissiveness.get(
                            (dns_status, assessment_status), 0,
                        )
                        replace = (
                            incoming_rank < current_rank
                            or incoming_rank == current_rank
                            and payload > current["assessment_json"]
                        )
            if not unchanged and replace:
                connection.execute("""
                    INSERT INTO domain_service_dns_assessments
                        (domain, service_id, assessment_json, dns_status, assessment,
                         assessed_at, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain, service_id) DO UPDATE SET
                        assessment_json = excluded.assessment_json,
                        dns_status = excluded.dns_status,
                        assessment = excluded.assessment,
                        assessed_at = excluded.assessed_at,
                        expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at
                """, (
                    key, service, payload, dns_status, assessment_status,
                    assessed_at, expires_at, updated_at,
                ))
            row = connection.execute(
                """SELECT * FROM domain_service_dns_assessments
                   WHERE domain = ? AND service_id = ?""", (key, service),
            ).fetchone()
        return {
            "domain": key,
            "service_id": service,
            **self._dns_public(row, instant),
        }

    def save_domain_service_observation(
        self,
        domain: str,
        service_id: str,
        observation: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        key, service, values = _validated_observation(
            domain, service_id, observation,
        )
        messages, passed, failed, distinct_days, last_seen = values
        instant = _now(now)
        updated_at = instant.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("""
                SELECT * FROM domain_service_observations
                WHERE domain = ? AND service_id = ?
            """, (key, service)).fetchone()
            unchanged = current is not None and values == (
                current["messages"], current["pass_messages"],
                current["fail_messages"], current["distinct_days"],
                current["last_seen"],
            )
            if not unchanged:
                connection.execute("""
                    INSERT INTO domain_service_observations
                        (domain, service_id, messages, pass_messages, fail_messages,
                         distinct_days, last_seen, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain, service_id) DO UPDATE SET
                        messages = excluded.messages,
                        pass_messages = excluded.pass_messages,
                        fail_messages = excluded.fail_messages,
                        distinct_days = excluded.distinct_days,
                        last_seen = excluded.last_seen,
                        updated_at = excluded.updated_at
                """, (key, service, *values, updated_at))
            rows = self._rows_for_assessment(connection, key, service)
            return self._public_assessment(key, service, *rows, instant)

    def replace_domain_service_observations(
        self,
        observations: Mapping[tuple[str, str], dict[str, Any]],
        *,
        service_ids: tuple[str, ...] = SERVICE_IDS,
        now: datetime | None = None,
    ) -> None:
        """Atomically replace one canonical rolling observation snapshot.

        Rows absent from the complete scan are removed so an automatic
        expectation cannot survive after its evidence has left the window.
        Validation completes before the transaction mutates any row.
        """
        if not isinstance(observations, Mapping):
            raise ValueError("Service observations must be a mapping")
        services = tuple(dict.fromkeys(
            canonical_service_id(value) for value in service_ids
        ))
        if not services:
            raise ValueError("At least one service ID is required")
        normalized: dict[
            tuple[str, str], tuple[int, int, int, int, str | None]
        ] = {}
        for raw_key, observation in observations.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise ValueError("Service observation keys must be domain/service pairs")
            domain, service_id = raw_key
            key, service, values = _validated_observation(
                domain, service_id, observation,
            )
            if service not in services:
                raise ValueError("Observation service is outside replacement scope")
            normalized[(key, service)] = values

        instant = _now(now)
        updated_at = instant.isoformat()
        placeholders = ",".join("?" for _ in services)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                (row["domain"], row["service_id"]): row
                for row in connection.execute(
                    "SELECT * FROM domain_service_observations "
                    f"WHERE service_id IN ({placeholders})",
                    services,
                )
            }
            stale = set(existing) - set(normalized)
            if stale:
                connection.executemany("""
                    DELETE FROM domain_service_observations
                    WHERE domain = ? AND service_id = ?
                """, sorted(stale))
            for (key, service), values in normalized.items():
                current = existing.get((key, service))
                unchanged = current is not None and values == (
                    current["messages"], current["pass_messages"],
                    current["fail_messages"], current["distinct_days"],
                    current["last_seen"],
                )
                if unchanged:
                    continue
                connection.execute("""
                    INSERT INTO domain_service_observations
                        (domain, service_id, messages, pass_messages, fail_messages,
                         distinct_days, last_seen, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain, service_id) DO UPDATE SET
                        messages = excluded.messages,
                        pass_messages = excluded.pass_messages,
                        fail_messages = excluded.fail_messages,
                        distinct_days = excluded.distinct_days,
                        last_seen = excluded.last_seen,
                        updated_at = excluded.updated_at
                """, (key, service, *values, updated_at))
