from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from app.store import StateStore


IP = "192.0.2.1"


class HostClassificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.db"

    def test_existing_schema_migration_preserves_every_old_value_and_timestamp(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("""
                CREATE TABLE host_overrides (
                    source_ip TEXT PRIMARY KEY, service_name TEXT,
                    trust_status TEXT NOT NULL, notes TEXT, updated_at TEXT NOT NULL
                )
            """)
            connection.execute(
                "INSERT INTO host_overrides VALUES (?, ?, ?, ?, ?)",
                (IP, "SMTP2GO", "automatic", "Original note", "2026-01-01T00:00:00+00:00"),
            )
        store = StateStore(self.path)
        row = store.host_overrides()[IP]
        self.assertEqual(row, {
            "source_ip": IP, "service_name": "SMTP2GO", "manual_service_name": "SMTP2GO",
            "classification_mode": "legacy_preserved", "trust_status": "automatic",
            "notes": "Original note", "updated_at": "2026-01-01T00:00:00+00:00",
        })
        self.assertEqual(StateStore(self.path).host_overrides()[IP], row)

    def test_new_note_creates_automatic_record_without_freezing_a_name(self):
        store = StateStore(self.path)
        saved = store.patch_host_classification(IP, {"notes": "Reviewed"})
        self.assertEqual(saved["classification_mode"], "automatic")
        self.assertEqual(saved["trust_status"], "automatic")
        self.assertIsNone(saved["service_name"])
        self.assertIsNone(saved["manual_service_name"])
        self.assertEqual(StateStore(self.path).host_overrides()[IP], saved)

    def test_rollback_put_name_survives_upgrade_without_changing_other_stored_values(self):
        store = StateStore(self.path)
        store.patch_host_classification(IP, {"notes": "Originally automatic"})
        automatic_ip, manual_ip = "192.0.2.2", "192.0.2.3"
        automatic = store.patch_host_classification(automatic_ip, {"notes": "Keep automatic"})
        manual = store.patch_host_classification(manual_ip, {
            "classification_mode": "manual", "manual_service_name": "Keep explicit mode",
            "trust_status": "confirmed", "notes": "Keep manual",
        })
        # Exact pre-classification_mode UPSERT from 7034669. A rollback can
        # update a migrated row without knowing its new classification column.
        with sqlite3.connect(self.path) as connection:
            connection.execute("""
                INSERT INTO host_overrides (
                    source_ip, service_name, trust_status, notes, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_ip) DO UPDATE SET
                    service_name = excluded.service_name,
                    trust_status = excluded.trust_status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
            """, (IP, " Rollback relay ", "ignored", "Edited by old release", "2026-09-08T12:34:56+00:00"))
        foreign_write = store.host_overrides()[IP]
        self.assertEqual(foreign_write["classification_mode"], "automatic")
        self.assertEqual(foreign_write["service_name"], " Rollback relay ")
        expected = {
            IP: {**foreign_write, "classification_mode": "legacy_preserved"},
            automatic_ip: automatic,
            manual_ip: manual,
        }
        self.assertEqual(StateStore(self.path).host_overrides(), expected)
        self.assertEqual(StateStore(self.path).host_overrides(), expected)

    def test_note_only_preserves_legacy_name_and_trust(self):
        store = StateStore(self.path)
        old = store.set_host_override(IP, service_name="SMTP2GO", trust_status="confirmed", notes="Old")
        saved = store.patch_host_classification(IP, {"notes": "Updated note"})
        for field in ("service_name", "manual_service_name", "trust_status", "classification_mode"):
            self.assertEqual(saved[field], old[field])
        self.assertEqual(saved["notes"], "Updated note")

    def test_note_only_preserves_manual_classification(self):
        store = StateStore(self.path)
        store.patch_host_classification(IP, {
            "classification_mode": "manual", "manual_service_name": "Custom sender",
            "trust_status": "confirmed", "notes": "Old note",
        })
        saved = store.patch_host_classification(IP, {"notes": None})
        self.assertEqual(saved["classification_mode"], "manual")
        self.assertEqual(saved["manual_service_name"], "Custom sender")
        self.assertEqual(saved["trust_status"], "confirmed")
        self.assertIsNone(saved["notes"])

    def test_restoring_automatic_clears_name_resets_default_trust_and_retains_note(self):
        store = StateStore(self.path)
        store.set_host_override(IP, service_name="SMTP2GO", trust_status="confirmed", notes="Keep this")
        saved = store.patch_host_classification(IP, {"classification_mode": "automatic"})
        self.assertEqual(saved["classification_mode"], "automatic")
        self.assertEqual(saved["trust_status"], "automatic")
        self.assertIsNone(saved["service_name"])
        self.assertIsNone(saved["manual_service_name"])
        self.assertEqual(saved["notes"], "Keep this")

    def test_restoring_automatic_honors_explicit_trust_choice(self):
        store = StateStore(self.path)
        store.set_host_override(IP, service_name="SMTP2GO", trust_status="confirmed", notes="Keep this")
        saved = store.patch_host_classification(IP, {
            "classification_mode": "automatic", "trust_status": "ignored",
        })
        self.assertEqual(saved["trust_status"], "ignored")
        self.assertIsNone(saved["manual_service_name"])

    def test_manual_mode_can_use_existing_preserved_name(self):
        store = StateStore(self.path)
        store.set_host_override(IP, service_name="SMTP2GO", trust_status="confirmed", notes="Keep this")
        saved = store.patch_host_classification(IP, {"classification_mode": "manual"})
        self.assertEqual(saved["classification_mode"], "manual")
        self.assertEqual(saved["manual_service_name"], "SMTP2GO")
        self.assertEqual(saved["trust_status"], "confirmed")
        self.assertEqual(saved["notes"], "Keep this")

    def test_manual_name_change_preserves_explicit_trust_and_notes(self):
        store = StateStore(self.path)
        store.patch_host_classification(IP, {
            "classification_mode": "manual", "manual_service_name": "First",
            "trust_status": "confirmed", "notes": "Keep this",
        })
        saved = store.patch_host_classification(IP, {"manual_service_name": " Second "})
        self.assertEqual(saved["manual_service_name"], "Second")
        self.assertEqual(saved["trust_status"], "confirmed")
        self.assertEqual(saved["notes"], "Keep this")

    def test_invalid_patches_leave_existing_record_unchanged(self):
        store = StateStore(self.path)
        original = store.patch_host_classification(IP, {"notes": "Keep this"})
        for changes in (
            {"classification_mode": "legacy_preserved"},
            {"classification_mode": []},
            {"classification_mode": "manual", "manual_service_name": "   ", "notes": "Must not save"},
            {"manual_service_name": "Cannot silently switch mode"},
            {"manual_service_name": "x" * 121},
            {"notes": "x" * 501},
            {"trust_status": None},
            {"trust_status": {}},
            {"notes": 123},
            {"service_name": "Old alias is not a PATCH field"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                store.patch_host_classification(IP, changes)
            self.assertEqual(store.host_overrides()[IP], original)

    def test_missing_manual_name_does_not_create_an_incomplete_record(self):
        store = StateStore(self.path)
        with self.assertRaisesRegex(ValueError, "Manual service name is required"):
            store.patch_host_classification(IP, {"classification_mode": "manual"})
        self.assertNotIn(IP, store.host_overrides())

    def test_empty_patch_is_a_noop_for_existing_record_and_does_not_create_one(self):
        store = StateStore(self.path)
        with self.assertRaises(ValueError):
            store.patch_host_classification(IP, {})
        saved = store.patch_host_classification(IP, {"notes": "Keep this"})
        self.assertEqual(store.patch_host_classification(IP, {}), saved)

    def test_legacy_put_retains_compatibility_and_does_not_claim_known_intent(self):
        store = StateStore(self.path)
        store.patch_host_classification(IP, {"classification_mode": "manual", "manual_service_name": "New API"})
        saved = store.set_host_override(IP, service_name="Old API", trust_status="ignored", notes="Old full update")
        self.assertEqual(saved["classification_mode"], "legacy_preserved")
        self.assertEqual(saved["manual_service_name"], "Old API")
        self.assertEqual(saved, store.host_overrides()[IP])
        self.assertTrue(store.clear_host_override(IP))
        self.assertNotIn(IP, store.host_overrides())
        self.assertFalse(store.clear_host_override(IP))

    def test_parallel_partial_patches_do_not_overwrite_each_others_fields(self):
        store = StateStore(self.path)
        store.patch_host_classification(IP, {"notes": "Initial"})
        other = StateStore(self.path)
        barrier = Barrier(2)

        def update(target, changes):
            barrier.wait()
            return target.patch_host_classification(IP, changes)

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(update, store, {"notes": "Concurrent note"})
            b = executor.submit(update, other, {"trust_status": "confirmed"})
            a.result()
            b.result()
        saved = store.host_overrides()[IP]
        self.assertEqual(saved["notes"], "Concurrent note")
        self.assertEqual(saved["trust_status"], "confirmed")
        self.assertEqual(saved["classification_mode"], "automatic")
        self.assertIsNone(saved["manual_service_name"])


if __name__ == "__main__":
    unittest.main()
