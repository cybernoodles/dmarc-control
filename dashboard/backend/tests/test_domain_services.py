from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.store import StateStore


NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def dns(
    *,
    dns_status: str = "fresh",
    assessment: str = "configured",
    expires: datetime | None = None,
) -> dict:
    return {
        "service_id": "microsoft365",
        "dns_status": dns_status,
        "assessment": assessment,
        "assessed_at": NOW,
        "expires_at": expires if expires is not None else NOW + timedelta(days=1),
        "evidence": [{
            "type": "spf",
            "value": "include:spf.protection.outlook.com",
            "rule_id": "microsoft365.spf.commercial.include.direct",
        }],
        "contradictions": [],
    }


def observation(*, messages: int = 100, passed: int = 99,
                failed: int = 1, days: int = 7) -> dict:
    return {
        "messages": messages,
        "pass": passed,
        "fail": failed,
        "distinct_days": days,
        "last_seen": NOW,
    }


class DomainServiceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / "state.db"
        self.store = StateStore(self.path)

    def test_schema_migration_and_reinitialization_are_idempotent(self) -> None:
        expected = {
            "domain_service_policies",
            "domain_service_dns_assessments",
            "domain_service_observations",
        }
        with sqlite3.connect(self.path) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
        self.assertTrue(expected <= tables)

        saved = self.store.set_domain_service_decision(
            "Example.COM.", "Microsoft365", "confirmed", now=NOW,
        )
        reopened = StateStore(self.path)
        self.assertEqual(
            reopened.domain_service_assessment(
                "example.com", "microsoft365", now=NOW,
            ),
            saved,
        )
        self.assertEqual(len(reopened.domain_service_assessments()), 1)

    def test_legacy_dns_snapshot_schema_is_migrated(self) -> None:
        path = Path(self.directory) / "legacy.db"
        with sqlite3.connect(path) as connection:
            connection.execute("""
                CREATE TABLE domain_service_dns_assessments (
                    domain TEXT PRIMARY KEY,
                    assessment_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO domain_service_dns_assessments
                    (domain, assessment_json, status, fetched_at, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "example.com",
                json.dumps({"evidence": [{"type": "spf"}]}),
                "configured",
                NOW.isoformat(),
                (NOW + timedelta(days=1)).isoformat(),
                NOW.isoformat(),
            ))

        migrated = StateStore(path)
        result = migrated.domain_service_assessment(
            "example.com", "microsoft365", now=NOW,
        )
        self.assertEqual(result["dns_status"], "fresh")
        self.assertEqual(result["assessment"], "configured")
        self.assertEqual(result["evidence"], [{"type": "spf"}])
        self.assertEqual(
            [item["service_id"] for item in migrated.domain_service_assessments(
                "example.com", now=NOW,
            )],
            ["microsoft365"],
        )

    def test_legacy_missing_or_naive_expiry_is_retained_but_fail_closed(self) -> None:
        path = Path(self.directory) / "legacy-invalid-time.db"
        with sqlite3.connect(path) as connection:
            connection.execute("""
                CREATE TABLE domain_service_dns_assessments (
                    domain TEXT PRIMARY KEY,
                    assessment_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.executemany("""
                INSERT INTO domain_service_dns_assessments
                    (domain, assessment_json, status, fetched_at, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                (
                    "missing.example", json.dumps({"evidence": [{"type": "spf"}]}),
                    "configured", "2020-01-01T00:00:00+00:00", None,
                    "2020-01-01T00:00:00+00:00",
                ),
                (
                    "naive.example", json.dumps({"evidence": [{"type": "spf"}]}),
                    "configured", "2020-01-01T00:00:00", "2099-01-01T00:00:00",
                    "2020-01-01T00:00:00",
                ),
            ))

        migrated = StateStore(path)
        for domain in ("missing.example", "naive.example"):
            with self.subTest(domain=domain):
                result = migrated.domain_service_assessment(
                    domain, "microsoft365", now=NOW,
                )
                self.assertEqual(result["dns_status"], "unavailable")
                self.assertEqual(result["assessment"], "unknown")
                self.assertTrue(result["dns_expired"])
                after_history = migrated.save_domain_service_observation(
                    domain, "microsoft365",
                    observation(passed=100, failed=0), now=NOW,
                )
                self.assertNotEqual(after_history["effective_status"], "expected")

    def test_domains_and_service_ids_are_canonicalized(self) -> None:
        saved = self.store.set_domain_service_decision(
            "  BÜCHER.Example. ", " Microsoft365 ", "confirmed", now=NOW,
        )
        self.assertEqual(saved["domain"], "xn--bcher-kva.example")
        self.assertEqual(saved["service_id"], "microsoft365")
        self.assertEqual(
            self.store.domain_service_assessment(
                "xn--bcher-kva.example", "MICROSOFT365", now=NOW,
            ),
            saved,
        )

    def test_missing_policy_is_automatic_and_decisions_take_precedence(self) -> None:
        missing = self.store.domain_service_assessment(
            "example.com", "microsoft365", now=NOW,
        )
        self.assertEqual(
            (
                missing["decision"], missing["effective_status"],
                missing["dns_status"], missing["assessment"],
            ),
            ("automatic", "unknown", "unavailable", "unknown"),
        )
        self.assertIsNone(missing["effective_from"])

        confirmed = self.store.set_domain_service_decision(
            "example.com", "microsoft365", "confirmed", now=NOW,
        )
        self.assertEqual(confirmed["effective_status"], "expected")
        self.assertEqual(confirmed["effective_from"], NOW.isoformat())

        rejected = self.store.set_domain_service_decision(
            "example.com", "microsoft365", "rejected",
            now=NOW + timedelta(hours=1),
        )
        self.assertEqual(rejected["effective_status"], "rejected")
        self.assertEqual(
            rejected["effective_from"], (NOW + timedelta(hours=1)).isoformat(),
        )
        same = self.store.set_domain_service_decision(
            "example.com", "microsoft365", "rejected",
            now=NOW + timedelta(hours=2),
        )
        self.assertEqual(same["effective_from"], rejected["effective_from"])
        self.assertEqual(same["updated_at"], rejected["updated_at"])

    def test_automatic_requires_all_observation_and_dns_thresholds(self) -> None:
        self.store.save_domain_service_dns_assessment("example.com", dns(), now=NOW)
        exact = self.store.save_domain_service_observation(
            "example.com", "microsoft365", observation(), now=NOW,
        )
        self.assertEqual(exact["effective_status"], "expected")
        self.assertEqual(exact["observation"]["pass_rate"], 99.0)
        self.assertEqual(exact["observation"]["dmarc_pass"], 99)
        self.assertEqual(exact["observation"]["dmarc_fail"], 1)

        cases = (
            ("few-messages", observation(messages=99, passed=99, failed=0)),
            ("few-days", observation(days=6)),
            ("low-pass-rate", observation(passed=98, failed=2)),
            ("rounded-pass-rate", observation(
                messages=100_000, passed=98_995, failed=1_005,
            )),
        )
        for service_id, value in cases:
            with self.subTest(service_id=service_id):
                result = self.store.save_domain_service_observation(
                    "example.com", service_id, value, now=NOW,
                )
                self.assertEqual(result["effective_status"], "suggested")

    def test_mx_only_is_a_hint_but_never_automatic_outbound_approval(self) -> None:
        mx_only = dns()
        mx_only["evidence"] = [{
            "type": "mx",
            "value": "example-com.mail.protection.outlook.com",
            "rule_id": "microsoft365.mx.exchange_online",
        }]
        self.store.save_domain_service_dns_assessment(
            "example.com", mx_only, now=NOW,
        )
        result = self.store.save_domain_service_observation(
            "example.com", "microsoft365", observation(), now=NOW,
        )

        self.assertEqual(result["effective_status"], "suggested")
        self.assertEqual(result["assessment"], "configured")

    def test_dns_freshness_and_assessment_are_independent(self) -> None:
        configured = self.store.save_domain_service_dns_assessment(
            "example.com", dns(assessment="strong"), now=NOW,
        )
        self.assertEqual(configured["dns_status"], "fresh")
        self.assertEqual(configured["assessment"], "strong")
        self.assertEqual(configured["assessed_at"], NOW.isoformat())
        self.assertEqual(configured["contradictions"], [])

        negative = self.store.save_domain_service_dns_assessment(
            "negative.example",
            dns(dns_status="negative", assessment="unknown"),
            now=NOW,
        )
        self.assertEqual(negative["dns_status"], "negative")
        self.assertEqual(negative["assessment"], "unknown")
        self.assertEqual(
            self.store.domain_service_assessment(
                "negative.example", "microsoft365", now=NOW,
            )["effective_status"],
            "unknown",
        )

        ttl_snapshot = dns()
        ttl_snapshot.pop("expires_at")
        ttl_snapshot["ttl_seconds"] = 60
        ttl = self.store.save_domain_service_dns_assessment(
            "ttl.example", ttl_snapshot, now=NOW,
        )
        self.assertEqual(
            ttl["dns_expires_at"], (NOW + timedelta(minutes=1)).isoformat(),
        )

    def test_confirmed_and_rejected_override_automatic_evidence(self) -> None:
        self.store.save_domain_service_dns_assessment("example.com", dns(), now=NOW)
        self.store.save_domain_service_observation(
            "example.com", "confirmed-service",
            observation(messages=1, passed=0, failed=1, days=1), now=NOW,
        )
        confirmed = self.store.set_domain_service_decision(
            "example.com", "confirmed-service", "confirmed", now=NOW,
        )
        self.assertEqual(confirmed["effective_status"], "expected")

        self.store.save_domain_service_observation(
            "example.com", "rejected-service", observation(), now=NOW,
        )
        rejected = self.store.set_domain_service_decision(
            "example.com", "rejected-service", "rejected", now=NOW,
        )
        self.assertEqual(rejected["effective_status"], "rejected")

    def test_stale_or_unknown_dns_never_auto_confirms(self) -> None:
        self.store.save_domain_service_observation(
            "unknown.example", "microsoft365", observation(), now=NOW,
        )
        unknown = self.store.domain_service_assessment(
            "unknown.example", "microsoft365", now=NOW,
        )
        self.assertEqual(unknown["dns_status"], "unavailable")
        self.assertEqual(unknown["assessment"], "unknown")
        self.assertEqual(unknown["effective_status"], "suggested")

        self.store.save_domain_service_dns_assessment(
            "stale.example", dns(expires=NOW + timedelta(minutes=1)), now=NOW,
        )
        self.store.save_domain_service_observation(
            "stale.example", "microsoft365", observation(), now=NOW,
        )
        stale = self.store.domain_service_assessment(
            "stale.example", "microsoft365", now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(stale["dns_status"], "unavailable")
        self.assertEqual(stale["assessment"], "configured")
        self.assertTrue(stale["dns_expired"])
        self.assertEqual(stale["effective_status"], "suggested")

    def test_snapshots_upsert_and_domain_listing_is_stable(self) -> None:
        first_dns = self.store.save_domain_service_dns_assessment(
            "example.com", dns(), now=NOW,
        )
        same_dns = self.store.save_domain_service_dns_assessment(
            "EXAMPLE.COM.", dns(), now=NOW + timedelta(hours=1),
        )
        self.assertEqual(first_dns["dns_updated_at"], same_dns["dns_updated_at"])

        # A DNS snapshot alone must make its service visible in the listing.
        self.store.save_domain_service_dns_assessment(
            "dns-only.example", dns(), now=NOW,
        )
        self.assertEqual(
            [item["service_id"] for item in self.store.domain_service_assessments(
                "dns-only.example", now=NOW,
            )],
            ["microsoft365"],
        )

        first = self.store.save_domain_service_observation(
            "example.com", "microsoft365", observation(), now=NOW,
        )
        same = self.store.save_domain_service_observation(
            "EXAMPLE.COM", "Microsoft365", observation(),
            now=NOW + timedelta(hours=1),
        )
        self.assertEqual(
            first["observation"]["updated_at"],
            same["observation"]["updated_at"],
        )
        updated = self.store.save_domain_service_observation(
            "example.com", "microsoft365",
            observation(messages=200, passed=200, failed=0, days=8),
            now=NOW + timedelta(hours=2),
        )
        self.assertEqual(updated["observation"]["messages"], 200)
        self.store.set_domain_service_decision(
            "other.example", "smtp2go", "automatic", now=NOW,
        )
        self.assertEqual(
            [
                item["service_id"]
                for item in self.store.domain_service_assessments(
                    "example.com", now=NOW,
                )
            ],
            ["microsoft365"],
        )
        self.assertEqual(
            [(item["domain"], item["service_id"])
             for item in self.store.domain_service_assessments(now=NOW)],
            [
                ("dns-only.example", "microsoft365"),
                ("example.com", "microsoft365"),
                ("other.example", "smtp2go"),
            ],
        )

    def test_invalid_snapshots_do_not_mutate_the_store(self) -> None:
        invalid_observations = (
            {"messages": 100, "pass": 101, "fail": 0, "distinct_days": 7},
            {"messages": True, "pass": 1, "fail": 0, "distinct_days": 1},
            {"messages": 1, "pass": 1, "fail": 0},
        )
        for value in invalid_observations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.save_domain_service_observation(
                    "example.com", "microsoft365", value, now=NOW,
                )
        with self.assertRaises(ValueError):
            self.store.save_domain_service_dns_assessment(
                "example.com", {"dns_status": "fresh"}, now=NOW,
            )
        self.assertEqual(self.store.domain_service_assessments(), [])

    def test_older_dns_completion_cannot_overwrite_newer_snapshot(self) -> None:
        newer = dns(dns_status="negative", assessment="unknown")
        newer.update(
            assessed_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            evidence=[],
        )
        self.store.save_domain_service_dns_assessment(
            "example.com", newer, now=NOW,
        )
        older = dns()
        older.update(
            assessed_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
        )
        result = self.store.save_domain_service_dns_assessment(
            "example.com", older, now=NOW + timedelta(minutes=1),
        )

        self.assertEqual(result["dns_status"], "negative")
        self.assertEqual(result["assessment"], "unknown")
        self.assertEqual(result["assessed_at"], NOW.isoformat())

    def test_equal_dns_completion_time_prefers_fail_closed_result(self) -> None:
        self.store.save_domain_service_dns_assessment(
            "example.com", dns(), now=NOW,
        )
        negative = dns(dns_status="negative", assessment="unknown")
        negative.update(evidence=[])
        fail_closed = self.store.save_domain_service_dns_assessment(
            "example.com", negative, now=NOW + timedelta(seconds=1),
        )
        later_permissive_completion = self.store.save_domain_service_dns_assessment(
            "example.com", dns(), now=NOW + timedelta(seconds=2),
        )

        self.assertEqual(fail_closed["dns_status"], "negative")
        self.assertEqual(later_permissive_completion["dns_status"], "negative")

    def test_observation_snapshot_replacement_is_atomic_and_removes_absent_rows(self) -> None:
        self.store.save_domain_service_observation(
            "stale.example", "microsoft365", observation(), now=NOW,
        )
        self.store.save_domain_service_observation(
            "other.example", "smtp2go", observation(), now=NOW,
        )

        self.store.replace_domain_service_observations({
            ("Current.Example", "Microsoft365"): observation(
                messages=200, passed=200, failed=0, days=8,
            ),
        }, now=NOW + timedelta(hours=1))

        self.assertIsNone(self.store.domain_service_assessment(
            "stale.example", "microsoft365", now=NOW,
        )["observation"])
        self.assertEqual(self.store.domain_service_assessment(
            "current.example", "microsoft365", now=NOW,
        )["observation"]["messages"], 200)
        self.assertIsNotNone(self.store.domain_service_assessment(
            "other.example", "smtp2go", now=NOW,
        )["observation"])

        before = self.store.domain_service_assessments(now=NOW)
        with self.assertRaises(ValueError):
            self.store.replace_domain_service_observations({
                ("broken.example", "microsoft365"): {"messages": -1},
            }, now=NOW + timedelta(hours=2))
        self.assertEqual(self.store.domain_service_assessments(now=NOW), before)


if __name__ == "__main__":
    unittest.main()
